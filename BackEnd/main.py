from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, status, Form, Request, File, UploadFile, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse, RedirectResponse
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
    from database import engine, SessionLocal, get_db
    from models import (
        Base, User, Message, Group, GroupMember, Channel, Subscription, 
        File as FileModel, Reaction, Notification, MessageType
    )
    from auth import create_access_token, verify_token, verify_password, get_password_hash
    print("✅ Все модули успешно импортированы")
except ImportError as e:
    print(f"❌ Ошибка импорта: {e}")
    raise

# ========== ИНИЦИАЛИЗАЦИЯ ==========

Base.metadata.create_all(bind=engine)

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
    print(f"❌ Ошибка создания каналов: {e}")

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
        "service": "DevNet Messenger API",
        "version": "5.0.0",
        "timestamp": datetime.utcnow().isoformat(),
        "features": ["auth", "websocket", "groups", "channels", "media", "reactions"]
    }

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
        token = request.cookies.get("access_token")
        if not token:
            raise HTTPException(status_code=401, detail="Требуется аутентификация")
        
        payload = verify_token(token)
        if not payload:
            raise HTTPException(status_code=401, detail="Недействительный токен")
        
        user_id = payload.get("user_id")
        
        # Получаем каналы
        query = db.query(Channel).filter(Channel.is_public == True)
        total = query.count()
        channels = query.order_by(desc(Channel.is_official), desc(Channel.last_activity)) \
                       .offset((page - 1) * limit) \
                       .limit(limit) \
                       .all()
        
        # Проверяем подписки
        subscribed_channel_ids = []
        if user_id:
            subscriptions = db.query(Subscription).filter(Subscription.user_id == user_id).all()
            subscribed_channel_ids = [sub.channel_id for sub in subscriptions]
        
        channels_data = []
        for channel in channels:
            # Получаем количество подписчиков
            subscribers_count = db.query(Subscription).filter(Subscription.channel_id == channel.id).count()
            
            # Получаем последнее сообщение
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
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка загрузки каналов: {str(e)}")

@app.post("/api/channels")
async def create_channel(
    request: Request,
    name: str = Form(...),
    description: str = Form(None),
    is_public: bool = Form(True),
    db: Session = Depends(get_db)
):
    """Создание нового канала"""
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
        
        # Проверяем имя канала
        if len(name) < 3:
            raise HTTPException(status_code=400, detail="Название канала должно быть не менее 3 символов")
        
        if len(name) > 100:
            raise HTTPException(status_code=400, detail="Название канала должно быть не более 100 символов")
        
        # Проверяем уникальность имени
        existing = db.query(Channel).filter(Channel.name == name).first()
        if existing:
            raise HTTPException(status_code=400, detail="Канал с таким именем уже существует")
        
        # Создаем канал
        channel = Channel(
            name=name,
            description=description,
            is_public=is_public,
            is_official=False,  # Только админ может создавать официальные каналы
            created_by=user_id
        )
        
        db.add(channel)
        db.commit()
        db.refresh(channel)
        
        # Автоматически подписываем создателя
        subscription = Subscription(
            channel_id=channel.id,
            user_id=user_id,
            notifications=True
        )
        db.add(subscription)
        db.commit()
        
        return {
            "success": True,
            "channel": {
                "id": channel.id,
                "name": channel.name,
                "description": channel.description,
                "avatar_url": channel.avatar_url,
                "is_public": channel.is_public,
                "is_official": channel.is_official,
                "created_by": channel.created_by,
                "created_at": channel.created_at.isoformat() if channel.created_at else None
            },
            "message": "Канал успешно создан"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Ошибка создания канала: {str(e)}")

@app.post("/api/channels/{channel_id}/subscribe")
async def subscribe_to_channel(
    channel_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Подписка на канал"""
    try:
        token = request.cookies.get("access_token")
        if not token:
            raise HTTPException(status_code=401, detail="Требуется аутентификация")
        
        payload = verify_token(token)
        if not payload:
            raise HTTPException(status_code=401, detail="Недействительный токен")
        
        user_id = payload.get("user_id")
        
        # Проверяем существование канала
        channel = db.query(Channel).filter(Channel.id == channel_id).first()
        if not channel:
            raise HTTPException(status_code=404, detail="Канал не найден")
        
        if not channel.is_public:
            raise HTTPException(status_code=403, detail="Этот канал является приватным")
        
        # Проверяем, подписан ли уже пользователь
        existing_sub = db.query(Subscription).filter(
            Subscription.channel_id == channel_id,
            Subscription.user_id == user_id
        ).first()
        
        if existing_sub:
            return {
                "success": True,
                "message": "Вы уже подписаны на этот канал"
            }
        
        # Создаем подписку
        subscription = Subscription(
            channel_id=channel_id,
            user_id=user_id,
            notifications=True
        )
        
        db.add(subscription)
        db.commit()
        
        # Обновляем активность канала
        channel.last_activity = datetime.utcnow()
        db.commit()
        
        return {
            "success": True,
            "message": "Вы успешно подписались на канал"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Ошибка подписки: {str(e)}")

@app.post("/api/channels/{channel_id}/unsubscribe")
async def unsubscribe_from_channel(
    channel_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Отписка от канала"""
    try:
        token = request.cookies.get("access_token")
        if not token:
            raise HTTPException(status_code=401, detail="Требуется аутентификация")
        
        payload = verify_token(token)
        if not payload:
            raise HTTPException(status_code=401, detail="Недействительный токен")
        
        user_id = payload.get("user_id")
        
        # Находим подписку
        subscription = db.query(Subscription).filter(
            Subscription.channel_id == channel_id,
            Subscription.user_id == user_id
        ).first()
        
        if not subscription:
            raise HTTPException(status_code=404, detail="Подписка не найдена")
        
        # Удаляем подписку
        db.delete(subscription)
        db.commit()
        
        return {
            "success": True,
            "message": "Вы отписались от канала"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Ошибка отписки: {str(e)}")

@app.get("/api/channels/{channel_id}")
async def get_channel_info(
    channel_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Получение информации о канале"""
    try:
        token = request.cookies.get("access_token")
        if not token:
            raise HTTPException(status_code=401, detail="Требуется аутентификация")
        
        payload = verify_token(token)
        if not payload:
            raise HTTPException(status_code=401, detail="Недействительный токен")
        
        user_id = payload.get("user_id")
        
        # Получаем канал
        channel = db.query(Channel).filter(Channel.id == channel_id).first()
        if not channel:
            raise HTTPException(status_code=404, detail="Канал не найден")
        
        if not channel.is_public:
            # Проверяем подписку
            subscription = db.query(Subscription).filter(
                Subscription.channel_id == channel_id,
                Subscription.user_id == user_id
            ).first()
            if not subscription:
                raise HTTPException(status_code=403, detail="Доступ запрещен")
        
        # Получаем количество подписчиков
        subscribers_count = db.query(Subscription).filter(Subscription.channel_id == channel_id).count()
        
        # Получаем количество сообщений
        messages_count = db.query(Message).filter(Message.channel_id == channel_id).count()
        
        # Проверяем подписку пользователя
        is_subscribed = False
        if user_id:
            subscription = db.query(Subscription).filter(
                Subscription.channel_id == channel_id,
                Subscription.user_id == user_id
            ).first()
            is_subscribed = subscription is not None
        
        # Получаем последние сообщения
        last_messages = db.query(Message).filter(Message.channel_id == channel_id) \
            .order_by(Message.created_at.desc()).limit(10).all()
        
        return {
            "success": True,
            "channel": {
                "id": channel.id,
                "name": channel.name,
                "description": channel.description,
                "avatar_url": channel.avatar_url,
                "banner_url": channel.banner_url,
                "is_public": channel.is_public,
                "is_official": channel.is_official,
                "created_by": channel.created_by,
                "created_at": channel.created_at.isoformat() if channel.created_at else None,
                "last_activity": channel.last_activity.isoformat() if channel.last_activity else None,
                "subscribers_count": subscribers_count,
                "messages_count": messages_count,
                "is_subscribed": is_subscribed
            },
            "recent_messages": [
                {
                    "id": msg.id,
                    "content": msg.content,
                    "type": msg.message_type,
                    "media_url": msg.media_url,
                    "created_at": msg.created_at.isoformat() if msg.created_at else None
                }
                for msg in last_messages
            ]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка загрузки канала: {str(e)}")

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
        token = request.cookies.get("access_token")
        if not token:
            raise HTTPException(status_code=401, detail="Требуется аутентификация")
        
        payload = verify_token(token)
        if not payload:
            raise HTTPException(status_code=401, detail="Недействительный токен")
        
        user_id = payload.get("user_id")
        
        # Получаем группы пользователя
        query = db.query(Group).join(GroupMember).filter(GroupMember.user_id == user_id)
        total = query.count()
        groups = query.order_by(desc(Group.last_activity)) \
                     .offset((page - 1) * limit) \
                     .limit(limit) \
                     .all()
        
        groups_data = []
        for group in groups:
            # Получаем количество участников
            members_count = db.query(GroupMember).filter(GroupMember.group_id == group.id).count()
            
            # Получаем последнее сообщение
            last_message = db.query(Message).filter(Message.group_id == group.id) \
                .order_by(Message.created_at.desc()).first()
            
            groups_data.append({
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
                "my_role": db.query(GroupMember).filter(
                    GroupMember.group_id == group.id,
                    GroupMember.user_id == user_id
                ).first().role if user_id else "member",
                "last_message": {
                    "content": last_message.content if last_message else None,
                    "timestamp": last_message.created_at.isoformat() if last_message else None
                } if last_message else None
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
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка загрузки групп: {str(e)}")

@app.post("/api/groups")
async def create_group(
    request: Request,
    name: str = Form(...),
    description: str = Form(None),
    is_public: bool = Form(True),
    db: Session = Depends(get_db)
):
    """Создание новой группы"""
    try:
        token = request.cookies.get("access_token")
        if not token:
            raise HTTPException(status_code=401, detail="Требуется аутентификация")
        
        payload = verify_token(token)
        if not payload:
            raise HTTPException(status_code=401, detail="Недействительный токен")
        
        user_id = payload.get("user_id")
        
        # Проверяем имя группы
        if len(name) < 3:
            raise HTTPException(status_code=400, detail="Название группы должно быть не менее 3 символов")
        
        if len(name) > 100:
            raise HTTPException(status_code=400, detail="Название группы должно быть не более 100 символов")
        
        # Проверяем уникальность имени
        existing = db.query(Group).filter(Group.name == name).first()
        if existing:
            raise HTTPException(status_code=400, detail="Группа с таким именем уже существует")
        
        # Создаем группу
        group = Group(
            name=name,
            description=description,
            is_public=is_public,
            created_by=user_id
        )
        
        db.add(group)
        db.commit()
        db.refresh(group)
        
        # Добавляем создателя как владельца
        group_member = GroupMember(
            group_id=group.id,
            user_id=user_id,
            role="owner"
        )
        db.add(group_member)
        db.commit()
        
        return {
            "success": True,
            "group": {
                "id": group.id,
                "name": group.name,
                "description": group.description,
                "avatar_url": group.avatar_url,
                "is_public": group.is_public,
                "created_by": group.created_by,
                "created_at": group.created_at.isoformat() if group.created_at else None
            },
            "message": "Группа успешно создана"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Ошибка создания группы: {str(e)}")

@app.post("/api/groups/{group_id}/join")
async def join_group(
    group_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Вступление в группу"""
    try:
        token = request.cookies.get("access_token")
        if not token:
            raise HTTPException(status_code=401, detail="Требуется аутентификация")
        
        payload = verify_token(token)
        if not payload:
            raise HTTPException(status_code=401, detail="Недействительный токен")
        
        user_id = payload.get("user_id")
        
        # Проверяем существование группы
        group = db.query(Group).filter(Group.id == group_id).first()
        if not group:
            raise HTTPException(status_code=404, detail="Группа не найдена")
        
        if not group.is_public:
            raise HTTPException(status_code=403, detail="Эта группа является приватной")
        
        # Проверяем, является ли пользователь уже участником
        existing_member = db.query(GroupMember).filter(
            GroupMember.group_id == group_id,
            GroupMember.user_id == user_id
        ).first()
        
        if existing_member:
            return {
                "success": True,
                "message": "Вы уже состоите в этой группе"
            }
        
        # Проверяем максимальное количество участников
        members_count = db.query(GroupMember).filter(GroupMember.group_id == group_id).count()
        if group.max_members and members_count >= group.max_members:
            raise HTTPException(status_code=400, detail="Группа достигла максимального количества участников")
        
        # Добавляем пользователя в группу
        group_member = GroupMember(
            group_id=group_id,
            user_id=user_id,
            role="member"
        )
        
        db.add(group_member)
        db.commit()
        
        # Обновляем активность группы
        group.last_activity = datetime.utcnow()
        db.commit()
        
        return {
            "success": True,
            "message": "Вы успешно вступили в группу"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Ошибка вступления в группу: {str(e)}")

@app.get("/api/groups/{group_id}")
async def get_group_info(
    group_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Получение информации о группе"""
    try:
        token = request.cookies.get("access_token")
        if not token:
            raise HTTPException(status_code=401, detail="Требуется аутентификация")
        
        payload = verify_token(token)
        if not payload:
            raise HTTPException(status_code=401, detail="Недействительный токен")
        
        user_id = payload.get("user_id")
        
        # Получаем группу
        group = db.query(Group).filter(Group.id == group_id).first()
        if not group:
            raise HTTPException(status_code=404, detail="Группа не найдена")
        
        # Проверяем, является ли пользователь участником
        membership = db.query(GroupMember).filter(
            GroupMember.group_id == group_id,
            GroupMember.user_id == user_id
        ).first()
        
        if not membership and not group.is_public:
            raise HTTPException(status_code=403, detail="Доступ запрещен")
        
        # Получаем количество участников
        members_count = db.query(GroupMember).filter(GroupMember.group_id == group_id).count()
        
        # Получаем список участников
        members = db.query(GroupMember, User).join(User, GroupMember.user_id == User.id) \
            .filter(GroupMember.group_id == group_id) \
            .order_by(GroupMember.role.desc(), GroupMember.joined_at) \
            .limit(50) \
            .all()
        
        # Получаем последние сообщения
        last_messages = db.query(Message).filter(Message.group_id == group_id) \
            .order_by(Message.created_at.desc()).limit(10).all()
        
        return {
            "success": True,
            "group": {
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
                "is_member": membership is not None,
                "my_role": membership.role if membership else None
            },
            "members": [
                {
                    "id": user.id,
                    "username": user.username,
                    "display_name": user.display_name,
                    "avatar_url": user.avatar_url,
                    "is_online": user.is_online,
                    "role": member.role,
                    "joined_at": member.joined_at.isoformat() if member.joined_at else None
                }
                for member, user in members
            ],
            "recent_messages": [
                {
                    "id": msg.id,
                    "from_user_id": msg.from_user_id,
                    "content": msg.content,
                    "type": msg.message_type,
                    "media_url": msg.media_url,
                    "created_at": msg.created_at.isoformat() if msg.created_at else None
                }
                for msg in last_messages
            ]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка загрузки группы: {str(e)}")

# ========== СООБЩЕНИЯ (для групп и каналов) ==========

@app.get("/api/chats/all")
async def get_all_chats(
    request: Request,
    db: Session = Depends(get_db)
):
    """Получение всех чатов пользователя (личные + группы + каналы)"""
    try:
        token = request.cookies.get("access_token")
        if not token:
            raise HTTPException(status_code=401, detail="Требуется аутентификация")
        
        payload = verify_token(token)
        if not payload:
            raise HTTPException(status_code=401, detail="Недействительный токен")
        
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
                    "avatar_url": user.avatar_url,
                    "username": user.username,
                    "is_online": user.is_online,
                    "last_message": {
                        "content": last_message.content if last_message else None,
                        "timestamp": last_message.created_at.isoformat() if last_message else None
                    } if last_message else None
                })
        
        # Получаем группы пользователя
        groups = db.query(Group).join(GroupMember).filter(GroupMember.user_id == current_user_id).all()
        group_chats = []
        
        for group in groups:
            members_count = db.query(GroupMember).filter(GroupMember.group_id == group.id).count()
            
            # Получаем последнее сообщение
            last_message = db.query(Message).filter(Message.group_id == group.id) \
                .order_by(Message.created_at.desc()).first()
            
            group_chats.append({
                "id": group.id,
                "name": group.name,
                "description": group.description,
                "type": "group",
                "avatar_url": group.avatar_url,
                "members_count": members_count,
                "last_message": {
                    "content": last_message.content if last_message else None,
                    "timestamp": last_message.created_at.isoformat() if last_message else None
                } if last_message else None
            })
        
        # Получаем каналы пользователя
        channels = db.query(Channel).join(Subscription).filter(Subscription.user_id == current_user_id).all()
        channel_chats = []
        
        for channel in channels:
            subscribers_count = db.query(Subscription).filter(Subscription.channel_id == channel.id).count()
            
            # Получаем последнее сообщение
            last_message = db.query(Message).filter(Message.channel_id == channel.id) \
                .order_by(Message.created_at.desc()).first()
            
            channel_chats.append({
                "id": channel.id,
                "name": channel.name,
                "description": channel.description,
                "type": "channel",
                "avatar_url": channel.avatar_url,
                "is_official": channel.is_official,
                "subscribers_count": subscribers_count,
                "last_message": {
                    "content": last_message.content if last_message else None,
                    "timestamp": last_message.created_at.isoformat() if last_message else None
                } if last_message else None
            })
        
        return {
            "success": True,
            "private_chats": private_chats,
            "group_chats": group_chats,
            "channel_chats": channel_chats,
            "counts": {
                "private": len(private_chats),
                "groups": len(group_chats),
                "channels": len(channel_chats),
                "total": len(private_chats) + len(group_chats) + len(channel_chats)
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка загрузки чатов: {str(e)}")

@app.get("/api/messages/chat/{chat_type}/{chat_id}")
async def get_chat_messages(
    chat_type: str,  # private, group, channel
    chat_id: int,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    request: Request = None,
    db: Session = Depends(get_db)
):
    """Получение сообщений чата"""
    try:
        token = request.cookies.get("access_token") if request else None
        if not token:
            raise HTTPException(status_code=401, detail="Требуется аутентификация")
        
        payload = verify_token(token)
        if not payload:
            raise HTTPException(status_code=401, detail="Недействительный токен")
        
        current_user_id = payload.get("user_id")
        
        query = db.query(Message)
        
        if chat_type == "private":
            query = query.filter(
                ((Message.from_user_id == current_user_id) & (Message.to_user_id == chat_id)) |
                ((Message.from_user_id == chat_id) & (Message.to_user_id == current_user_id))
            )
        elif chat_type == "group":
            # Проверяем членство в группе
            membership = db.query(GroupMember).filter(
                GroupMember.group_id == chat_id,
                GroupMember.user_id == current_user_id
            ).first()
            if not membership:
                raise HTTPException(status_code=403, detail="Доступ запрещен")
            query = query.filter(Message.group_id == chat_id)
        elif chat_type == "channel":
            # Проверяем подписку на канал
            subscription = db.query(Subscription).filter(
                Subscription.channel_id == chat_id,
                Subscription.user_id == current_user_id
            ).first()
            if not subscription:
                raise HTTPException(status_code=403, detail="Доступ запрещен")
            query = query.filter(Message.channel_id == chat_id)
        else:
            raise HTTPException(status_code=400, detail="Неверный тип чата")
        
        total = query.count()
        messages = query.order_by(Message.created_at.desc()) \
                       .offset((page - 1) * limit) \
                       .limit(limit) \
                       .all()
        
        # Получаем информацию о реакциях
        messages_data = []
        for msg in messages:
            reactions = db.query(Reaction).filter(Reaction.message_id == msg.id).all()
            
            # Группируем реакции по emoji
            reactions_grouped = {}
            for reaction in reactions:
                if reaction.emoji not in reactions_grouped:
                    reactions_grouped[reaction.emoji] = {
                        "count": 0,
                        "users": []
                    }
                reactions_grouped[reaction.emoji]["count"] += 1
                reactions_grouped[reaction.emoji]["users"].append(reaction.user_id)
            
            messages_data.append({
                "id": msg.id,
                "from_user_id": msg.from_user_id,
                "to_user_id": msg.to_user_id,
                "group_id": msg.group_id,
                "channel_id": msg.channel_id,
                "content": msg.content,
                "type": msg.message_type,
                "media_url": msg.media_url,
                "media_size": msg.media_size,
                "media_duration": msg.media_duration,
                "thumb_url": msg.thumb_url,
                "reply_to_id": msg.reply_to_id,
                "is_edited": msg.is_edited,
                "is_pinned": msg.is_pinned,
                "views_count": msg.views_count,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
                "reactions": reactions_grouped,
                "is_my_message": msg.from_user_id == current_user_id
            })
        
        return {
            "success": True,
            "messages": list(reversed(messages_data)),  # В правильном порядке
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
        raise HTTPException(status_code=500, detail=f"Ошибка загрузки сообщений: {str(e)}")

# ========== ЗАГРУЗКА МЕДИА ==========

@app.post("/api/upload/media")
async def upload_media(
    file: UploadFile = File(...),
    media_type: str = Query("image", regex="^(image|video|audio|file)$"),
    request: Request = None,
    db: Session = Depends(get_db)
):
    """Загрузка медиа файла"""
    try:
        # Проверяем авторизацию
        token = request.cookies.get("access_token") if request else None
        if not token:
            raise HTTPException(status_code=401, detail="Требуется аутентификация")
        
        payload = verify_token(token)
        if not payload:
            raise HTTPException(status_code=401, detail="Недействительный токен")
        
        user_id = payload.get("user_id")
        
        # Определяем тип файла
        if media_type == "image":
            allowed_types = ["image/jpeg", "image/png", "image/gif", "image/webp"]
            max_size = 10 * 1024 * 1024  # 10MB
        elif media_type == "video":
            allowed_types = ["video/mp4", "video/webm", "video/ogg"]
            max_size = 100 * 1024 * 1024  # 100MB
        elif media_type == "audio":
            allowed_types = ["audio/mpeg", "audio/wav", "audio/ogg"]
            max_size = 50 * 1024 * 1024  # 50MB
        else:  # file
            allowed_types = ["*/*"]
            max_size = 50 * 1024 * 1024  # 50MB
        
        # Проверяем тип файла
        if file.content_type and media_type != "file":
            if file.content_type not in allowed_types:
                return JSONResponse(
                    status_code=400,
                    content={"success": False, "detail": f"Неподдерживаемый тип файла. Разрешены: {', '.join(allowed_types)}"}
                )
        
        # Проверяем размер
        file.file.seek(0, 2)
        file_size = file.file.tell()
        file.file.seek(0)
        
        if file_size > max_size:
            return JSONResponse(
                status_code=400,
                content={"success": False, "detail": f"Файл слишком большой. Максимум: {max_size / 1024 / 1024:.1f}MB"}
            )
        
        # Генерируем уникальное имя
        file_extension = ""
        if '.' in file.filename:
            file_extension = file.filename.split('.')[-1]
        
        unique_filename = f"{uuid.uuid4()}"
        if file_extension:
            unique_filename += f".{file_extension}"
        
        # Сохраняем файл
        save_dir = UPLOAD_DIR / f"{media_type}s"
        save_dir.mkdir(exist_ok=True)
        save_path = save_dir / unique_filename
        
        with open(save_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # Сохраняем в базу
        db_file = FileModel(
            filename=unique_filename,
            original_filename=file.filename,
            file_type=media_type,
            file_size=file_size,
            uploaded_by=user_id,
            url=f"/uploads/{media_type}s/{unique_filename}"
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
                "size": db_file.file_size,
                "uploaded_at": db_file.created_at.isoformat() if db_file.created_at else None
            }
        }
        
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "detail": f"Ошибка загрузки файла: {str(e)}"}
        )

# ========== РЕАКЦИИ ==========

@app.post("/api/messages/{message_id}/reactions")
async def add_reaction(
    message_id: int,
    emoji: str = Form(...),
    request: Request = None,
    db: Session = Depends(get_db)
):
    """Добавление реакции к сообщению"""
    try:
        token = request.cookies.get("access_token") if request else None
        if not token:
            raise HTTPException(status_code=401, detail="Требуется аутентификация")
        
        payload = verify_token(token)
        if not payload:
            raise HTTPException(status_code=401, detail="Недействительный токен")
        
        user_id = payload.get("user_id")
        
        # Проверяем существование сообщения
        message = db.query(Message).filter(Message.id == message_id).first()
        if not message:
            raise HTTPException(status_code=404, detail="Сообщение не найдено")
        
        # Проверяем доступ к сообщению
        can_react = False
        if message.group_id:
            membership = db.query(GroupMember).filter(
                GroupMember.group_id == message.group_id,
                GroupMember.user_id == user_id
            ).first()
            can_react = membership is not None
        elif message.channel_id:
            subscription = db.query(Subscription).filter(
                Subscription.channel_id == message.channel_id,
                Subscription.user_id == user_id
            ).first()
            can_react = subscription is not None
        else:  # приватное сообщение
            can_react = message.from_user_id == user_id or message.to_user_id == user_id
        
        if not can_react:
            raise HTTPException(status_code=403, detail="Нет доступа к этому сообщению")
        
        # Проверяем существующую реакцию
        existing_reaction = db.query(Reaction).filter(
            Reaction.message_id == message_id,
            Reaction.user_id == user_id,
            Reaction.emoji == emoji
        ).first()
        
        if existing_reaction:
            # Удаляем реакцию (toggle)
            db.delete(existing_reaction)
            action = "removed"
        else:
            # Удаляем другие реакции пользователя на это сообщение
            db.query(Reaction).filter(
                Reaction.message_id == message_id,
                Reaction.user_id == user_id
            ).delete()
            
            # Добавляем новую реакцию
            reaction = Reaction(
                message_id=message_id,
                user_id=user_id,
                emoji=emoji
            )
            db.add(reaction)
            action = "added"
        
        db.commit()
        
        # Получаем обновленные реакции
        reactions = db.query(Reaction).filter(Reaction.message_id == message_id).all()
        reactions_grouped = {}
        for reaction in reactions:
            if reaction.emoji not in reactions_grouped:
                reactions_grouped[reaction.emoji] = {
                    "count": 0,
                    "users": []
                }
            reactions_grouped[reaction.emoji]["count"] += 1
            reactions_grouped[reaction.emoji]["users"].append(reaction.user_id)
        
        # Отправляем обновление через WebSocket
        await manager.send_personal_message(
            json.dumps({
                "type": "reaction_update",
                "message_id": message_id,
                "reactions": reactions_grouped
            }),
            user_id
        )
        
        # Отправляем другим участникам чата
        if message.group_id:
            members = db.query(GroupMember).filter(GroupMember.group_id == message.group_id).all()
            for member in members:
                if member.user_id != user_id:
                    await manager.send_personal_message(
                        json.dumps({
                            "type": "reaction_update",
                            "message_id": message_id,
                            "reactions": reactions_grouped
                        }),
                        member.user_id
                    )
        
        return {
            "success": True,
            "action": action,
            "reactions": reactions_grouped,
            "message": f"Реакция {action}"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Ошибка добавления реакции: {str(e)}")

# ========== WEB SOCKET (расширенный) ==========

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
            elif message_type == "media_message":
                await handle_media_message(message_data, user_id)
            elif message_type == "typing":
                await handle_typing_indicator(message_data, user_id)
            elif message_type == "read_receipt":
                await handle_read_receipt(message_data, user_id)
            elif message_type == "call":
                await handle_call_message(message_data, user_id)
                
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
        chat_type = message_data.get("chat_type", "private")  # private, group, channel
        chat_id = message_data.get("chat_id")
        content = message_data.get("content", "").strip()
        reply_to_id = message_data.get("reply_to_id")
        
        if not content:
            return
        
        # Проверяем доступ к чату
        if chat_type == "group":
            # Проверяем членство в группе
            membership = db.query(GroupMember).filter(
                GroupMember.group_id == chat_id,
                GroupMember.user_id == sender_id
            ).first()
            if not membership:
                return
        elif chat_type == "channel":
            # Проверяем подписку на канал
            subscription = db.query(Subscription).filter(
                Subscription.channel_id == chat_id,
                Subscription.user_id == sender_id
            ).first()
            if not subscription:
                return
            # В каналах сообщения не имеют отправителя (анонимны)
            sender_id = None
        
        # Сохраняем в базу
        db_message = Message(
            from_user_id=sender_id if chat_type != "channel" else None,
            to_user_id=chat_id if chat_type == "private" else None,
            group_id=chat_id if chat_type == "group" else None,
            channel_id=chat_id if chat_type == "channel" else None,
            content=content,
            message_type=MessageType.TEXT.value,
            reply_to_id=reply_to_id
        )
        
        db.add(db_message)
        db.commit()
        db.refresh(db_message)
        
        # Обновляем активность чата
        if chat_type == "group":
            group = db.query(Group).filter(Group.id == chat_id).first()
            if group:
                group.last_activity = datetime.utcnow()
                db.commit()
        elif chat_type == "channel":
            channel = db.query(Channel).filter(Channel.id == chat_id).first()
            if channel:
                channel.last_activity = datetime.utcnow()
                db.commit()
        
        # Отправляем получателям
        if chat_type == "private":
            await manager.send_personal_message(
                json.dumps({
                    "type": "message",
                    "chat_type": "private",
                    "id": db_message.id,
                    "from_user_id": sender_id,
                    "to_user_id": chat_id,
                    "content": content,
                    "reply_to_id": reply_to_id,
                    "timestamp": db_message.created_at.isoformat()
                }),
                chat_id
            )
        elif chat_type == "group":
            members = db.query(GroupMember).filter(GroupMember.group_id == chat_id).all()
            for member in members:
                if member.user_id != sender_id:
                    await manager.send_personal_message(
                        json.dumps({
                            "type": "message",
                            "chat_type": "group",
                            "id": db_message.id,
                            "group_id": chat_id,
                            "from_user_id": sender_id,
                            "content": content,
                            "reply_to_id": reply_to_id,
                            "timestamp": db_message.created_at.isoformat()
                        }),
                        member.user_id
                    )
        elif chat_type == "channel":
            subscribers = db.query(Subscription).filter(Subscription.channel_id == chat_id).all()
            for subscriber in subscribers:
                await manager.send_personal_message(
                    json.dumps({
                        "type": "message",
                        "chat_type": "channel",
                        "id": db_message.id,
                        "channel_id": chat_id,
                        "content": content,
                        "reply_to_id": reply_to_id,
                        "timestamp": db_message.created_at.isoformat()
                    }),
                    subscriber.user_id
                )
        
        # Подтверждение отправителю
        if sender_id:
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

async def handle_media_message(message_data: dict, sender_id: int):
    """Обработка медиа сообщений"""
    await handle_text_message(message_data, sender_id)

async def handle_typing_indicator(message_data: dict, sender_id: int):
    """Обработка индикатора набора текста"""
    chat_type = message_data.get("chat_type", "private")
    chat_id = message_data.get("chat_id")
    is_typing = message_data.get("is_typing", False)
    
    if chat_type == "private":
        await manager.send_personal_message(
            json.dumps({
                "type": "typing",
                "chat_type": "private",
                "from_user_id": sender_id,
                "is_typing": is_typing
            }),
            chat_id
        )
    elif chat_type == "group":
        db = SessionLocal()
        try:
            members = db.query(GroupMember).filter(GroupMember.group_id == chat_id).all()
            for member in members:
                if member.user_id != sender_id:
                    await manager.send_personal_message(
                        json.dumps({
                            "type": "typing",
                            "chat_type": "group",
                            "group_id": chat_id,
                            "from_user_id": sender_id,
                            "is_typing": is_typing
                        }),
                        member.user_id
                    )
        finally:
            db.close()
    elif chat_type == "channel":
        # В каналах индикаторы набора не отображаются
        pass

async def handle_read_receipt(message_data: dict, user_id: int):
    """Обработка подтверждения прочтения"""
    message_id = message_data.get("message_id")
    
    db = SessionLocal()
    try:
        message = db.query(Message).filter(Message.id == message_id).first()
        if message:
            # Увеличиваем счетчик просмотров
            message.views_count += 1
            db.commit()
    finally:
        db.close()

async def handle_call_message(message_data: dict, user_id: int):
    """Обработка сообщений о звонках"""
    call_type = message_data.get("call_type", "offer")
    target_id = message_data.get("target_id")
    
    await manager.send_personal_message(
        json.dumps({
            "type": "call",
            "call_type": call_type,
            "from_user_id": user_id,
            "data": message_data.get("data")
        }),
        target_id
    )

# ========== СТАТИЧЕСКИЕ ФАЙЛЫ ==========

@app.get("/index.html")
async def serve_index():
    """Главная страница"""
    index_path = frontend_dir / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return HTMLResponse("Главная страница не найдена")

@app.get("/chat")
async def serve_chat():
    """Страница чата"""
    chat_path = frontend_dir / "chat.html"
    if chat_path.exists():
        return FileResponse(str(chat_path))
    return HTMLResponse("Страница чата не найдена")

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
