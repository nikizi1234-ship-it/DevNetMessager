from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, status, Form, Request, File, UploadFile, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse, RedirectResponse, PlainTextResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_, desc, asc, func as sql_func
import json
from datetime import datetime, timedelta
from pathlib import Path
import uvicorn 
import os
import sys
import shutil
import uuid
import random
import re
from typing import Optional, List
from enum import Enum

# Добавляем путь для импорта модулей
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from websocket_manager import manager
    from database import engine, SessionLocal, get_db, init_database
    from models import (
        Base, User, Message, Group, GroupMember, Channel, Subscription, 
        File as FileModel, Reaction, Notification, MessageType
    )
    from auth import create_access_token, verify_token, verify_password, get_password_hash
    print("✅ Все модули успешно импортированы")
except ImportError as e:
    print(f"❌ Ошибка импорта: {e}")
    raise

# ========== ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ ==========

print("📦 Инициализация базы данных...")
try:
    # Инициализируем базу данных
    init_database()
    print("✅ База данных инициализирована")
except Exception as e:
    print(f"⚠️  Ошибка инициализации базы данных: {e}")

# ========== СОЗДАНИЕ АДМИН-ПОЛЬЗОВАТЕЛЯ ЕСЛИ ЕГО НЕТ ==========

def create_admin_user():
    """Создает администратора если его нет в базе"""
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.username == "admin").first()
        if not admin:
            print("👑 Создаем администратора...")
            admin_user = User(
                username="admin",
                email="admin@devnet.local",
                display_name="Администратор",
                password_hash=get_password_hash("admin123"),
                role="admin",
                is_verified=True
            )
            db.add(admin_user)
            db.commit()
            print("✅ Администратор создан (логин: admin, пароль: admin123)")
        else:
            print("✅ Администратор уже существует")
    except Exception as e:
        print(f"❌ Ошибка создания администратора: {e}")
    finally:
        db.close()

# Вызываем создание администратора
create_admin_user()

# ========== СОЗДАНИЕ FASTAPI ПРИЛОЖЕНИЯ ==========

app = FastAPI(
    title="DevNet Messenger API",
    description="API для мессенджера DevNet с поддержкой WebSocket, групп и каналов",
    version="5.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc"
)

# Настройка CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# Создаем директории для медиа
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)
for media_type in ["images", "videos", "audios", "files", "avatars", "banners"]:
    (UPLOAD_DIR / media_type).mkdir(exist_ok=True)

print(f"📁 Директория для загрузок: {UPLOAD_DIR}")

# Получаем абсолютный путь к фронтенду
current_dir = Path(__file__).parent
project_root = current_dir.parent
frontend_dir = project_root / "frontend"

print(f"📁 Корневая директория: {project_root}")
print(f"📁 Фронтенд директория: {frontend_dir}")

# Проверяем существование фронтенда
if frontend_dir.exists():
    print(f"✅ Фронтенд найден: {frontend_dir}")
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")
    print("✅ Статические файлы подключены")
else:
    print(f"⚠️  Фронтенд не найден: {frontend_dir}")

# Монтируем директорию загрузок
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

# ========== ДИАГНОСТИЧЕСКАЯ СТРАНИЦА ==========

@app.get("/api/debug")
async def debug_info():
    """Страница диагностики и тестирования API"""
    db = SessionLocal()
    try:
        # Проверка базы данных
        db_status = "OK"
        try:
            db.execute("SELECT 1")
            users_count = db.query(User).count()
            groups_count = db.query(Group).count()
            channels_count = db.query(Channel).count()
        except Exception as e:
            db_status = f"ERROR: {str(e)}"
            users_count = groups_count = channels_count = 0
        
        # Проверка директорий
        dirs = {
            "uploads": UPLOAD_DIR.exists(),
            "frontend": frontend_dir.exists(),
            "current": current_dir.exists()
        }
        
        # Проверка зависимостей
        deps = {}
        try:
            import fastapi
            deps["fastapi"] = f"OK ({fastapi.__version__})"
        except ImportError:
            deps["fastapi"] = "MISSING"
            
        try:
            import sqlalchemy
            deps["sqlalchemy"] = f"OK ({sqlalchemy.__version__})"
        except ImportError:
            deps["sqlalchemy"] = "MISSING"
            
        try:
            import passlib
            deps["passlib"] = "OK"
        except ImportError:
            deps["passlib"] = "MISSING"
        
        return {
            "status": "online",
            "timestamp": datetime.utcnow().isoformat(),
            "environment": {
                "is_railway": os.environ.get("RAILWAY_ENVIRONMENT") is not None,
                "port": os.environ.get("PORT", 8000),
                "python_version": sys.version
            },
            "database": {
                "status": db_status,
                "url": str(db.bind.url) if hasattr(db, 'bind') else "unknown",
                "users": users_count,
                "groups": groups_count,
                "channels": channels_count
            },
            "directories": dirs,
            "dependencies": deps,
            "endpoints": [
                {"path": "/", "method": "GET", "description": "Главная страница"},
                {"path": "/api/health", "method": "GET", "description": "Проверка здоровья"},
                {"path": "/api/debug", "method": "GET", "description": "Эта диагностическая страница"},
                {"path": "/api/auth/register", "method": "POST", "description": "Регистрация"},
                {"path": "/api/auth/login", "method": "POST", "description": "Вход"},
                {"path": "/api/auth/me", "method": "GET", "description": "Текущий пользователь"},
                {"path": "/api/docs", "method": "GET", "description": "Документация API"}
            ]
        }
    finally:
        db.close()

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========

def get_current_user(request: Request, db: Session = Depends(get_db)):
    """Получает текущего пользователя из токена"""
    token = request.cookies.get("access_token")
    if not token:
        return None
    
    payload = verify_token(token)
    if not payload:
        return None
    
    user_id = payload.get("user_id")
    if not user_id:
        return None
    
    user = db.query(User).filter(User.id == user_id).first()
    return user

def create_default_channels(db: Session):
    """Создает каналы по умолчанию"""
    default_channels = [
        {
            "name": "📢 DevNet Official",
            "description": "Официальный канал DevNet Messenger",
            "avatar_url": "/uploads/avatars/devnet_logo.png",
            "is_public": True,
            "is_official": True
        },
        {
            "name": "💬 General Chat",
            "description": "Общий чат для общения",
            "avatar_url": "/uploads/avatars/general_chat.png",
            "is_public": True,
            "is_official": False
        },
        {
            "name": "🚀 Updates & News",
            "description": "Обновления и новости проекта",
            "avatar_url": "/uploads/avatars/updates.png",
            "is_public": True,
            "is_official": True
        },
        {
            "name": "💻 Development",
            "description": "Обсуждение разработки",
            "avatar_url": "/uploads/avatars/dev.png",
            "is_public": True,
            "is_official": False
        },
        {
            "name": "🎮 Gaming",
            "description": "Обсуждение игр",
            "avatar_url": "/uploads/avatars/gaming.png",
            "is_public": True,
            "is_official": False
        }
    ]
    
    for channel_data in default_channels:
        existing = db.query(Channel).filter(Channel.name == channel_data["name"]).first()
        if not existing:
            channel = Channel(
                name=channel_data["name"],
                description=channel_data["description"],
                avatar_url=channel_data["avatar_url"],
                is_public=channel_data["is_public"],
                is_official=channel_data["is_official"],
                created_by=1  # admin user
            )
            db.add(channel)
    
    db.commit()
    print("✅ Каналы по умолчанию созданы")

# Создаем каналы по умолчанию при запуске
try:
    db = SessionLocal()
    create_default_channels(db)
    db.close()
except Exception as e:
    print(f"⚠️  Ошибка создания каналов: {e}")

# ========== API ENDPOINTS ==========

@app.get("/")
async def root():
    """Главная страница"""
    return RedirectResponse("/index.html")

@app.get("/api/health")
async def health_check():
    """Проверка здоровья API"""
    try:
        db = SessionLocal()
        try:
            db.execute("SELECT 1")
            db_status = "connected"
        except Exception as e:
            db_status = f"error: {str(e)}"
        finally:
            db.close()
        
        return {
            "status": "healthy",
            "service": "DevNet Messenger API",
            "version": "5.0.0",
            "timestamp": datetime.utcnow().isoformat(),
            "database": db_status,
            "environment": "railway" if os.environ.get("RAILWAY_ENVIRONMENT") else "local"
        }
    except Exception as e:
        return {
            "status": "degraded",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }

@app.get("/api/test")
async def test_endpoints():
    """Тестирование основных endpoint'ов"""
    endpoints = [
        ("GET", "/api/health", "Проверка здоровья"),
        ("GET", "/api/debug", "Диагностика"),
        ("GET", "/api/docs", "Документация")
    ]
    
    results = []
    for method, path, description in endpoints:
        results.append({
            "method": method,
            "path": path,
            "description": description,
            "status": "available"
        })
    
    return {
        "success": True,
        "endpoints": results,
        "message": "API работает корректно"
    }

# ========== АУТЕНТИФИКАЦИЯ ==========

@app.post("/api/auth/register")
async def register_user(
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    display_name: str = Form(None),
    db: Session = Depends(get_db)
):
    """Регистрация нового пользователя"""
    try:
        # Проверяем уникальность username
        existing_user = db.query(User).filter(User.username == username).first()
        if existing_user:
            raise HTTPException(status_code=400, detail="Имя пользователя уже занято")
        
        # Проверяем уникальность email
        existing_email = db.query(User).filter(User.email == email).first()
        if existing_email:
            raise HTTPException(status_code=400, detail="Email уже используется")
        
        # Проверяем пароль
        if len(password) < 6:
            raise HTTPException(status_code=400, detail="Пароль должен быть не менее 6 символов")
        if len(password) > 72:
            raise HTTPException(status_code=400, detail="Пароль должен быть не более 72 символов")
        
        # Создаем пользователя
        user = User(
            username=username,
            email=email,
            display_name=display_name or username,
            password_hash=get_password_hash(password)
        )
        
        db.add(user)
        db.commit()
        db.refresh(user)
        
        # Создаем токен
        access_token = create_access_token(data={"user_id": user.id, "username": user.username})
        
        response = JSONResponse({
            "success": True,
            "user": {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "email": user.email,
                "avatar_url": user.avatar_url
            },
            "access_token": access_token,
            "message": "Регистрация прошла успешно"
        })
        
        # Устанавливаем cookie с токеном
        response.set_cookie(
            key="access_token",
            value=access_token,
            httponly=True,
            max_age=7*24*60*60,  # 7 дней
            samesite="lax"
        )
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Ошибка регистрации: {str(e)}")

@app.post("/api/auth/login")
async def login_user(
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    """Вход пользователя"""
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user or not verify_password(password, user.password_hash):
            raise HTTPException(status_code=401, detail="Неверное имя пользователя или пароль")
        
        # Создаем токен
        access_token = create_access_token(data={"user_id": user.id, "username": user.username})
        
        response = JSONResponse({
            "success": True,
            "user": {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "email": user.email,
                "avatar_url": user.avatar_url,
                "role": user.role
            },
            "access_token": access_token,
            "message": "Вход выполнен успешно"
        })
        
        # Устанавливаем cookie с токеном
        response.set_cookie(
            key="access_token",
            value=access_token,
            httponly=True,
            max_age=7*24*60*60,  # 7 дней
            samesite="lax"
        )
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка входа: {str(e)}")

@app.get("/api/auth/me")
async def get_current_user_info(
    request: Request,
    db: Session = Depends(get_db)
):
    """Получение информации о текущем пользователе"""
    try:
        user = get_current_user(request, db)
        if not user:
            raise HTTPException(status_code=401, detail="Требуется аутентификация")
        
        return {
            "success": True,
            "user": {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "email": user.email,
                "avatar_url": user.avatar_url,
                "banner_url": user.banner_url,
                "bio": user.bio,
                "role": user.role,
                "is_verified": user.is_verified,
                "is_online": user.is_online,
                "created_at": user.created_at.isoformat() if user.created_at else None
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка загрузки пользователя: {str(e)}")

@app.post("/api/auth/logout")
async def logout_user():
    """Выход пользователя"""
    response = JSONResponse({
        "success": True,
        "message": "Вы успешно вышли"
    })
    response.delete_cookie(key="access_token")
    return response

# ========== ПОЛЬЗОВАТЕЛИ ==========

@app.get("/api/users")
async def get_users(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    search: str = Query(None),
    db: Session = Depends(get_db)
):
    """Получение списка пользователей"""
    try:
        user = get_current_user(request, db)
        if not user:
            raise HTTPException(status_code=401, detail="Требуется аутентификация")
        
        query = db.query(User).filter(User.id != user.id)
        
        if search:
            query = query.filter(
                or_(
                    User.username.ilike(f"%{search}%"),
                    User.display_name.ilike(f"%{search}%"),
                    User.email.ilike(f"%{search}%")
                )
            )
        
        total = query.count()
        users = query.order_by(User.username) \
                   .offset((page - 1) * limit) \
                   .limit(limit) \
                   .all()
        
        users_data = []
        for u in users:
            users_data.append({
                "id": u.id,
                "username": u.username,
                "display_name": u.display_name,
                "avatar_url": u.avatar_url,
                "bio": u.bio,
                "is_online": u.is_online,
                "created_at": u.created_at.isoformat() if u.created_at else None
            })
        
        return {
            "success": True,
            "users": users_data,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "pages": (total + limit - 1) // limit
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка загрузки пользователей: {str(e)}")

# ========== КАНАЛЫ ==========

@app.get("/api/channels")
async def get_channels(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """Получение списка каналов"""
    try:
        user = get_current_user(request, db)
        if not user:
            # Возвращаем только публичные каналы для неавторизованных
            query = db.query(Channel).filter(Channel.is_public == True)
            is_authenticated = False
        else:
            query = db.query(Channel).filter(Channel.is_public == True)
            is_authenticated = True
        
        total = query.count()
        channels = query.order_by(desc(Channel.is_official), desc(Channel.last_activity)) \
                       .offset((page - 1) * limit) \
                       .limit(limit) \
                       .all()
        
        # Проверяем подписки если пользователь авторизован
        subscribed_channel_ids = []
        if is_authenticated:
            subscriptions = db.query(Subscription).filter(Subscription.user_id == user.id).all()
            subscribed_channel_ids = [sub.channel_id for sub in subscriptions]
        
        channels_data = []
        for channel in channels:
            subscribers_count = db.query(Subscription).filter(Subscription.channel_id == channel.id).count()
            
            last_message = db.query(Message).filter(Message.channel_id == channel.id) \
                .order_by(Message.created_at.desc()).first()
            
            channels_data.append({
                "id": channel.id,
                "name": channel.name,
                "description": channel.description,
                "avatar_url": channel.avatar_url,
                "banner_url": channel.banner_url,
                "is_public": channel.is_public,
                "is_official": channel.is_official,
                "subscribers_count": subscribers_count,
                "is_subscribed": channel.id in subscribed_channel_ids,
                "created_at": channel.created_at.isoformat() if channel.created_at else None,
                "last_activity": channel.last_activity.isoformat() if channel.last_activity else None,
                "last_message": {
                    "content": last_message.content if last_message else None,
                    "timestamp": last_message.created_at.isoformat() if last_message else None
                } if last_message else None
            })
        
        return {
            "success": True,
            "channels": channels_data,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "pages": (total + limit - 1) // limit
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка загрузки каналов: {str(e)}")

# ========== ГРУППЫ ==========

@app.get("/api/groups")
async def get_groups(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """Получение списка групп"""
    try:
        user = get_current_user(request, db)
        if not user:
            # Возвращаем только публичные группы для неавторизованных
            query = db.query(Group).filter(Group.is_public == True)
            is_authenticated = False
        else:
            # Для авторизованных показываем их группы + публичные
            user_group_ids = [gm.group_id for gm in db.query(GroupMember).filter(GroupMember.user_id == user.id).all()]
            query = db.query(Group).filter(
                or_(
                    Group.id.in_(user_group_ids),
                    Group.is_public == True
                )
            )
            is_authenticated = True
        
        total = query.count()
        groups = query.order_by(desc(Group.last_activity)) \
                     .offset((page - 1) * limit) \
                     .limit(limit) \
                     .all()
        
        groups_data = []
        for group in groups:
            members_count = db.query(GroupMember).filter(GroupMember.group_id == group.id).count()
            
            last_message = db.query(Message).filter(Message.group_id == group.id) \
                .order_by(Message.created_at.desc()).first()
            
            group_info = {
                "id": group.id,
                "name": group.name,
                "description": group.description,
                "avatar_url": group.avatar_url,
                "banner_url": group.banner_url,
                "is_public": group.is_public,
                "max_members": group.max_members,
                "created_by": group.created_by,
                "created_at": group.created_at.isoformat() if group.created_at else None,
                "last_activity": group.last_activity.isoformat() if group.last_activity else None,
                "members_count": members_count,
                "last_message": {
                    "content": last_message.content if last_message else None,
                    "timestamp": last_message.created_at.isoformat() if last_message else None
                } if last_message else None
            }
            
            # Добавляем информацию о членстве для авторизованных
            if is_authenticated:
                membership = db.query(GroupMember).filter(
                    GroupMember.group_id == group.id,
                    GroupMember.user_id == user.id
                ).first()
                group_info["is_member"] = membership is not None
                group_info["my_role"] = membership.role if membership else None
            
            groups_data.append(group_info)
        
        return {
            "success": True,
            "groups": groups_data,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "pages": (total + limit - 1) // limit
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка загрузки групп: {str(e)}")

# ========== ВЕБ СТРАНИЦЫ ДЛЯ ФРОНТЕНДА ==========

@app.get("/register")
async def serve_register():
    """Страница регистрации"""
    register_path = frontend_dir / "register.html"
    if register_path.exists():
        return FileResponse(str(register_path))
    
    # Создаем простую страницу если файла нет
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>DevNet - Регистрация</title>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 20px;
            }
            .container {
                background: white;
                border-radius: 10px;
                box-shadow: 0 20px 60px rgba(0,0,0,0.3);
                padding: 40px;
                max-width: 400px;
                width: 100%;
            }
            h1 {
                color: #333;
                text-align: center;
                margin-bottom: 10px;
            }
            .subtitle {
                color: #666;
                text-align: center;
                margin-bottom: 30px;
            }
            .form-group {
                margin-bottom: 20px;
            }
            label {
                display: block;
                margin-bottom: 5px;
                color: #555;
                font-weight: 500;
            }
            input {
                width: 100%;
                padding: 12px;
                border: 2px solid #e0e0e0;
                border-radius: 5px;
                font-size: 16px;
                transition: border-color 0.3s;
                box-sizing: border-box;
            }
            input:focus {
                outline: none;
                border-color: #667eea;
            }
            button {
                width: 100%;
                padding: 14px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                border: none;
                border-radius: 5px;
                font-size: 16px;
                font-weight: 600;
                cursor: pointer;
                transition: transform 0.2s;
            }
            button:hover {
                transform: translateY(-2px);
            }
            .login-link {
                text-align: center;
                margin-top: 20px;
                color: #666;
            }
            .login-link a {
                color: #667eea;
                text-decoration: none;
                font-weight: 500;
            }
            .error {
                color: #e74c3c;
                font-size: 14px;
                margin-top: 5px;
            }
            .success {
                color: #27ae60;
                font-size: 14px;
                margin-top: 5px;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Регистрация</h1>
            <div class="subtitle">Присоединяйтесь к сообществу разработчиков</div>
            
            <form id="registerForm">
                <div class="form-group">
                    <label>Имя пользователя</label>
                    <input type="text" id="username" name="username" required>
                    <div id="usernameError" class="error"></div>
                </div>
                
                <div class="form-group">
                    <label>Email</label>
                    <input type="email" id="email" name="email" required>
                    <div id="emailError" class="error"></div>
                </div>
                
                <div class="form-group">
                    <label>Пароль</label>
                    <input type="password" id="password" name="password" required>
                    <div id="passwordError" class="error">Пароль должен быть от 6 до 72 символов</div>
                </div>
                
                <div class="form-group">
                    <label>Отображаемое имя (опционально)</label>
                    <input type="text" id="displayName" name="display_name">
                </div>
                
                <button type="submit">Создать аккаунт</button>
            </form>
            
            <div class="login-link">
                Уже есть аккаунт? <a href="/login">Войти</a>
            </div>
            
            <div id="message" class="error" style="margin-top: 15px;"></div>
        </div>
        
        <script>
            document.getElementById('registerForm').addEventListener('submit', async function(e) {
                e.preventDefault();
                
                // Сброс ошибок
                document.querySelectorAll('.error').forEach(el => el.textContent = '');
                document.getElementById('message').textContent = '';
                
                const formData = new FormData(this);
                
                try {
                    const response = await fetch('/api/auth/register', {
                        method: 'POST',
                        body: formData
                    });
                    
                    const result = await response.json();
                    
                    if (response.ok) {
                        document.getElementById('message').textContent = 'Регистрация успешна!';
                        document.getElementById('message').className = 'success';
                        
                        // Перенаправление через 2 секунды
                        setTimeout(() => {
                            window.location.href = '/chat';
                        }, 2000);
                    } else {
                        document.getElementById('message').textContent = result.detail || 'Ошибка регистрации';
                        document.getElementById('message').className = 'error';
                    }
                } catch (error) {
                    document.getElementById('message').textContent = 'Ошибка соединения';
                    document.getElementById('message').className = 'error';
                }
            });
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

@app.get("/login")
async def serve_login():
    """Страница входа"""
    login_path = frontend_dir / "login.html"
    if login_path.exists():
        return FileResponse(str(login_path))
    
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>DevNet - Вход</title>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 20px;
            }
            .container {
                background: white;
                border-radius: 10px;
                box-shadow: 0 20px 60px rgba(0,0,0,0.3);
                padding: 40px;
                max-width: 400px;
                width: 100%;
            }
            h1 {
                color: #333;
                text-align: center;
                margin-bottom: 10px;
            }
            .subtitle {
                color: #666;
                text-align: center;
                margin-bottom: 30px;
            }
            .form-group {
                margin-bottom: 20px;
            }
            label {
                display: block;
                margin-bottom: 5px;
                color: #555;
                font-weight: 500;
            }
            input {
                width: 100%;
                padding: 12px;
                border: 2px solid #e0e0e0;
                border-radius: 5px;
                font-size: 16px;
                transition: border-color 0.3s;
                box-sizing: border-box;
            }
            input:focus {
                outline: none;
                border-color: #667eea;
            }
            button {
                width: 100%;
                padding: 14px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                border: none;
                border-radius: 5px;
                font-size: 16px;
                font-weight: 600;
                cursor: pointer;
                transition: transform 0.2s;
            }
            button:hover {
                transform: translateY(-2px);
            }
            .register-link {
                text-align: center;
                margin-top: 20px;
                color: #666;
            }
            .register-link a {
                color: #667eea;
                text-decoration: none;
                font-weight: 500;
            }
            .error {
                color: #e74c3c;
                font-size: 14px;
                margin-top: 5px;
            }
            .success {
                color: #27ae60;
                font-size: 14px;
                margin-top: 5px;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Вход</h1>
            <div class="subtitle">Войдите в свой аккаунт DevNet</div>
            
            <form id="loginForm">
                <div class="form-group">
                    <label>Имя пользователя</label>
                    <input type="text" id="username" name="username" required>
                </div>
                
                <div class="form-group">
                    <label>Пароль</label>
                    <input type="password" id="password" name="password" required>
                </div>
                
                <button type="submit">Войти</button>
            </form>
            
            <div class="register-link">
                Нет аккаунта? <a href="/register">Зарегистрироваться</a>
            </div>
            
            <div id="message" class="error" style="margin-top: 15px;"></div>
        </div>
        
        <script>
            document.getElementById('loginForm').addEventListener('submit', async function(e) {
                e.preventDefault();
                document.getElementById('message').textContent = '';
                
                const formData = new FormData(this);
                
                try {
                    const response = await fetch('/api/auth/login', {
                        method: 'POST',
                        body: formData
                    });
                    
                    const result = await response.json();
                    
                    if (response.ok) {
                        document.getElementById('message').textContent = 'Вход выполнен успешно!';
                        document.getElementById('message').className = 'success';
                        
                        // Перенаправление через 1 секунду
                        setTimeout(() => {
                            window.location.href = '/chat';
                        }, 1000);
                    } else {
                        document.getElementById('message').textContent = result.detail || 'Ошибка входа';
                        document.getElementById('message').className = 'error';
                    }
                } catch (error) {
                    document.getElementById('message').textContent = 'Ошибка соединения';
                    document.getElementById('message').className = 'error';
                }
            });
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

@app.get("/chat")
async def serve_chat():
    """Страница чата"""
    chat_path = frontend_dir / "chat.html"
    if chat_path.exists():
        return FileResponse(str(chat_path))
    
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>DevNet - Чат</title>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                padding: 20px;
            }
            .app {
                display: flex;
                max-width: 1400px;
                margin: 0 auto;
                background: white;
                border-radius: 10px;
                box-shadow: 0 20px 60px rgba(0,0,0,0.3);
                overflow: hidden;
                height: calc(100vh - 40px);
            }
            /* Sidebar */
            .sidebar {
                width: 300px;
                background: #f8f9fa;
                border-right: 1px solid #e9ecef;
                display: flex;
                flex-direction: column;
            }
            .user-info {
                padding: 20px;
                background: white;
                border-bottom: 1px solid #e9ecef;
            }
            .user-avatar {
                width: 60px;
                height: 60px;
                border-radius: 50%;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 24px;
                font-weight: bold;
                margin-bottom: 10px;
            }
            .user-name {
                font-weight: 600;
                color: #333;
                margin-bottom: 5px;
            }
            .user-status {
                font-size: 14px;
                color: #28a745;
                display: flex;
                align-items: center;
            }
            .status-dot {
                width: 8px;
                height: 8px;
                background: #28a745;
                border-radius: 50%;
                margin-right: 5px;
            }
            /* Tabs */
            .tabs {
                display: flex;
                background: white;
                border-bottom: 1px solid #e9ecef;
            }
            .tab {
                flex: 1;
                padding: 15px;
                text-align: center;
                cursor: pointer;
                border-bottom: 3px solid transparent;
                transition: all 0.3s;
                font-weight: 500;
                color: #666;
            }
            .tab:hover {
                background: #f8f9fa;
            }
            .tab.active {
                color: #667eea;
                border-bottom-color: #667eea;
            }
            /* Chat List */
            .chat-list {
                flex: 1;
                overflow-y: auto;
            }
            .chat-item {
                padding: 15px 20px;
                border-bottom: 1px solid #e9ecef;
                cursor: pointer;
                transition: background 0.2s;
            }
            .chat-item:hover {
                background: #f8f9fa;
            }
            .chat-item.active {
                background: #e3f2fd;
            }
            .chat-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 5px;
            }
            .chat-name {
                font-weight: 600;
                color: #333;
            }
            .chat-time {
                font-size: 12px;
                color: #999;
            }
            .chat-preview {
                font-size: 14px;
                color: #666;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
            }
            /* Main Chat */
            .main-chat {
                flex: 1;
                display: flex;
                flex-direction: column;
                background: white;
            }
            .chat-header-bar {
                padding: 20px;
                border-bottom: 1px solid #e9ecef;
                display: flex;
                justify-content: space-between;
                align-items: center;
            }
            .current-chat-info {
                display: flex;
                align-items: center;
            }
            .chat-avatar {
                width: 40px;
                height: 40px;
                border-radius: 50%;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                display: flex;
                align-items: center;
                justify-content: center;
                font-weight: bold;
                margin-right: 10px;
            }
            .chat-title {
                font-weight: 600;
                color: #333;
                font-size: 18px;
            }
            .chat-subtitle {
                font-size: 14px;
                color: #666;
            }
            /* Messages */
            .messages-container {
                flex: 1;
                padding: 20px;
                overflow-y: auto;
                background: #f5f7fb;
            }
            .message {
                margin-bottom: 15px;
                max-width: 70%;
            }
            .message.sent {
                margin-left: auto;
            }
            .message-content {
                padding: 10px 15px;
                border-radius: 18px;
                background: white;
                box-shadow: 0 1px 2px rgba(0,0,0,0.1);
            }
            .message.sent .message-content {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
            }
            .message-time {
                font-size: 12px;
                color: #999;
                margin-top: 5px;
                text-align: right;
            }
            /* Message Input */
            .message-input-container {
                padding: 20px;
                border-top: 1px solid #e9ecef;
                display: flex;
                gap: 10px;
            }
            .message-input {
                flex: 1;
                padding: 12px 15px;
                border: 2px solid #e0e0e0;
                border-radius: 25px;
                font-size: 16px;
                outline: none;
                transition: border-color 0.3s;
            }
            .message-input:focus {
                border-color: #667eea;
            }
            .send-button {
                width: 50px;
                height: 50px;
                border-radius: 50%;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                border: none;
                display: flex;
                align-items: center;
                justify-content: center;
                cursor: pointer;
                transition: transform 0.2s;
            }
            .send-button:hover {
                transform: scale(1.05);
            }
            /* Empty State */
            .empty-state {
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                height: 100%;
                color: #666;
                text-align: center;
                padding: 40px;
            }
            .empty-icon {
                font-size: 48px;
                margin-bottom: 20px;
            }
            .empty-title {
                font-size: 24px;
                font-weight: 600;
                margin-bottom: 10px;
                color: #333;
            }
            .empty-description {
                font-size: 16px;
                margin-bottom: 30px;
                max-width: 400px;
            }
            /* Auth State */
            .auth-state {
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                height: 100%;
                padding: 40px;
                text-align: center;
            }
            .auth-state h2 {
                margin-bottom: 20px;
                color: #333;
            }
            .auth-buttons {
                display: flex;
                gap: 15px;
                margin-top: 20px;
            }
            .auth-button {
                padding: 12px 30px;
                border-radius: 25px;
                font-size: 16px;
                font-weight: 600;
                cursor: pointer;
                transition: transform 0.2s;
                text-decoration: none;
            }
            .auth-button.primary {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                border: none;
            }
            .auth-button.secondary {
                background: white;
                color: #667eea;
                border: 2px solid #667eea;
            }
        </style>
    </head>
    <body>
        <div class="app">
            <div class="sidebar">
                <div class="user-info">
                    <div class="user-avatar" id="userAvatar">U</div>
                    <div class="user-name" id="userName">Гость</div>
                    <div class="user-status" id="userStatus">
                        <span class="status-dot"></span>
                        <span>Не в сети</span>
                    </div>
                </div>
                
                <div class="tabs">
                    <div class="tab active" onclick="showTab('private')">Чаты</div>
                    <div class="tab" onclick="showTab('groups')">Группы</div>
                    <div class="tab" onclick="showTab('channels')">Каналы</div>
                </div>
                
                <div class="chat-list" id="chatList">
                    <!-- Список чатов будет загружен здесь -->
                </div>
            </div>
            
            <div class="main-chat">
                <div class="chat-header-bar">
                    <div class="current-chat-info">
                        <div class="chat-avatar" id="currentChatAvatar">C</div>
                        <div>
                            <div class="chat-title" id="currentChatTitle">Выберите чат</div>
                            <div class="chat-subtitle" id="currentChatSubtitle">Начните общение</div>
                        </div>
                    </div>
                </div>
                
                <div class="messages-container" id="messagesContainer">
                    <div class="empty-state" id="emptyState">
                        <div class="empty-icon">💬</div>
                        <div class="empty-title">Выберите чат</div>
                        <div class="empty-description">
                            Выберите чат из списка слева чтобы начать общение
                        </div>
                    </div>
                </div>
                
                <div class="message-input-container">
                    <input type="text" class="message-input" id="messageInput" placeholder="Введите сообщение..." disabled>
                    <button class="send-button" id="sendButton" disabled>→</button>
                </div>
            </div>
        </div>
        
        <script>
            let currentUser = null;
            let currentChat = null;
            let ws = null;
            let currentTab = 'private';
            
            // Загрузка информации о пользователе
            async function loadUserInfo() {
                try {
                    const response = await fetch('/api/auth/me');
                    if (response.ok) {
                        const data = await response.json();
                        currentUser = data.user;
                        
                        // Обновление интерфейса
                        document.getElementById('userAvatar').textContent = 
                            currentUser.display_name?.charAt(0) || currentUser.username.charAt(0);
                        document.getElementById('userName').textContent = currentUser.display_name || currentUser.username;
                        document.getElementById('userStatus').innerHTML = '<span class="status-dot"></span><span>В сети</span>';
                        
                        // Подключение WebSocket
                        connectWebSocket();
                        
                        // Загрузка чатов
                        loadChats();
                        
                        return true;
                    } else {
                        showAuthState();
                        return false;
                    }
                } catch (error) {
                    showAuthState();
                    return false;
                }
            }
            
            // Показать состояние авторизации
            function showAuthState() {
                const chatList = document.getElementById('chatList');
                chatList.innerHTML = `
                    <div class="auth-state">
                        <h2>Требуется авторизация</h2>
                        <p>Войдите или зарегистрируйтесь чтобы использовать чат</p>
                        <div class="auth-buttons">
                            <a href="/login" class="auth-button primary">Войти</a>
                            <a href="/register" class="auth-button secondary">Регистрация</a>
                        </div>
                    </div>
                `;
                
                document.getElementById('emptyState').innerHTML = `
                    <div class="auth-state">
                        <h2>Добро пожаловать в DevNet!</h2>
                        <p>Общайтесь с коллегами в реальном времени</p>
                        <div class="features" style="margin-top: 30px; text-align: left;">
                            <div style="margin-bottom: 10px;">⚡ <b>Real-time чат</b> - Мгновенная отправка сообщений через WebSocket</div>
                            <div style="margin-bottom: 10px;">👥 <b>Группы</b> - Создавайте группы для общения с командой</div>
                            <div style="margin-bottom: 10px;">🖼️ <b>Файлы</b> - Отправляйте изображения и документы</div>
                        </div>
                        <div class="auth-buttons">
                            <a href="/login" class="auth-button primary">Войти</a>
                            <a href="/register" class="auth-button secondary">Зарегистрироваться</a>
                        </div>
                    </div>
                `;
            }
            
            // Подключение WebSocket
            function connectWebSocket() {
                if (!currentUser || ws) return;
                
                ws = new WebSocket(`ws://${window.location.host}/ws/${currentUser.id}`);
                
                ws.onopen = function() {
                    console.log('WebSocket connected');
                    updateOnlineStatus(true);
                };
                
                ws.onmessage = function(event) {
                    const data = JSON.parse(event.data);
                    handleWebSocketMessage(data);
                };
                
                ws.onclose = function() {
                    console.log('WebSocket disconnected');
                    updateOnlineStatus(false);
                    // Попытка переподключения через 5 секунд
                    setTimeout(() => {
                        if (currentUser) connectWebSocket();
                    }, 5000);
                };
            }
            
            // Обновление статуса онлайн
            function updateOnlineStatus(isOnline) {
                const statusElement = document.getElementById('userStatus');
                if (isOnline) {
                    statusElement.innerHTML = '<span class="status-dot"></span><span>В сети</span>';
                } else {
                    statusElement.innerHTML = '<span class="status-dot" style="background: #dc3545;"></span><span>Не в сети</span>';
                }
            }
            
            // Загрузка чатов
            async function loadChats() {
                try {
                    const response = await fetch('/api/chats/all');
                    if (response.ok) {
                        const data = await response.json();
                        displayChats(data);
                    }
                } catch (error) {
                    console.error('Ошибка загрузки чатов:', error);
                }
            }
            
            // Отображение чатов
            function displayChats(data) {
                const chatList = document.getElementById('chatList');
                let html = '';
                
                if (currentTab === 'private') {
                    if (data.private_chats && data.private_chats.length > 0) {
                        data.private_chats.forEach(chat => {
                            html += createChatItem(chat, 'private');
                        });
                    } else {
                        html = '<div style="padding: 20px; color: #666; text-align: center;">Нет личных чатов</div>';
                    }
                } else if (currentTab === 'groups') {
                    if (data.group_chats && data.group_chats.length > 0) {
                        data.group_chats.forEach(chat => {
                            html += createChatItem(chat, 'group');
                        });
                    } else {
                        html = '<div style="padding: 20px; color: #666; text-align: center;">Нет групп</div>';
                    }
                } else if (currentTab === 'channels') {
                    if (data.channel_chats && data.channel_chats.length > 0) {
                        data.channel_chats.forEach(chat => {
                            html += createChatItem(chat, 'channel');
                        });
                    } else {
                        html = '<div style="padding: 20px; color: #666; text-align: center;">Нет каналов</div>';
                    }
                }
                
                chatList.innerHTML = html;
            }
            
            // Создание элемента чата
            function createChatItem(chat, type) {
                const lastMsg = chat.last_message ? `
                    <div class="chat-time">${formatTime(chat.last_message.timestamp)}</div>
                    <div class="chat-preview">${chat.last_message.content || ''}</div>
                ` : '';
                
                return `
                    <div class="chat-item" onclick="selectChat(${chat.id}, '${type}')">
                        <div class="chat-header">
                            <div class="chat-name">${chat.name}</div>
                            ${chat.last_message ? `<div class="chat-time">${formatTime(chat.last_message.timestamp)}</div>` : ''}
                        </div>
                        ${lastMsg}
                    </div>
                `;
            }
            
            // Выбор чата
            async function selectChat(chatId, type) {
                currentChat = { id: chatId, type: type };
                
                // Обновление интерфейса
                document.querySelectorAll('.chat-item').forEach(item => item.classList.remove('active'));
                event.currentTarget.classList.add('active');
                
                // Загрузка информации о чате
                await loadChatInfo(chatId, type);
                
                // Загрузка сообщений
                await loadMessages(chatId, type);
                
                // Активация поля ввода
                document.getElementById('messageInput').disabled = false;
                document.getElementById('sendButton').disabled = false;
                document.getElementById('messageInput').focus();
            }
            
            // Загрузка информации о чате
            async function loadChatInfo(chatId, type) {
                let title = '';
                let subtitle = '';
                
                if (type === 'private') {
                    // Для приватного чата загружаем информацию о пользователе
                    try {
                        const response = await fetch('/api/users');
                        if (response.ok) {
                            const data = await response.json();
                            const user = data.users.find(u => u.id === chatId);
                            if (user) {
                                title = user.display_name || user.username;
                                subtitle = user.is_online ? 'В сети' : 'Не в сети';
                            }
                        }
                    } catch (error) {
                        console.error('Ошибка загрузки информации о пользователе:', error);
                    }
                } else if (type === 'group') {
                    title = `Группа #${chatId}`;
                    subtitle = 'Групповой чат';
                } else if (type === 'channel') {
                    title = `Канал #${chatId}`;
                    subtitle = 'Канал';
                }
                
                document.getElementById('currentChatTitle').textContent = title;
                document.getElementById('currentChatSubtitle').textContent = subtitle;
                document.getElementById('currentChatAvatar').textContent = title.charAt(0);
                
                // Скрываем пустое состояние
                document.getElementById('emptyState').style.display = 'none';
            }
            
            // Загрузка сообщений
            async function loadMessages(chatId, type) {
                try {
                    const response = await fetch(`/api/messages/chat/${type}/${chatId}`);
                    if (response.ok) {
                        const data = await response.json();
                        displayMessages(data.messages);
                    }
                } catch (error) {
                    console.error('Ошибка загрузки сообщений:', error);
                }
            }
            
            // Отображение сообщений
            function displayMessages(messages) {
                const container = document.getElementById('messagesContainer');
                let html = '';
                
                messages.forEach(msg => {
                    const isSent = msg.from_user_id === currentUser?.id;
                    const time = msg.created_at ? formatTime(msg.created_at) : '';
                    
                    html += `
                        <div class="message ${isSent ? 'sent' : 'received'}">
                            <div class="message-content">${msg.content || ''}</div>
                            <div class="message-time">${time}</div>
                        </div>
                    `;
                });
                
                container.innerHTML = html;
                container.scrollTop = container.scrollHeight;
            }
            
            // Отправка сообщения
            async function sendMessage() {
                const input = document.getElementById('messageInput');
                const content = input.value.trim();
                
                if (!content || !currentChat || !ws || ws.readyState !== WebSocket.OPEN) return;
                
                const message = {
                    type: 'message',
                    chat_type: currentChat.type,
                    chat_id: currentChat.id,
                    content: content
                };
                
                ws.send(JSON.stringify(message));
                
                // Добавление сообщения в интерфейс
                const container = document.getElementById('messagesContainer');
                const time = new Date().toISOString();
                
                container.innerHTML += `
                    <div class="message sent">
                        <div class="message-content">${content}</div>
                        <div class="message-time">${formatTime(time)}</div>
                    </div>
                `;
                
                input.value = '';
                container.scrollTop = container.scrollHeight;
            }
            
            // Обработка сообщений WebSocket
            function handleWebSocketMessage(data) {
                if (data.type === 'message' && currentChat && 
                    ((currentChat.type === 'private' && data.to_user_id === currentUser?.id) ||
                     (currentChat.type === 'group' && data.group_id === currentChat.id) ||
                     (currentChat.type === 'channel' && data.channel_id === currentChat.id))) {
                    
                    const container = document.getElementById('messagesContainer');
                    const time = data.timestamp || new Date().toISOString();
                    
                    container.innerHTML += `
                        <div class="message received">
                            <div class="message-content">${data.content || ''}</div>
                            <div class="message-time">${formatTime(time)}</div>
                        </div>
                    `;
                    
                    container.scrollTop = container.scrollHeight;
                }
            }
            
            // Форматирование времени
            function formatTime(isoString) {
                const date = new Date(isoString);
                return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            }
            
            // Показать вкладку
            function showTab(tab) {
                currentTab = tab;
                
                // Обновление активной вкладки
                document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
                event.currentTarget.classList.add('active');
                
                // Перезагрузка чатов
                if (currentUser) {
                    loadChats();
                }
            }
            
            // Инициализация
            document.addEventListener('DOMContentLoaded', async () => {
                // Загрузка пользователя
                const isAuthenticated = await loadUserInfo();
                
                if (isAuthenticated) {
                    // Настройка отправки сообщения
                    document.getElementById('sendButton').onclick = sendMessage;
                    document.getElementById('messageInput').onkeypress = function(e) {
                        if (e.key === 'Enter') sendMessage();
                    };
                }
            });
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

# ========== ЗАПУСК СЕРВЕРА ==========

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"🚀 Запуск DevNet Messenger API на порту {port}")
    print(f"📁 Директория загрузок: {UPLOAD_DIR}")
    print(f"📁 Директория фронтенда: {frontend_dir}")
    print(f"📱 Документация API: http://localhost:{port}/api/docs")
    print(f"🐛 Диагностика: http://localhost:{port}/api/debug")
    print(f"📝 Регистрация: http://localhost:{port}/register")
    print(f"🔐 Вход: http://localhost:{port}/login")
    print(f"💬 Чат: http://localhost:{port}/chat")
    print("👑 Администратор: admin / admin123")
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=False
    )
