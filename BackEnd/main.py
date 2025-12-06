from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, Form, Request, File, UploadFile, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc, func, or_, and_
import json
from datetime import datetime, timedelta
from pathlib import Path
import uvicorn 
import os
import sys
import shutil
import uuid
from typing import Optional, List, Dict, Any
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

# ========== УПРОЩЕННЫЙ ИМПОРТ МОДЕЛЕЙ ==========

# Создаем простые модели напрямую чтобы избежать ошибок импорта
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, JSON
from sqlalchemy.orm import relationship

# Создаем базовые модели
Base = None
try:
    from database import Base
    from models import User, Message, Group, Channel, Subscription, GroupMember
    print("✅ Full models imported successfully")
except ImportError as e:
    print(f"⚠️  Warning importing models: {e}")
    print("⚠️  Creating simplified models...")
    
    # Создаем базовый класс если не импортировался
    from sqlalchemy.ext.declarative import declarative_base
    Base = declarative_base()
    
    # Простая модель User
    class User(Base):
        __tablename__ = "users"
        
        id = Column(Integer, primary_key=True, index=True)
        username = Column(String(50), unique=True, index=True, nullable=False)
        email = Column(String(100), unique=True, index=True, nullable=False)
        display_name = Column(String(100))
        avatar_url = Column(String(500))
        password_hash = Column(String(255), nullable=False)
        is_online = Column(Boolean, default=False)
        is_guest = Column(Boolean, default=False)
        is_admin = Column(Boolean, default=False)
        created_at = Column(DateTime, default=datetime.utcnow)
    
    # Простая модель Message
    class Message(Base):
        __tablename__ = "messages"
        
        id = Column(Integer, primary_key=True, index=True)
        from_user_id = Column(Integer, ForeignKey("users.id"))
        to_user_id = Column(Integer, ForeignKey("users.id"))
        group_id = Column(Integer, nullable=True)
        channel_id = Column(Integer, nullable=True)
        content = Column(Text)
        message_type = Column(String(20), default="text")
        media_url = Column(String(500))
        media_size = Column(Integer)
        filename = Column(String(255))
        created_at = Column(DateTime, default=datetime.utcnow)
    
    # Простые версии других моделей
    class Group(Base):
        __tablename__ = "groups"
        id = Column(Integer, primary_key=True, index=True)
        name = Column(String(100))
        description = Column(Text)
        avatar_url = Column(String(500))
        is_public = Column(Boolean, default=True)
        owner_id = Column(Integer, ForeignKey("users.id"))
        members_count = Column(Integer, default=0)
        created_at = Column(DateTime, default=datetime.utcnow)
    
    class Channel(Base):
        __tablename__ = "channels"
        id = Column(Integer, primary_key=True, index=True)
        name = Column(String(100))
        description = Column(Text)
        avatar_url = Column(String(500))
        is_public = Column(Boolean, default=True)
        owner_id = Column(Integer, ForeignKey("users.id"))
        subscribers_count = Column(Integer, default=0)
        created_at = Column(DateTime, default=datetime.utcnow)
    
    class Subscription(Base):
        __tablename__ = "subscriptions"
        id = Column(Integer, primary_key=True, index=True)
        channel_id = Column(Integer, ForeignKey("channels.id"))
        user_id = Column(Integer, ForeignKey("users.id"))
        role = Column(String(20), default="subscriber")
        created_at = Column(DateTime, default=datetime.utcnow)
    
    class GroupMember(Base):
        __tablename__ = "group_members"
        id = Column(Integer, primary_key=True, index=True)
        group_id = Column(Integer, ForeignKey("groups.id"))
        user_id = Column(Integer, ForeignKey("users.id"))
        role = Column(String(20), default="member")
        created_at = Column(DateTime, default=datetime.utcnow)
    
    print("✅ Simplified models created")

# ========== WEBSOCKET MANAGER ==========

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, WebSocket] = {}
    
    async def connect(self, websocket: WebSocket, user_id: int):
        await websocket.accept()
        self.active_connections[user_id] = websocket
        print(f"✅ User {user_id} connected")
    
    def disconnect(self, user_id: int):
        if user_id in self.active_connections:
            del self.active_connections[user_id]
        print(f"📴 User {user_id} disconnected")
    
    async def send_to_user(self, user_id: int, message: Dict[str, Any]):
        if user_id in self.active_connections:
            try:
                await self.active_connections[user_id].send_json(message)
            except:
                self.disconnect(user_id)
    
    async def broadcast(self, message: Dict[str, Any], exclude_user_id: Optional[int] = None):
        disconnected = []
        for user_id, connection in self.active_connections.items():
            if user_id != exclude_user_id:
                try:
                    await connection.send_json(message)
                except:
                    disconnected.append(user_id)
        
        for user_id in disconnected:
            self.disconnect(user_id)

manager = ConnectionManager()

# ========== AUTH MODULE ==========

from passlib.context import CryptContext
from jose import JWTError, jwt

SECRET_KEY = "devnet_secret_key_change_in_production_1234567890"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440  # 24 часа

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password, hashed_password):
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception as e:
        print(f"❌ Password verification error: {e}")
        return False

def get_password_hash(password):
    # Обрезаем пароль если слишком длинный для bcrypt
    password_to_hash = password[:72] if len(password) > 72 else password
    return pwd_context.hash(password_to_hash)

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
    except JWTError as e:
        print(f"❌ Token verification error: {e}")
        return None

def get_current_user(request: Request, db: Session = Depends(get_db)):
    """Получаем текущего пользователя из токена"""
    token = request.cookies.get("access_token")
    if not token:
        # Пробуем получить из заголовков Authorization
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
    
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
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный токен"
        )
    
    user = db.query(User).filter(User.id == user_id).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден"
        )
    
    return user

# ========== СОЗДАНИЕ АДМИНИСТРАТОРА ==========

def create_admin_user():
    """Создает администратора если его нет в базе"""
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.username == "admin").first()
        if not admin:
            print("👑 Создаем администратора...")
            admin_password = "admin123"
            
            admin_user = User(
                username="admin",
                email="admin@devnet.local",
                display_name="Администратор",
                password_hash=get_password_hash(admin_password),
                is_admin=True
            )
            db.add(admin_user)
            db.commit()
            print("✅ Администратор создан (логин: admin, пароль: admin123)")
        else:
            print("✅ Администратор уже существует")
    except Exception as e:
        print(f"⚠️  Ошибка создания администратора: {e}")
        db.rollback()
    finally:
        db.close()

create_admin_user()

# ========== СОЗДАНИЕ FASTAPI ПРИЛОЖЕНИЯ ==========

app = FastAPI(
    title="DevNet Messenger API",
    description="Simple messenger for developers",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc"
)

# Настройка CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Создаем директории
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)
for media_type in ["images", "avatars", "files"]:
    (UPLOAD_DIR / media_type).mkdir(exist_ok=True)

print(f"📁 Upload directory: {UPLOAD_DIR}")

# Получаем абсолютный путь к фронтенду
current_dir = Path(__file__).parent
project_root = current_dir.parent
frontend_dir = project_root / "frontend"

print(f"📁 Project root: {project_root}")
print(f"📁 Frontend directory: {frontend_dir}")

# ========== HEALTH CHECK ==========

@app.get("/health")
async def health_check():
    return JSONResponse(content={"status": "ok"}, status_code=200)

@app.get("/api/health")
async def api_health_check():
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

# ========== AUTH ENDPOINTS ==========

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
    print(f"🔵 Регистрация: username={username}, email={email}")
    try:
        # Проверяем уникальность username
        existing_user = db.query(User).filter(User.username == username).first()
        if existing_user:
            print(f"❌ Имя пользователя уже занято: {username}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Имя пользователя уже занято"
            )
        
        # Проверяем уникальность email
        existing_email = db.query(User).filter(User.email == email).first()
        if existing_email:
            print(f"❌ Email уже используется: {email}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email уже используется"
            )
        
        # Проверяем пароль
        if len(password) < 6:
            print(f"❌ Пароль слишком короткий: {len(password)} символов")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Пароль должен быть не менее 6 символов"
            )
        
        if len(password) > 72:
            print(f"❌ Пароль слишком длинный: {len(password)} символов")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Пароль не должен превышать 72 символа"
            )
        
        # Создаем пользователя
        user = User(
            username=username,
            email=email,
            display_name=display_name or username,
            password_hash=get_password_hash(password),
            is_guest=False
        )
        
        db.add(user)
        db.commit()
        db.refresh(user)
        
        print(f"✅ Пользователь создан: {username} (ID: {user.id})")
        
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
                "email": user.email,
                "is_admin": user.is_admin
            },
            "access_token": access_token
        }
        
        response = JSONResponse(content=response_data)
        
        response.set_cookie(
            key="access_token",
            value=access_token,
            httponly=True,
            max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            samesite="lax",
            secure=os.environ.get("RAILWAY_ENVIRONMENT") is not None  # HTTPS в production
        )
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print(f"❌ Ошибка регистрации: {str(e)}")
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
    print(f"🔵 Попытка входа: username={username}")
    try:
        # Ищем пользователя по username
        user = db.query(User).filter(User.username == username).first()
        
        if not user:
            print(f"❌ Пользователь не найден: {username}")
            # Проверяем может быть это email
            user = db.query(User).filter(User.email == username).first()
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Пользователь не найден"
                )
        
        print(f"🔵 Найден пользователь: {user.username}, проверка пароля...")
        
        # Проверяем пароль
        if not verify_password(password, user.password_hash):
            print(f"❌ Неверный пароль для пользователя: {user.username}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Неверное имя пользователя или пароль"
            )
        
        print(f"✅ Успешный вход: {user.username} (ID: {user.id})")
        
        # Обновляем время последнего входа
        user.last_login = datetime.utcnow()
        db.commit()
        
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
                "avatar_url": user.avatar_url,
                "is_admin": user.is_admin
            },
            "access_token": access_token
        }
        
        response = JSONResponse(content=response_data)
        
        response.set_cookie(
            key="access_token",
            value=access_token,
            httponly=True,
            max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            samesite="lax",
            secure=os.environ.get("RAILWAY_ENVIRONMENT") is not None
        )
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Ошибка входа: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка входа: {str(e)}"
        )

@app.get("/api/me")
@app.get("/api/auth/me")
async def get_current_user_info(
    user: User = Depends(get_current_user)
):
    """Получение информации о текущем пользователе"""
    return {
        "success": True,
        "user": {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "email": user.email,
            "avatar_url": user.avatar_url,
            "is_online": user.is_online,
            "is_admin": user.is_admin,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "last_login": user.last_login.isoformat() if user.last_login else None
        }
    }

@app.post("/api/auth/logout")
async def logout_user():
    """Выход пользователя"""
    response = JSONResponse(content={
        "success": True,
        "message": "Выход выполнен успешно"
    })
    response.delete_cookie(key="access_token")
    return response

# ========== USERS ENDPOINTS ==========

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
        
        if online_only:
            query = query.filter(User.is_online == True)
        
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

@app.get("/api/users/{user_id}")
async def get_user_by_id(user_id: int, db: Session = Depends(get_db)):
    """Получение информации о конкретном пользователе"""
    try:
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
                "avatar_url": user.avatar_url,
                "is_online": user.is_online,
                "created_at": user.created_at.isoformat() if user.created_at else None,
                "email": user.email
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка загрузки пользователя: {str(e)}"
        )

# ========== MESSAGES ENDPOINTS ==========

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

@app.get("/api/messages/chat/{chat_type}/{chat_id}")
async def get_chat_messages(
    chat_type: str,
    chat_id: int,
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение сообщений для чата"""
    try:
        query = db.query(Message)
        
        if chat_type == "private":
            # Личные сообщения с пользователем
            query = query.filter(
                or_(
                    and_(Message.from_user_id == user.id, Message.to_user_id == chat_id),
                    and_(Message.from_user_id == chat_id, Message.to_user_id == user.id)
                )
            )
        elif chat_type == "group":
            # Сообщения группы
            query = query.filter(Message.group_id == chat_id)
        elif chat_type == "channel":
            # Сообщения канала
            query = query.filter(Message.channel_id == chat_id)
        else:
            raise HTTPException(status_code=400, detail="Неверный тип чата")
        
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
                "media_url": msg.media_url,
                "media_size": msg.media_size,
                "filename": msg.filename,
                "is_my_message": msg.from_user_id == user.id,
                "from_user_id": msg.from_user_id,
                "group_id": msg.group_id,
                "channel_id": msg.channel_id,
                "reactions": {},
                "sender": {
                    "id": sender.id if sender else None,
                    "username": sender.username if sender else None,
                    "display_name": sender.display_name if sender else None,
                    "avatar_url": sender.avatar_url if sender else None
                } if sender else None,
                "created_at": msg.created_at.isoformat() if msg.created_at else None
            })
        
        messages_data.reverse()  # Чтобы старые сообщения были в начале
        
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
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка загрузки сообщений: {str(e)}"
        )

@app.post("/api/messages")
async def create_message(
    content: str = Form(...),
    message_type: str = Form("text"),
    to_user_id: Optional[int] = Form(None),
    group_id: Optional[int] = Form(None),
    channel_id: Optional[int] = Form(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Создание нового сообщения"""
    try:
        if not content or len(content.strip()) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Сообщение не может быть пустым"
            )
        
        # Проверяем, куда отправляется сообщение
        chat_type = None
        if to_user_id:
            chat_type = "private"
            # Проверяем существование получателя
            recipient = db.query(User).filter(User.id == to_user_id).first()
            if not recipient:
                raise HTTPException(status_code=404, detail="Получатель не найден")
        elif group_id:
            chat_type = "group"
            # Проверяем существование группы
            group = db.query(Group).filter(Group.id == group_id).first()
            if not group:
                raise HTTPException(status_code=404, detail="Группа не найдена")
        elif channel_id:
            chat_type = "channel"
            # Проверяем существование канала
            channel = db.query(Channel).filter(Channel.id == channel_id).first()
            if not channel:
                raise HTTPException(status_code=404, detail="Канал не найден")
        else:
            raise HTTPException(status_code=400, detail="Не указан получатель")
        
        # Создаем сообщение
        message = Message(
            from_user_id=user.id,
            to_user_id=to_user_id,
            group_id=group_id,
            channel_id=channel_id,
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

# ========== STATIC FILES AND PAGES ==========

# Проверяем существование фронтенда
if frontend_dir.exists():
    print(f"✅ Frontend found: {frontend_dir}")
    
    # Явные маршруты для основных страниц
    @app.get("/")
    async def serve_home():
        """Главная страница"""
        index_path = frontend_dir / "index.html"
        if index_path.exists():
            return FileResponse(str(index_path))
        return HTMLResponse("""
        <!DOCTYPE html>
        <html>
        <head><title>DevNet Messenger</title></head>
        <body>
            <h1>DevNet Messenger</h1>
            <p>index.html not found in frontend folder</p>
            <p><a href="/api/docs">API Documentation</a></p>
        </body>
        </html>
        """)
    
    @app.get("/chat")
    async def serve_chat():
        """Страница чата"""
        chat_path = frontend_dir / "chat.html"
        if chat_path.exists():
            return FileResponse(str(chat_path))
        return HTMLResponse("""
        <!DOCTYPE html>
        <html>
        <head>
            <title>DevNet Chat</title>
            <style>
                body { font-family: Arial; padding: 50px; text-align: center; }
                .error { background: #ffebee; padding: 20px; border-radius: 10px; margin: 20px auto; max-width: 600px; }
            </style>
        </head>
        <body>
            <h1>DevNet Chat</h1>
            <div class="error">
                <h2>⚠️ chat.html not found</h2>
                <p>The chat.html file was not found in the frontend folder.</p>
                <p><a href="/">Go to Home</a></p>
            </div>
        </body>
        </html>
        """)
    
    @app.get("/test")
    async def test_page():
        """Тестовая страница"""
        return HTMLResponse("""
        <!DOCTYPE html>
        <html>
        <head><title>Test Page</title></head>
        <body>
            <h1>DevNet Messenger Test</h1>
            <div id="result"></div>
            <script>
                async function testAuth() {
                    try {
                        const response = await fetch('/api/me');
                        const data = await response.json();
                        document.getElementById('result').innerHTML = 
                            `<pre>${JSON.stringify(data, null, 2)}</pre>`;
                    } catch (error) {
                        document.getElementById('result').innerHTML = 
                            `<p style="color: red;">Error: ${error}</p>`;
                    }
                }
                testAuth();
            </script>
        </body>
        </html>
        """)
    
    # Монтируем статику
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")
    
    # Обработчик для остальных статических файлов
    @app.get("/{path:path}")
    async def serve_static_files(path: str):
        """Сервит статические файлы"""
        # Игнорируем API маршруты
        if path.startswith("api/"):
            return JSONResponse(
                status_code=404,
                content={"detail": "API endpoint not found"}
            )
        
        file_path = frontend_dir / path
        
        # Если это путь к файлу, отдаем его
        if file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))
        
        # Если это директория или файл не найден, возвращаем index.html
        index_path = frontend_dir / "index.html"
        if index_path.exists():
            return FileResponse(str(index_path))
        
        return JSONResponse(
            status_code=404,
            content={"detail": "File not found"}
        )
        
else:
    print(f"⚠️  Frontend not found: {frontend_dir}")
    
    @app.get("/")
    async def serve_index():
        return HTMLResponse("""
        <!DOCTYPE html>
        <html>
        <head><title>DevNet Messenger</title></head>
        <body>
            <h1>DevNet Messenger</h1>
            <p>Frontend files not found. Please check your deployment.</p>
            <p><a href="/api/health">API Health Check</a> | <a href="/api/docs">API Docs</a></p>
        </body>
        </html>
        """)
    
    @app.get("/chat")
    async def serve_chat_fallback():
        return RedirectResponse("/")

# Монтируем директорию загрузок
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

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
            data = await websocket.receive_json()
            await handle_websocket_message(data, user_id)
                        
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

async def handle_websocket_message(data: Dict[str, Any], user_id: int):
    """Обработка сообщений WebSocket"""
    message_type = data.get("type")
    
    if message_type == "message":
        await handle_chat_message(data, user_id)
    elif message_type == "typing":
        await handle_typing_indicator(data, user_id)

async def handle_chat_message(data: Dict[str, Any], user_id: int):
    """Обработка сообщения чата"""
    chat_type = data.get("chat_type")
    chat_id = data.get("chat_id")
    content = data.get("content", "").strip()
    
    if not content:
        return
    
    db = SessionLocal()
    try:
        # Сохраняем сообщение в БД
        message = Message(
            from_user_id=user_id,
            content=content,
            message_type=data.get("message_type", "text")
        )
        
        if chat_type == "private":
            message.to_user_id = chat_id
        elif chat_type == "group":
            message.group_id = chat_id
        elif chat_type == "channel":
            message.channel_id = chat_id
        
        db.add(message)
        db.commit()
        db.refresh(message)
        
        # Получаем информацию об отправителе
        sender = db.query(User).filter(User.id == user_id).first()
        
        # Формируем сообщение для отправки
        ws_message = {
            "type": "message",
            "chat_type": chat_type,
            "chat_id": chat_id,
            "message": {
                "id": message.id,
                "content": message.content,
                "type": message.message_type,
                "is_my_message": False,
                "from_user_id": message.from_user_id,
                "group_id": message.group_id,
                "channel_id": message.channel_id,
                "sender": {
                    "id": sender.id,
                    "username": sender.username,
                    "display_name": sender.display_name,
                    "avatar_url": sender.avatar_url
                } if sender else None,
                "created_at": message.created_at.isoformat() if message.created_at else None
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Отправляем сообщение
        if chat_type == "private":
            # Отправляем отправителю (подтверждение)
            await manager.send_to_user(user_id, {
                **ws_message,
                "message": {**ws_message["message"], "is_my_message": True}
            })
            # Отправляем получателю
            if chat_id != user_id:
                await manager.send_to_user(chat_id, ws_message)
        elif chat_type in ["group", "channel"]:
            # Отправляем всем кроме отправителя
            await manager.broadcast(ws_message, user_id)
            
    except Exception as e:
        print(f"❌ Ошибка обработки сообщения: {e}")
    finally:
        db.close()

async def handle_typing_indicator(data: Dict[str, Any], user_id: int):
    """Обработка индикатора набора текста"""
    chat_type = data.get("chat_type")
    chat_id = data.get("chat_id")
    is_typing = data.get("is_typing", True)
    
    typing_message = {
        "type": "typing",
        "user_id": user_id,
        "chat_type": chat_type,
        "chat_id": chat_id,
        "is_typing": is_typing,
        "timestamp": datetime.utcnow().isoformat()
    }
    
    if chat_type == "private":
        # Отправляем получателю
        if chat_id != user_id:
            await manager.send_to_user(chat_id, typing_message)
    elif chat_type in ["group", "channel"]:
        # Отправляем всем в чате кроме отправителя
        await manager.broadcast(typing_message, user_id)

# ========== START SERVER ==========

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print("=" * 50)
    print("🚀 DevNet Messenger API запущен!")
    print(f"📡 Порт: {port}")
    print(f"📁 Директория загрузок: {UPLOAD_DIR}")
    print(f"📁 Директория фронтенда: {frontend_dir}")
    print(f"🔗 Главная страница: http://localhost:{port}/")
    print(f"💬 Чат: http://localhost:{port}/chat")
    print(f"🔧 Тестовая страница: http://localhost:{port}/test")
    print(f"📖 API документация: http://localhost:{port}/api/docs")
    print("👑 Тестовый пользователь: admin / admin123")
    print("=" * 50)
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=False
    )
