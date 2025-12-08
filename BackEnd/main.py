from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, Form, Request, File, UploadFile, Query, status, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc, func, or_, and_, text, Column, Integer, String, Boolean, DateTime, Text, ForeignKey, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, relationship
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

# ========== КОНСТАНТЫ И НАСТРОЙКИ ==========

# Получаем настройки из окружения
DOMAIN = os.environ.get("DOMAIN", "localhost")
IS_PRODUCTION = os.environ.get("RAILWAY_ENVIRONMENT") is not None or os.environ.get("PRODUCTION") == "true"
SECRET_KEY = os.environ.get("SECRET_KEY", "devnet_secret_key_change_in_production_1234567890_very_long_and_secure_key_12345")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440  # 24 часа
REFRESH_TOKEN_EXPIRE_DAYS = 30  # 30 дней

print(f"🌍 Domain: {DOMAIN}")
print(f"🚀 Production mode: {IS_PRODUCTION}")
print(f"🔐 Secret key length: {len(SECRET_KEY)}")

# ========== БАЗА ДАННЫХ ==========

# Настройка базы данных
SQLALCHEMY_DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./devnet.db")

# Для SQLite нужно специальное подключение
if SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        connect_args={"check_same_thread": False},
        pool_pre_ping=True
    )
else:
    # Для PostgreSQL/MySQL
    engine = create_engine(SQLALCHEMY_DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    """Dependency для получения сессии БД"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ========== МОДЕЛИ БАЗЫ ДАННЫХ ==========

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
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime)
    last_seen = Column(DateTime)
    
    # Связи
    sent_messages = relationship("Message", foreign_keys="Message.from_user_id", back_populates="sender")
    received_messages = relationship("Message", foreign_keys="Message.to_user_id", back_populates="receiver")
    owned_groups = relationship("Group", foreign_keys="Group.owner_id", back_populates="owner")
    owned_channels = relationship("Channel", foreign_keys="Channel.owner_id", back_populates="owner")
    group_memberships = relationship("GroupMember", back_populates="user")
    channel_subscriptions = relationship("ChannelSubscription", back_populates="user")
    refresh_tokens = relationship("RefreshToken", back_populates="user")

class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    token = Column(String(500), unique=True, index=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_revoked = Column(Boolean, default=False)
    
    # Связи
    user = relationship("User", back_populates="refresh_tokens")

class Message(Base):
    __tablename__ = "messages"
    
    id = Column(Integer, primary_key=True, index=True)
    from_user_id = Column(Integer, ForeignKey("users.id"))
    to_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    group_id = Column(Integer, nullable=True)
    channel_id = Column(Integer, nullable=True)
    content = Column(Text)
    message_type = Column(String(20), default="text")
    media_url = Column(String(500))
    media_size = Column(Integer)
    filename = Column(String(255))
    reactions = Column(JSON, default=dict)
    is_edited = Column(Boolean, default=False)
    is_deleted = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Связи
    sender = relationship("User", foreign_keys=[from_user_id], back_populates="sent_messages")
    receiver = relationship("User", foreign_keys=[to_user_id], back_populates="received_messages")

class Group(Base):
    __tablename__ = "groups"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    avatar_url = Column(String(500))
    is_public = Column(Boolean, default=True)
    is_active = Column(Boolean, default=True)
    owner_id = Column(Integer, ForeignKey("users.id"))
    members_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Связи
    owner = relationship("User", foreign_keys=[owner_id], back_populates="owned_groups")
    members = relationship("GroupMember", back_populates="group")
    messages = relationship("Message", backref="group_ref")

class Channel(Base):
    __tablename__ = "channels"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    avatar_url = Column(String(500))
    is_public = Column(Boolean, default=True)
    is_active = Column(Boolean, default=True)
    owner_id = Column(Integer, ForeignKey("users.id"))
    subscribers_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Связи
    owner = relationship("User", foreign_keys=[owner_id], back_populates="owned_channels")
    subscribers = relationship("ChannelSubscription", back_populates="channel")
    messages = relationship("Message", backref="channel_ref")

class GroupMember(Base):
    __tablename__ = "group_members"
    
    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("groups.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    role = Column(String(20), default="member")
    is_banned = Column(Boolean, default=False)
    joined_at = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime)
    
    # Связи
    group = relationship("Group", back_populates="members")
    user = relationship("User", back_populates="group_memberships")

class ChannelSubscription(Base):
    __tablename__ = "channel_subscriptions"
    
    id = Column(Integer, primary_key=True, index=True)
    channel_id = Column(Integer, ForeignKey("channels.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    role = Column(String(20), default="subscriber")
    is_banned = Column(Boolean, default=False)
    subscribed_at = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime)
    
    # Связи
    channel = relationship("Channel", back_populates="subscribers")
    user = relationship("User", back_populates="channel_subscriptions")

# Создаем таблицы
def create_tables():
    """Создает таблицы в базе данных"""
    try:
        Base.metadata.create_all(bind=engine)
        print("✅ Database tables created successfully")
    except Exception as e:
        print(f"❌ Error creating database tables: {e}")

create_tables()

# ========== АВТОРИЗАЦИЯ И JWT ==========

from passlib.context import CryptContext
from jose import JWTError, jwt

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password, hashed_password):
    """Проверка пароля"""
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception as e:
        print(f"❌ Password verification error: {e}")
        return False

def get_password_hash(password):
    """Хеширование пароля"""
    password_to_hash = password[:72] if len(password) > 72 else password
    return pwd_context.hash(password_to_hash)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Создание access токена"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({
        "exp": expire,
        "iat": datetime.utcnow(),
        "type": "access"
    })
    
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def create_refresh_token(data: dict, db: Session):
    """Создание refresh токена"""
    # Генерируем уникальный токен
    token = secrets.token_urlsafe(64)
    
    # Создаем JWT refresh токен
    expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    
    to_encode = data.copy()
    to_encode.update({
        "exp": expire,
        "iat": datetime.utcnow(),
        "type": "refresh",
        "jti": token  # JWT ID
    })
    
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    
    # Сохраняем в базу данных
    refresh_token = RefreshToken(
        user_id=data["user_id"],
        token=token,
        expires_at=expire
    )
    
    db.add(refresh_token)
    db.commit()
    db.refresh(refresh_token)
    
    return encoded_jwt

def verify_token(token: str):
    """Проверка JWT токена"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        print("❌ Token has expired")
        return None
    except jwt.JWTError as e:
        print(f"❌ Token verification error: {e}")
        return None

def verify_refresh_token(token: str, db: Session):
    """Проверка refresh токена"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        
        if payload.get("type") != "refresh":
            print("❌ Not a refresh token")
            return None
        
        token_jti = payload.get("jti")
        if not token_jti:
            print("❌ No JTI in refresh token")
            return None
        
        # Проверяем в базе данных
        refresh_token = db.query(RefreshToken).filter(
            RefreshToken.token == token_jti,
            RefreshToken.is_revoked == False,
            RefreshToken.expires_at > datetime.utcnow()
        ).first()
        
        if not refresh_token:
            print("❌ Refresh token not found or revoked")
            return None
        
        return payload
    except jwt.ExpiredSignatureError:
        print("❌ Refresh token has expired")
        return None
    except jwt.JWTError as e:
        print(f"❌ Refresh token verification error: {e}")
        return None

def revoke_refresh_token(token_jti: str, db: Session):
    """Отзыв refresh токена"""
    refresh_token = db.query(RefreshToken).filter(
        RefreshToken.token == token_jti
    ).first()
    
    if refresh_token:
        refresh_token.is_revoked = True
        db.commit()
        return True
    
    return False

async def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
    require_auth: bool = True
):
    """Получение текущего пользователя"""
    # Пробуем получить токен из разных источников
    token = None
    
    # 1. Из cookies
    token = request.cookies.get("access_token")
    
    # 2. Из заголовка Authorization
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
    
    # 3. Из query параметра (для WebSocket и т.д.)
    if not token:
        token = request.query_params.get("token")
    
    if not token:
        if require_auth:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Требуется аутентификация",
                headers={"WWW-Authenticate": "Bearer"},
            )
        else:
            return None
    
    print(f"🔍 Token received: {token[:20]}...")
    
    payload = verify_token(token)
    if not payload:
        if require_auth:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Недействительный или просроченный токен",
                headers={"WWW-Authenticate": "Bearer"},
            )
        else:
            return None
    
    user_id = payload.get("user_id")
    if not user_id:
        if require_auth:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Неверный формат токена",
            )
        else:
            return None
    
    user = db.query(User).filter(User.id == user_id).first()
    
    if not user:
        if require_auth:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Пользователь не найден"
            )
        else:
            return None
    
    if not user.is_active:
        if require_auth:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Пользователь заблокирован"
            )
        else:
            return None
    
    # Обновляем время последней активности
    user.last_seen = datetime.utcnow()
    db.commit()
    
    print(f"✅ User authenticated: {user.username} (ID: {user.id})")
    return user

def set_auth_cookies(
    response: Response,
    access_token: str,
    refresh_token: Optional[str] = None
):
    """Установка cookies для аутентификации"""
    # Настройки cookies
    cookie_settings = {
        "httponly": True,
        "samesite": "lax" if IS_PRODUCTION else "none",
        "secure": IS_PRODUCTION,
        "path": "/"
    }
    
    # Добавляем домен если не localhost
    if DOMAIN != "localhost":
        cookie_settings["domain"] = DOMAIN
    
    # Устанавливаем access token cookie
    response.set_cookie(
        key="access_token",
        value=access_token,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        **cookie_settings
    )
    
    # Устанавливаем refresh token cookie если есть
    if refresh_token:
        response.set_cookie(
            key="refresh_token",
            value=refresh_token,
            max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
            **cookie_settings
        )

def clear_auth_cookies(response: Response):
    """Очистка auth cookies"""
    cookie_settings = {
        "path": "/"
    }
    
    if DOMAIN != "localhost":
        cookie_settings["domain"] = DOMAIN
    
    response.delete_cookie("access_token", **cookie_settings)
    response.delete_cookie("refresh_token", **cookie_settings)

# ========== СОЗДАНИЕ ТЕСТОВЫХ ДАННЫХ ==========

def create_initial_data():
    """Создание начальных данных в базе"""
    db = SessionLocal()
    try:
        # Создаем администратора если его нет
        admin = db.query(User).filter(User.username == "admin").first()
        if not admin:
            print("👑 Создаем администратора...")
            admin_user = User(
                username="admin",
                email="admin@devnet.local",
                display_name="Администратор",
                password_hash=get_password_hash("admin123"),
                is_admin=True,
                is_active=True,
                last_login=datetime.utcnow(),
                last_seen=datetime.utcnow()
            )
            db.add(admin_user)
            db.commit()
            print("✅ Администратор создан")
            print("   Логин: admin")
            print("   Пароль: admin123")
        else:
            print("✅ Администратор уже существует")
        
        # Создаем тестовых пользователей
        test_users = [
            ("alice", "alice@devnet.local", "Алиса", "alice123"),
            ("bob", "bob@devnet.local", "Боб", "bob123"),
            ("charlie", "charlie@devnet.local", "Чарли", "charlie123"),
            ("david", "david@devnet.local", "Давид", "david123"),
            ("eve", "eve@devnet.local", "Ева", "eve123"),
        ]
        
        created_users = []
        for username, email, display_name, password in test_users:
            user = db.query(User).filter(User.username == username).first()
            if not user:
                user = User(
                    username=username,
                    email=email,
                    display_name=display_name,
                    password_hash=get_password_hash(password),
                    is_active=True,
                    last_login=datetime.utcnow(),
                    last_seen=datetime.utcnow()
                )
                db.add(user)
                created_users.append(username)
        
        if created_users:
            db.commit()
            print(f"✅ Созданы пользователи: {', '.join(created_users)}")
        
        # Создаем тестовую группу
        group = db.query(Group).filter(Group.name == "Общий чат").first()
        if not group:
            admin_user = db.query(User).filter(User.username == "admin").first()
            if admin_user:
                group = Group(
                    name="Общий чат",
                    description="Общий чат для всех пользователей",
                    is_public=True,
                    owner_id=admin_user.id,
                    members_count=1
                )
                db.add(group)
                db.commit()
                db.refresh(group)
                
                # Добавляем администратора в группу
                group_member = GroupMember(
                    group_id=group.id,
                    user_id=admin_user.id,
                    role="admin"
                )
                db.add(group_member)
                db.commit()
                print("✅ Создана тестовая группа: Общий чат")
        
        # Создаем тестовый канал
        channel = db.query(Channel).filter(Channel.name == "Новости").first()
        if not channel:
            admin_user = db.query(User).filter(User.username == "admin").first()
            if admin_user:
                channel = Channel(
                    name="Новости",
                    description="Канал с новостями проекта",
                    is_public=True,
                    owner_id=admin_user.id,
                    subscribers_count=1
                )
                db.add(channel)
                db.commit()
                db.refresh(channel)
                
                # Добавляем администратора в подписчики
                subscription = ChannelSubscription(
                    channel_id=channel.id,
                    user_id=admin_user.id,
                    role="admin"
                )
                db.add(subscription)
                db.commit()
                print("✅ Создан тестовый канал: Новости")
        
        print("✅ Начальные данные созданы успешно")
        
    except Exception as e:
        print(f"❌ Ошибка создания начальных данных: {e}")
        db.rollback()
    finally:
        db.close()

create_initial_data()

# ========== WEBSOCKET MANAGER ==========

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, WebSocket] = {}
        self.user_activity: Dict[int, datetime] = {}
    
    async def connect(self, websocket: WebSocket, user_id: int):
        await websocket.accept()
        self.active_connections[user_id] = websocket
        self.user_activity[user_id] = datetime.utcnow()
        print(f"✅ User {user_id} connected to WebSocket")
        
        # Обновляем статус пользователя в БД
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if user:
                user.is_online = True
                user.last_seen = datetime.utcnow()
                db.commit()
                
                # Уведомляем других пользователей
                await self.broadcast_user_status(user_id, True)
        except Exception as e:
            print(f"⚠️  Error updating user status: {e}")
        finally:
            db.close()
    
    def disconnect(self, user_id: int):
        if user_id in self.active_connections:
            del self.active_connections[user_id]
        if user_id in self.user_activity:
            del self.user_activity[user_id]
        print(f"📴 User {user_id} disconnected from WebSocket")
        
        # Обновляем статус пользователя в БД
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if user:
                user.is_online = False
                user.last_seen = datetime.utcnow()
                db.commit()
                
                # Уведомляем других пользователей
                asyncio.create_task(self.broadcast_user_status(user_id, False))
        except Exception as e:
            print(f"⚠️  Error updating user status on disconnect: {e}")
        finally:
            db.close()
    
    async def send_to_user(self, user_id: int, message: Dict[str, Any]):
        if user_id in self.active_connections:
            try:
                await self.active_connections[user_id].send_json(message)
                self.user_activity[user_id] = datetime.utcnow()
            except Exception as e:
                print(f"❌ Error sending to user {user_id}: {e}")
                self.disconnect(user_id)
    
    async def broadcast(self, message: Dict[str, Any], exclude_user_id: Optional[int] = None):
        disconnected = []
        for user_id, connection in self.active_connections.items():
            if user_id != exclude_user_id:
                try:
                    await connection.send_json(message)
                    self.user_activity[user_id] = datetime.utcnow()
                except Exception as e:
                    print(f"❌ Error broadcasting to user {user_id}: {e}")
                    disconnected.append(user_id)
        
        for user_id in disconnected:
            self.disconnect(user_id)
    
    async def broadcast_user_status(self, user_id: int, is_online: bool):
        """Уведомление о изменении статуса пользователя"""
        message = {
            "type": "user_status",
            "user_id": user_id,
            "is_online": is_online,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        await self.broadcast(message, exclude_user_id=user_id)
    
    def get_online_users(self) -> List[int]:
        """Получение списка онлайн пользователей"""
        return list(self.active_connections.keys())

import asyncio
manager = ConnectionManager()

# ========== СОЗДАНИЕ FASTAPI ПРИЛОЖЕНИЯ ==========

app = FastAPI(
    title="DevNet Messenger API",
    description="Full-featured messenger for developers",
    version="2.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json"
)

# Настройка CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # В production заменить на конкретные домены
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"]
)

# Создаем директории для загрузок
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

for media_type in ["images", "avatars", "files", "videos", "audios"]:
    (UPLOAD_DIR / media_type).mkdir(exist_ok=True)

print(f"📁 Upload directory: {UPLOAD_DIR}")

# Получаем абсолютный путь к фронтенду
current_dir = Path(__file__).parent
project_root = current_dir.parent
frontend_dir = project_root / "frontend"

print(f"📁 Project root: {project_root}")
print(f"📁 Frontend directory: {frontend_dir}")

# ========== HEALTH CHECK ==========

@app.get("/")
async def root():
    """Корневой эндпоинт"""
    return {
        "message": "DevNet Messenger API",
        "version": "2.0.0",
        "docs": "/api/docs",
        "status": "running"
    }

@app.get("/health")
async def health_check():
    """Health check эндпоинт"""
    return JSONResponse(
        content={"status": "ok", "timestamp": datetime.utcnow().isoformat()},
        status_code=200
    )

@app.get("/api/health")
async def api_health_check(db: Session = Depends(get_db)):
    """Проверка здоровья API и базы данных"""
    try:
        # Проверяем подключение к базе данных
        db.execute(text("SELECT 1"))
        
        # Получаем статистику
        users_count = db.query(User).count()
        messages_count = db.query(Message).count()
        groups_count = db.query(Group).count()
        channels_count = db.query(Channel).count()
        
        return {
            "status": "healthy",
            "service": "DevNet Messenger",
            "version": "2.0.0",
            "timestamp": datetime.utcnow().isoformat(),
            "database": "connected",
            "production": IS_PRODUCTION,
            "domain": DOMAIN,
            "statistics": {
                "users": users_count,
                "messages": messages_count,
                "groups": groups_count,
                "channels": channels_count
            }
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Service unavailable: {str(e)}"
        )

# ========== AUTH ENDPOINTS ==========

@app.post("/api/register")
async def register_user(
    response: Response,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    display_name: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """Регистрация нового пользователя"""
    print(f"🔵 Регистрация: username={username}, email={email}")
    
    try:
        # Валидация username
        if len(username) < 3:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Имя пользователя должно быть не менее 3 символов"
            )
        
        if not username.isalnum() and "_" not in username and "-" not in username:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Имя пользователя может содержать только буквы, цифры, дефисы и подчеркивания"
            )
        
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
        
        # Валидация пароля
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
            password_hash=get_password_hash(password),
            is_guest=False,
            is_active=True,
            last_login=datetime.utcnow(),
            last_seen=datetime.utcnow()
        )
        
        db.add(user)
        db.commit()
        db.refresh(user)
        
        print(f"✅ Пользователь создан: {username} (ID: {user.id})")
        
        # Создаем токены
        access_token = create_access_token(
            data={"user_id": user.id, "username": user.username}
        )
        
        refresh_token = create_refresh_token(
            data={"user_id": user.id, "username": user.username},
            db=db
        )
        
        # Устанавливаем cookies
        set_auth_cookies(response, access_token, refresh_token)
        
        return {
            "success": True,
            "message": "Регистрация успешна",
            "user": {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "email": user.email,
                "avatar_url": user.avatar_url,
                "is_admin": user.is_admin,
                "is_online": user.is_online,
                "created_at": user.created_at.isoformat() if user.created_at else None
            },
            "tokens": {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60
            }
        }
        
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
async def login_user(
    response: Response,
    username: str = Form(...),
    password: str = Form(...),
    remember_me: bool = Form(False),
    db: Session = Depends(get_db)
):
    """Вход пользователя"""
    print(f"🔵 Попытка входа: username={username}, remember_me={remember_me}")
    
    try:
        # Ищем пользователя по username или email
        user = db.query(User).filter(
            or_(
                User.username == username,
                User.email == username
            )
        ).first()
        
        if not user:
            print(f"❌ Пользователь не найден: {username}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Неверное имя пользователя или пароль"
            )
        
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Пользователь заблокирован"
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
        user.last_seen = datetime.utcnow()
        user.is_online = True
        db.commit()
        
        # Создаем токены
        access_token_expires = timedelta(
            minutes=ACCESS_TOKEN_EXPIRE_MINUTES if not remember_me else ACCESS_TOKEN_EXPIRE_MINUTES * 7
        )
        
        access_token = create_access_token(
            data={"user_id": user.id, "username": user.username},
            expires_delta=access_token_expires
        )
        
        refresh_token = create_refresh_token(
            data={"user_id": user.id, "username": user.username},
            db=db
        )
        
        # Устанавливаем cookies
        set_auth_cookies(response, access_token, refresh_token)
        
        return {
            "success": True,
            "message": "Вход выполнен успешно",
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
            },
            "tokens": {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_in": access_token_expires.total_seconds()
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Ошибка входа: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка входа: {str(e)}"
        )

@app.post("/api/auth/refresh")
async def refresh_token(
    request: Request,
    response: Response,
    db: Session = Depends(get_db)
):
    """Обновление access токена с помощью refresh токена"""
    # Получаем refresh токен из cookies или тела запроса
    refresh_token = request.cookies.get("refresh_token")
    
    if not refresh_token:
        # Пробуем получить из тела запроса
        try:
            body = await request.json()
            refresh_token = body.get("refresh_token")
        except:
            pass
    
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token не предоставлен"
        )
    
    # Проверяем refresh токен
    payload = verify_refresh_token(refresh_token, db)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Недействительный или просроченный refresh token"
        )
    
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный формат refresh token"
        )
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден или заблокирован"
        )
    
    # Создаем новый access токен
    access_token = create_access_token(
        data={"user_id": user.id, "username": user.username}
    )
    
    # Создаем новый refresh токен (ротация токенов)
    new_refresh_token = create_refresh_token(
        data={"user_id": user.id, "username": user.username},
        db=db
    )
    
    # Отзываем старый refresh токен
    token_jti = payload.get("jti")
    if token_jti:
        revoke_refresh_token(token_jti, db)
    
    # Устанавливаем новые cookies
    set_auth_cookies(response, access_token, new_refresh_token)
    
    return {
        "success": True,
        "message": "Токены успешно обновлены",
        "tokens": {
            "access_token": access_token,
            "refresh_token": new_refresh_token,
            "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60
        }
    }

@app.get("/api/me")
async def get_current_user_info(
    user: User = Depends(get_current_user)
):
    """Получение информации о текущем пользователе"""
    print(f"📊 Запрос информации о пользователе: {user.username}")
    
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
            "is_active": user.is_active,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "last_login": user.last_login.isoformat() if user.last_login else None,
            "last_seen": user.last_seen.isoformat() if user.last_seen else None
        }
    }

@app.post("/api/auth/logout")
async def logout_user(
    response: Response,
    request: Request,
    user: Optional[User] = Depends(lambda request=Request: get_current_user(request, require_auth=False)),
    db: Session = Depends(get_db)
):
    """Выход пользователя"""
    print(f"🚪 Выход пользователя: {user.username if user else 'unknown'}")
    
    try:
        if user:
            # Обновляем статус пользователя
            user.is_online = False
            user.last_seen = datetime.utcnow()
            db.commit()
            
            # Отзываем refresh токен если есть
            refresh_token = request.cookies.get("refresh_token")
            if refresh_token:
                try:
                    payload = jwt.decode(refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
                    token_jti = payload.get("jti")
                    if token_jti:
                        revoke_refresh_token(token_jti, db)
                except:
                    pass
    
    except Exception as e:
        print(f"⚠️  Ошибка при выходе: {e}")
    
    # Очищаем cookies
    clear_auth_cookies(response)
    
    return {
        "success": True,
        "message": "Выход выполнен успешно"
    }

@app.get("/api/auth/check")
async def check_auth(
    user: Optional[User] = Depends(lambda request=Request: get_current_user(request, require_auth=False))
):
    """Проверка авторизации (не выбрасывает исключение если не авторизован)"""
    if user:
        return {
            "success": True,
            "authenticated": True,
            "user": {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "avatar_url": user.avatar_url,
                "is_online": user.is_online
            }
        }
    else:
        return {
            "success": True,
            "authenticated": False,
            "message": "Не авторизован"
        }

# ========== USERS ENDPOINTS ==========

@app.get("/api/users")
async def get_users(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    online_only: bool = Query(False),
    search: Optional[str] = Query(None),
    exclude_current: bool = Query(True),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение списка пользователей"""
    try:
        query = db.query(User).filter(User.is_active == True)
        
        if exclude_current:
            query = query.filter(User.id != user.id)
        
        if online_only:
            query = query.filter(User.is_online == True)
        
        if search and search.strip():
            search_filter = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    User.username.ilike(search_filter),
                    User.display_name.ilike(search_filter),
                    User.email.ilike(search_filter)
                )
            )
        
        total = query.count()
        users = query.order_by(
            desc(User.is_online),
            desc(User.last_seen),
            User.display_name,
            User.username
        ).offset((page - 1) * limit).limit(limit).all()
        
        users_data = []
        for user_item in users:
            users_data.append({
                "id": user_item.id,
                "username": user_item.username,
                "display_name": user_item.display_name or user_item.username,
                "avatar_url": user_item.avatar_url,
                "is_online": user_item.is_online,
                "is_admin": user_item.is_admin,
                "last_seen": user_item.last_seen.isoformat() if user_item.last_seen else None,
                "created_at": user_item.created_at.isoformat() if user_item.created_at else None
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
async def get_user_by_id(
    user_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение информации о конкретном пользователе"""
    try:
        user_item = db.query(User).filter(
            User.id == user_id,
            User.is_active == True
        ).first()
        
        if not user_item:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Пользователь не найден"
            )
        
        # Проверяем, есть ли общие чаты
        common_chats = False
        common_messages = db.query(Message).filter(
            or_(
                and_(Message.from_user_id == user.id, Message.to_user_id == user_id),
                and_(Message.from_user_id == user_id, Message.to_user_id == user.id)
            )
        ).first()
        
        if common_messages:
            common_chats = True
        
        return {
            "success": True,
            "user": {
                "id": user_item.id,
                "username": user_item.username,
                "display_name": user_item.display_name or user_item.username,
                "avatar_url": user_item.avatar_url,
                "is_online": user_item.is_online,
                "is_admin": user_item.is_admin,
                "last_seen": user_item.last_seen.isoformat() if user_item.last_seen else None,
                "created_at": user_item.created_at.isoformat() if user_item.created_at else None
            },
            "common_chats": common_chats
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка загрузки пользователя: {str(e)}"
        )

@app.put("/api/users/profile")
async def update_user_profile(
    display_name: Optional[str] = Form(None),
    avatar: Optional[UploadFile] = File(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Обновление профиля пользователя"""
    try:
        if display_name:
            user.display_name = display_name.strip() or user.username
        
        if avatar:
            # Сохраняем аватар
            file_ext = avatar.filename.split('.')[-1] if '.' in avatar.filename else 'jpg'
            if file_ext.lower() not in ['jpg', 'jpeg', 'png', 'gif', 'webp']:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Неподдерживаемый формат изображения"
                )
            
            filename = f"avatar_{user.id}_{uuid.uuid4()}.{file_ext}"
            filepath = UPLOAD_DIR / "avatars" / filename
            
            with open(filepath, "wb") as buffer:
                shutil.copyfileobj(avatar.file, buffer)
            
            user.avatar_url = f"/uploads/avatars/{filename}"
        
        user.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(user)
        
        return {
            "success": True,
            "message": "Профиль обновлен",
            "user": {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "avatar_url": user.avatar_url,
                "updated_at": user.updated_at.isoformat() if user.updated_at else None
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка обновления профиля: {str(e)}"
        )

# ========== MESSAGES ENDPOINTS ==========

@app.get("/api/messages")
async def get_messages(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    chat_type: Optional[str] = Query(None),
    chat_id: Optional[int] = Query(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение последних сообщений пользователя"""
    try:
        query = db.query(Message).filter(Message.is_deleted == False)
        
        # Фильтрация по типу чата
        if chat_type and chat_id:
            if chat_type == "private":
                query = query.filter(
                    or_(
                        and_(Message.from_user_id == user.id, Message.to_user_id == chat_id),
                        and_(Message.from_user_id == chat_id, Message.to_user_id == user.id)
                    )
                )
            elif chat_type == "group":
                query = query.filter(Message.group_id == chat_id)
            elif chat_type == "channel":
                query = query.filter(Message.channel_id == chat_id)
        
        # Если не указан чат, получаем все сообщения пользователя
        if not chat_type or not chat_id:
            query = query.filter(
                or_(
                    Message.from_user_id == user.id,
                    Message.to_user_id == user.id,
                    Message.group_id.in_(
                        db.query(GroupMember.group_id).filter(GroupMember.user_id == user.id)
                    ),
                    Message.channel_id.in_(
                        db.query(ChannelSubscription.channel_id).filter(ChannelSubscription.user_id == user.id)
                    )
                )
            )
        
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
            
            # Определяем тип чата
            msg_chat_type = "private"
            msg_chat_id = msg.to_user_id if msg.from_user_id == user.id else msg.from_user_id
            
            if msg.group_id:
                msg_chat_type = "group"
                msg_chat_id = msg.group_id
            elif msg.channel_id:
                msg_chat_type = "channel"
                msg_chat_id = msg.channel_id
            
            messages_data.append({
                "id": msg.id,
                "content": msg.content,
                "type": msg.message_type,
                "media_url": msg.media_url,
                "media_size": msg.media_size,
                "filename": msg.filename,
                "is_my_message": msg.from_user_id == user.id,
                "is_edited": msg.is_edited,
                "chat_type": msg_chat_type,
                "chat_id": msg_chat_id,
                "from_user_id": msg.from_user_id,
                "to_user_id": msg.to_user_id,
                "group_id": msg.group_id,
                "channel_id": msg.channel_id,
                "reactions": msg.reactions or {},
                "sender": {
                    "id": sender.id if sender else None,
                    "username": sender.username if sender else "System",
                    "display_name": sender.display_name if sender else None,
                    "avatar_url": sender.avatar_url if sender else None
                } if sender else {"username": "System"},
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
                "updated_at": msg.updated_at.isoformat() if msg.updated_at else None
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
    before: Optional[str] = Query(None),
    after: Optional[str] = Query(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение сообщений для чата с пагинацией"""
    try:
        query = db.query(Message).filter(Message.is_deleted == False)
        
        if chat_type == "private":
            # Личные сообщения с пользователем
            other_user = db.query(User).filter(
                User.id == chat_id,
                User.is_active == True
            ).first()
            
            if not other_user:
                raise HTTPException(status_code=404, detail="Пользователь не найден")
            
            query = query.filter(
                or_(
                    and_(Message.from_user_id == user.id, Message.to_user_id == chat_id),
                    and_(Message.from_user_id == chat_id, Message.to_user_id == user.id)
                )
            )
            
        elif chat_type == "group":
            # Сообщения группы
            group = db.query(Group).filter(
                Group.id == chat_id,
                Group.is_active == True
            ).first()
            
            if not group:
                raise HTTPException(status_code=404, detail="Группа не найдена")
            
            # Проверяем доступ
            if not group.is_public:
                membership = db.query(GroupMember).filter(
                    GroupMember.group_id == chat_id,
                    GroupMember.user_id == user.id,
                    GroupMember.is_banned == False
                ).first()
                
                if not membership:
                    raise HTTPException(status_code=403, detail="Вы не состоите в этой группе")
            
            query = query.filter(Message.group_id == chat_id)
            
        elif chat_type == "channel":
            # Сообщения канала
            channel = db.query(Channel).filter(
                Channel.id == chat_id,
                Channel.is_active == True
            ).first()
            
            if not channel:
                raise HTTPException(status_code=404, detail="Канал не найден")
            
            # Проверяем доступ
            if not channel.is_public:
                subscription = db.query(ChannelSubscription).filter(
                    ChannelSubscription.channel_id == chat_id,
                    ChannelSubscription.user_id == user.id,
                    ChannelSubscription.is_banned == False
                ).first()
                
                if not subscription:
                    raise HTTPException(status_code=403, detail="Вы не подписаны на этот канал")
            
            query = query.filter(Message.channel_id == chat_id)
            
        else:
            raise HTTPException(status_code=400, detail="Неверный тип чата")
        
        # Фильтрация по времени
        if before:
            try:
                before_time = datetime.fromisoformat(before.replace('Z', '+00:00'))
                query = query.filter(Message.created_at < before_time)
            except:
                pass
        
        if after:
            try:
                after_time = datetime.fromisoformat(after.replace('Z', '+00:00'))
                query = query.filter(Message.created_at > after_time)
            except:
                pass
        
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
                "is_edited": msg.is_edited,
                "from_user_id": msg.from_user_id,
                "to_user_id": msg.to_user_id,
                "group_id": msg.group_id,
                "channel_id": msg.channel_id,
                "reactions": msg.reactions or {},
                "sender": {
                    "id": sender.id if sender else None,
                    "username": sender.username if sender else None,
                    "display_name": sender.display_name if sender else None,
                    "avatar_url": sender.avatar_url if sender else None
                } if sender else None,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
                "updated_at": msg.updated_at.isoformat() if msg.updated_at else None
            })
        
        messages_data.reverse()  # Чтобы старые сообщения были в начале
        
        # Получаем информацию о чате
        chat_info = None
        if chat_type == "private" and other_user:
            chat_info = {
                "type": "private",
                "id": other_user.id,
                "name": other_user.display_name or other_user.username,
                "avatar_url": other_user.avatar_url,
                "is_online": other_user.is_online
            }
        elif chat_type == "group" and group:
            chat_info = {
                "type": "group",
                "id": group.id,
                "name": group.name,
                "avatar_url": group.avatar_url,
                "description": group.description,
                "is_public": group.is_public,
                "members_count": group.members_count
            }
        elif chat_type == "channel" and channel:
            chat_info = {
                "type": "channel",
                "id": channel.id,
                "name": channel.name,
                "avatar_url": channel.avatar_url,
                "description": channel.description,
                "is_public": channel.is_public,
                "subscribers_count": channel.subscribers_count
            }
        
        return {
            "success": True,
            "chat_info": chat_info,
            "messages": messages_data,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "pages": (total + limit - 1) // limit,
                "has_more": total > page * limit
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
    media: Optional[UploadFile] = File(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Создание нового сообщения"""
    try:
        content = content.strip()
        media_url = None
        media_size = None
        filename = None
        
        if not content and not media:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Сообщение не может быть пустым"
            )
        
        # Проверяем получателя
        chat_type = None
        if to_user_id:
            chat_type = "private"
            recipient = db.query(User).filter(
                User.id == to_user_id,
                User.is_active == True
            ).first()
            
            if not recipient:
                raise HTTPException(status_code=404, detail="Получатель не найден")
            
            if to_user_id == user.id:
                raise HTTPException(status_code=400, detail="Нельзя отправлять сообщения самому себе")
                
        elif group_id:
            chat_type = "group"
            group = db.query(Group).filter(
                Group.id == group_id,
                Group.is_active == True
            ).first()
            
            if not group:
                raise HTTPException(status_code=404, detail="Группа не найдена")
            
            # Проверяем доступ
            if not group.is_public:
                membership = db.query(GroupMember).filter(
                    GroupMember.group_id == group_id,
                    GroupMember.user_id == user.id,
                    GroupMember.is_banned == False
                ).first()
                
                if not membership:
                    raise HTTPException(status_code=403, detail="Вы не состоите в этой группе")
                    
        elif channel_id:
            chat_type = "channel"
            channel = db.query(Channel).filter(
                Channel.id == channel_id,
                Channel.is_active == True
            ).first()
            
            if not channel:
                raise HTTPException(status_code=404, detail="Канал не найден")
            
            # Проверяем доступ (владелец может писать всегда)
            if channel.owner_id != user.id:
                subscription = db.query(ChannelSubscription).filter(
                    ChannelSubscription.channel_id == channel_id,
                    ChannelSubscription.user_id == user.id,
                    ChannelSubscription.is_banned == False
                ).first()
                
                if not subscription and not channel.is_public:
                    raise HTTPException(status_code=403, detail="Вы не подписаны на этот канал")
        else:
            raise HTTPException(status_code=400, detail="Не указан получатель")
        
        # Обработка медиа файла
        if media:
            message_type = "file"
            filename = media.filename
            
            # Определяем тип файла
            content_type = media.content_type or ""
            file_ext = filename.split('.')[-1] if '.' in filename else 'bin'
            
            if content_type.startswith('image/'):
                file_type = "images"
                message_type = "image"
            elif content_type.startswith('video/'):
                file_type = "videos"
                message_type = "video"
            elif content_type.startswith('audio/'):
                file_type = "audios"
                message_type = "audio"
            else:
                file_type = "files"
                message_type = "file"
            
            # Сохраняем файл
            unique_filename = f"{uuid.uuid4()}.{file_ext}"
            filepath = UPLOAD_DIR / file_type / unique_filename
            
            with open(filepath, "wb") as buffer:
                shutil.copyfileobj(media.file, buffer)
            
            media_url = f"/uploads/{file_type}/{unique_filename}"
            media_size = filepath.stat().st_size
        
        # Создаем сообщение
        message = Message(
            from_user_id=user.id,
            to_user_id=to_user_id,
            group_id=group_id,
            channel_id=channel_id,
            content=content,
            message_type=message_type,
            media_url=media_url,
            media_size=media_size,
            filename=filename,
            reactions={}
        )
        
        db.add(message)
        db.commit()
        db.refresh(message)
        
        # Получаем информацию об отправителе
        sender = db.query(User).filter(User.id == user.id).first()
        
        # Подготавливаем данные для WebSocket
        ws_message = {
            "type": "message",
            "chat_type": chat_type,
            "chat_id": to_user_id or group_id or channel_id,
            "message": {
                "id": message.id,
                "content": message.content,
                "type": message.message_type,
                "media_url": message.media_url,
                "filename": message.filename,
                "is_my_message": False,
                "is_edited": False,
                "from_user_id": message.from_user_id,
                "to_user_id": message.to_user_id,
                "group_id": message.group_id,
                "channel_id": message.channel_id,
                "reactions": message.reactions or {},
                "sender": {
                    "id": sender.id,
                    "username": sender.username,
                    "display_name": sender.display_name,
                    "avatar_url": sender.avatar_url
                } if sender else None,
                "created_at": message.created_at.isoformat() if message.created_at else datetime.utcnow().isoformat(),
                "updated_at": message.updated_at.isoformat() if message.updated_at else None
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Отправляем через WebSocket
        if chat_type == "private":
            # Отправляем отправителю подтверждение
            await manager.send_to_user(user.id, {
                **ws_message,
                "type": "message_sent",
                "message_id": message.id
            })
            
            # Отправляем получателю
            if to_user_id != user.id:
                await manager.send_to_user(to_user_id, ws_message)
                
        elif chat_type == "group":
            # Получаем всех участников группы
            members = db.query(GroupMember).filter(
                GroupMember.group_id == group_id,
                GroupMember.is_banned == False
            ).all()
            
            for member in members:
                if member.user_id != user.id:
                    await manager.send_to_user(member.user_id, ws_message)
                    
        elif chat_type == "channel":
            # Получаем всех подписчиков канала
            subscribers = db.query(ChannelSubscription).filter(
                ChannelSubscription.channel_id == channel_id,
                ChannelSubscription.is_banned == False
            ).all()
            
            for subscriber in subscribers:
                if subscriber.user_id != user.id:
                    await manager.send_to_user(subscriber.user_id, ws_message)
        
        return {
            "success": True,
            "message": "Сообщение отправлено",
            "data": {
                "id": message.id,
                "content": message.content,
                "type": message.message_type,
                "media_url": message.media_url,
                "filename": message.filename,
                "chat_type": chat_type,
                "chat_id": to_user_id or group_id or channel_id,
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

@app.put("/api/messages/{message_id}")
async def update_message(
    message_id: int,
    content: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Редактирование сообщения"""
    try:
        message = db.query(Message).filter(
            Message.id == message_id,
            Message.from_user_id == user.id,
            Message.is_deleted == False
        ).first()
        
        if not message:
            raise HTTPException(status_code=404, detail="Сообщение не найдено")
        
        # Проверяем, что прошло не слишком много времени
        time_diff = datetime.utcnow() - message.created_at
        if time_diff.total_seconds() > 3600:  # 1 час
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Сообщение можно редактировать только в течение часа"
            )
        
        message.content = content.strip()
        message.is_edited = True
        message.updated_at = datetime.utcnow()
        db.commit()
        
        # Уведомляем через WebSocket
        ws_message = {
            "type": "message_updated",
            "message_id": message.id,
            "content": message.content,
            "updated_at": message.updated_at.isoformat()
        }
        
        # Определяем чат и отправляем уведомление
        if message.to_user_id:
            # Личное сообщение
            participants = [message.from_user_id, message.to_user_id]
            for participant in participants:
                if participant in manager.active_connections:
                    await manager.send_to_user(participant, ws_message)
        elif message.group_id:
            # Групповое сообщение
            members = db.query(GroupMember).filter(
                GroupMember.group_id == message.group_id,
                GroupMember.is_banned == False
            ).all()
            
            for member in members:
                if member.user_id in manager.active_connections:
                    await manager.send_to_user(member.user_id, ws_message)
        elif message.channel_id:
            # Сообщение в канале
            subscribers = db.query(ChannelSubscription).filter(
                ChannelSubscription.channel_id == message.channel_id,
                ChannelSubscription.is_banned == False
            ).all()
            
            for subscriber in subscribers:
                if subscriber.user_id in manager.active_connections:
                    await manager.send_to_user(subscriber.user_id, ws_message)
        
        return {
            "success": True,
            "message": "Сообщение обновлено",
            "data": {
                "id": message.id,
                "content": message.content,
                "is_edited": message.is_edited,
                "updated_at": message.updated_at.isoformat()
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка обновления сообщения: {str(e)}"
        )

@app.delete("/api/messages/{message_id}")
async def delete_message(
    message_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Удаление сообщения"""
    try:
        message = db.query(Message).filter(
            Message.id == message_id,
            Message.from_user_id == user.id,
            Message.is_deleted == False
        ).first()
        
        if not message:
            raise HTTPException(status_code=404, detail="Сообщение не найдено")
        
        # Помечаем как удаленное (мягкое удаление)
        message.is_deleted = True
        message.content = "Сообщение удалено"
        message.media_url = None
        message.filename = None
        message.updated_at = datetime.utcnow()
        db.commit()
        
        # Уведомляем через WebSocket
        ws_message = {
            "type": "message_deleted",
            "message_id": message.id
        }
        
        # Определяем чат и отправляем уведомление
        if message.to_user_id:
            # Личное сообщение
            participants = [message.from_user_id, message.to_user_id]
            for participant in participants:
                if participant in manager.active_connections:
                    await manager.send_to_user(participant, ws_message)
        elif message.group_id:
            # Групповое сообщение
            members = db.query(GroupMember).filter(
                GroupMember.group_id == message.group_id,
                GroupMember.is_banned == False
            ).all()
            
            for member in members:
                if member.user_id in manager.active_connections:
                    await manager.send_to_user(member.user_id, ws_message)
        elif message.channel_id:
            # Сообщение в канале
            subscribers = db.query(ChannelSubscription).filter(
                ChannelSubscription.channel_id == message.channel_id,
                ChannelSubscription.is_banned == False
            ).all()
            
            for subscriber in subscribers:
                if subscriber.user_id in manager.active_connections:
                    await manager.send_to_user(subscriber.user_id, ws_message)
        
        return {
            "success": True,
            "message": "Сообщение удалено"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка удаления сообщения: {str(e)}"
        )

@app.post("/api/messages/{message_id}/reaction")
async def add_message_reaction(
    message_id: int,
    reaction: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Добавление реакции к сообщению"""
    try:
        message = db.query(Message).filter(
            Message.id == message_id,
            Message.is_deleted == False
        ).first()
        
        if not message:
            raise HTTPException(status_code=404, detail="Сообщение не найдено")
        
        # Проверяем доступ к сообщению
        can_react = False
        
        if message.to_user_id:
            # Личное сообщение
            if user.id in [message.from_user_id, message.to_user_id]:
                can_react = True
        elif message.group_id:
            # Групповое сообщение
            membership = db.query(GroupMember).filter(
                GroupMember.group_id == message.group_id,
                GroupMember.user_id == user.id,
                GroupMember.is_banned == False
            ).first()
            
            if membership:
                can_react = True
        elif message.channel_id:
            # Сообщение в канале
            subscription = db.query(ChannelSubscription).filter(
                ChannelSubscription.channel_id == message.channel_id,
                ChannelSubscription.user_id == user.id,
                ChannelSubscription.is_banned == False
            ).first()
            
            if subscription:
                can_react = True
        
        if not can_react:
            raise HTTPException(status_code=403, detail="Нет доступа к сообщению")
        
        # Инициализируем реакции если их нет
        if not message.reactions:
            message.reactions = {}
        
        # Добавляем или удаляем реакцию
        reaction_data = message.reactions.get(reaction, {"count": 0, "users": []})
        
        if user.id in reaction_data["users"]:
            # Удаляем реакцию
            reaction_data["users"].remove(user.id)
            reaction_data["count"] -= 1
            
            if reaction_data["count"] <= 0:
                del message.reactions[reaction]
            else:
                message.reactions[reaction] = reaction_data
        else:
            # Добавляем реакцию
            reaction_data["users"].append(user.id)
            reaction_data["count"] += 1
            message.reactions[reaction] = reaction_data
        
        message.updated_at = datetime.utcnow()
        db.commit()
        
        # Уведомляем через WebSocket
        ws_message = {
            "type": "reaction_update",
            "message_id": message.id,
            "reactions": message.reactions,
            "user_id": user.id,
            "reaction": reaction,
            "added": user.id in reaction_data["users"],
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Определяем чат и отправляем уведомление
        if message.to_user_id:
            # Личное сообщение
            participants = [message.from_user_id, message.to_user_id]
            for participant in participants:
                if participant in manager.active_connections:
                    await manager.send_to_user(participant, ws_message)
        elif message.group_id:
            # Групповое сообщение
            members = db.query(GroupMember).filter(
                GroupMember.group_id == message.group_id,
                GroupMember.is_banned == False
            ).all()
            
            for member in members:
                if member.user_id in manager.active_connections:
                    await manager.send_to_user(member.user_id, ws_message)
        elif message.channel_id:
            # Сообщение в канале
            subscribers = db.query(ChannelSubscription).filter(
                ChannelSubscription.channel_id == message.channel_id,
                ChannelSubscription.is_banned == False
            ).all()
            
            for subscriber in subscribers:
                if subscriber.user_id in manager.active_connections:
                    await manager.send_to_user(subscriber.user_id, ws_message)
        
        return {
            "success": True,
            "message": "Реакция обновлена",
            "reactions": message.reactions
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка добавления реакции: {str(e)}"
        )

# ========== GROUPS ENDPOINTS ==========

@app.get("/api/groups")
async def get_groups(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    search: Optional[str] = Query(None),
    only_my: bool = Query(False),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение списка групп"""
    try:
        query = db.query(Group).filter(Group.is_active == True)
        
        if only_my:
            # Только группы, в которых состоит пользователь
            user_group_ids = db.query(GroupMember.group_id).filter(
                GroupMember.user_id == user.id,
                GroupMember.is_banned == False
            ).subquery()
            
            query = query.filter(Group.id.in_(user_group_ids))
        else:
            # Публичные группы или группы, в которых состоит пользователь
            user_group_ids = db.query(GroupMember.group_id).filter(
                GroupMember.user_id == user.id,
                GroupMember.is_banned == False
            ).subquery()
            
            query = query.filter(
                or_(
                    Group.is_public == True,
                    Group.id.in_(user_group_ids)
                )
            )
        
        if search and search.strip():
            search_filter = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    Group.name.ilike(search_filter),
                    Group.description.ilike(search_filter)
                )
            )
        
        total = query.count()
        groups = query.order_by(desc(Group.created_at)) \
                      .offset((page - 1) * limit) \
                      .limit(limit) \
                      .all()
        
        groups_data = []
        for group in groups:
            # Проверяем, состоит ли пользователь в группе
            is_member = db.query(GroupMember).filter(
                GroupMember.group_id == group.id,
                GroupMember.user_id == user.id,
                GroupMember.is_banned == False
            ).first() is not None
            
            # Проверяем, является ли владельцем
            is_owner = group.owner_id == user.id
            
            # Получаем последнее сообщение
            last_message = db.query(Message).filter(
                Message.group_id == group.id,
                Message.is_deleted == False
            ).order_by(desc(Message.created_at)).first()
            
            groups_data.append({
                "id": group.id,
                "name": group.name,
                "description": group.description,
                "avatar_url": group.avatar_url,
                "is_public": group.is_public,
                "owner_id": group.owner_id,
                "members_count": group.members_count,
                "is_member": is_member,
                "is_owner": is_owner,
                "last_message": {
                    "content": last_message.content if last_message else None,
                    "timestamp": last_message.created_at.isoformat() if last_message else None,
                    "sender_id": last_message.from_user_id if last_message else None
                } if last_message else None,
                "created_at": group.created_at.isoformat() if group.created_at else None,
                "updated_at": group.updated_at.isoformat() if group.updated_at else None
            })
        
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
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка загрузки групп: {str(e)}"
        )

@app.post("/api/groups")
async def create_group(
    name: str = Form(...),
    description: Optional[str] = Form(None),
    is_public: bool = Form(True),
    avatar: Optional[UploadFile] = File(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Создание новой группы"""
    try:
        if not name or len(name.strip()) < 3:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Название группы должно быть не менее 3 символов"
            )
        
        name = name.strip()
        
        # Проверяем, существует ли группа с таким именем
        existing_group = db.query(Group).filter(
            Group.name == name,
            Group.is_active == True
        ).first()
        
        if existing_group:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Группа с таким названием уже существует"
            )
        
        avatar_url = None
        if avatar:
            # Сохраняем аватар
            file_ext = avatar.filename.split('.')[-1] if '.' in avatar.filename else 'jpg'
            if file_ext.lower() not in ['jpg', 'jpeg', 'png', 'gif', 'webp']:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Неподдерживаемый формат изображения"
                )
            
            filename = f"group_{uuid.uuid4()}.{file_ext}"
            filepath = UPLOAD_DIR / "avatars" / filename
            
            with open(filepath, "wb") as buffer:
                shutil.copyfileobj(avatar.file, buffer)
            
            avatar_url = f"/uploads/avatars/{filename}"
        
        # Создаем группу
        group = Group(
            name=name,
            description=description.strip() if description else None,
            avatar_url=avatar_url,
            is_public=is_public,
            owner_id=user.id,
            members_count=1
        )
        
        db.add(group)
        db.commit()
        db.refresh(group)
        
        # Добавляем создателя в группу
        group_member = GroupMember(
            group_id=group.id,
            user_id=user.id,
            role="admin"
        )
        db.add(group_member)
        db.commit()
        
        return {
            "success": True,
            "message": "Группа создана успешно",
            "group": {
                "id": group.id,
                "name": group.name,
                "description": group.description,
                "avatar_url": group.avatar_url,
                "is_public": group.is_public,
                "owner_id": group.owner_id,
                "members_count": group.members_count,
                "created_at": group.created_at.isoformat() if group.created_at else None
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка создания группы: {str(e)}"
        )

@app.get("/api/groups/{group_id}")
async def get_group_by_id(
    group_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение информации о группе"""
    try:
        group = db.query(Group).filter(
            Group.id == group_id,
            Group.is_active == True
        ).first()
        
        if not group:
            raise HTTPException(status_code=404, detail="Группа не найдена")
        
        # Проверяем доступ
        is_member = db.query(GroupMember).filter(
            GroupMember.group_id == group_id,
            GroupMember.user_id == user.id,
            GroupMember.is_banned == False
        ).first() is not None
        
        is_owner = group.owner_id == user.id
        
        if not group.is_public and not is_member and not is_owner:
            raise HTTPException(status_code=403, detail="У вас нет доступа к этой группе")
        
        # Получаем участников
        members = db.query(User).join(GroupMember).filter(
            GroupMember.group_id == group_id,
            GroupMember.is_banned == False
        ).all()
        
        members_data = []
        for member in members:
            member_role = db.query(GroupMember).filter(
                GroupMember.group_id == group_id,
                GroupMember.user_id == member.id
            ).first()
            
            members_data.append({
                "id": member.id,
                "username": member.username,
                "display_name": member.display_name,
                "avatar_url": member.avatar_url,
                "is_online": member.is_online,
                "role": member_role.role if member_role else "member",
                "joined_at": member_role.joined_at.isoformat() if member_role and member_role.joined_at else None
            })
        
        # Получаем последние сообщения
        last_messages = db.query(Message).filter(
            Message.group_id == group_id,
            Message.is_deleted == False
        ).order_by(desc(Message.created_at)).limit(10).all()
        
        messages_data = []
        for msg in last_messages:
            sender = db.query(User).filter(User.id == msg.from_user_id).first()
            messages_data.append({
                "id": msg.id,
                "content": msg.content,
                "type": msg.message_type,
                "is_my_message": msg.from_user_id == user.id,
                "sender": {
                    "id": sender.id if sender else None,
                    "username": sender.username if sender else None,
                    "display_name": sender.display_name if sender else None
                } if sender else None,
                "created_at": msg.created_at.isoformat() if msg.created_at else None
            })
        
        messages_data.reverse()
        
        return {
            "success": True,
            "group": {
                "id": group.id,
                "name": group.name,
                "description": group.description,
                "avatar_url": group.avatar_url,
                "is_public": group.is_public,
                "owner_id": group.owner_id,
                "members_count": group.members_count,
                "is_member": is_member,
                "is_owner": is_owner,
                "members": members_data,
                "last_messages": messages_data,
                "created_at": group.created_at.isoformat() if group.created_at else None,
                "updated_at": group.updated_at.isoformat() if group.updated_at else None
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка загрузки группы: {str(e)}"
        )

@app.post("/api/groups/{group_id}/join")
async def join_group(
    group_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Вступление в группу"""
    try:
        group = db.query(Group).filter(
            Group.id == group_id,
            Group.is_active == True
        ).first()
        
        if not group:
            raise HTTPException(status_code=404, detail="Группа не найдена")
        
        # Проверяем, состоит ли уже в группе
        existing_member = db.query(GroupMember).filter(
            GroupMember.group_id == group_id,
            GroupMember.user_id == user.id
        ).first()
        
        if existing_member:
            if existing_member.is_banned:
                raise HTTPException(status_code=403, detail="Вы забанены в этой группе")
            else:
                raise HTTPException(status_code=400, detail="Вы уже состоите в этой группе")
        
        # Проверяем, публичная ли группа
        if not group.is_public:
            raise HTTPException(status_code=403, detail="Эта группа закрытая")
        
        # Добавляем в группу
        group_member = GroupMember(
            group_id=group_id,
            user_id=user.id,
            role="member"
        )
        db.add(group_member)
        
        # Обновляем счетчик участников
        group.members_count += 1
        group.updated_at = datetime.utcnow()
        db.commit()
        
        # Уведомляем участников группы
        ws_message = {
            "type": "group_member_joined",
            "group_id": group_id,
            "user": {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "avatar_url": user.avatar_url
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
        members = db.query(GroupMember).filter(
            GroupMember.group_id == group_id,
            GroupMember.is_banned == False,
            GroupMember.user_id != user.id
        ).all()
        
        for member in members:
            if member.user_id in manager.active_connections:
                await manager.send_to_user(member.user_id, ws_message)
        
        return {
            "success": True,
            "message": "Вы успешно присоединились к группе",
            "group": {
                "id": group.id,
                "name": group.name,
                "members_count": group.members_count
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка вступления в группу: {str(e)}"
        )

@app.post("/api/groups/{group_id}/leave")
async def leave_group(
    group_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Выход из группы"""
    try:
        group = db.query(Group).filter(
            Group.id == group_id,
            Group.is_active == True
        ).first()
        
        if not group:
            raise HTTPException(status_code=404, detail="Группа не найдена")
        
        # Проверяем, состоит ли в группе
        membership = db.query(GroupMember).filter(
            GroupMember.group_id == group_id,
            GroupMember.user_id == user.id,
            GroupMember.is_banned == False
        ).first()
        
        if not membership:
            raise HTTPException(status_code=400, detail="Вы не состоите в этой группе")
        
        # Нельзя выйти если ты владелец
        if group.owner_id == user.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Владелец не может выйти из группы. Сначала передайте владение."
            )
        
        # Удаляем из группы
        db.delete(membership)
        
        # Обновляем счетчик участников
        if group.members_count > 0:
            group.members_count -= 1
        group.updated_at = datetime.utcnow()
        db.commit()
        
        # Уведомляем участников группы
        ws_message = {
            "type": "group_member_left",
            "group_id": group_id,
            "user_id": user.id,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        members = db.query(GroupMember).filter(
            GroupMember.group_id == group_id,
            GroupMember.is_banned == False
        ).all()
        
        for member in members:
            if member.user_id in manager.active_connections:
                await manager.send_to_user(member.user_id, ws_message)
        
        return {
            "success": True,
            "message": "Вы вышли из группы"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка выхода из группы: {str(e)}"
        )

# ========== CHANNELS ENDPOINTS ==========

@app.get("/api/channels")
async def get_channels(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    search: Optional[str] = Query(None),
    only_my: bool = Query(False),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение списка каналов"""
    try:
        query = db.query(Channel).filter(Channel.is_active == True)
        
        if only_my:
            # Только каналы, на которые подписан пользователь
            user_channel_ids = db.query(ChannelSubscription.channel_id).filter(
                ChannelSubscription.user_id == user.id,
                ChannelSubscription.is_banned == False
            ).subquery()
            
            query = query.filter(Channel.id.in_(user_channel_ids))
        else:
            # Публичные каналы или каналы, на которые подписан пользователь
            user_channel_ids = db.query(ChannelSubscription.channel_id).filter(
                ChannelSubscription.user_id == user.id,
                ChannelSubscription.is_banned == False
            ).subquery()
            
            query = query.filter(
                or_(
                    Channel.is_public == True,
                    Channel.id.in_(user_channel_ids)
                )
            )
        
        if search and search.strip():
            search_filter = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    Channel.name.ilike(search_filter),
                    Channel.description.ilike(search_filter)
                )
            )
        
        total = query.count()
        channels = query.order_by(desc(Channel.created_at)) \
                        .offset((page - 1) * limit) \
                        .limit(limit) \
                        .all()
        
        channels_data = []
        for channel in channels:
            # Проверяем, подписан ли пользователь на канал
            is_subscribed = db.query(ChannelSubscription).filter(
                ChannelSubscription.channel_id == channel.id,
                ChannelSubscription.user_id == user.id,
                ChannelSubscription.is_banned == False
            ).first() is not None
            
            # Проверяем, является ли владельцем
            is_owner = channel.owner_id == user.id
            
            # Получаем последнее сообщение
            last_message = db.query(Message).filter(
                Message.channel_id == channel.id,
                Message.is_deleted == False
            ).order_by(desc(Message.created_at)).first()
            
            channels_data.append({
                "id": channel.id,
                "name": channel.name,
                "description": channel.description,
                "avatar_url": channel.avatar_url,
                "is_public": channel.is_public,
                "owner_id": channel.owner_id,
                "subscribers_count": channel.subscribers_count,
                "is_subscribed": is_subscribed,
                "is_owner": is_owner,
                "last_message": {
                    "content": last_message.content if last_message else None,
                    "timestamp": last_message.created_at.isoformat() if last_message else None
                } if last_message else None,
                "created_at": channel.created_at.isoformat() if channel.created_at else None,
                "updated_at": channel.updated_at.isoformat() if channel.updated_at else None
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
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка загрузки каналов: {str(e)}"
        )

@app.post("/api/channels")
async def create_channel(
    name: str = Form(...),
    description: Optional[str] = Form(None),
    is_public: bool = Form(True),
    avatar: Optional[UploadFile] = File(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Создание нового канала"""
    try:
        if not name or len(name.strip()) < 3:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Название канала должно быть не менее 3 символов"
            )
        
        name = name.strip()
        
        # Проверяем, существует ли канал с таким именем
        existing_channel = db.query(Channel).filter(
            Channel.name == name,
            Channel.is_active == True
        ).first()
        
        if existing_channel:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Канал с таким названием уже существует"
            )
        
        avatar_url = None
        if avatar:
            # Сохраняем аватар
            file_ext = avatar.filename.split('.')[-1] if '.' in avatar.filename else 'jpg'
            if file_ext.lower() not in ['jpg', 'jpeg', 'png', 'gif', 'webp']:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Неподдерживаемый формат изображения"
                )
            
            filename = f"channel_{uuid.uuid4()}.{file_ext}"
            filepath = UPLOAD_DIR / "avatars" / filename
            
            with open(filepath, "wb") as buffer:
                shutil.copyfileobj(avatar.file, buffer)
            
            avatar_url = f"/uploads/avatars/{filename}"
        
        # Создаем канал
        channel = Channel(
            name=name,
            description=description.strip() if description else None,
            avatar_url=avatar_url,
            is_public=is_public,
            owner_id=user.id,
            subscribers_count=1
        )
        
        db.add(channel)
        db.commit()
        db.refresh(channel)
        
        # Добавляем владельца в подписчики
        subscription = ChannelSubscription(
            channel_id=channel.id,
            user_id=user.id,
            role="admin"
        )
        db.add(subscription)
        db.commit()
        
        return {
            "success": True,
            "message": "Канал создан успешно",
            "channel": {
                "id": channel.id,
                "name": channel.name,
                "description": channel.description,
                "avatar_url": channel.avatar_url,
                "is_public": channel.is_public,
                "owner_id": channel.owner_id,
                "subscribers_count": channel.subscribers_count,
                "created_at": channel.created_at.isoformat() if channel.created_at else None
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка создания канала: {str(e)}"
        )

@app.get("/api/channels/{channel_id}")
async def get_channel_by_id(
    channel_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение информации о канале"""
    try:
        channel = db.query(Channel).filter(
            Channel.id == channel_id,
            Channel.is_active == True
        ).first()
        
        if not channel:
            raise HTTPException(status_code=404, detail="Канал не найден")
        
        # Проверяем доступ
        is_subscribed = db.query(ChannelSubscription).filter(
            ChannelSubscription.channel_id == channel_id,
            ChannelSubscription.user_id == user.id,
            ChannelSubscription.is_banned == False
        ).first() is not None
        
        is_owner = channel.owner_id == user.id
        
        if not channel.is_public and not is_subscribed and not is_owner:
            raise HTTPException(status_code=403, detail="У вас нет доступа к этому каналу")
        
        # Получаем подписчиков
        subscribers = db.query(User).join(ChannelSubscription).filter(
            ChannelSubscription.channel_id == channel_id,
            ChannelSubscription.is_banned == False
        ).all()
        
        subscribers_data = []
        for subscriber in subscribers:
            sub_info = db.query(ChannelSubscription).filter(
                ChannelSubscription.channel_id == channel_id,
                ChannelSubscription.user_id == subscriber.id
            ).first()
            
            subscribers_data.append({
                "id": subscriber.id,
                "username": subscriber.username,
                "display_name": subscriber.display_name,
                "avatar_url": subscriber.avatar_url,
                "is_online": subscriber.is_online,
                "role": sub_info.role if sub_info else "subscriber",
                "subscribed_at": sub_info.subscribed_at.isoformat() if sub_info and sub_info.subscribed_at else None
            })
        
        # Получаем последние сообщения
        last_messages = db.query(Message).filter(
            Message.channel_id == channel_id,
            Message.is_deleted == False
        ).order_by(desc(Message.created_at)).limit(10).all()
        
        messages_data = []
        for msg in last_messages:
            sender = db.query(User).filter(User.id == msg.from_user_id).first()
            messages_data.append({
                "id": msg.id,
                "content": msg.content,
                "type": msg.message_type,
                "sender": {
                    "id": sender.id if sender else None,
                    "username": sender.username if sender else None,
                    "display_name": sender.display_name if sender else None
                } if sender else None,
                "created_at": msg.created_at.isoformat() if msg.created_at else None
            })
        
        messages_data.reverse()
        
        return {
            "success": True,
            "channel": {
                "id": channel.id,
                "name": channel.name,
                "description": channel.description,
                "avatar_url": channel.avatar_url,
                "is_public": channel.is_public,
                "owner_id": channel.owner_id,
                "subscribers_count": channel.subscribers_count,
                "is_subscribed": is_subscribed,
                "is_owner": is_owner,
                "subscribers": subscribers_data,
                "last_messages": messages_data,
                "created_at": channel.created_at.isoformat() if channel.created_at else None,
                "updated_at": channel.updated_at.isoformat() if channel.updated_at else None
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка загрузки канала: {str(e)}"
        )

@app.post("/api/channels/{channel_id}/subscribe")
async def subscribe_to_channel(
    channel_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Подписка на канал"""
    try:
        channel = db.query(Channel).filter(
            Channel.id == channel_id,
            Channel.is_active == True
        ).first()
        
        if not channel:
            raise HTTPException(status_code=404, detail="Канал не найден")
        
        # Проверяем, подписан ли уже
        existing_subscription = db.query(ChannelSubscription).filter(
            ChannelSubscription.channel_id == channel_id,
            ChannelSubscription.user_id == user.id
        ).first()
        
        if existing_subscription:
            if existing_subscription.is_banned:
                raise HTTPException(status_code=403, detail="Вы забанены в этом канале")
            else:
                raise HTTPException(status_code=400, detail="Вы уже подписаны на этот канал")
        
        # Проверяем, публичный ли канал
        if not channel.is_public:
            raise HTTPException(status_code=403, detail="Это приватный канал")
        
        # Подписываемся
        subscription = ChannelSubscription(
            channel_id=channel_id,
            user_id=user.id,
            role="subscriber"
        )
        db.add(subscription)
        
        # Обновляем счетчик подписчиков
        channel.subscribers_count += 1
        channel.updated_at = datetime.utcnow()
        db.commit()
        
        # Уведомляем владельца канала
        if channel.owner_id in manager.active_connections:
            ws_message = {
                "type": "channel_new_subscriber",
                "channel_id": channel_id,
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "display_name": user.display_name,
                    "avatar_url": user.avatar_url
                },
                "timestamp": datetime.utcnow().isoformat()
            }
            
            await manager.send_to_user(channel.owner_id, ws_message)
        
        return {
            "success": True,
            "message": "Вы успешно подписались на канал",
            "channel": {
                "id": channel.id,
                "name": channel.name,
                "subscribers_count": channel.subscribers_count
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка подписки на канал: {str(e)}"
        )

@app.post("/api/channels/{channel_id}/unsubscribe")
async def unsubscribe_from_channel(
    channel_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Отписка от канала"""
    try:
        channel = db.query(Channel).filter(
            Channel.id == channel_id,
            Channel.is_active == True
        ).first()
        
        if not channel:
            raise HTTPException(status_code=404, detail="Канал не найден")
        
        # Проверяем, подписан ли
        subscription = db.query(ChannelSubscription).filter(
            ChannelSubscription.channel_id == channel_id,
            ChannelSubscription.user_id == user.id,
            ChannelSubscription.is_banned == False
        ).first()
        
        if not subscription:
            raise HTTPException(status_code=400, detail="Вы не подписаны на этот канал")
        
        # Нельзя отписаться если ты владелец
        if channel.owner_id == user.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Владелец не может отписаться от канала"
            )
        
        # Удаляем подписку
        db.delete(subscription)
        
        # Обновляем счетчик подписчиков
        if channel.subscribers_count > 0:
            channel.subscribers_count -= 1
        channel.updated_at = datetime.utcnow()
        db.commit()
        
        return {
            "success": True,
            "message": "Вы отписались от канала"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка отписки от канала: {str(e)}"
        )

# ========== CHATS ENDPOINTS ==========

@app.get("/api/chats/all")
async def get_all_chats(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение всех чатов пользователя"""
    try:
        # Личные чаты (пользователи, с которыми есть переписка)
        private_chats = []
        
        # Получаем пользователей, с которыми есть переписка
        chat_partners_query = db.query(Message.from_user_id).filter(
            Message.to_user_id == user.id,
            Message.is_deleted == False
        ).union(
            db.query(Message.to_user_id).filter(
                Message.from_user_id == user.id,
                Message.is_deleted == False
            )
        ).distinct()
        
        chat_partners = [row[0] for row in chat_partners_query.all()]
        
        for partner_id in chat_partners:
            if partner_id == user.id:
                continue
                
            partner = db.query(User).filter(
                User.id == partner_id,
                User.is_active == True
            ).first()
            
            if not partner:
                continue
            
            # Получаем последнее сообщение
            last_message = db.query(Message).filter(
                or_(
                    and_(Message.from_user_id == user.id, Message.to_user_id == partner_id),
                    and_(Message.from_user_id == partner_id, Message.to_user_id == user.id)
                ),
                Message.is_deleted == False
            ).order_by(desc(Message.created_at)).first()
            
            # Считаем непрочитанные сообщения
            unread_count = db.query(Message).filter(
                Message.from_user_id == partner_id,
                Message.to_user_id == user.id,
                Message.is_deleted == False
            ).count()  # В реальном приложении нужно хранить статус прочтения
            
            private_chats.append({
                "id": partner.id,
                "type": "private",
                "name": partner.display_name or partner.username,
                "avatar_url": partner.avatar_url,
                "is_online": partner.is_online,
                "last_message": {
                    "content": last_message.content if last_message else None,
                    "timestamp": last_message.created_at.isoformat() if last_message else None,
                    "is_my_message": last_message.from_user_id == user.id if last_message else False
                } if last_message else None,
                "unread_count": unread_count
            })
        
        # Групповые чаты
        group_chats = []
        user_groups = db.query(Group).join(GroupMember).filter(
            GroupMember.user_id == user.id,
            GroupMember.is_banned == False,
            Group.is_active == True
        ).all()
        
        for group in user_groups:
            last_message = db.query(Message).filter(
                Message.group_id == group.id,
                Message.is_deleted == False
            ).order_by(desc(Message.created_at)).first()
            
            group_chats.append({
                "id": group.id,
                "type": "group",
                "name": group.name,
                "avatar_url": group.avatar_url,
                "last_message": {
                    "content": last_message.content if last_message else None,
                    "timestamp": last_message.created_at.isoformat() if last_message else None,
                    "sender_id": last_message.from_user_id if last_message else None
                } if last_message else None,
                "unread_count": 0,
                "members_count": group.members_count
            })
        
        # Каналы
        channel_chats = []
        user_channels = db.query(Channel).join(ChannelSubscription).filter(
            ChannelSubscription.user_id == user.id,
            ChannelSubscription.is_banned == False,
            Channel.is_active == True
        ).all()
        
        for channel in user_channels:
            last_message = db.query(Message).filter(
                Message.channel_id == channel.id,
                Message.is_deleted == False
            ).order_by(desc(Message.created_at)).first()
            
            channel_chats.append({
                "id": channel.id,
                "type": "channel",
                "name": channel.name,
                "avatar_url": channel.avatar_url,
                "last_message": {
                    "content": last_message.content if last_message else None,
                    "timestamp": last_message.created_at.isoformat() if last_message else None
                } if last_message else None,
                "unread_count": 0,
                "subscribers_count": channel.subscribers_count
            })
        
        # Объединяем все чаты и сортируем по времени последнего сообщения
        all_chats = private_chats + group_chats + channel_chats
        
        def get_chat_timestamp(chat):
            if chat.get('last_message') and chat['last_message'].get('timestamp'):
                try:
                    return datetime.fromisoformat(chat['last_message']['timestamp'].replace('Z', '+00:00'))
                except:
                    return datetime.min
            return datetime.min
        
        all_chats.sort(key=get_chat_timestamp, reverse=True)
        
        return {
            "success": True,
            "chats": all_chats,
            "count": len(all_chats)
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка загрузки чатов: {str(e)}"
        )

# ========== FILE UPLOAD ENDPOINTS ==========

ALLOWED_IMAGE_TYPES = ["image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp"]
ALLOWED_VIDEO_TYPES = ["video/mp4", "video/webm", "video/ogg"]
ALLOWED_AUDIO_TYPES = ["audio/mpeg", "audio/ogg", "audio/wav", "audio/webm"]
ALLOWED_FILE_TYPES = [
    "application/pdf", 
    "text/plain", 
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/zip",
    "application/x-rar-compressed"
]
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB

@app.post("/api/upload")
async def upload_file(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Загрузка файла"""
    try:
        if not file:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Файл не предоставлен"
            )
        
        # Проверяем размер файла
        file.file.seek(0, 2)  # Перемещаемся в конец файла
        file_size = file.file.tell()
        file.file.seek(0)  # Возвращаемся в начало
        
        if file_size > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Файл слишком большой. Максимальный размер: {MAX_FILE_SIZE // (1024*1024)} MB"
            )
        
        # Определяем тип файла
        content_type = file.content_type or ""
        filename = file.filename
        file_ext = filename.split('.')[-1].lower() if '.' in filename else ''
        
        if content_type.startswith('image/'):
            if content_type not in ALLOWED_IMAGE_TYPES:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Неподдерживаемый формат изображения"
                )
            file_type = "images"
            message_type = "image"
        elif content_type.startswith('video/'):
            if content_type not in ALLOWED_VIDEO_TYPES:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Неподдерживаемый формат видео"
                )
            file_type = "videos"
            message_type = "video"
        elif content_type.startswith('audio/'):
            if content_type not in ALLOWED_AUDIO_TYPES:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Неподдерживаемый формат аудио"
                )
            file_type = "audios"
            message_type = "audio"
        else:
            if content_type not in ALLOWED_FILE_TYPES:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Неподдерживаемый тип файла"
                )
            file_type = "files"
            message_type = "file"
        
        # Генерируем уникальное имя файла
        unique_filename = f"{uuid.uuid4()}.{file_ext}"
        filepath = UPLOAD_DIR / file_type / unique_filename
        
        # Сохраняем файл
        with open(filepath, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # Формируем URL
        file_url = f"/uploads/{file_type}/{unique_filename}"
        
        return {
            "success": True,
            "url": file_url,
            "filename": filename,
            "size": file_size,
            "type": content_type,
            "message_type": message_type
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка загрузки файла: {str(e)}"
        )

# ========== WEB SOCKET ENDPOINT ==========

@app.websocket("/ws/{user_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    user_id: int,
    token: Optional[str] = None
):
    """WebSocket endpoint для реального времени"""
    # Проверяем авторизацию
    db = SessionLocal()
    try:
        user = db.query(User).filter(
            User.id == user_id,
            User.is_active == True
        ).first()
        
        if not user:
            await websocket.close(code=1008)
            return
        
        # Если передан токен, проверяем его
        if token:
            payload = verify_token(token)
            if not payload or payload.get("user_id") != user_id:
                await websocket.close(code=1008)
                return
        # Иначе проверяем по cookies (для браузера)
        # FastAPI WebSocket не поддерживает cookies напрямую, 
        # поэтому используем query параметр token
        
    except Exception as e:
        print(f"❌ WebSocket auth error: {e}")
        await websocket.close(code=1011)
        return
    finally:
        db.close()
    
    # Подключаем пользователя
    await manager.connect(websocket, user_id)
    
    try:
        while True:
            data = await websocket.receive_json()
            await handle_websocket_message(data, user_id)
            
    except WebSocketDisconnect:
        print(f"📴 User disconnected: {user_id}")
        manager.disconnect(user_id)
    except Exception as e:
        print(f"❌ WebSocket error: {e}")
        manager.disconnect(user_id)

async def handle_websocket_message(data: Dict[str, Any], user_id: int):
    """Обработка сообщений WebSocket"""
    message_type = data.get("type")
    
    if message_type == "typing":
        await handle_typing_indicator(data, user_id)
    elif message_type == "ping":
        # Ответ на ping
        await manager.send_to_user(user_id, {"type": "pong", "timestamp": datetime.utcnow().isoformat()})
    else:
        print(f"❌ Unknown WebSocket message type: {message_type}")

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
    
    db = SessionLocal()
    try:
        if chat_type == "private":
            # Отправляем получателю
            if chat_id != user_id:
                await manager.send_to_user(chat_id, typing_message)
        elif chat_type == "group":
            # Получаем всех участников группы кроме отправителя
            members = db.query(GroupMember).filter(
                GroupMember.group_id == chat_id,
                GroupMember.user_id != user_id,
                GroupMember.is_banned == False
            ).all()
            
            for member in members:
                await manager.send_to_user(member.user_id, typing_message)
        elif chat_type == "channel":
            # Получаем всех подписчиков канала кроме отправителя
            subscribers = db.query(ChannelSubscription).filter(
                ChannelSubscription.channel_id == chat_id,
                ChannelSubscription.user_id != user_id,
                ChannelSubscription.is_banned == False
            ).all()
            
            for subscriber in subscribers:
                await manager.send_to_user(subscriber.user_id, typing_message)
    except Exception as e:
        print(f"❌ Ошибка обработки typing индикатора: {e}")
    finally:
        db.close()

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

# ========== START SERVER ==========

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print("=" * 60)
    print("🚀 DevNet Messenger API запущен!")
    print(f"📡 Порт: {port}")
    print(f"🌍 Домен: {DOMAIN}")
    print(f"🔧 Режим: {'Production' if IS_PRODUCTION else 'Development'}")
    print(f"🔐 Secret key: {SECRET_KEY[:10]}...")
    print(f"📁 Директория загрузок: {UPLOAD_DIR}")
    print(f"📁 Директория фронтенда: {frontend_dir}")
    print(f"🔗 Главная страница: http://localhost:{port}/")
    print(f"💬 Чат: http://localhost:{port}/chat")
    print(f"📖 API документация: http://localhost:{port}/api/docs")
    print("👑 Тестовый пользователь: admin / admin123")
    print("👤 Другие пользователи:")
    print("   - alice / alice123")
    print("   - bob / bob123")
    print("   - charlie / charlie123")
    print("   - david / david123")
    print("   - eve / eve123")
    print("=" * 60)
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=False
          )
