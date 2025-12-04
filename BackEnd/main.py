from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, status, Form, Request, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
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

# Добавляем путь для импорта модулей
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from websocket_manager import manager
    from database import engine, SessionLocal, get_db
    from models import Base, User, Message, Group, GroupMember, File as FileModel
    from auth import create_access_token, verify_token, verify_password, get_password_hash
    print("✅ Все модули успешно импортированы")
except ImportError as e:
    print(f"❌ Ошибка импорта: {e}")
    raise

# ========== ИНИЦИАЛИЗАЦИЯ ==========

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="DevNet Messenger API",
    description="API для мессенджера DevNet с поддержкой WebSocket",
    version="4.0.0",
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

# Создаем директории
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)
(UPLOAD_DIR / "images").mkdir(exist_ok=True)

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
    
    # Монтируем статические файлы
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")
    print("✅ Статические файлы подключены")
else:
    print(f"⚠️  Фронтенд не найден: {frontend_dir}")

# Монтируем директорию загрузок
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

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

def validate_username(username: str) -> tuple[bool, str]:
    """Проверяет валидность имени пользователя"""
    if len(username) < 3:
        return False, "Имя пользователя должно быть не менее 3 символов"
    if len(username) > 50:
        return False, "Имя пользователя должно быть не более 50 символов"
    if not re.match(r'^[a-zA-Z0-9_.-]+$', username):
        return False, "Имя пользователя может содержать только буквы, цифры, точки, дефисы и подчеркивания"
    return True, ""

def validate_email(email: str) -> tuple[bool, str]:
    """Проверяет валидность email"""
    if len(email) > 100:
        return False, "Email слишком длинный"
    
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(pattern, email):
        return False, "Неверный формат email"
    
    return True, ""

def validate_password(password: str) -> tuple[bool, str]:
    """Проверяет валидность пароля"""
    if len(password) < 6:
        return False, "Пароль должен содержать минимум 6 символов"
    if len(password) > 72:
        return False, "Пароль слишком длинный (максимум 72 символа)"
    return True, ""

def generate_guest_username() -> str:
    """Генерирует уникальное имя для гостя"""
    adjectives = ["Быстрый", "Умный", "Яркий", "Смелый", "Ловкий", "Храбрый", "Мудрый", "Сильный"]
    nouns = ["Тигр", "Орел", "Волк", "Лев", "Медведь", "Сокол", "Ястреб", "Феникс"]
    
    adjective = random.choice(adjectives)
    noun = random.choice(nouns)
    number = random.randint(1000, 9999)
    
    return f"{adjective}{noun}{number}"

# ========== API ENDPOINTS ==========

@app.get("/")
async def root():
    """Главная страница - перенаправляет на страницу авторизации"""
    return RedirectResponse("/index.html")

@app.get("/api/health")
async def health_check():
    """Проверка здоровья API"""
    return {
        "status": "healthy",
        "service": "DevNet Messenger API",
        "version": "4.0.0",
        "timestamp": datetime.utcnow().isoformat(),
        "database": "connected",
        "features": ["auth", "websocket", "groups", "file_upload"]
    }

# ========== АУТЕНТИФИКАЦИЯ ==========

@app.post("/api/register")
async def register_user(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    display_name: str = Form(None),
    db: Session = Depends(get_db)
):
    """Регистрация нового пользователя"""
    try:
        print(f"🔧 Попытка регистрации: {username}")
        
        # Валидация данных
        username_valid, username_error = validate_username(username)
        if not username_valid:
            return JSONResponse(
                status_code=400,
                content={"success": False, "detail": username_error}
            )
        
        email_valid, email_error = validate_email(email)
        if not email_valid:
            return JSONResponse(
                status_code=400,
                content={"success": False, "detail": email_error}
            )
        
        password_valid, password_error = validate_password(password)
        if not password_valid:
            return JSONResponse(
                status_code=400,
                content={"success": False, "detail": password_error}
            )
        
        # Проверяем, существует ли пользователь
        existing_user = db.query(User).filter(
            (User.username == username) | (User.email == email)
        ).first()
        
        if existing_user:
            if existing_user.username == username:
                return JSONResponse(
                    status_code=400,
                    content={"success": False, "detail": "Имя пользователя уже занято"}
                )
            else:
                return JSONResponse(
                    status_code=400,
                    content={"success": False, "detail": "Email уже используется"}
                )
        
        # Создаем нового пользователя
        db_user = User(
            username=username,
            email=email,
            display_name=display_name or username,
            password_hash=get_password_hash(password),  # Используем безопасное хеширование
            is_online=False,
            is_guest=False,
            last_login=datetime.utcnow()
        )
        
        db.add(db_user)
        db.commit()
        db.refresh(db_user)
        
        print(f"✅ Пользователь зарегистрирован: {username}")
        
        # Создаем токен
        access_token = create_access_token(
            data={
                "sub": username,
                "user_id": db_user.id,
                "is_guest": False
            }
        )
        
        response_data = {
            "success": True,
            "user": {
                "id": db_user.id,
                "username": db_user.username,
                "display_name": db_user.display_name,
                "email": db_user.email,
                "is_guest": db_user.is_guest
            },
            "message": "Регистрация успешна!"
        }
        
        response = JSONResponse(response_data)
        
        # Устанавливаем токен в cookie
        response.set_cookie(
            key="access_token",
            value=access_token,
            httponly=True,
            max_age=7 * 24 * 60 * 60,  # 7 дней
            secure=request.url.scheme == "https",
            samesite="lax",
            path="/"
        )
        
        return response
        
    except Exception as e:
        print(f"❌ Ошибка регистрации: {e}")
        db.rollback()
        return JSONResponse(
            status_code=500,
            content={"success": False, "detail": f"Ошибка сервера: {str(e)}"}
        )

@app.post("/api/login")
async def login_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    """Вход пользователя"""
    try:
        print(f"🔧 Попытка входа: {username}")
        
        # Ищем пользователя по username
        user = db.query(User).filter(User.username == username).first()
        
        # Если не нашли по username, пробуем найти по email
        if not user:
            user = db.query(User).filter(User.email == username).first()
        
        if not user:
            return JSONResponse(
                status_code=401,
                content={"success": False, "detail": "Неверное имя пользователя или пароль"}
            )
        
        # Проверяем пароль
        if not verify_password(password, user.password_hash):
            return JSONResponse(
                status_code=401,
                content={"success": False, "detail": "Неверное имя пользователя или пароль"}
            )
        
        # Обновляем время последнего входа
        user.is_online = True
        user.last_login = datetime.utcnow()
        db.commit()
        
        print(f"✅ Пользователь вошел: {username}")
        
        # Создаем токен
        access_token = create_access_token(
            data={
                "sub": user.username,
                "user_id": user.id,
                "is_guest": user.is_guest
            }
        )
        
        response_data = {
            "success": True,
            "user": {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "email": user.email,
                "is_guest": user.is_guest
            },
            "message": "Вход выполнен успешно!"
        }
        
        response = JSONResponse(response_data)
        
        # Устанавливаем токен в cookie
        response.set_cookie(
            key="access_token",
            value=access_token,
            httponly=True,
            max_age=7 * 24 * 60 * 60,
            secure=request.url.scheme == "https",
            samesite="lax",
            path="/"
        )
        
        return response
        
    except Exception as e:
        print(f"❌ Ошибка входа: {e}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "detail": f"Ошибка сервера: {str(e)}"}
        )

@app.post("/api/logout")
async def logout_user(request: Request, db: Session = Depends(get_db)):
    """Выход пользователя"""
    try:
        token = request.cookies.get("access_token")
        if token:
            payload = verify_token(token)
            if payload:
                user_id = payload.get("user_id")
                if user_id:
                    user = db.query(User).filter(User.id == user_id).first()
                    if user:
                        user.is_online = False
                        db.commit()
                        print(f"✅ Пользователь вышел: {user.username}")
        
        response = JSONResponse({"success": True, "message": "Выход выполнен успешно"})
        response.delete_cookie("access_token", path="/")
        return response
        
    except Exception as e:
        print(f"❌ Ошибка выхода: {e}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "detail": f"Ошибка выхода: {str(e)}"}
        )

@app.post("/api/auto-login")
async def auto_login_user(
    request: Request,
    db: Session = Depends(get_db)
):
    """Автоматический вход/регистрация гостя"""
    try:
        print("🔧 Попытка автоматического входа")
        
        # Проверяем существующий токен
        token = request.cookies.get("access_token")
        if token:
            payload = verify_token(token)
            if payload:
                user_id = payload.get("user_id")
                if user_id:
                    user = db.query(User).filter(User.id == user_id).first()
                    if user:
                        return JSONResponse({
                            "success": True,
                            "user": {
                                "id": user.id,
                                "username": user.username,
                                "display_name": user.display_name,
                                "is_guest": user.is_guest
                            },
                            "message": "Пользователь уже авторизован"
                        })
        
        # Создаем гостевого пользователя
        username = generate_guest_username()
        email = f"{username}@guest.devnet.com"
        display_name = f"Гость {random.randint(1000, 9999)}"
        
        # Проверяем уникальность
        existing = db.query(User).filter(User.username == username).first()
        if existing:
            username = f"{username}_{random.randint(100, 999)}"
        
        # Создаем безопасный пароль для гостя
        guest_password = str(uuid.uuid4())[:20]
        
        db_user = User(
            username=username,
            email=email,
            display_name=display_name,
            password_hash=get_password_hash(guest_password),
            is_online=True,
            is_guest=True
        )
        
        db.add(db_user)
        db.commit()
        db.refresh(db_user)
        
        print(f"✅ Гостевой пользователь создан: {username}")
        
        # Создаем токен
        access_token = create_access_token(
            data={
                "sub": username,
                "user_id": db_user.id,
                "is_guest": True
            }
        )
        
        response_data = {
            "success": True,
            "user": {
                "id": db_user.id,
                "username": db_user.username,
                "display_name": db_user.display_name,
                "is_guest": db_user.is_guest
            },
            "message": "Гостевой аккаунт создан"
        }
        
        response = JSONResponse(response_data)
        
        # Устанавливаем токен в cookie
        response.set_cookie(
            key="access_token",
            value=access_token,
            httponly=True,
            max_age=7 * 24 * 60 * 60,
            secure=request.url.scheme == "https",
            samesite="lax",
            path="/"
        )
        
        return response
        
    except Exception as e:
        print(f"❌ Ошибка автоматического входа: {e}")
        db.rollback()
        return JSONResponse(
            status_code=500,
            content={"success": False, "detail": f"Ошибка создания аккаунта: {str(e)}"}
        )

@app.get("/api/me")
async def get_current_user_info(
    request: Request,
    db: Session = Depends(get_db)
):
    """Получение информации о текущем пользователе"""
    try:
        token = request.cookies.get("access_token")
        if not token:
            raise HTTPException(
                status_code=401, 
                detail="Требуется аутентификация",
                headers={"WWW-Authenticate": "Bearer"}
            )
        
        payload = verify_token(token)
        if not payload:
            raise HTTPException(
                status_code=401, 
                detail="Недействительный токен",
                headers={"WWW-Authenticate": "Bearer"}
            )
        
        user_id = payload.get("user_id")
        if not user_id:
            raise HTTPException(
                status_code=401, 
                detail="Неверный токен",
                headers={"WWW-Authenticate": "Bearer"}
            )
        
        user = db.query(User).filter(User.id == user_id).first()
        
        if not user:
            raise HTTPException(
                status_code=404, 
                detail="Пользователь не найден"
            )
        
        return {
            "success": True,
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "display_name": user.display_name,
                "is_online": user.is_online,
                "is_guest": user.is_guest,
                "last_login": user.last_login.isoformat() if user.last_login else None,
                "created_at": user.created_at.isoformat() if user.created_at else None
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Ошибка сервера: {str(e)}"
        )

# ========== ПОЛЬЗОВАТЕЛИ ==========

@app.get("/api/users")
async def get_all_users(
    request: Request,
    db: Session = Depends(get_db)
):
    """Получение списка всех пользователей"""
    try:
        # Проверяем авторизацию
        token = request.cookies.get("access_token")
        if not token:
            raise HTTPException(
                status_code=401, 
                detail="Требуется аутентификация",
                headers={"WWW-Authenticate": "Bearer"}
            )
        
        payload = verify_token(token)
        if not payload:
            raise HTTPException(
                status_code=401, 
                detail="Недействительный токен",
                headers={"WWW-Authenticate": "Bearer"}
            )
        
        current_user_id = payload.get("user_id")
        users = db.query(User).filter(User.id != current_user_id).all()
        
        return {
            "success": True,
            "users": [
                {
                    "id": user.id,
                    "username": user.username,
                    "display_name": user.display_name,
                    "email": user.email,
                    "is_online": user.is_online,
                    "is_guest": user.is_guest,
                    "last_login": user.last_login.isoformat() if user.last_login else None
                }
                for user in users
            ]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Ошибка сервера: {str(e)}"
        )

# ========== ГРУППЫ ==========

@app.post("/api/groups")
async def create_group(
    name: str = Form(...),
    description: str = Form(None),
    request: Request = None,
    db: Session = Depends(get_db)
):
    """Создание новой группы"""
    try:
        # Проверяем авторизацию
        token = request.cookies.get("access_token") if request else None
        if not token:
            raise HTTPException(
                status_code=401, 
                detail="Требуется аутентификация"
            )
        
        payload = verify_token(token)
        if not payload:
            raise HTTPException(
                status_code=401, 
                detail="Недействительный токен"
            )
        
        user_id = payload.get("user_id")
        
        # Создаем группу
        group = Group(
            name=name,
            description=description,
            created_by=user_id
        )
        
        db.add(group)
        db.commit()
        db.refresh(group)
        
        # Добавляем создателя в группу
        group_member = GroupMember(
            group_id=group.id,
            user_id=user_id
        )
        db.add(group_member)
        db.commit()
        
        return {
            "success": True,
            "group": {
                "id": group.id,
                "name": group.name,
                "description": group.description,
                "created_by": group.created_by,
                "created_at": group.created_at.isoformat() if group.created_at else None
            },
            "message": "Группа создана успешно"
        }
        
    except Exception as e:
        db.rollback()
        return JSONResponse(
            status_code=500,
            content={"success": False, "detail": f"Ошибка создания группы: {str(e)}"}
        )

@app.get("/api/groups")
async def get_groups(
    request: Request,
    db: Session = Depends(get_db)
):
    """Получение списка групп пользователя"""
    try:
        token = request.cookies.get("access_token")
        if not token:
            raise HTTPException(
                status_code=401, 
                detail="Требуется аутентификация"
            )
        
        payload = verify_token(token)
        if not payload:
            raise HTTPException(
                status_code=401, 
                detail="Недействительный токен"
            )
        
        user_id = payload.get("user_id")
        
        # Получаем группы пользователя
        groups = db.query(Group).join(GroupMember).filter(GroupMember.user_id == user_id).all()
        
        groups_data = []
        for group in groups:
            members_count = db.query(GroupMember).filter(GroupMember.group_id == group.id).count()
            groups_data.append({
                "id": group.id,
                "name": group.name,
                "description": group.description,
                "created_by": group.created_by,
                "created_at": group.created_at.isoformat() if group.created_at else None,
                "members_count": members_count
            })
        
        return {
            "success": True,
            "groups": groups_data
        }
        
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "detail": f"Ошибка загрузки групп: {str(e)}"}
        )

# ========== СООБЩЕНИЯ ==========

@app.get("/api/messages/{user_id}/{other_user_id}")
async def get_message_history(
    user_id: int,
    other_user_id: int,
    db: Session = Depends(get_db)
):
    """Получение истории сообщений между двумя пользователями"""
    try:
        messages = db.query(Message).filter(
            ((Message.from_user_id == user_id) & (Message.to_user_id == other_user_id)) |
            ((Message.from_user_id == other_user_id) & (Message.to_user_id == user_id))
        ).order_by(Message.created_at.asc()).all()
        
        return [
            {
                "id": msg.id,
                "from_user_id": msg.from_user_id,
                "to_user_id": msg.to_user_id,
                "content": msg.content,
                "type": msg.message_type,
                "file_url": msg.file_url,
                "timestamp": msg.created_at.isoformat(),
                "is_my_message": msg.from_user_id == user_id
            }
            for msg in messages
        ]
        
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"detail": f"Ошибка загрузки истории сообщений: {str(e)}"}
        )

@app.get("/api/chats")
async def get_all_chats(
    request: Request,
    db: Session = Depends(get_db)
):
    """Получение всех чатов пользователя"""
    try:
        token = request.cookies.get("access_token")
        if not token:
            raise HTTPException(
                status_code=401, 
                detail="Требуется аутентификация"
            )
        
        payload = verify_token(token)
        if not payload:
            raise HTTPException(
                status_code=401, 
                detail="Недействительный токен"
            )
        
        current_user_id = payload.get("user_id")
        
        # Получаем личные чаты
        private_chats = []
        users = db.query(User).filter(User.id != current_user_id).all()
        
        for user in users:
            # Проверяем, есть ли сообщения
            messages_count = db.query(Message).filter(
                ((Message.from_user_id == current_user_id) & (Message.to_user_id == user.id)) |
                ((Message.from_user_id == user.id) & (Message.to_user_id == current_user_id))
            ).count()
            
            if messages_count > 0:
                # Получаем последнее сообщение
                last_message = db.query(Message).filter(
                    ((Message.from_user_id == current_user_id) & (Message.to_user_id == user.id)) |
                    ((Message.from_user_id == user.id) & (Message.to_user_id == current_user_id))
                ).order_by(Message.created_at.desc()).first()
                
                private_chats.append({
                    "id": user.id,
                    "name": user.display_name or user.username,
                    "type": "private",
                    "username": user.username,
                    "is_online": user.is_online,
                    "last_message": {
                        "content": last_message.content if last_message else None,
                        "timestamp": last_message.created_at.isoformat() if last_message else None
                    } if last_message else None
                })
        
        # Получаем группы
        groups = db.query(Group).join(GroupMember).filter(GroupMember.user_id == current_user_id).all()
        group_chats = []
        
        for group in groups:
            members_count = db.query(GroupMember).filter(GroupMember.group_id == group.id).count()
            
            # Получаем последнее сообщение
            last_message = db.query(Message).filter(Message.group_id == group.id)\
                .order_by(Message.created_at.desc()).first()
            
            group_chats.append({
                "id": group.id,
                "name": group.name,
                "description": group.description,
                "type": "group",
                "members_count": members_count,
                "last_message": {
                    "content": last_message.content if last_message else None,
                    "timestamp": last_message.created_at.isoformat() if last_message else None
                } if last_message else None
            })
        
        return {
            "success": True,
            "private_chats": private_chats,
            "group_chats": group_chats
        }
        
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "detail": f"Ошибка загрузки чатов: {str(e)}"}
        )

# ========== ФАЙЛЫ ==========

@app.post("/api/upload")
async def upload_file(
    file: UploadFile = File(...),
    request: Request = None,
    db: Session = Depends(get_db)
):
    """Загрузка файла"""
    try:
        # Проверяем авторизацию
        token = request.cookies.get("access_token") if request else None
        if not token:
            raise HTTPException(
                status_code=401, 
                detail="Требуется аутентификация"
            )
        
        payload = verify_token(token)
        if not payload:
            raise HTTPException(
                status_code=401, 
                detail="Недействительный токен"
            )
        
        user_id = payload.get("user_id")
        
        # Определяем тип файла
        file_type = "file"
        if file.content_type and file.content_type.startswith("image/"):
            file_type = "image"
        
        # Проверяем размер (максимум 10MB)
        MAX_SIZE = 10 * 1024 * 1024
        file.file.seek(0, 2)
        file_size = file.file.tell()
        file.file.seek(0)
        
        if file_size > MAX_SIZE:
            return JSONResponse(
                status_code=400,
                content={"success": False, "detail": "Файл слишком большой (максимум 10MB)"}
            )
        
        # Генерируем уникальное имя
        file_extension = ""
        if '.' in file.filename:
            file_extension = file.filename.split('.')[-1]
        
        unique_filename = f"{uuid.uuid4()}"
        if file_extension:
            unique_filename += f".{file_extension}"
        
        # Сохраняем файл
        save_dir = UPLOAD_DIR / f"{file_type}s"
        save_dir.mkdir(exist_ok=True)
        save_path = save_dir / unique_filename
        
        with open(save_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # Сохраняем в базу
        db_file = FileModel(
            filename=unique_filename,
            original_filename=file.filename,
            file_type=file_type,
            file_size=file_size,
            uploaded_by=user_id,
            url=f"/uploads/{file_type}s/{unique_filename}"
        )
        
        db.add(db_file)
        db.commit()
        db.refresh(db_file)
        
        return {
            "success": True,
            "file": {
                "id": db_file.id,
                "url": db_file.url,
                "filename": db_file.original_filename,
                "type": db_file.file_type,
                "size": db_file.file_size
            }
        }
        
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "detail": f"Ошибка загрузки файла: {str(e)}"}
        )

# ========== WEB SOCKET ==========

@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: int):
    """WebSocket endpoint для реального времени"""
    await manager.connect(websocket, user_id)
    
    # Обновляем статус пользователя
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            user.is_online = True
            db.commit()
    except:
        pass
    finally:
        db.close()
    
    try:
        while True:
            data = await websocket.receive_text()
            message_data = json.loads(data)
            message_type = message_data.get("type", "message")
            
            print(f"📨 WebSocket сообщение от {user_id}: {message_type}")
            
            if message_type == "message":
                await handle_text_message(message_data, user_id)
            elif message_type == "file_message":
                await handle_file_message(message_data, user_id)
            elif message_type == "typing":
                await handle_typing_indicator(message_data, user_id)
            elif message_type == "group_message":
                await handle_group_message(message_data, user_id)
                
    except WebSocketDisconnect:
        print(f"📴 Пользователь отключился: {user_id}")
        
        # Обновляем статус
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if user:
                user.is_online = False
                db.commit()
        except:
            pass
        finally:
            db.close()
        
        manager.disconnect(user_id)

async def handle_text_message(message_data: dict, sender_id: int):
    """Обработка текстовых сообщений"""
    db = SessionLocal()
    try:
        receiver_id = message_data.get("to_user_id")
        group_id = message_data.get("group_id")
        content = message_data.get("content", "").strip()
        
        if not content:
            return
        
        # Сохраняем в базу
        db_message = Message(
            from_user_id=sender_id,
            to_user_id=receiver_id,
            group_id=group_id,
            content=content,
            message_type="text"
        )
        
        db.add(db_message)
        db.commit()
        db.refresh(db_message)
        
        # Отправляем получателю
        if receiver_id:
            await manager.send_personal_message(
                json.dumps({
                    "type": "message",
                    "id": db_message.id,
                    "from_user_id": sender_id,
                    "to_user_id": receiver_id,
                    "content": content,
                    "timestamp": db_message.created_at.isoformat()
                }),
                receiver_id
            )
        elif group_id:
            members = db.query(GroupMember).filter(GroupMember.group_id == group_id).all()
            for member in members:
                if member.user_id != sender_id:
                    await manager.send_personal_message(
                        json.dumps({
                            "type": "group_message",
                            "id": db_message.id,
                            "group_id": group_id,
                            "from_user_id": sender_id,
                            "content": content,
                            "timestamp": db_message.created_at.isoformat()
                        }),
                        member.user_id
                    )
        
        # Подтверждение отправителю
        await manager.send_personal_message(
            json.dumps({
                "type": "message_sent",
                "id": db_message.id,
                "timestamp": db_message.created_at.isoformat()
            }),
            sender_id
        )
        
    except Exception as e:
        db.rollback()
        print(f"❌ Ошибка обработки текстового сообщения: {e}")
    finally:
        db.close()

async def handle_file_message(message_data: dict, sender_id: int):
    """Обработка сообщений с файлами"""
    await handle_text_message(message_data, sender_id)

async def handle_typing_indicator(message_data: dict, sender_id: int):
    """Обработка индикатора набора текста"""
    receiver_id = message_data.get("to_user_id")
    group_id = message_data.get("group_id")
    is_typing = message_data.get("is_typing", False)
    
    if receiver_id:
        await manager.send_personal_message(
            json.dumps({
                "type": "typing",
                "from_user_id": sender_id,
                "is_typing": is_typing
            }),
            receiver_id
        )
    elif group_id:
        db = SessionLocal()
        try:
            members = db.query(GroupMember).filter(GroupMember.group_id == group_id).all()
            for member in members:
                if member.user_id != sender_id:
                    await manager.send_personal_message(
                        json.dumps({
                            "type": "group_typing",
                            "group_id": group_id,
                            "from_user_id": sender_id,
                            "is_typing": is_typing
                        }),
                        member.user_id
                    )
        finally:
            db.close()

async def handle_group_message(message_data: dict, sender_id: int):
    """Обработка групповых сообщений"""
    await handle_text_message(message_data, sender_id)

# ========== СТАТИЧЕСКИЕ ФАЙЛЫ ==========

# Добавляем маршрут для главной страницы
@app.get("/index.html")
async def serve_index():
    """Главная страница с авторизацией"""
    index_path = frontend_dir / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    
    # Если index.html не найден, создаем простую страницу
    return HTMLResponse("""
        <!DOCTYPE html>
        <html>
        <head>
            <title>DevNet Messenger</title>
            <style>
                body { 
                    background: #0f0f0f; 
                    color: white; 
                    font-family: sans-serif; 
                    display: flex; 
                    justify-content: center; 
                    align-items: center; 
                    height: 100vh; 
                    margin: 0; 
                }
                .container { 
                    text-align: center; 
                    padding: 2rem; 
                    background: #1a1a1a; 
                    border-radius: 1rem; 
                    border: 1px solid rgba(255,255,255,0.1); 
                }
                h1 { 
                    color: #10a37f; 
                    margin-bottom: 1rem; 
                }
                a { 
                    color: #10a37f; 
                    text-decoration: none; 
                    margin: 0 1rem; 
                }
                a:hover { 
                    text-decoration: underline; 
                }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>DevNet Messenger</h1>
                <p>Современный мессенджер для разработчиков</p>
                <div style="margin-top: 2rem;">
                    <a href="/api/register">Регистрация</a>
                    <a href="/api/login">Вход</a>
                    <a href="/chat">Чат</a>
                    <a href="/api/docs">API Docs</a>
                </div>
            </div>
        </body>
        </html>
    """)

@app.get("/chat")
async def serve_chat():
    """Страница чата"""
    chat_path = frontend_dir / "chat.html"
    if chat_path.exists():
        return FileResponse(str(chat_path))
    return HTMLResponse("Chat page not found")

# ========== ЗАПУСК СЕРВЕРА ==========

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"🚀 Запуск DevNet Messenger API на порту {port}")
    print(f"📁 Директория загрузок: {UPLOAD_DIR}")
    print(f"📁 Директория фронтенда: {frontend_dir}")
    print(f"📱 Документация API: http://localhost:{port}/api/docs")
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=False
    )
