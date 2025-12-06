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

# ========== ИМПОРТ МОДЕЛЕЙ ==========

try:
    from models import User, Message, Group, Channel, Subscription, GroupMember
    print("✅ Models imported successfully")
except ImportError as e:
    print(f"❌ Error importing models: {e}")
    raise

# ========== WEBSOCKET MANAGER ==========

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, WebSocket] = {}
        self.user_statuses: Dict[int, bool] = {}
    
    async def connect(self, websocket: WebSocket, user_id: int):
        await websocket.accept()
        self.active_connections[user_id] = websocket
        self.user_statuses[user_id] = True
        print(f"✅ User {user_id} connected")
        
        # Уведомляем о новом статусе онлайн
        await self.broadcast_status(user_id, True)
    
    def disconnect(self, user_id: int):
        if user_id in self.active_connections:
            del self.active_connections[user_id]
        self.user_statuses[user_id] = False
        print(f"📴 User {user_id} disconnected")
    
    async def send_personal_message(self, message: Dict[str, Any], user_id: int):
        if user_id in self.active_connections:
            await self.active_connections[user_id].send_json(message)
    
    async def send_to_user(self, user_id: int, message: Dict[str, Any]):
        if user_id in self.active_connections:
            await self.active_connections[user_id].send_json(message)
    
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
    
    async def broadcast_to_group(self, group_id: int, message: Dict[str, Any], exclude_user_id: Optional[int] = None):
        # Здесь должна быть логика отправки участникам группы
        # Пока отправляем всем
        await self.broadcast(message, exclude_user_id)
    
    async def broadcast_status(self, user_id: int, is_online: bool):
        status_message = {
            "type": "user_status",
            "user_id": user_id,
            "is_online": is_online,
            "timestamp": datetime.utcnow().isoformat()
        }
        await self.broadcast(status_message, user_id)

manager = ConnectionManager()

# ========== AUTH MODULE ==========

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

def get_current_user(request: Request, db: Session = Depends(get_db)):
    """Получаем текущего пользователя из токена"""
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
            "created_at": user.created_at.isoformat() if user.created_at else None
        }
    }

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
                "reactions": msg.reactions or {},
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
        
        # Уведомляем через WebSocket
        ws_message = {
            "type": "message",
            "chat_type": chat_type,
            "chat_id": to_user_id or group_id or channel_id,
            "message": {
                "id": message.id,
                "content": message.content,
                "type": message.message_type,
                "is_my_message": False,
                "from_user_id": message.from_user_id,
                "group_id": message.group_id,
                "channel_id": message.channel_id,
                "sender": {
                    "id": user.id,
                    "username": user.username,
                    "display_name": user.display_name,
                    "avatar_url": user.avatar_url
                },
                "created_at": message.created_at.isoformat() if message.created_at else None
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Отправляем получателю/участникам
        if chat_type == "private" and to_user_id:
            await manager.send_to_user(to_user_id, ws_message)
        elif chat_type == "group" and group_id:
            # TODO: Отправка участникам группы
            await manager.broadcast(ws_message, user.id)
        elif chat_type == "channel" and channel_id:
            # TODO: Отправка подписчикам канала
            await manager.broadcast(ws_message, user.id)
        
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

# ========== CHATS ENDPOINTS ==========

@app.get("/api/chats/all")
async def get_all_chats(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение всех чатов пользователя"""
    try:
        # Личные чаты (пользователи, с которыми есть переписка)
        private_messages = db.query(Message).filter(
            or_(Message.from_user_id == user.id, Message.to_user_id == user.id)
        ).all()
        
        # Собираем уникальных пользователей из переписки
        user_ids = set()
        for msg in private_messages:
            if msg.from_user_id != user.id:
                user_ids.add(msg.from_user_id)
            if msg.to_user_id and msg.to_user_id != user.id:
                user_ids.add(msg.to_user_id)
        
        private_chats = []
        for uid in user_ids:
            contact = db.query(User).filter(User.id == uid).first()
            if contact:
                # Получаем последнее сообщение
                last_msg = db.query(Message).filter(
                    or_(
                        and_(Message.from_user_id == user.id, Message.to_user_id == uid),
                        and_(Message.from_user_id == uid, Message.to_user_id == user.id)
                    )
                ).order_by(desc(Message.created_at)).first()
                
                private_chats.append({
                    "id": contact.id,
                    "name": contact.display_name or contact.username,
                    "avatar_url": contact.avatar_url,
                    "is_online": contact.is_online,
                    "last_message": {
                        "content": last_msg.content if last_msg else "",
                        "timestamp": last_msg.created_at.isoformat() if last_msg else None
                    } if last_msg else None
                })
        
        # Группы пользователя
        user_groups = db.query(Group).join(GroupMember).filter(GroupMember.user_id == user.id).all()
        group_chats = []
        for group in user_groups:
            # Получаем последнее сообщение
            last_msg = db.query(Message).filter(Message.group_id == group.id)\
                .order_by(desc(Message.created_at)).first()
            
            group_chats.append({
                "id": group.id,
                "name": group.name,
                "avatar_url": group.avatar_url,
                "members_count": group.members_count or 0,
                "last_message": {
                    "content": last_msg.content if last_msg else "",
                    "timestamp": last_msg.created_at.isoformat() if last_msg else None
                } if last_msg else None
            })
        
        # Каналы пользователя
        user_channels = db.query(Channel).join(Subscription).filter(Subscription.user_id == user.id).all()
        channel_chats = []
        for channel in user_channels:
            # Получаем последнее сообщение
            last_msg = db.query(Message).filter(Message.channel_id == channel.id)\
                .order_by(desc(Message.created_at)).first()
            
            channel_chats.append({
                "id": channel.id,
                "name": channel.name,
                "avatar_url": channel.avatar_url,
                "subscribers_count": channel.subscribers_count or 0,
                "last_message": {
                    "content": last_msg.content if last_msg else "",
                    "timestamp": last_msg.created_at.isoformat() if last_msg else None
                } if last_msg else None
            })
        
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

# ========== GROUPS ENDPOINTS ==========

@app.get("/api/groups")
async def get_groups(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    search: Optional[str] = Query(None),
    public_only: bool = Query(False),
    db: Session = Depends(get_db)
):
    """Получение списка групп"""
    try:
        query = db.query(Group)
        
        if public_only:
            query = query.filter(Group.is_public == True)
        
        if search:
            search_filter = f"%{search}%"
            query = query.filter(
                (Group.name.ilike(search_filter)) |
                (Group.description.ilike(search_filter))
            )
        
        total = query.count()
        groups = query.order_by(desc(Group.created_at)) \
                     .offset((page - 1) * limit) \
                     .limit(limit) \
                     .all()
        
        groups_data = []
        for group in groups:
            groups_data.append({
                "id": group.id,
                "name": group.name,
                "description": group.description,
                "avatar_url": group.avatar_url,
                "is_public": group.is_public,
                "members_count": group.members_count or 0,
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
    avatar: Optional[UploadFile] = File(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Создание новой группы"""
    try:
        # Проверяем уникальность имени
        existing_group = db.query(Group).filter(Group.name == name).first()
        if existing_group:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Группа с таким названием уже существует"
            )
        
        # Обрабатываем аватар
        avatar_url = None
        if avatar:
            file_ext = avatar.filename.split('.')[-1]
            filename = f"{uuid.uuid4()}.{file_ext}"
            file_path = UPLOAD_DIR / "avatars" / filename
            
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(avatar.file, buffer)
            
            avatar_url = f"/uploads/avatars/{filename}"
        
        # Создаем группу
        group = Group(
            name=name,
            description=description,
            is_public=is_public,
            avatar_url=avatar_url,
            owner_id=user.id,
            members_count=1
        )
        
        db.add(group)
        db.commit()
        db.refresh(group)
        
        # Добавляем создателя как участника
        group_member = GroupMember(
            group_id=group.id,
            user_id=user.id,
            role="owner"
        )
        db.add(group_member)
        db.commit()
        
        return {
            "success": True,
            "message": "Группа создана",
            "group": {
                "id": group.id,
                "name": group.name,
                "description": group.description,
                "avatar_url": group.avatar_url,
                "is_public": group.is_public,
                "members_count": group.members_count
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

# ========== CHANNELS ENDPOINTS ==========

@app.get("/api/channels")
async def get_channels(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    search: Optional[str] = Query(None),
    public_only: bool = Query(False),
    db: Session = Depends(get_db)
):
    """Получение списка каналов"""
    try:
        query = db.query(Channel)
        
        if public_only:
            query = query.filter(Channel.is_public == True)
        
        if search:
            search_filter = f"%{search}%"
            query = query.filter(
                (Channel.name.ilike(search_filter)) |
                (Channel.description.ilike(search_filter))
            )
        
        total = query.count()
        channels = query.order_by(desc(Channel.created_at)) \
                       .offset((page - 1) * limit) \
                       .limit(limit) \
                       .all()
        
        channels_data = []
        for channel in channels:
            channels_data.append({
                "id": channel.id,
                "name": channel.name,
                "description": channel.description,
                "avatar_url": channel.avatar_url,
                "is_public": channel.is_public,
                "subscribers_count": channel.subscribers_count or 0,
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
    avatar: Optional[UploadFile] = File(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Создание нового канала"""
    try:
        # Проверяем уникальность имени
        existing_channel = db.query(Channel).filter(Channel.name == name).first()
        if existing_channel:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Канал с таким названием уже существует"
            )
        
        # Обрабатываем аватар
        avatar_url = None
        if avatar:
            file_ext = avatar.filename.split('.')[-1]
            filename = f"{uuid.uuid4()}.{file_ext}"
            file_path = UPLOAD_DIR / "avatars" / filename
            
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(avatar.file, buffer)
            
            avatar_url = f"/uploads/avatars/{filename}"
        
        # Создаем канал
        channel = Channel(
            name=name,
            description=description,
            is_public=is_public,
            avatar_url=avatar_url,
            owner_id=user.id,
            subscribers_count=1
        )
        
        db.add(channel)
        db.commit()
        db.refresh(channel)
        
        # Добавляем создателя как подписчика
        subscription = Subscription(
            channel_id=channel.id,
            user_id=user.id,
            role="owner"
        )
        db.add(subscription)
        db.commit()
        
        return {
            "success": True,
            "message": "Канал создан",
            "channel": {
                "id": channel.id,
                "name": channel.name,
                "description": channel.description,
                "avatar_url": channel.avatar_url,
                "is_public": channel.is_public,
                "subscribers_count": channel.subscribers_count
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
    elif message_type == "reaction":
        await handle_message_reaction(data, user_id)
    elif message_type == "call":
        await handle_call(data, user_id)

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
        elif chat_type == "group":
            # Отправляем всем участникам группы
            await manager.broadcast_to_group(chat_id, ws_message, user_id)
        elif chat_type == "channel":
            # Отправляем всем подписчикам канала
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

async def handle_message_reaction(data: Dict[str, Any], user_id: int):
    """Обработка реакции на сообщение"""
    # TODO: Реализовать реакции
    pass

async def handle_call(data: Dict[str, Any], user_id: int):
    """Обработка звонка"""
    # TODO: Реализовать звонки
    pass

# ========== STATIC FILES ==========

# Монтируем статические файлы в самом конце
if frontend_dir.exists():
    print(f"✅ Frontend found: {frontend_dir}")
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
else:
    print(f"⚠️  Frontend not found: {frontend_dir}")

# Монтируем директорию загрузок
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

# ========== FALLBACK ROUTES ==========

@app.get("/{path:path}")
async def serve_frontend(path: str):
    """Сервим статические файлы фронтенда"""
    if path.startswith("api/"):
        return JSONResponse(
            status_code=404,
            content={"detail": "API endpoint not found"}
        )
    
    file_path = frontend_dir / path
    
    if file_path.exists() and file_path.is_file():
        return FileResponse(str(file_path))
    
    # Если файл не найден, отдаем index.html
    index_path = frontend_dir / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    
    return JSONResponse(
        status_code=404,
        content={"detail": "File not found"}
    )

# ========== START SERVER ==========

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print("=" * 50)
    print("🚀 DevNet Messenger API запущен!")
    print(f"📡 Порт: {port}")
    print(f"📁 Директория загрузок: {UPLOAD_DIR}")
    print(f"📁 Директория фронтенда: {frontend_dir}")
    print(f"🔗 API документация: http://localhost:{port}/api/docs")
    print(f"💬 Чат: http://localhost:{port}/chat")
    print("👑 Тестовый пользователь: admin / admin123")
    print("=" * 50)
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=False
    )
