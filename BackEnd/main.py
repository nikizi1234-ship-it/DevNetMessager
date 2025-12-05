from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, Form, Request, File, UploadFile, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
import json
from datetime import datetime, timedelta
from pathlib import Path
import uvicorn 
import os
import sys
import shutil
import uuid
from typing import Optional, List
import hashlib
import secrets

# Добавляем путь для импорта модулей
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# ========== ИМПОРТ МОДУЛЕЙ ==========

try:
    from database import engine, SessionLocal, get_db, init_database
    print("✅ Database module imported successfully")
except ImportError as e:
    print(f"❌ Error importing database module: {e}")
    raise

try:
    # Инициализируем базу данных
    init_database()
    print("✅ Database initialized successfully")
except Exception as e:
    print(f"⚠️  Warning during database init: {e}")

# ========== ИМПОРТ МОДЕЛЕЙ ==========

try:
    from models import User, Message, Group, Channel, Subscription, GroupMember
    print("✅ Models imported successfully")
except ImportError as e:
    print(f"❌ Error importing models: {e}")
    raise

# ========== ПРОСТОЙ WEBSOCKET MANAGER ==========

class ConnectionManager:
    def __init__(self):
        self.active_connections = {}
    
    async def connect(self, websocket: WebSocket, user_id: int):
        await websocket.accept()
        self.active_connections[user_id] = websocket
    
    def disconnect(self, user_id: int):
        if user_id in self.active_connections:
            del self.active_connections[user_id]
    
    async def send_personal_message(self, message: str, user_id: int):
        if user_id in self.active_connections:
            await self.active_connections[user_id].send_text(message)

manager = ConnectionManager()

# ========== ПРОСТОЙ AUTH MODULE ==========

from passlib.context import CryptContext
from jose import JWTError, jwt

SECRET_KEY = "devnet_secret_key_change_in_production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def verify_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None

# ========== СОЗДАНИЕ АДМИНИСТРАТОРА (если нет) ==========

def create_admin_user():
    """Создает администратора если его нет в базе"""
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.username == "admin").first()
        if not admin:
            print("👑 Создаем администратора...")
            admin_password = "admin123"
            # Обрезаем пароль если он слишком длинный для bcrypt
            if len(admin_password) > 72:
                admin_password = admin_password[:72]
            
            admin_user = User(
                username="admin",
                email="admin@devnet.local",
                display_name="Администратор",
                password_hash=get_password_hash(admin_password)
            )
            db.add(admin_user)
            db.commit()
            print("✅ Администратор создан (логин: admin, пароль: admin123)")
        else:
            print("✅ Администратор уже существует")
    except Exception as e:
        print(f"⚠️  Ошибка создания администратора: {e}")
    finally:
        db.close()

# Вызываем создание администратора
create_admin_user()

# ========== СОЗДАНИЕ FASTAPI ПРИЛОЖЕНИЯ ==========

app = FastAPI(
    title="DevNet Messenger API",
    description="Simple messenger for developers",
    version="1.0.0"
)

# Настройка CORS - разрешаем все для фронтенда
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Создаем директории для загрузок
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)
for media_type in ["images", "avatars"]:
    (UPLOAD_DIR / media_type).mkdir(exist_ok=True)

print(f"📁 Upload directory: {UPLOAD_DIR}")

# Получаем абсолютный путь к фронтенду
current_dir = Path(__file__).parent
project_root = current_dir.parent
frontend_dir = project_root / "frontend"

print(f"📁 Project root: {project_root}")
print(f"📁 Frontend directory: {frontend_dir}")

# Монтируем статические файлы фронтенда
if frontend_dir.exists():
    print(f"✅ Frontend found: {frontend_dir}")
    # Монтируем всю директорию фронтенда как статическую
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
else:
    print(f"⚠️  Frontend not found: {frontend_dir}")
    # Создаем минимальный фронтенд если его нет
    frontend_dir.mkdir(exist_ok=True)

# Монтируем директорию загрузок
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

# ========== API ENDPOINTS ==========

@app.get("/api/health")
async def health_check():
    """Проверка здоровья API"""
    return {
        "status": "healthy",
        "service": "DevNet Messenger",
        "version": "1.0.0",
        "timestamp": datetime.utcnow().isoformat(),
        "database": "sqlite",
        "railway": os.environ.get("RAILWAY_ENVIRONMENT") is not None
    }

@app.get("/api/debug")
async def debug_info():
    """Отладочная информация"""
    return {
        "database_url": "sqlite:///:memory:" if os.environ.get("RAILWAY_ENVIRONMENT") else "sqlite:///./devnet.db",
        "railway_env": os.environ.get("RAILWAY_ENVIRONMENT"),
        "port": os.environ.get("PORT", 8080),
        "upload_dir": str(UPLOAD_DIR),
        "frontend_dir": str(frontend_dir),
        "current_time": datetime.utcnow().isoformat(),
        "frontend_exists": frontend_dir.exists()
    }

# ========== СОВМЕСТИМОСТЬ СО СТАРЫМ ФРОНТЕНДОМ ==========

# Редирект для старых URL на новые
@app.post("/api/register")
@app.post("/api/auth/register")
async def register_user(
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    display_name: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """Регистрация нового пользователя"""
    try:
        # Проверяем уникальность username
        existing_user = db.query(User).filter(User.username == username).first()
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Имя пользователя уже занято"
            )
        
        # Проверяем уникальность email
        existing_email = db.query(User).filter(User.email == email).first()
        if existing_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email уже используется"
            )
        
        # Проверяем пароль
        if len(password) < 6:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Пароль должен быть не менее 6 символов"
            )
        
        if len(password) > 72:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Пароль не должен превышать 72 символа"
            )
        
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
        access_token = create_access_token(
            data={"user_id": user.id, "username": user.username}
        )
        
        response_data = {
            "success": True,
            "message": "Регистрация успешна",
            "user": {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "email": user.email
            },
            "access_token": access_token
        }
        
        response = JSONResponse(content=response_data)
        
        # Устанавливаем токен в куки
        response.set_cookie(
            key="access_token",
            value=access_token,
            httponly=True,
            max_age=1800,  # 30 минут
            samesite="lax"
        )
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка регистрации: {str(e)}"
        )

@app.post("/api/login")
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
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Неверное имя пользователя или пароль"
            )
        
        # Создаем токен
        access_token = create_access_token(
            data={"user_id": user.id, "username": user.username}
        )
        
        response_data = {
            "success": True,
            "message": "Вход выполнен успешно",
            "user": {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "email": user.email,
                "avatar_url": user.avatar_url
            },
            "access_token": access_token
        }
        
        response = JSONResponse(content=response_data)
        
        # Устанавливаем токен в куки
        response.set_cookie(
            key="access_token",
            value=access_token,
            httponly=True,
            max_age=1800,
            samesite="lax"
        )
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка входа: {str(e)}"
        )

@app.get("/api/me")
@app.get("/api/auth/me")
async def get_current_user_info(
    request: Request,
    db: Session = Depends(get_db)
):
    """Получение информации о текущем пользователе"""
    try:
        token = request.cookies.get("access_token")
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Требуется аутентификация"
            )
        
        payload = verify_token(token)
        if not payload:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Недействительный токен"
            )
        
        user_id = payload.get("user_id")
        user = db.query(User).filter(User.id == user_id).first()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Пользователь не найден"
            )
        
        return {
            "success": True,
            "user": {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "email": user.email,
                "avatar_url": user.avatar_url,
                "is_online": user.is_online,
                "created_at": user.created_at.isoformat() if user.created_at else None
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка загрузки пользователя: {str(e)}"
        )

# Остальные эндпоинты (users, messages, stats) оставляем как в предыдущей версии
# ========== ПОЛЬЗОВАТЕЛИ ==========

@app.get("/api/users")
async def get_users(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    online_only: bool = Query(False),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """Получение списка пользователей"""
    try:
        query = db.query(User)
        
        # Фильтр по онлайн статусу
        if online_only:
            query = query.filter(User.is_online == True)
        
        # Поиск по имени пользователя или отображаемому имени
        if search:
            search_filter = f"%{search}%"
            query = query.filter(
                (User.username.ilike(search_filter)) |
                (User.display_name.ilike(search_filter))
            )
        
        total = query.count()
        users = query.order_by(User.username) \
                    .offset((page - 1) * limit) \
                    .limit(limit) \
                    .all()
        
        users_data = []
        for user in users:
            users_data.append({
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "avatar_url": user.avatar_url,
                "is_online": user.is_online,
                "created_at": user.created_at.isoformat() if user.created_at else None
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
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка загрузки пользователей: {str(e)}"
        )

# ========== СООБЩЕНИЯ ==========

@app.get("/api/messages")
async def get_messages(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """Получение последних сообщений"""
    try:
        query = db.query(Message)
        total = query.count()
        messages = query.order_by(desc(Message.created_at)) \
                       .offset((page - 1) * limit) \
                       .limit(limit) \
                       .all()
        
        messages_data = []
        for msg in messages:
            sender = None
            if msg.from_user_id:
                sender = db.query(User).filter(User.id == msg.from_user_id).first()
            
            messages_data.append({
                "id": msg.id,
                "content": msg.content,
                "type": msg.message_type,
                "sender": {
                    "id": sender.id if sender else None,
                    "username": sender.username if sender else "System",
                    "display_name": sender.display_name if sender else None,
                    "avatar_url": sender.avatar_url if sender else None
                } if sender else {"username": "System"},
                "created_at": msg.created_at.isoformat() if msg.created_at else None
            })
        
        return {
            "success": True,
            "messages": messages_data,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "pages": (total + limit - 1) // limit
            }
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка загрузки сообщений: {str(e)}"
        )

@app.post("/api/messages")
async def create_message(
    content: str = Form(...),
    message_type: str = Form("text"),
    request: Request = None,
    db: Session = Depends(get_db)
):
    """Создание нового сообщения"""
    try:
        # Проверяем аутентификацию
        token = request.cookies.get("access_token") if request else None
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Требуется аутентификация"
            )
        
        payload = verify_token(token)
        if not payload:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Недействительный токен"
            )
        
        user_id = payload.get("user_id")
        user = db.query(User).filter(User.id == user_id).first()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Пользователь не найден"
            )
        
        # Проверяем сообщение
        if not content or len(content.strip()) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Сообщение не может быть пустым"
            )
        
        # Создаем сообщение
        message = Message(
            from_user_id=user_id,
            content=content.strip(),
            message_type=message_type
        )
        
        db.add(message)
        db.commit()
        db.refresh(message)
        
        return {
            "success": True,
            "message": "Сообщение отправлено",
            "data": {
                "id": message.id,
                "content": message.content,
                "type": message.message_type,
                "sender": {
                    "id": user.id,
                    "username": user.username,
                    "display_name": user.display_name,
                    "avatar_url": user.avatar_url
                },
                "created_at": message.created_at.isoformat() if message.created_at else None
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка отправки сообщения: {str(e)}"
        )

# ========== СТАТИСТИКА ==========

@app.get("/api/stats")
async def get_statistics(
    db: Session = Depends(get_db)
):
    """Получение статистики системы"""
    try:
        # Подсчет пользователей
        total_users = db.query(func.count(User.id)).scalar()
        online_users = db.query(func.count(User.id)).filter(User.is_online == True).scalar()
        
        # Подсчет сообщений
        total_messages = db.query(func.count(Message.id)).scalar()
        
        # Последнее сообщение
        last_message = db.query(Message).order_by(desc(Message.created_at)).first()
        last_message_time = last_message.created_at if last_message else None
        
        return {
            "success": True,
            "stats": {
                "users": {
                    "total": total_users,
                    "online": online_users,
                    "offline": total_users - online_users
                },
                "messages": {
                    "total": total_messages,
                    "last_message_time": last_message_time.isoformat() if last_message_time else None
                },
                "system": {
                    "timestamp": datetime.utcnow().isoformat(),
                    "railway": os.environ.get("RAILWAY_ENVIRONMENT") is not None
                }
            }
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка получения статистики: {str(e)}"
        )

# ========== WEB SOCKET ==========

@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: int):
    """WebSocket endpoint для реального времени"""
    await manager.connect(websocket, user_id)
    
    # Обновляем статус пользователя на онлайн
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
            
            if message_type == "message":
                content = message_data.get("content", "").strip()
                if content:
                    # Сохраняем сообщение в БД
                    db = SessionLocal()
                    try:
                        message = Message(
                            from_user_id=user_id,
                            content=content,
                            message_type="text"
                        )
                        db.add(message)
                        db.commit()
                        
                        # Отправляем всем подключенным пользователям
                        for uid, ws_conn in manager.active_connections.items():
                            if uid != user_id:
                                await ws_conn.send_text(json.dumps({
                                    "type": "message",
                                    "from_user_id": user_id,
                                    "content": content,
                                    "timestamp": datetime.utcnow().isoformat()
                                }))
                    finally:
                        db.close()
            elif message_type == "typing":
                # Пересылаем информацию о наборе текста
                for uid, ws_conn in manager.active_connections.items():
                    if uid != user_id:
                        await ws_conn.send_text(json.dumps({
                            "type": "typing",
                            "user_id": user_id,
                            "is_typing": message_data.get("is_typing", True)
                        }))
                        
    except WebSocketDisconnect:
        print(f"📴 User disconnected: {user_id}")
        manager.disconnect(user_id)
        
        # Обновляем статус пользователя на офлайн
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

# ========== ФАЛЛБЭК ДЛЯ СТАТИЧЕСКИХ ФАЙЛОВ ==========

@app.get("/{path:path}")
async def serve_frontend(path: str):
    """Сервим статические файлы фронтенда"""
    # Если запрос идет к API, возвращаем 404
    if path.startswith("api/"):
        return JSONResponse(
            status_code=404,
            content={"detail": "API endpoint not found"}
        )
    
    # Определяем путь к файлу
    file_path = frontend_dir / path
    
    # Если запрос к корню или HTML файлу
    if path == "" or path.endswith(".html") or "." not in path:
        # Проверяем существование файла
        if path == "" or path == "/":
            index_path = frontend_dir / "index.html"
        elif not path.endswith(".html"):
            html_path = frontend_dir / f"{path}.html"
            if html_path.exists():
                file_path = html_path
            else:
                file_path = frontend_dir / "index.html"
        else:
            file_path = frontend_dir / path
        
        if file_path.exists():
            return FileResponse(str(file_path))
    
    # Если файл существует, отдаем его
    if file_path.exists() and file_path.is_file():
        return FileResponse(str(file_path))
    
    # Если файл не найден, отдаем index.html
    index_path = frontend_dir / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    
    # Если index.html тоже нет, возвращаем 404
    return JSONResponse(
        status_code=404,
        content={"detail": "File not found"}
    )

# ========== ЗАПУСК СЕРВЕРА ==========

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print("=" * 50)
    print("🚀 DevNet Messenger API запущен!")
    print(f"📡 Порт: {port}")
    print(f"📁 Директория загрузок: {UPLOAD_DIR}")
    print(f"📁 Директория фронтенда: {frontend_dir}")
    print(f"🔗 API документация: http://localhost:{port}/api/docs")
    print(f"🏠 Главная страница: http://localhost:{port}/")
    print(f"💬 Чат: http://localhost:{port}/chat")
    print("👑 Тестовый пользователь: admin / admin123")
    print("=" * 50)
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=False
    )
