from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, Form, Request, File, UploadFile, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc, func, or_, and_, text
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
    # Создаем простой fallback
    from sqlalchemy.ext.declarative import declarative_base
    from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Text, ForeignKey
    from sqlalchemy.orm import sessionmaker, relationship
    
    SQLALCHEMY_DATABASE_URL = "sqlite:///./devnet.db"
    engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base = declarative_base()
    
    def get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()
    
    print("⚠️  Created simple database connection")

# ========== МОДЕЛИ БАЗЫ ДАННЫХ ==========

from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, JSON, LargeBinary
from sqlalchemy.orm import relationship

Base = declarative_base()

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
    last_login = Column(DateTime)
    
    # Связи
    sent_messages = relationship("Message", foreign_keys="Message.from_user_id", back_populates="sender")
    received_messages = relationship("Message", foreign_keys="Message.to_user_id", back_populates="receiver")

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
    created_at = Column(DateTime, default=datetime.utcnow)
    edited_at = Column(DateTime, nullable=True)
    
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
    owner_id = Column(Integer, ForeignKey("users.id"))
    members_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

class Channel(Base):
    __tablename__ = "channels"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    avatar_url = Column(String(500))
    is_public = Column(Boolean, default=True)
    owner_id = Column(Integer, ForeignKey("users.id"))
    subscribers_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

class GroupMember(Base):
    __tablename__ = "group_members"
    
    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("groups.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    role = Column(String(20), default="member")
    joined_at = Column(DateTime, default=datetime.utcnow)

class ChannelSubscription(Base):
    __tablename__ = "channel_subscriptions"
    
    id = Column(Integer, primary_key=True, index=True)
    channel_id = Column(Integer, ForeignKey("channels.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    role = Column(String(20), default="subscriber")
    subscribed_at = Column(DateTime, default=datetime.utcnow)

# ========== ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ ==========

def init_database():
    try:
        Base.metadata.create_all(bind=engine)
        print("✅ Database tables created successfully")
    except Exception as e:
        print(f"❌ Error creating database tables: {e}")

# Создаем таблицы
init_database()

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
            except Exception as e:
                print(f"❌ Error sending to user {user_id}: {e}")
                self.disconnect(user_id)
    
    async def broadcast(self, message: Dict[str, Any], exclude_user_id: Optional[int] = None):
        disconnected = []
        for user_id, connection in self.active_connections.items():
            if user_id != exclude_user_id:
                try:
                    await connection.send_json(message)
                except Exception as e:
                    print(f"❌ Error broadcasting to user {user_id}: {e}")
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
            detail="Требуется аутентификация. Пожалуйста, войдите в систему."
        )
    
    payload = verify_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Недействительный токен. Пожалуйста, войдите снова."
        )
    
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный формат токена."
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
            
            # Создаем тестовых пользователей
            test_users = [
                ("alice", "alice@devnet.local", "Алиса", "alice123"),
                ("bob", "bob@devnet.local", "Боб", "bob123"),
                ("charlie", "charlie@devnet.local", "Чарли", "charlie123"),
            ]
            
            for username, email, display_name, password in test_users:
                user = db.query(User).filter(User.username == username).first()
                if not user:
                    user = User(
                        username=username,
                        email=email,
                        display_name=display_name,
                        password_hash=get_password_hash(password)
                    )
                    db.add(user)
            
            db.commit()
            print("✅ Тестовые пользователи созданы")
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
    request: Request,
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
            is_guest=False,
            last_login=datetime.utcnow()
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
                "avatar_url": user.avatar_url,
                "is_admin": user.is_admin,
                "is_online": user.is_online
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
        db.rollback()
        print(f"❌ Ошибка регистрации: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка регистрации: {str(e)}"
        )

@app.post("/api/login")
@app.post("/api/auth/login")
async def login_user(
    request: Request,
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
            print(f"❌ Пользователь не найден по username: {username}")
            # Проверяем может быть это email
            user = db.query(User).filter(User.email == username).first()
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Неверное имя пользователя или пароль"
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
        
        # Обновляем время последнего входа и статус
        user.last_login = datetime.utcnow()
        user.is_online = True
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
                "is_online": user.is_online,
                "is_admin": user.is_admin,
                "created_at": user.created_at.isoformat() if user.created_at else None,
                "last_login": user.last_login.isoformat() if user.last_login else None
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
async def logout_user(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Выход пользователя"""
    try:
        # Обновляем статус пользователя
        user.is_online = False
        db.commit()
    except Exception as e:
        print(f"⚠️  Ошибка обновления статуса при выходе: {e}")
    
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
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение списка пользователей"""
    try:
        query = db.query(User).filter(User.id != user.id)  # Исключаем текущего пользователя
        
        if online_only:
            query = query.filter(User.is_online == True)
        
        if search:
            search_filter = f"%{search}%"
            query = query.filter(
                (User.username.ilike(search_filter)) |
                (User.display_name.ilike(search_filter)) |
                (User.email.ilike(search_filter))
            )
        
        total = query.count()
        users = query.order_by(
            desc(User.is_online),  # Сначала онлайн
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
                "created_at": user_item.created_at.isoformat() if user_item.created_at else None,
                "last_login": user_item.last_login.isoformat() if user_item.last_login else None
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
        user_item = db.query(User).filter(User.id == user_id).first()
        
        if not user_item:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Пользователь не найден"
            )
        
        return {
            "success": True,
            "user": {
                "id": user_item.id,
                "username": user_item.username,
                "display_name": user_item.display_name or user_item.username,
                "avatar_url": user_item.avatar_url,
                "is_online": user_item.is_online,
                "is_admin": user_item.is_admin,
                "created_at": user_item.created_at.isoformat() if user_item.created_at else None,
                "last_login": user_item.last_login.isoformat() if user_item.last_login else None
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
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение последних сообщений"""
    try:
        # Получаем сообщения пользователя (личные, групповые, канальные)
        query = db.query(Message).filter(
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
            chat_type = "private"
            chat_id = msg.to_user_id if msg.from_user_id == user.id else msg.from_user_id
            if msg.group_id:
                chat_type = "group"
                chat_id = msg.group_id
            elif msg.channel_id:
                chat_type = "channel"
                chat_id = msg.channel_id
            
            messages_data.append({
                "id": msg.id,
                "content": msg.content,
                "type": msg.message_type,
                "media_url": msg.media_url,
                "media_size": msg.media_size,
                "filename": msg.filename,
                "is_my_message": msg.from_user_id == user.id,
                "chat_type": chat_type,
                "chat_id": chat_id,
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
                "edited_at": msg.edited_at.isoformat() if msg.edited_at else None
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
            other_user = db.query(User).filter(User.id == chat_id).first()
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
            group = db.query(Group).filter(Group.id == chat_id).first()
            if not group:
                raise HTTPException(status_code=404, detail="Группа не найдена")
            
            # Проверяем, состоит ли пользователь в группе
            membership = db.query(GroupMember).filter(
                GroupMember.group_id == chat_id,
                GroupMember.user_id == user.id
            ).first()
            
            if not membership and not group.is_public:
                raise HTTPException(status_code=403, detail="Вы не состоите в этой группе")
            
            query = query.filter(Message.group_id == chat_id)
        elif chat_type == "channel":
            # Сообщения канала
            channel = db.query(Channel).filter(Channel.id == chat_id).first()
            if not channel:
                raise HTTPException(status_code=404, detail="Канал не найден")
            
            # Проверяем, подписан ли пользователь на канал
            subscription = db.query(ChannelSubscription).filter(
                ChannelSubscription.channel_id == chat_id,
                ChannelSubscription.user_id == user.id
            ).first()
            
            if not subscription and not channel.is_public:
                raise HTTPException(status_code=403, detail="Вы не подписаны на этот канал")
            
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
                "edited_at": msg.edited_at.isoformat() if msg.edited_at else None
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
            
            # Нельзя отправлять сообщения самому себе
            if to_user_id == user.id:
                raise HTTPException(status_code=400, detail="Нельзя отправлять сообщения самому себе")
                
        elif group_id:
            chat_type = "group"
            # Проверяем существование группы
            group = db.query(Group).filter(Group.id == group_id).first()
            if not group:
                raise HTTPException(status_code=404, detail="Группа не найдена")
            
            # Проверяем, состоит ли пользователь в группе
            membership = db.query(GroupMember).filter(
                GroupMember.group_id == group_id,
                GroupMember.user_id == user.id
            ).first()
            
            if not membership and not group.is_public:
                raise HTTPException(status_code=403, detail="Вы не состоите в этой группе")
                
        elif channel_id:
            chat_type = "channel"
            # Проверяем существование канала
            channel = db.query(Channel).filter(Channel.id == channel_id).first()
            if not channel:
                raise HTTPException(status_code=404, detail="Канал не найден")
            
            # Проверяем, является ли пользователь владельцем или подписчиком
            if channel.owner_id != user.id:
                subscription = db.query(ChannelSubscription).filter(
                    ChannelSubscription.channel_id == channel_id,
                    ChannelSubscription.user_id == user.id
                ).first()
                
                if not subscription and not channel.is_public:
                    raise HTTPException(status_code=403, detail="Вы не подписаны на этот канал")
        else:
            raise HTTPException(status_code=400, detail="Не указан получатель")
        
        # Создаем сообщение
        message = Message(
            from_user_id=user.id,
            to_user_id=to_user_id,
            group_id=group_id,
            channel_id=channel_id,
            content=content.strip(),
            message_type=message_type,
            reactions={}
        )
        
        db.add(message)
        db.commit()
        db.refresh(message)
        
        # Получаем информацию об отправителе
        sender = db.query(User).filter(User.id == user.id).first()
        
        # Отправляем через WebSocket если есть активные соединения
        ws_message = {
            "type": "message_sent",
            "message_id": message.id,
            "chat_type": chat_type,
            "chat_id": to_user_id or group_id or channel_id,
            "content": message.content,
            "timestamp": message.created_at.isoformat() if message.created_at else datetime.utcnow().isoformat()
        }
        
        # Отправляем себе подтверждение
        if user.id in manager.active_connections:
            await manager.send_to_user(user.id, ws_message)
        
        # Отправляем получателю/группе/каналу
        if chat_type == "private" and to_user_id in manager.active_connections:
            await manager.send_to_user(to_user_id, {
                **ws_message,
                "type": "message",
                "message": {
                    "id": message.id,
                    "content": message.content,
                    "type": message.message_type,
                    "is_my_message": False,
                    "from_user_id": message.from_user_id,
                    "to_user_id": message.to_user_id,
                    "sender": {
                        "id": sender.id,
                        "username": sender.username,
                        "display_name": sender.display_name,
                        "avatar_url": sender.avatar_url
                    } if sender else None,
                    "created_at": message.created_at.isoformat() if message.created_at else None
                }
            })
        
        return {
            "success": True,
            "message": "Сообщение отправлено",
            "data": {
                "id": message.id,
                "content": message.content,
                "type": message.message_type,
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

# ========== GROUPS ENDPOINTS ==========

@app.get("/api/groups")
async def get_groups(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    search: Optional[str] = Query(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение списка групп"""
    try:
        query = db.query(Group)
        
        if search:
            search_filter = f"%{search}%"
            query = query.filter(Group.name.ilike(search_filter))
        
        # Показываем публичные группы или группы, в которых состоит пользователь
        user_group_ids = db.query(GroupMember.group_id).filter(GroupMember.user_id == user.id).subquery()
        query = query.filter(
            or_(
                Group.is_public == True,
                Group.id.in_(user_group_ids)
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
                GroupMember.user_id == user.id
            ).first() is not None
            
            # Получаем последнее сообщение
            last_message = db.query(Message).filter(
                Message.group_id == group.id
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
                "last_message": {
                    "content": last_message.content if last_message else None,
                    "timestamp": last_message.created_at.isoformat() if last_message else None
                } if last_message else None,
                "created_at": group.created_at.isoformat() if group.created_at else None
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
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Создание новой группы"""
    try:
        if not name or len(name.strip()) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Название группы не может быть пустым"
            )
        
        # Проверяем, существует ли группа с таким именем
        existing_group = db.query(Group).filter(Group.name == name).first()
        if existing_group:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Группа с таким названием уже существует"
            )
        
        # Создаем группу
        group = Group(
            name=name.strip(),
            description=description.strip() if description else None,
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
        group = db.query(Group).filter(Group.id == group_id).first()
        
        if not group:
            raise HTTPException(status_code=404, detail="Группа не найдена")
        
        # Проверяем доступ
        is_member = db.query(GroupMember).filter(
            GroupMember.group_id == group_id,
            GroupMember.user_id == user.id
        ).first() is not None
        
        if not group.is_public and not is_member:
            raise HTTPException(status_code=403, detail="У вас нет доступа к этой группе")
        
        # Получаем участников
        members = db.query(User).join(GroupMember).filter(
            GroupMember.group_id == group_id
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
                "role": member_role.role if member_role else "member"
            })
        
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
                "members": members_data,
                "created_at": group.created_at.isoformat() if group.created_at else None
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
        group = db.query(Group).filter(Group.id == group_id).first()
        
        if not group:
            raise HTTPException(status_code=404, detail="Группа не найдена")
        
        # Проверяем, состоит ли уже в группе
        existing_member = db.query(GroupMember).filter(
            GroupMember.group_id == group_id,
            GroupMember.user_id == user.id
        ).first()
        
        if existing_member:
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
        db.commit()
        
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

# ========== CHANNELS ENDPOINTS ==========

@app.get("/api/channels")
async def get_channels(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    search: Optional[str] = Query(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение списка каналов"""
    try:
        query = db.query(Channel)
        
        if search:
            search_filter = f"%{search}%"
            query = query.filter(Channel.name.ilike(search_filter))
        
        # Показываем публичные каналы или каналы, на которые подписан пользователь
        user_channel_ids = db.query(ChannelSubscription.channel_id).filter(
            ChannelSubscription.user_id == user.id
        ).subquery()
        
        query = query.filter(
            or_(
                Channel.is_public == True,
                Channel.id.in_(user_channel_ids)
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
                ChannelSubscription.user_id == user.id
            ).first() is not None
            
            # Проверяем, является ли пользователь владельцем
            is_owner = channel.owner_id == user.id
            
            # Получаем последнее сообщение
            last_message = db.query(Message).filter(
                Message.channel_id == channel.id
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
                "created_at": channel.created_at.isoformat() if channel.created_at else None
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
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Создание нового канала"""
    try:
        if not name or len(name.strip()) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Название канала не может быть пустым"
            )
        
        # Проверяем, существует ли канал с таким именем
        existing_channel = db.query(Channel).filter(Channel.name == name).first()
        if existing_channel:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Канал с таким названием уже существует"
            )
        
        # Создаем канал
        channel = Channel(
            name=name.strip(),
            description=description.strip() if description else None,
            is_public=is_public,
            owner_id=user.id,
            subscribers_count=1  # Владелец автоматически подписывается
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
        channel = db.query(Channel).filter(Channel.id == channel_id).first()
        
        if not channel:
            raise HTTPException(status_code=404, detail="Канал не найден")
        
        # Проверяем доступ
        is_subscribed = db.query(ChannelSubscription).filter(
            ChannelSubscription.channel_id == channel_id,
            ChannelSubscription.user_id == user.id
        ).first() is not None
        
        is_owner = channel.owner_id == user.id
        
        if not channel.is_public and not is_subscribed and not is_owner:
            raise HTTPException(status_code=403, detail="У вас нет доступа к этому каналу")
        
        # Получаем подписчиков
        subscribers = db.query(User).join(ChannelSubscription).filter(
            ChannelSubscription.channel_id == channel_id
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
                "created_at": channel.created_at.isoformat() if channel.created_at else None
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
        channel = db.query(Channel).filter(Channel.id == channel_id).first()
        
        if not channel:
            raise HTTPException(status_code=404, detail="Канал не найден")
        
        # Проверяем, подписан ли уже
        existing_subscription = db.query(ChannelSubscription).filter(
            ChannelSubscription.channel_id == channel_id,
            ChannelSubscription.user_id == user.id
        ).first()
        
        if existing_subscription:
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
        db.commit()
        
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

# ========== CHATS ENDPOINTS ==========

@app.get("/api/chats/all")
async def get_all_chats(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение всех чатов пользователя"""
    try:
        # Личные чаты
        private_chats = []
        # Получаем всех пользователей, с которыми есть переписка
        distinct_user_ids = db.query(Message.from_user_id).filter(
            Message.to_user_id == user.id
        ).union(
            db.query(Message.to_user_id).filter(
                Message.from_user_id == user.id
            )
        ).distinct().all()
        
        for user_id_tuple in distinct_user_ids:
            other_user_id = user_id_tuple[0]
            if other_user_id == user.id:
                continue
                
            other_user = db.query(User).filter(User.id == other_user_id).first()
            if not other_user:
                continue
            
            # Получаем последнее сообщение
            last_message = db.query(Message).filter(
                or_(
                    and_(Message.from_user_id == user.id, Message.to_user_id == other_user_id),
                    and_(Message.from_user_id == other_user_id, Message.to_user_id == user.id)
                )
            ).order_by(desc(Message.created_at)).first()
            
            # Считаем непрочитанные сообщения
            unread_count = db.query(Message).filter(
                Message.from_user_id == other_user_id,
                Message.to_user_id == user.id
            ).count()  # В реальном приложении нужно хранить статус прочтения
            
            private_chats.append({
                "id": other_user.id,
                "name": other_user.display_name or other_user.username,
                "avatar_url": other_user.avatar_url,
                "is_online": other_user.is_online,
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
            GroupMember.user_id == user.id
        ).all()
        
        for group in user_groups:
            last_message = db.query(Message).filter(
                Message.group_id == group.id
            ).order_by(desc(Message.created_at)).first()
            
            group_chats.append({
                "id": group.id,
                "name": group.name,
                "avatar_url": group.avatar_url,
                "is_online": False,  # Группы не имеют статуса онлайн
                "last_message": {
                    "content": last_message.content if last_message else None,
                    "timestamp": last_message.created_at.isoformat() if last_message else None,
                    "sender_id": last_message.from_user_id if last_message else None
                } if last_message else None,
                "unread_count": 0  # В реальном приложении нужно считать
            })
        
        # Каналы
        channel_chats = []
        user_channels = db.query(Channel).join(ChannelSubscription).filter(
            ChannelSubscription.user_id == user.id
        ).all()
        
        for channel in user_channels:
            last_message = db.query(Message).filter(
                Message.channel_id == channel.id
            ).order_by(desc(Message.created_at)).first()
            
            channel_chats.append({
                "id": channel.id,
                "name": channel.name,
                "avatar_url": channel.avatar_url,
                "is_online": False,  # Каналы не имеют статуса онлайн
                "last_message": {
                    "content": last_message.content if last_message else None,
                    "timestamp": last_message.created_at.isoformat() if last_message else None
                } if last_message else None,
                "unread_count": 0  # В реальном приложении нужно считать
            })
        
        # Сортируем по времени последнего сообщения
        def get_timestamp(chat):
            if chat.get('last_message') and chat['last_message'].get('timestamp'):
                return datetime.fromisoformat(chat['last_message']['timestamp'].replace('Z', '+00:00'))
            return datetime.min
        
        private_chats.sort(key=get_timestamp, reverse=True)
        group_chats.sort(key=get_timestamp, reverse=True)
        channel_chats.sort(key=get_timestamp, reverse=True)
        
        return {
            "success": True,
            "private_chats": private_chats,
            "group_chats": group_chats,
            "channel_chats": channel_chats
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка загрузки чатов: {str(e)}"
        )

# ========== FILE UPLOAD ENDPOINTS ==========

ALLOWED_IMAGE_TYPES = ["image/jpeg", "image/png", "image/gif", "image/webp"]
ALLOWED_FILE_TYPES = ["application/pdf", "text/plain", "application/msword", 
                      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                      "application/vnd.ms-excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"]

@app.post("/api/upload/image")
async def upload_image(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Загрузка изображения"""
    try:
        if file.content_type not in ALLOWED_IMAGE_TYPES:
            raise HTTPException(status_code=400, detail="Неподдерживаемый тип файла")
        
        # Генерируем уникальное имя файла
        file_ext = file.filename.split('.')[-1] if '.' in file.filename else 'jpg'
        filename = f"{uuid.uuid4()}.{file_ext}"
        filepath = UPLOAD_DIR / "images" / filename
        
        # Сохраняем файл
        with open(filepath, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # Формируем URL
        file_url = f"/uploads/images/{filename}"
        
        return {
            "success": True,
            "url": file_url,
            "filename": file.filename,
            "size": filepath.stat().st_size,
            "type": file.content_type
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка загрузки файла: {str(e)}"
        )

@app.post("/api/upload/file")
async def upload_file(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Загрузка файла"""
    try:
        if file.content_type not in ALLOWED_FILE_TYPES and not file.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="Неподдерживаемый тип файла")
        
        # Определяем тип файла и директорию
        if file.content_type.startswith("image/"):
            file_type = "images"
        else:
            file_type = "files"
        
        # Генерируем уникальное имя файла
        file_ext = file.filename.split('.')[-1] if '.' in file.filename else 'bin'
        filename = f"{uuid.uuid4()}.{file_ext}"
        filepath = UPLOAD_DIR / file_type / filename
        
        # Сохраняем файл
        with open(filepath, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # Формируем URL
        file_url = f"/uploads/{file_type}/{filename}"
        
        return {
            "success": True,
            "url": file_url,
            "filename": file.filename,
            "size": filepath.stat().st_size,
            "type": file.content_type
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка загрузки файла: {str(e)}"
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
    except Exception as e:
        print(f"⚠️  Error updating user status: {e}")
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
        except Exception as e:
            print(f"⚠️  Error updating user status on disconnect: {e}")
        finally:
            db.close()
    except Exception as e:
        print(f"❌ WebSocket error: {e}")
        manager.disconnect(user_id)

async def handle_websocket_message(data: Dict[str, Any], user_id: int):
    """Обработка сообщений WebSocket"""
    message_type = data.get("type")
    
    if message_type == "message":
        await handle_chat_message(data, user_id)
    elif message_type == "typing":
        await handle_typing_indicator(data, user_id)
    elif message_type == "reaction":
        await handle_reaction(data, user_id)
    else:
        print(f"❌ Unknown WebSocket message type: {message_type}")

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
            message_type=data.get("message_type", "text"),
            reactions={}
        )
        
        if chat_type == "private":
            message.to_user_id = chat_id
        elif chat_type == "group":
            message.group_id = chat_id
        elif chat_type == "channel":
            message.channel_id = chat_id
        else:
            print(f"❌ Unknown chat type: {chat_type}")
            return
        
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
                "created_at": message.created_at.isoformat() if message.created_at else datetime.utcnow().isoformat()
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Отправляем сообщение
        if chat_type == "private":
            # Отправляем отправителю (подтверждение)
            await manager.send_to_user(user_id, {
                **ws_message,
                "type": "message_sent",
                "message_id": message.id
            })
            # Отправляем получателю
            if chat_id != user_id:
                await manager.send_to_user(chat_id, ws_message)
        elif chat_type == "group":
            # Получаем всех участников группы
            members = db.query(GroupMember).filter(GroupMember.group_id == chat_id).all()
            for member in members:
                if member.user_id != user_id:
                    await manager.send_to_user(member.user_id, ws_message)
        elif chat_type == "channel":
            # Получаем всех подписчиков канала
            subscribers = db.query(ChannelSubscription).filter(ChannelSubscription.channel_id == chat_id).all()
            for subscriber in subscribers:
                if subscriber.user_id != user_id:
                    await manager.send_to_user(subscriber.user_id, ws_message)
            
    except Exception as e:
        print(f"❌ Ошибка обработки сообщения: {e}")
        db.rollback()
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
                GroupMember.user_id != user_id
            ).all()
            for member in members:
                await manager.send_to_user(member.user_id, typing_message)
        elif chat_type == "channel":
            # Получаем всех подписчиков канала кроме отправителя
            subscribers = db.query(ChannelSubscription).filter(
                ChannelSubscription.channel_id == chat_id,
                ChannelSubscription.user_id != user_id
            ).all()
            for subscriber in subscribers:
                await manager.send_to_user(subscriber.user_id, typing_message)
    except Exception as e:
        print(f"❌ Ошибка обработки typing индикатора: {e}")
    finally:
        db.close()

async def handle_reaction(data: Dict[str, Any], user_id: int):
    """Обработка реакции на сообщение"""
    message_id = data.get("message_id")
    reaction = data.get("reaction")
    
    if not message_id or not reaction:
        return
    
    db = SessionLocal()
    try:
        message = db.query(Message).filter(Message.id == message_id).first()
        if not message:
            return
        
        # Инициализируем реакции если их нет
        if not message.reactions:
            message.reactions = {}
        
        # Добавляем или удаляем реакцию
        if reaction not in message.reactions:
            message.reactions[reaction] = {"count": 1, "users": [user_id]}
        else:
            if user_id in message.reactions[reaction]["users"]:
                # Удаляем реакцию
                message.reactions[reaction]["users"].remove(user_id)
                message.reactions[reaction]["count"] -= 1
                if message.reactions[reaction]["count"] <= 0:
                    del message.reactions[reaction]
            else:
                # Добавляем реакцию
                message.reactions[reaction]["users"].append(user_id)
                message.reactions[reaction]["count"] += 1
        
        db.commit()
        
        # Отправляем обновление всем в чате
        reaction_message = {
            "type": "reaction_update",
            "message_id": message_id,
            "reactions": message.reactions or {},
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Определяем чат и отправляем обновление
        if message.to_user_id:
            # Личный чат
            participants = [message.from_user_id, message.to_user_id]
            for participant in participants:
                if participant in manager.active_connections:
                    await manager.send_to_user(participant, reaction_message)
        elif message.group_id:
            # Групповой чат
            members = db.query(GroupMember).filter(GroupMember.group_id == message.group_id).all()
            for member in members:
                if member.user_id in manager.active_connections:
                    await manager.send_to_user(member.user_id, reaction_message)
        elif message.channel_id:
            # Канал
            subscribers = db.query(ChannelSubscription).filter(
                ChannelSubscription.channel_id == message.channel_id
            ).all()
            for subscriber in subscribers:
                if subscriber.user_id in manager.active_connections:
                    await manager.send_to_user(subscriber.user_id, reaction_message)
                    
    except Exception as e:
        print(f"❌ Ошибка обработки реакции: {e}")
        db.rollback()
    finally:
        db.close()

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
    print(f"📖 API документация: http://localhost:{port}/api/docs")
    print("👑 Тестовый пользователь: admin / admin123")
    print("👤 Другие пользователи: alice/alice123, bob/bob123, charlie/charlie123")
    print("=" * 50)
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=False
    )
