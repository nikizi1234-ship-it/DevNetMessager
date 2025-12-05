from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, Form, Request, File, UploadFile, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc, Column, Integer, String, Boolean, DateTime, ForeignKey, Text
import json
from datetime import datetime, timedelta
from pathlib import Path
import uvicorn 
import os
import sys
import shutil
import uuid
from typing import Optional
import enum

# Добавляем путь для импорта модулей
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# ========== ИМПОРТ МОДУЛЕЙ ==========

try:
    from database import engine, SessionLocal, get_db, Base
    print("✅ Database module imported successfully")
except ImportError as e:
    print(f"❌ Error importing database module: {e}")
    raise

# ========== МОДЕЛИ (должны быть ОДИН раз) ==========

# Enums
class MessageType(str, enum.Enum):
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    FILE = "file"

# Models
class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    display_name = Column(String(100))
    password_hash = Column(String(255), nullable=False)
    avatar_url = Column(String(500))
    bio = Column(Text)
    is_verified = Column(Boolean, default=False)
    is_online = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class Message(Base):
    __tablename__ = "messages"
    
    id = Column(Integer, primary_key=True, index=True)
    from_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    to_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    group_id = Column(Integer, nullable=True)
    channel_id = Column(Integer, nullable=True)
    content = Column(Text)
    message_type = Column(String(20), default=MessageType.TEXT.value)
    created_at = Column(DateTime, default=datetime.utcnow)

class Group(Base):
    __tablename__ = "groups"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    avatar_url = Column(String(500))
    is_public = Column(Boolean, default=True)
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)

# ========== СОЗДАНИЕ ТАБЛИЦ (если их нет) ==========

try:
    Base.metadata.create_all(bind=engine)
    print("✅ Database tables created/verified successfully")
except Exception as e:
    print(f"⚠️  Warning during table creation: {e}")

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
            admin_user = User(
                username="admin",
                email="admin@devnet.local",
                display_name="Администратор",
                password_hash=get_password_hash("admin123")
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

# Настройка CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
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

# Проверяем существование фронтенда
if frontend_dir.exists():
    print(f"✅ Frontend found: {frontend_dir}")
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")
else:
    print(f"⚠️  Frontend not found: {frontend_dir}")

# Монтируем директорию загрузок
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

# ========== API ENDPOINTS ==========

@app.get("/")
async def root():
    """Главная страница"""
    return RedirectResponse("/index.html")

@app.get("/api/health")
async def health_check():
    """Проверка здоровья API"""
    return {
        "status": "healthy",
        "service": "DevNet Messenger",
        "version": "1.0.0",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/api/debug")
async def debug_info():
    """Отладочная информация"""
    return {
        "database_url": "sqlite:///:memory:" if os.environ.get("RAILWAY_ENVIRONMENT") else "sqlite:///./devnet.db",
        "railway_env": os.environ.get("RAILWAY_ENVIRONMENT"),
        "port": os.environ.get("PORT", 8000),
        "upload_dir": str(UPLOAD_DIR),
        "frontend_dir": str(frontend_dir),
        "current_time": datetime.utcnow().isoformat()
    }

@app.get("/api/test-endpoints")
async def test_endpoints():
    """Тест всех доступных endpoint'ов"""
    endpoints = [
        {"method": "GET", "path": "/", "description": "Главная страница"},
        {"method": "GET", "path": "/api/health", "description": "Проверка здоровья"},
        {"method": "GET", "path": "/api/debug", "description": "Отладочная информация"},
        {"method": "POST", "path": "/api/auth/register", "description": "Регистрация"},
        {"method": "POST", "path": "/api/auth/login", "description": "Вход"},
        {"method": "GET", "path": "/api/auth/me", "description": "Информация о пользователе"},
        {"method": "GET", "path": "/api/users", "description": "Список пользователей"},
        {"method": "GET", "path": "/chat", "description": "Страница чата"},
        {"method": "GET", "path": "/test", "description": "Тестовая страница"},
        {"method": "GET", "path": "/api/docs", "description": "Документация API (Swagger)"},
    ]
    return {"endpoints": endpoints}

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
        
        response = JSONResponse(content={
            "success": True,
            "user": {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "email": user.email
            },
            "access_token": access_token
        })
        
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
        
        response = JSONResponse(content={
            "success": True,
            "user": {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "email": user.email,
                "avatar_url": user.avatar_url
            },
            "access_token": access_token
        })
        
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
        raise HTTPException(status_code=500, detail=f"Ошибка входа: {str(e)}")

@app.get("/api/auth/me")
async def get_current_user_info(
    request: Request,
    db: Session = Depends(get_db)
):
    """Получение информации о текущем пользователе"""
    try:
        token = request.cookies.get("access_token")
        if not token:
            raise HTTPException(status_code=401, detail="Требуется аутентификация")
        
        payload = verify_token(token)
        if not payload:
            raise HTTPException(status_code=401, detail="Недействительный токен")
        
        user_id = payload.get("user_id")
        user = db.query(User).filter(User.id == user_id).first()
        
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        
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
        raise HTTPException(status_code=500, detail=f"Ошибка загрузки пользователя: {str(e)}")

# ========== ПОЛЬЗОВАТЕЛИ ==========

@app.get("/api/users")
async def get_users(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """Получение списка пользователей"""
    try:
        query = db.query(User)
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
        raise HTTPException(status_code=500, detail=f"Ошибка загрузки пользователей: {str(e)}")

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
                    "display_name": sender.display_name if sender else None
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
        raise HTTPException(status_code=500, detail=f"Ошибка загрузки сообщений: {str(e)}")

# ========== ЗАГРУЗКА ФАЙЛОВ ==========

@app.post("/api/upload/avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """Загрузка аватарки"""
    try:
        # Проверяем тип файла
        allowed_types = ["image/jpeg", "image/png", "image/gif", "image/webp"]
        if file.content_type not in allowed_types:
            return JSONResponse(
                status_code=400,
                content={"success": False, "detail": "Неподдерживаемый тип файла. Разрешены только изображения."}
            )
        
        # Проверяем размер (максимум 5MB)
        max_size = 5 * 1024 * 1024
        file.file.seek(0, 2)
        file_size = file.file.tell()
        file.file.seek(0)
        
        if file_size > max_size:
            return JSONResponse(
                status_code=400,
                content={"success": False, "detail": "Файл слишком большой. Максимум 5MB."}
            )
        
        # Генерируем уникальное имя
        file_extension = file.filename.split('.')[-1] if '.' in file.filename else "jpg"
        unique_filename = f"{uuid.uuid4()}.{file_extension}"
        
        # Сохраняем файл
        save_dir = UPLOAD_DIR / "avatars"
        save_dir.mkdir(exist_ok=True)
        save_path = save_dir / unique_filename
        
        with open(save_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        return {
            "success": True,
            "url": f"/uploads/avatars/{unique_filename}"
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
                        for uid, ws in manager.active_connections.items():
                            if uid != user_id:
                                await ws.send_text(json.dumps({
                                    "type": "message",
                                    "from_user_id": user_id,
                                    "content": content,
                                    "timestamp": datetime.utcnow().isoformat()
                                }))
                    finally:
                        db.close()
                        
    except WebSocketDisconnect:
        print(f"📴 User disconnected: {user_id}")
        manager.disconnect(user_id)

# ========== СТАТИЧЕСКИЕ ФАЙЛЫ И СТРАНИЦЫ ==========

@app.get("/index.html")
async def serve_index():
    """Главная страница"""
    index_path = frontend_dir / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    
    # Если файла нет, возвращаем простую HTML страницу
    html_content = """
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>DevNet Messenger</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                margin: 0;
                padding: 20px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                min-height: 100vh;
            }
            .container {
                max-width: 800px;
                margin: 0 auto;
                padding: 40px;
                background: rgba(255, 255, 255, 0.1);
                backdrop-filter: blur(10px);
                border-radius: 20px;
                box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
            }
            h1 {
                text-align: center;
                margin-bottom: 40px;
                font-size: 3em;
            }
            .features {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
                gap: 20px;
                margin-bottom: 40px;
            }
            .feature {
                background: rgba(255, 255, 255, 0.2);
                padding: 20px;
                border-radius: 10px;
                text-align: center;
            }
            .feature h3 {
                margin-top: 0;
            }
            .buttons {
                display: flex;
                gap: 20px;
                justify-content: center;
                margin-top: 30px;
            }
            .btn {
                padding: 15px 30px;
                border: none;
                border-radius: 50px;
                font-size: 1.1em;
                font-weight: bold;
                cursor: pointer;
                transition: transform 0.3s, box-shadow 0.3s;
            }
            .btn-primary {
                background: white;
                color: #667eea;
            }
            .btn-secondary {
                background: transparent;
                color: white;
                border: 2px solid white;
            }
            .btn:hover {
                transform: translateY(-2px);
                box-shadow: 0 5px 15px rgba(0, 0, 0, 0.3);
            }
            .api-links {
                margin-top: 40px;
                text-align: center;
            }
            .api-links a {
                color: white;
                margin: 0 10px;
                text-decoration: none;
                border-bottom: 1px solid white;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>DevNet Messenger</h1>
            <p style="text-align: center; font-size: 1.2em; margin-bottom: 40px;">
                Простой и быстрый мессенджер для разработчиков
            </p>
            
            <div class="features">
                <div class="feature">
                    <h3>⚡ Real-time чат</h3>
                    <p>Мгновенная отправка сообщений через WebSocket</p>
                </div>
                <div class="feature">
                    <h3>👥 Группы</h3>
                    <p>Создавайте группы для общения с командой</p>
                </div>
                <div class="feature">
                    <h3>🖼️ Файлы</h3>
                    <p>Отправляйте изображения и документы</p>
                </div>
            </div>
            
            <div class="buttons">
                <button class="btn btn-primary" onclick="window.location.href='/test'">
                    📋 Тест функций
                </button>
                <button class="btn btn-secondary" onclick="window.location.href='/chat'">
                    💬 Перейти в чат
                </button>
            </div>
            
            <div class="api-links">
                <a href="/api/docs">API Docs</a>
                <a href="/api/debug">Debug Info</a>
                <a href="/api/test-endpoints">Test Endpoints</a>
                <a href="/api/health">Health Check</a>
            </div>
        </div>
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
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>DevNet Chat</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                margin: 0;
                padding: 20px;
                background: #f5f5f5;
            }
            .container {
                max-width: 1000px;
                margin: 0 auto;
                background: white;
                border-radius: 10px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                overflow: hidden;
            }
            .header {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                padding: 20px;
                text-align: center;
            }
            .chat-container {
                display: flex;
                height: 600px;
            }
            .sidebar {
                width: 300px;
                border-right: 1px solid #eee;
                padding: 20px;
                overflow-y: auto;
            }
            .chat-area {
                flex: 1;
                display: flex;
                flex-direction: column;
            }
            .messages {
                flex: 1;
                padding: 20px;
                overflow-y: auto;
                background: #f9f9f9;
            }
            .message-input {
                padding: 20px;
                border-top: 1px solid #eee;
                display: flex;
                gap: 10px;
            }
            input, textarea {
                flex: 1;
                padding: 10px;
                border: 1px solid #ddd;
                border-radius: 5px;
                font-size: 16px;
            }
            button {
                padding: 10px 20px;
                background: #667eea;
                color: white;
                border: none;
                border-radius: 5px;
                cursor: pointer;
                font-size: 16px;
            }
            button:hover {
                background: #764ba2;
            }
            .message {
                margin-bottom: 15px;
                padding: 10px;
                background: white;
                border-radius: 5px;
                border: 1px solid #eee;
            }
            .message-header {
                display: flex;
                justify-content: space-between;
                margin-bottom: 5px;
                font-size: 0.9em;
                color: #666;
            }
            .auth-section {
                padding: 20px;
                text-align: center;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>DevNet Chat</h1>
                <p>Real-time messaging</p>
            </div>
            
            <div id="auth-section" class="auth-section">
                <h2>Войдите в систему</h2>
                <div style="max-width: 400px; margin: 0 auto;">
                    <input type="text" id="login-username" placeholder="Имя пользователя" style="width: 100%; margin-bottom: 10px;">
                    <input type="password" id="login-password" placeholder="Пароль" style="width: 100%; margin-bottom: 10px;">
                    <button onclick="login()">Войти</button>
                    <button onclick="showRegister()" style="background: #666; margin-left: 10px;">Регистрация</button>
                </div>
            </div>
            
            <div id="chat-section" style="display: none;">
                <div class="chat-container">
                    <div class="sidebar">
                        <h3>Пользователи</h3>
                        <div id="users-list"></div>
                        <h3 style="margin-top: 20px;">Мой профиль</h3>
                        <div id="my-profile"></div>
                        <button onclick="logout()" style="margin-top: 20px; width: 100%; background: #dc3545;">Выйти</button>
                    </div>
                    
                    <div class="chat-area">
                        <div class="messages" id="messages-container"></div>
                        <div class="message-input">
                            <input type="text" id="message-input" placeholder="Введите сообщение..." onkeypress="if(event.key==='Enter') sendMessage()">
                            <button onclick="sendMessage()">Отправить</button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        
        <script>
            let currentUser = null;
            let ws = null;
            
            async function login() {
                const username = document.getElementById('login-username').value;
                const password = document.getElementById('login-password').value;
                
                const response = await fetch('/api/auth/login', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                    body: `username=${encodeURIComponent(username)}&password=${encodeURIComponent(password)}`
                });
                
                if (response.ok) {
                    const data = await response.json();
                    currentUser = data.user;
                    document.getElementById('auth-section').style.display = 'none';
                    document.getElementById('chat-section').style.display = 'block';
                    loadProfile();
                    loadUsers();
                    connectWebSocket();
                } else {
                    alert('Ошибка входа');
                }
            }
            
            function showRegister() {
                const username = prompt('Введите имя пользователя:');
                const email = prompt('Введите email:');
                const password = prompt('Введите пароль:');
                const displayName = prompt('Введите отображаемое имя (необязательно):');
                
                if (username && email && password) {
                    register(username, email, password, displayName);
                }
            }
            
            async function register(username, email, password, displayName) {
                const formData = new FormData();
                formData.append('username', username);
                formData.append('email', email);
                formData.append('password', password);
                if (displayName) formData.append('display_name', displayName);
                
                const response = await fetch('/api/auth/register', {
                    method: 'POST',
                    body: formData
                });
                
                if (response.ok) {
                    alert('Регистрация успешна! Теперь войдите.');
                } else {
                    const error = await response.json();
                    alert('Ошибка регистрации: ' + error.detail);
                }
            }
            
            async function loadProfile() {
                const response = await fetch('/api/auth/me');
                if (response.ok) {
                    const data = await response.json();
                    document.getElementById('my-profile').innerHTML = `
                        <p><strong>Имя:</strong> ${data.user.display_name || data.user.username}</p>
                        <p><strong>Email:</strong> ${data.user.email}</p>
                    `;
                }
            }
            
            async function loadUsers() {
                const response = await fetch('/api/users');
                if (response.ok) {
                    const data = await response.json();
                    const usersList = document.getElementById('users-list');
                    usersList.innerHTML = data.users.map(user => `
                        <div style="padding: 5px; border-bottom: 1px solid #eee;">
                            ${user.display_name || user.username}
                            <span style="color: ${user.is_online ? 'green' : 'gray'}; font-size: 0.8em;">
                                ${user.is_online ? '● онлайн' : '○ офлайн'}
                            </span>
                        </div>
                    `).join('');
                }
            }
            
            function connectWebSocket() {
                if (!currentUser) return;
                
                ws = new WebSocket(`ws://${window.location.host}/ws/${currentUser.id}`);
                
                ws.onmessage = function(event) {
                    const message = JSON.parse(event.data);
                    displayMessage(message);
                };
                
                ws.onopen = function() {
                    console.log('WebSocket connected');
                };
            }
            
            function sendMessage() {
                if (!ws || ws.readyState !== WebSocket.OPEN) {
                    alert('WebSocket не подключен');
                    return;
                }
                
                const input = document.getElementById('message-input');
                const message = input.value.trim();
                
                if (message) {
                    ws.send(JSON.stringify({
                        type: 'message',
                        content: message
                    }));
                    input.value = '';
                }
            }
            
            function displayMessage(message) {
                const container = document.getElementById('messages-container');
                const messageDiv = document.createElement('div');
                messageDiv.className = 'message';
                
                const time = new Date().toLocaleTimeString();
                messageDiv.innerHTML = `
                    <div class="message-header">
                        <strong>User ${message.from_user_id || 'Unknown'}</strong>
                        <span>${time}</span>
                    </div>
                    <div>${message.content}</div>
                `;
                
                container.appendChild(messageDiv);
                container.scrollTop = container.scrollHeight;
            }
            
            function logout() {
                document.cookie = 'access_token=; Max-Age=0; path=/';
                currentUser = null;
                if (ws) ws.close();
                document.getElementById('auth-section').style.display = 'block';
                document.getElementById('chat-section').style.display = 'none';
            }
            
            // Загружаем профиль при загрузке страницы
            window.onload = async function() {
                const response = await fetch('/api/auth/me');
                if (response.ok) {
                    const data = await response.json();
                    currentUser = data.user;
                    document.getElementById('auth-section').style.display = 'none';
                    document.getElementById('chat-section').style.display = 'block';
                    loadProfile();
                    loadUsers();
                    connectWebSocket();
                }
            };
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

@app.get("/test")
async def test_page():
    """Тестовая страница для проверки функций"""
    html_content = """
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>DevNet - Test Page</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                margin: 0;
                padding: 20px;
                background: #f0f2f5;
            }
            .container {
                max-width: 1200px;
                margin: 0 auto;
            }
            .header {
                text-align: center;
                margin-bottom: 40px;
                padding: 20px;
                background: white;
                border-radius: 10px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            }
            .test-section {
                background: white;
                padding: 20px;
                margin-bottom: 20px;
                border-radius: 10px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            }
            .test-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
                gap: 20px;
                margin-top: 20px;
            }
            .test-card {
                background: #f8f9fa;
                padding: 15px;
                border-radius: 8px;
                border-left: 4px solid #667eea;
            }
            button {
                padding: 10px 20px;
                background: #667eea;
                color: white;
                border: none;
                border-radius: 5px;
                cursor: pointer;
                margin-right: 10px;
                margin-bottom: 10px;
            }
            button:hover {
                background: #764ba2;
            }
            .success { color: green; }
            .error { color: red; }
            pre {
                background: #f4f4f4;
                padding: 10px;
                border-radius: 5px;
                overflow-x: auto;
                max-height: 200px;
                overflow-y: auto;
            }
            .status-badge {
                display: inline-block;
                padding: 3px 8px;
                border-radius: 12px;
                font-size: 0.8em;
                margin-left: 10px;
            }
            .online { background: #d4edda; color: #155724; }
            .offline { background: #f8d7da; color: #721c24; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🔧 DevNet Messenger - Test Page</h1>
                <p>Проверка всех функций API</p>
                <div id="global-status">
                    <button onclick="testAll()">Запустить все тесты</button>
                    <span id="overall-status"></span>
                </div>
            </div>
            
            <div class="test-section">
                <h2>📡 Проверка подключения</h2>
                <div class="test-grid">
                    <div class="test-card">
                        <h3>Health Check</h3>
                        <p>Проверка доступности API</p>
                        <button onclick="testHealth()">Тест</button>
                        <div id="health-result"></div>
                    </div>
                    <div class="test-card">
                        <h3>Debug Info</h3>
                        <p>Информация о сервере</p>
                        <button onclick="testDebug()">Тест</button>
                        <div id="debug-result"></div>
                    </div>
                    <div class="test-card">
                        <h3>Все Endpoints</h3>
                        <p>Список доступных API</p>
                        <button onclick="testEndpoints()">Тест</button>
                        <div id="endpoints-result"></div>
                    </div>
                </div>
            </div>
            
            <div class="test-section">
                <h2>🔐 Аутентификация</h2>
                <div class="test-grid">
                    <div class="test-card">
                        <h3>Регистрация</h3>
                        <p>Создание нового пользователя</p>
                        <button onclick="testRegister()">Тест регистрации</button>
                        <div id="register-result"></div>
                    </div>
                    <div class="test-card">
                        <h3>Вход</h3>
                        <p>Аутентификация пользователя</p>
                        <button onclick="testLogin()">Тест входа</button>
                        <div id="login-result"></div>
                    </div>
                    <div class="test-card">
                        <h3>Профиль</h3>
                        <p>Информация о текущем пользователе</p>
                        <button onclick="testProfile()">Тест профиля</button>
                        <div id="profile-result"></div>
                    </div>
                </div>
            </div>
            
            <div class="test-section">
                <h2>👥 Пользователи и сообщения</h2>
                <div class="test-grid">
                    <div class="test-card">
                        <h3>Список пользователей</h3>
                        <p>Получение всех пользователей</p>
                        <button onclick="testUsers()">Тест</button>
                        <div id="users-result"></div>
                    </div>
                    <div class="test-card">
                        <h3>Сообщения</h3>
                        <p>Получение последних сообщений</p>
                        <button onclick="testMessages()">Тест</button>
                        <div id="messages-result"></div>
                    </div>
                    <div class="test-card">
                        <h3>WebSocket</h3>
                        <p>Проверка WebSocket подключения</p>
                        <button onclick="testWebSocket()">Тест</button>
                        <div id="websocket-result"></div>
                    </div>
                </div>
            </div>
            
            <div class="test-section">
                <h2>📊 Статус системы</h2>
                <div id="system-status">
                    <p>Загрузка информации о системе...</p>
                </div>
            </div>
        </div>
        
        <script>
            let testResults = {};
            
            async function testAll() {
                clearResults();
                
                const tests = [
                    testHealth,
                    testDebug,
                    testEndpoints,
                    testUsers,
                    testMessages,
                    testWebSocket
                ];
                
                for (const test of tests) {
                    await test();
                    await new Promise(resolve => setTimeout(resolve, 500));
                }
                
                updateOverallStatus();
            }
            
            function clearResults() {
                document.querySelectorAll('[id$="-result"]').forEach(el => {
                    el.innerHTML = '';
                    el.className = '';
                });
                testResults = {};
            }
            
            function updateOverallStatus() {
                const total = Object.keys(testResults).length;
                const passed = Object.values(testResults).filter(r => r === 'success').length;
                const statusEl = document.getElementById('overall-status');
                
                statusEl.innerHTML = `
                    <span class="status-badge ${passed === total ? 'online' : 'offline'}">
                        ${passed}/${total} тестов пройдено
                    </span>
                `;
            }
            
            async function testHealth() {
                const resultEl = document.getElementById('health-result');
                try {
                    const response = await fetch('/api/health');
                    const data = await response.json();
                    resultEl.innerHTML = `<pre>${JSON.stringify(data, null, 2)}</pre>`;
                    resultEl.className = 'success';
                    testResults.health = 'success';
                } catch (error) {
                    resultEl.innerHTML = `Ошибка: ${error}`;
                    resultEl.className = 'error';
                    testResults.health = 'error';
                }
            }
            
            async function testDebug() {
                const resultEl = document.getElementById('debug-result');
                try {
                    const response = await fetch('/api/debug');
                    const data = await response.json();
                    resultEl.innerHTML = `<pre>${JSON.stringify(data, null, 2)}</pre>`;
                    resultEl.className = 'success';
                    testResults.debug = 'success';
                } catch (error) {
                    resultEl.innerHTML = `Ошибка: ${error}`;
                    resultEl.className = 'error';
                    testResults.debug = 'error';
                }
            }
            
            async function testEndpoints() {
                const resultEl = document.getElementById('endpoints-result');
                try {
                    const response = await fetch('/api/test-endpoints');
                    const data = await response.json();
                    const list = data.endpoints.map(ep => 
                        `${ep.method} ${ep.path} - ${ep.description}`
                    ).join('<br>');
                    resultEl.innerHTML = list;
                    resultEl.className = 'success';
                    testResults.endpoints = 'success';
                } catch (error) {
                    resultEl.innerHTML = `Ошибка: ${error}`;
                    resultEl.className = 'error';
                    testResults.endpoints = 'error';
                }
            }
            
            async function testRegister() {
                const resultEl = document.getElementById('register-result');
                const testUser = {
                    username: 'testuser_' + Date.now(),
                    email: 'test' + Date.now() + '@test.com',
                    password: 'test123',
                    display_name: 'Test User'
                };
                
                try {
                    const formData = new FormData();
                    for (const [key, value] of Object.entries(testUser)) {
                        formData.append(key, value);
                    }
                    
                    const response = await fetch('/api/auth/register', {
                        method: 'POST',
                        body: formData
                    });
                    
                    if (response.ok) {
                        const data = await response.json();
                        resultEl.innerHTML = `✅ Успешно! ID: ${data.user.id}`;
                        resultEl.className = 'success';
                        testResults.register = 'success';
                    } else {
                        const error = await response.json();
                        resultEl.innerHTML = `❌ Ошибка: ${error.detail}`;
                        resultEl.className = 'error';
                        testResults.register = 'error';
                    }
                } catch (error) {
                    resultEl.innerHTML = `❌ Ошибка: ${error}`;
                    resultEl.className = 'error';
                    testResults.register = 'error';
                }
            }
            
            async function testLogin() {
                const resultEl = document.getElementById('login-result');
                try {
                    const response = await fetch('/api/auth/login', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                        body: 'username=admin&password=admin123'
                    });
                    
                    if (response.ok) {
                        const data = await response.json();
                        resultEl.innerHTML = `✅ Успешно! Пользователь: ${data.user.username}`;
                        resultEl.className = 'success';
                        testResults.login = 'success';
                    } else {
                        resultEl.innerHTML = '❌ Ошибка входа';
                        resultEl.className = 'error';
                        testResults.login = 'error';
                    }
                } catch (error) {
                    resultEl.innerHTML = `❌ Ошибка: ${error}`;
                    resultEl.className = 'error';
                    testResults.login = 'error';
                }
            }
            
            async function testProfile() {
                const resultEl = document.getElementById('profile-result');
                try {
                    const response = await fetch('/api/auth/me');
                    if (response.ok) {
                        const data = await response.json();
                        resultEl.innerHTML = `✅ Успешно! Имя: ${data.user.display_name}`;
                        resultEl.className = 'success';
                        testResults.profile = 'success';
                    } else {
                        resultEl.innerHTML = '❌ Не авторизован';
                        resultEl.className = 'error';
                        testResults.profile = 'error';
                    }
                } catch (error) {
                    resultEl.innerHTML = `❌ Ошибка: ${error}`;
                    resultEl.className = 'error';
                    testResults.profile = 'error';
                }
            }
            
            async function testUsers() {
                const resultEl = document.getElementById('users-result');
                try {
                    const response = await fetch('/api/users');
                    const data = await response.json();
                    resultEl.innerHTML = `✅ Успешно! Пользователей: ${data.users.length}`;
                    resultEl.className = 'success';
                    testResults.users = 'success';
                } catch (error) {
                    resultEl.innerHTML = `❌ Ошибка: ${error}`;
                    resultEl.className = 'error';
                    testResults.users = 'error';
                }
            }
            
            async function testMessages() {
                const resultEl = document.getElementById('messages-result');
                try {
                    const response = await fetch('/api/messages');
                    const data = await response.json();
                    resultEl.innerHTML = `✅ Успешно! Сообщений: ${data.messages.length}`;
                    resultEl.className = 'success';
                    testResults.messages = 'success';
                } catch (error) {
                    resultEl.innerHTML = `❌ Ошибка: ${error}`;
                    resultEl.className = 'error';
                    testResults.messages = 'error';
                }
            }
            
            async function testWebSocket() {
                const resultEl = document.getElementById('websocket-result');
                try {
                    const ws = new WebSocket(`ws://${window.location.host}/ws/1`);
                    
                    return new Promise((resolve) => {
                        ws.onopen = () => {
                            resultEl.innerHTML = '✅ WebSocket подключен';
                            resultEl.className = 'success';
                            testResults.websocket = 'success';
                            ws.close();
                            resolve();
                        };
                        
                        ws.onerror = () => {
                            resultEl.innerHTML = '❌ WebSocket ошибка';
                            resultEl.className = 'error';
                            testResults.websocket = 'error';
                            resolve();
                        };
                        
                        setTimeout(() => {
                            if (!testResults.websocket) {
                                resultEl.innerHTML = '❌ WebSocket timeout';
                                resultEl.className = 'error';
                                testResults.websocket = 'error';
                                resolve();
                            }
                        }, 3000);
                    });
                } catch (error) {
                    resultEl.innerHTML = `❌ Ошибка: ${error}`;
                    resultEl.className = 'error';
                    testResults.websocket = 'error';
                }
            }
            
            // Запускаем базовые тесты при загрузке страницы
            window.onload = async function() {
                await testHealth();
                await testDebug();
                await testEndpoints();
                updateOverallStatus();
                
                // Обновляем статус системы
                const statusEl = document.getElementById('system-status');
                try {
                    const [health, debug] = await Promise.all([
                        fetch('/api/health'),
                        fetch('/api/debug')
                    ]);
                    
                    const healthData = await health.json();
                    const debugData = await debug.json();
                    
                    statusEl.innerHTML = `
                        <h3>Система работает нормально</h3>
                        <p><strong>Версия:</strong> ${healthData.version}</p>
                        <p><strong>Среда:</strong> ${debugData.railway_env || 'Локальная'}</p>
                        <p><strong>База данных:</strong> ${debugData.database_url.includes('memory') ? 'In-memory SQLite' : 'Файловая SQLite'}</p>
                        <p><strong>Время сервера:</strong> ${new Date(healthData.timestamp).toLocaleString()}</p>
                    `;
                } catch (error) {
                    statusEl.innerHTML = `<p class="error">Ошибка загрузки статуса: ${error}</p>`;
                }
            };
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

# ========== ЗАПУСК СЕРВЕРА ==========

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print("=" * 50)
    print("🚀 DevNet Messenger API запущен!")
    print(f"📡 Порт: {port}")
    print(f"📁 Директория загрузок: {UPLOAD_DIR}")
    print(f"🔗 API документация: http://localhost:{port}/api/docs")
    print(f"🔧 Тестовая страница: http://localhost:{port}/test")
    print(f"💬 Чат: http://localhost:{port}/chat")
    print("👑 Тестовый пользователь: admin / admin123")
    print("=" * 50)
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=False
    )
