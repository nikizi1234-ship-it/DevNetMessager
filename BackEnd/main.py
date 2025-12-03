from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, status, Form, Request, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
import json
from datetime import datetime, timedelta
from pathlib import Path
import uvicorn 
import os
import shutil
import uuid
from typing import List, Optional

from websocket_manager import manager
from database import engine, SessionLocal, get_db
from models import Base, User, Message, Chat, ChatMember, StickerPack, Sticker, File as FileModel, Channel, Group
from auth import create_access_token, verify_token, ACCESS_TOKEN_EXPIRE_MINUTES, verify_password, get_password_hash

# Создаем таблицы
Base.metadata.create_all(bind=engine)

app = FastAPI(title="DevNet Messenger")

# CORS для фронтенда
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Создаем директории для загрузок
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)
(UPLOAD_DIR / "images").mkdir(exist_ok=True)
(UPLOAD_DIR / "stickers").mkdir(exist_ok=True)
(UPLOAD_DIR / "files").mkdir(exist_ok=True)

# Получаем абсолютный путь к frontend
current_dir = Path(__file__).parent
frontend_dir = current_dir.parent / "frontend"

print(f"📁 Frontend directory: {frontend_dir}")

# Функция для создания тестовых данных при запуске
def create_initial_data():
    db = SessionLocal()
    try:
        # Проверяем есть ли уже пользователи
        existing_users = db.query(User).count()
        if existing_users == 0:
            print("👥 Создаем тестовых пользователей...")
            
            test_users = [
                User(
                    username="user1",
                    email="user1@example.com",
                    display_name="User One",
                    password_hash=get_password_hash("password123"),
                    is_online=False
                ),
                User(
                    username="user2", 
                    email="user2@example.com",
                    display_name="User Two", 
                    password_hash=get_password_hash("password123"),
                    is_online=False
                ),
                User(
                    username="user3",
                    email="user3@example.com",
                    display_name="User Three",
                    password_hash=get_password_hash("password123"),
                    is_online=False
                ),
                User(
                    username="alice",
                    email="alice@example.com",
                    display_name="Alice Smith",
                    password_hash=get_password_hash("password123"),
                    is_online=False
                ),
                User(
                    username="bob",
                    email="bob@example.com",
                    display_name="Bob Johnson",
                    password_hash=get_password_hash("password123"),
                    is_online=False
                )
            ]
            
            for user in test_users:
                db.add(user)
            
            db.commit()
            print("✅ Тестовые пользователи созданы!")
            
            # Создаем тестовые группы
            print("👥 Создаем тестовые группы...")
            
            # Получаем ID пользователей
            users = db.query(User).all()
            
            # Создаем группу
            group = Group(
                name="DevNet Team",
                description="Команда разработчиков",
                created_by=users[0].id,
                is_public=True
            )
            db.add(group)
            db.commit()
            db.refresh(group)
            
            # Добавляем участников в группу
            for i, user in enumerate(users[:3]):
                chat_member = ChatMember(
                    chat_id=group.id,
                    user_id=user.id,
                    role="admin" if i == 0 else "member"
                )
                db.add(chat_member)
            
            # Создаем канал
            channel = Channel(
                name="Tech News",
                description="Последние новости технологий",
                created_by=users[0].id,
                is_public=True
            )
            db.add(channel)
            db.commit()
            db.refresh(channel)
            
            # Добавляем создателя в канал
            chat_member = ChatMember(
                chat_id=channel.id,
                user_id=users[0].id,
                role="admin"
            )
            db.add(chat_member)
            
            # Создаем приватную группу
            private_group = Group(
                name="Secret Project",
                description="Секретный проект разработки",
                created_by=users[1].id,
                is_public=False,
                invite_link=str(uuid.uuid4())[:8]
            )
            db.add(private_group)
            db.commit()
            db.refresh(private_group)
            
            # Добавляем участников в приватную группу
            for user in users[1:4]:
                chat_member = ChatMember(
                    chat_id=private_group.id,
                    user_id=user.id,
                    role="member"
                )
                db.add(chat_member)
            
            # Создаем тестовые стикерпаки
            print("🎨 Создаем тестовые стикерпаки...")
            
            sticker_packs = [
                StickerPack(
                    name="Cute Animals",
                    publisher="DevNet",
                    is_animated=False,
                    is_free=True
                ),
                StickerPack(
                    name="Tech Memes",
                    publisher="DevNet",
                    is_animated=False,
                    is_free=True
                ),
                StickerPack(
                    name="Animated Emojis",
                    publisher="DevNet",
                    is_animated=True,
                    is_free=True
                )
            ]
            
            for pack in sticker_packs:
                db.add(pack)
            
            db.commit()
            print("✅ Тестовые данные созданы!")
            
        else:
            print(f"✅ В базе уже есть {existing_users} пользователей")
            
    except Exception as e:
        print(f"❌ Ошибка создания данных: {e}")
        db.rollback()
    finally:
        db.close()

# Создаем данные при запуске
create_initial_data()

# Получение текущего пользователя из токена
async def get_current_user(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("access_token")
    if not token:
        return None
    
    payload = verify_token(token)
    if not payload:
        return None
    
    user_id = payload.get("user_id")
    user = db.query(User).filter(User.id == user_id).first()
    return user

# API для автоматического создания/получения аккаунта
@app.post("/api/auto-login")
async def auto_login(
    request: Request,
    db: Session = Depends(get_db)
):
    """Автоматически создает или возвращает аккаунт"""
    try:
        # Проверяем, есть ли уже пользователь в куках
        token = request.cookies.get("access_token")
        if token:
            payload = verify_token(token)
            if payload:
                user_id = payload.get("user_id")
                user = db.query(User).filter(User.id == user_id).first()
                if user:
                    return JSONResponse({
                        "success": True,
                        "user": {
                            "id": user.id,
                            "username": user.username,
                            "display_name": user.display_name
                        },
                        "message": "Пользователь уже авторизован"
                    })
        
        # Создаем нового пользователя (гостя)
        import random
        adjectives = ["Cool", "Fast", "Smart", "Quick", "Bright", "Clever", "Sharp", "Wise"]
        nouns = ["Fox", "Wolf", "Eagle", "Tiger", "Lion", "Bear", "Hawk", "Falcon"]
        
        username = f"{random.choice(adjectives)}_{random.choice(nouns)}_{random.randint(100, 999)}"
        display_name = f"Гость {random.randint(1000, 9999)}"
        email = f"{username}@temp.devnet.com"
        
        # Проверяем уникальность username
        existing = db.query(User).filter(User.username == username).first()
        if existing:
            username = f"{username}_{random.randint(100, 999)}"
        
        user = User(
            username=username,
            email=email,
            display_name=display_name,
            password_hash=get_password_hash(str(uuid.uuid4())),  # Случайный пароль
            is_online=True,
            is_guest=True
        )
        
        db.add(user)
        db.commit()
        db.refresh(user)
        
        # Создаем токен
        access_token_expires = timedelta(days=7)  # Гостевой токен на 7 дней
        access_token = create_access_token(
            data={"sub": user.username, "user_id": user.id, "is_guest": True},
            expires_delta=access_token_expires
        )
        
        response = JSONResponse({
            "success": True,
            "user": {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "is_guest": user.is_guest
            },
            "message": "Гостевой аккаунт создан"
        })
        
        # Устанавливаем токен в cookie
        response.set_cookie(
            key="access_token",
            value=access_token,
            httponly=True,
            max_age=7 * 24 * 60 * 60,  # 7 дней
            secure=request.url.scheme == "https",
            samesite="lax"
        )
        
        return response
        
    except Exception as e:
        print(f"❌ Ошибка автоматического входа: {e}")
        return JSONResponse(
            status_code=500,
            content={"detail": f"Ошибка создания аккаунта: {str(e)}"}
        )

# Регистрация пользователя
@app.post("/api/register")
async def register(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    display_name: str = Form(None),
    db: Session = Depends(get_db)
):
    try:
        print(f"🔧 Регистрация пользователя: {username}")
        
        # Проверяем, существует ли пользователь
        existing_user = db.query(User).filter(
            (User.username == username) | (User.email == email)
        ).first()
        
        if existing_user:
            return JSONResponse(
                status_code=400,
                content={"detail": "Пользователь с таким именем или email уже существует"}
            )
        
        # Создаем нового пользователя
        db_user = User(
            username=username,
            email=email,
            display_name=display_name or username,
            password_hash=get_password_hash(password),
            is_online=False,
            is_guest=False
        )
        
        db.add(db_user)
        db.commit()
        db.refresh(db_user)
        
        # Создаем токен
        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={"sub": db_user.username, "user_id": db_user.id, "is_guest": False},
            expires_delta=access_token_expires
        )
        
        print(f"✅ Пользователь {username} успешно зарегистрирован!")
        
        response = JSONResponse({
            "success": True,
            "user": {
                "id": db_user.id,
                "username": db_user.username,
                "display_name": db_user.display_name,
                "is_guest": db_user.is_guest
            },
            "message": "Регистрация успешна!"
        })
        
        # Устанавливаем токен в cookie
        response.set_cookie(
            key="access_token",
            value=access_token,
            httponly=True,
            max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            secure=request.url.scheme == "https",
            samesite="lax"
        )
        
        return response
        
    except Exception as e:
        print(f"❌ Ошибка регистрации: {e}")
        return JSONResponse(
            status_code=500,
            content={"detail": f"Ошибка сервера: {str(e)}"}
        )

# Авторизация пользователя
@app.post("/api/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    try:
        print(f"🔧 Попытка входа: {username}")
        
        user = db.query(User).filter(User.username == username).first()
        
        if not user or not verify_password(password, user.password_hash):
            return JSONResponse(
                status_code=401,
                content={"detail": "Неверное имя пользователя или пароль"}
            )
        
        # Обновляем время последнего входа
        user.last_login = datetime.utcnow()
        user.is_online = True
        user.is_guest = False  # Если был гостем, теперь полноценный пользователь
        db.commit()
        
        # Создаем токен
        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={"sub": user.username, "user_id": user.id, "is_guest": False},
            expires_delta=access_token_expires
        )
        
        print(f"✅ Пользователь {username} вошел в систему!")
        
        response = JSONResponse({
            "success": True,
            "user": {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "is_guest": user.is_guest
            },
            "message": "Вход выполнен успешно!"
        })
        
        # Устанавливаем токен в cookie
        response.set_cookie(
            key="access_token",
            value=access_token,
            httponly=True,
            max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            secure=request.url.scheme == "https",
            samesite="lax"
        )
        
        return response
        
    except Exception as e:
        print(f"❌ Ошибка входа: {e}")
        return JSONResponse(
            status_code=500,
            content={"detail": f"Ошибка сервера: {str(e)}"}
        )

# Получение информации о текущем пользователе
@app.get("/api/me")
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Требуется аутентификация")
    
    return {
        "id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
        "display_name": current_user.display_name,
        "is_online": current_user.is_online or False,
        "is_guest": current_user.is_guest or False,
        "last_login": current_user.last_login.isoformat() if current_user.last_login else None,
        "created_at": current_user.created_at.isoformat() if current_user.created_at else None
    }

# Получение всех пользователей
@app.get("/api/users")
async def get_all_users(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Требуется аутентификация")
    
    users = db.query(User).filter(User.id != current_user.id).all()
    
    return {
        "total_users": len(users),
        "current_user": {
            "id": current_user.id,
            "username": current_user.username
        },
        "users": [
            {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "is_online": user.is_online or False,
                "is_guest": user.is_guest or False,
                "last_login": user.last_login.isoformat() if user.last_login else None,
                "created_at": user.created_at.isoformat() if user.created_at else None
            }
            for user in users
        ]
    }

# Получение групп и каналов
@app.get("/api/chats")
async def get_chats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Требуется аутентификация")
    
    # Получаем чаты, в которых пользователь является участником
    chat_members = db.query(ChatMember).filter(ChatMember.user_id == current_user.id).all()
    chat_ids = [cm.chat_id for cm in chat_members]
    
    # Получаем информацию о чатах
    chats = []
    for chat_id in chat_ids:
        # Проверяем тип чата
        group = db.query(Group).filter(Group.id == chat_id).first()
        if group:
            chats.append({
                "id": group.id,
                "name": group.name,
                "description": group.description,
                "type": "group",
                "is_public": group.is_public,
                "members_count": db.query(ChatMember).filter(ChatMember.chat_id == group.id).count(),
                "created_at": group.created_at.isoformat() if group.created_at else None
            })
            continue
            
        channel = db.query(Channel).filter(Channel.id == chat_id).first()
        if channel:
            chats.append({
                "id": channel.id,
                "name": channel.name,
                "description": channel.description,
                "type": "channel",
                "is_public": channel.is_public,
                "members_count": db.query(ChatMember).filter(ChatMember.chat_id == channel.id).count(),
                "created_at": channel.created_at.isoformat() if channel.created_at else None
            })
            continue
    
    # Получаем приватные чаты с пользователями
    private_chats = []
    all_users = db.query(User).filter(User.id != current_user.id).all()
    for user in all_users:
        # Проверяем, есть ли сообщения между пользователями
        messages_count = db.query(Message).filter(
            or_(
                and_(Message.from_user_id == current_user.id, Message.to_user_id == user.id),
                and_(Message.from_user_id == user.id, Message.to_user_id == current_user.id)
            )
        ).count()
        
        if messages_count > 0:
            private_chats.append({
                "id": user.id,
                "name": user.display_name,
                "type": "private",
                "username": user.username,
                "is_online": user.is_online,
                "last_login": user.last_login.isoformat() if user.last_login else None
            })
    
    return {
        "groups": [chat for chat in chats if chat["type"] == "group"],
        "channels": [chat for chat in chats if chat["type"] == "channel"],
        "private_chats": private_chats
    }

# Создание группы
@app.post("/api/groups")
async def create_group(
    name: str = Form(...),
    description: str = Form(None),
    is_public: bool = Form(True),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Требуется аутентификация")
    
    try:
        group = Group(
            name=name,
            description=description,
            created_by=current_user.id,
            is_public=is_public,
            invite_link=str(uuid.uuid4())[:8] if not is_public else None
        )
        
        db.add(group)
        db.commit()
        db.refresh(group)
        
        # Добавляем создателя как администратора
        chat_member = ChatMember(
            chat_id=group.id,
            user_id=current_user.id,
            role="admin"
        )
        db.add(chat_member)
        db.commit()
        
        return {
            "success": True,
            "group": {
                "id": group.id,
                "name": group.name,
                "description": group.description,
                "invite_link": group.invite_link
            },
            "message": "Группа создана успешно"
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Ошибка создания группы: {str(e)}")

# Создание канала
@app.post("/api/channels")
async def create_channel(
    name: str = Form(...),
    description: str = Form(None),
    is_public: bool = Form(True),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Требуется аутентификация")
    
    try:
        channel = Channel(
            name=name,
            description=description,
            created_by=current_user.id,
            is_public=is_public
        )
        
        db.add(channel)
        db.commit()
        db.refresh(channel)
        
        # Добавляем создателя как администратора
        chat_member = ChatMember(
            chat_id=channel.id,
            user_id=current_user.id,
            role="admin"
        )
        db.add(chat_member)
        db.commit()
        
        return {
            "success": True,
            "channel": {
                "id": channel.id,
                "name": channel.name,
                "description": channel.description
            },
            "message": "Канал создан успешно"
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Ошибка создания канала: {str(e)}")

# Получение стикерпаков
@app.get("/api/stickers")
async def get_sticker_packs(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Требуется аутентификация")
    
    sticker_packs = db.query(StickerPack).all()
    
    return {
        "packs": [
            {
                "id": pack.id,
                "name": pack.name,
                "publisher": pack.publisher,
                "is_animated": pack.is_animated,
                "is_free": pack.is_free,
                "cover_url": pack.cover_url,
                "stickers": [
                    {
                        "id": sticker.id,
                        "emoji": sticker.emoji,
                        "url": sticker.url,
                        "width": sticker.width,
                        "height": sticker.height
                    }
                    for sticker in pack.stickers
                ] if hasattr(pack, 'stickers') else []
            }
            for pack in sticker_packs
        ]
    }

# Загрузка файлов (изображений, документов)
@app.post("/api/upload")
async def upload_file(
    file: UploadFile = File(...),
    file_type: str = Form("image"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Требуется аутентификация")
    
    try:
        # Генерируем уникальное имя файла
        file_extension = file.filename.split('.')[-1] if '.' in file.filename else ''
        unique_filename = f"{uuid.uuid4()}.{file_extension}"
        
        # Определяем путь для сохранения
        if file_type == "sticker":
            save_path = UPLOAD_DIR / "stickers" / unique_filename
        elif file_type == "image":
            save_path = UPLOAD_DIR / "images" / unique_filename
        else:
            save_path = UPLOAD_DIR / "files" / unique_filename
        
        # Сохраняем файл
        with open(save_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # Сохраняем информацию в базе данных
        db_file = FileModel(
            filename=unique_filename,
            original_filename=file.filename,
            file_type=file_type,
            file_size=os.path.getsize(save_path),
            uploaded_by=current_user.id,
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
        raise HTTPException(status_code=500, detail=f"Ошибка загрузки файла: {str(e)}")

# WebSocket endpoint
@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: int):
    await manager.connect(websocket, user_id)
    
    # Обновляем статус пользователя как онлайн
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            user.is_online = True
            user.last_login = datetime.utcnow()
            db.commit()
            print(f"✅ Пользователь {user.username} подключен (ID: {user_id})")
    except Exception as e:
        print(f"❌ Ошибка обновления статуса: {e}")
    finally:
        db.close()
    
    try:
        while True:
            data = await websocket.receive_text()
            message_data = json.loads(data)
            message_type = message_data.get("type", "message")
            
            # Обработка различных типов сообщений
            if message_type == "message":
                await handle_text_message(message_data, user_id)
            elif message_type == "sticker":
                await handle_sticker_message(message_data, user_id)
            elif message_type == "image":
                await handle_image_message(message_data, user_id)
            elif message_type == "group_message":
                await handle_group_message(message_data, user_id)
            elif message_type == "channel_message":
                await handle_channel_message(message_data, user_id)
            elif message_type == "typing":
                await handle_typing_indicator(message_data, user_id)
            elif message_type == "read_receipt":
                await handle_read_receipt(message_data, user_id)
                
    except WebSocketDisconnect:
        # Обновляем статус пользователя как офлайн при отключении
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if user:
                user.is_online = False
                db.commit()
                print(f"✅ Пользователь {user.username} отключен (ID: {user_id})")
        except Exception as e:
            print(f"❌ Ошибка обновления статуса: {e}")
        finally:
            db.close()
        
        manager.disconnect(user_id)

async def handle_text_message(message_data, sender_id):
    """Обработка текстовых сообщений"""
    db = SessionLocal()
    try:
        receiver_id = message_data.get("to_user_id")
        chat_id = message_data.get("chat_id")
        content = message_data.get("content", "")
        
        if not content.strip():
            return
        
        db_message = Message(
            from_user_id=sender_id,
            to_user_id=receiver_id,
            chat_id=chat_id,
            content=content,
            message_type="text"
        )
        
        db.add(db_message)
        db.commit()
        db.refresh(db_message)
        
        # Отправляем получателю если он онлайн
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
        
        # Отправляем в группу/канал если есть chat_id
        elif chat_id:
            members = db.query(ChatMember).filter(ChatMember.chat_id == chat_id).all()
            for member in members:
                if member.user_id != sender_id:  # Не отправляем отправителю
                    await manager.send_personal_message(
                        json.dumps({
                            "type": "group_message",
                            "id": db_message.id,
                            "chat_id": chat_id,
                            "from_user_id": sender_id,
                            "content": content,
                            "timestamp": db_message.created_at.isoformat()
                        }),
                        member.user_id
                    )
        
        # Подтверждение отправки отправителю
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
        print(f"❌ Database error: {e}")
    finally:
        db.close()

async def handle_sticker_message(message_data, sender_id):
    """Обработка стикеров"""
    db = SessionLocal()
    try:
        receiver_id = message_data.get("to_user_id")
        chat_id = message_data.get("chat_id")
        sticker_id = message_data.get("sticker_id")
        
        db_message = Message(
            from_user_id=sender_id,
            to_user_id=receiver_id,
            chat_id=chat_id,
            content="",  # Для стикеров контент пустой
            message_type="sticker",
            sticker_id=sticker_id
        )
        
        db.add(db_message)
        db.commit()
        db.refresh(db_message)
        
        # Получаем информацию о стикере
        sticker = db.query(Sticker).filter(Sticker.id == sticker_id).first()
        
        if receiver_id:
            await manager.send_personal_message(
                json.dumps({
                    "type": "sticker",
                    "id": db_message.id,
                    "from_user_id": sender_id,
                    "to_user_id": receiver_id,
                    "sticker": {
                        "id": sticker.id,
                        "url": sticker.url,
                        "emoji": sticker.emoji
                    },
                    "timestamp": db_message.created_at.isoformat()
                }),
                receiver_id
            )
        elif chat_id:
            members = db.query(ChatMember).filter(ChatMember.chat_id == chat_id).all()
            for member in members:
                if member.user_id != sender_id:
                    await manager.send_personal_message(
                        json.dumps({
                            "type": "sticker",
                            "id": db_message.id,
                            "chat_id": chat_id,
                            "from_user_id": sender_id,
                            "sticker": {
                                "id": sticker.id,
                                "url": sticker.url,
                                "emoji": sticker.emoji
                            },
                            "timestamp": db_message.created_at.isoformat()
                        }),
                        member.user_id
                    )
        
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
        print(f"❌ Sticker error: {e}")
    finally:
        db.close()

async def handle_image_message(message_data, sender_id):
    """Обработка изображений"""
    db = SessionLocal()
    try:
        receiver_id = message_data.get("to_user_id")
        chat_id = message_data.get("chat_id")
        image_url = message_data.get("image_url")
        caption = message_data.get("caption", "")
        
        db_message = Message(
            from_user_id=sender_id,
            to_user_id=receiver_id,
            chat_id=chat_id,
            content=caption,
            message_type="image",
            file_url=image_url
        )
        
        db.add(db_message)
        db.commit()
        db.refresh(db_message)
        
        if receiver_id:
            await manager.send_personal_message(
                json.dumps({
                    "type": "image",
                    "id": db_message.id,
                    "from_user_id": sender_id,
                    "to_user_id": receiver_id,
                    "image_url": image_url,
                    "caption": caption,
                    "timestamp": db_message.created_at.isoformat()
                }),
                receiver_id
            )
        elif chat_id:
            members = db.query(ChatMember).filter(ChatMember.chat_id == chat_id).all()
            for member in members:
                if member.user_id != sender_id:
                    await manager.send_personal_message(
                        json.dumps({
                            "type": "image",
                            "id": db_message.id,
                            "chat_id": chat_id,
                            "from_user_id": sender_id,
                            "image_url": image_url,
                            "caption": caption,
                            "timestamp": db_message.created_at.isoformat()
                        }),
                        member.user_id
                    )
        
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
        print(f"❌ Image error: {e}")
    finally:
        db.close()

async def handle_group_message(message_data, sender_id):
    """Обработка сообщений в группах"""
    await handle_text_message(message_data, sender_id)

async def handle_channel_message(message_data, sender_id):
    """Обработка сообщений в каналах"""
    await handle_text_message(message_data, sender_id)

async def handle_typing_indicator(message_data, sender_id):
    """Обработка индикатора набора текста"""
    receiver_id = message_data.get("to_user_id")
    chat_id = message_data.get("chat_id")
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
    elif chat_id:
        members = db.query(ChatMember).filter(ChatMember.chat_id == chat_id).all()
        for member in members:
            if member.user_id != sender_id:
                await manager.send_personal_message(
                    json.dumps({
                        "type": "typing",
                        "chat_id": chat_id,
                        "from_user_id": sender_id,
                        "is_typing": is_typing
                    }),
                    member.user_id
                )

async def handle_read_receipt(message_data, sender_id):
    """Обработка подтверждения прочтения"""
    message_id = message_data.get("message_id")
    
    db = SessionLocal()
    try:
        message = db.query(Message).filter(Message.id == message_id).first()
        if message:
            message.read_at = datetime.utcnow()
            db.commit()
            
            # Отправляем отправителю, что его сообщение прочитано
            await manager.send_personal_message(
                json.dumps({
                    "type": "read_receipt",
                    "message_id": message_id,
                    "read_at": datetime.utcnow().isoformat()
                }),
                message.from_user_id
            )
    except Exception as e:
        print(f"❌ Read receipt error: {e}")
    finally:
        db.close()

# API для получения истории сообщений
@app.get("/api/messages")
async def get_message_history(
    chat_id: Optional[int] = None,
    user_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Требуется аутентификация")
    
    try:
        if chat_id:
            # Получаем сообщения из чата (группы/канала)
            messages = db.query(Message).filter(Message.chat_id == chat_id).order_by(Message.created_at.asc()).all()
        elif user_id:
            # Получаем приватные сообщения между пользователями
            messages = db.query(Message).filter(
                or_(
                    and_(Message.from_user_id == current_user.id, Message.to_user_id == user_id),
                    and_(Message.from_user_id == user_id, Message.to_user_id == current_user.id)
                )
            ).order_by(Message.created_at.asc()).all()
        else:
            return JSONResponse(
                status_code=400,
                content={"detail": "Необходимо указать chat_id или user_id"}
            )
        
        formatted_messages = []
        for msg in messages:
            message_data = {
                "id": msg.id,
                "from_user_id": msg.from_user_id,
                "to_user_id": msg.to_user_id,
                "chat_id": msg.chat_id,
                "content": msg.content,
                "type": msg.message_type,
                "timestamp": msg.created_at.isoformat(),
                "read_at": msg.read_at.isoformat() if msg.read_at else None,
                "is_my_message": msg.from_user_id == current_user.id
            }
            
            # Добавляем дополнительную информацию в зависимости от типа сообщения
            if msg.message_type == "sticker" and msg.sticker_id:
                sticker = db.query(Sticker).filter(Sticker.id == msg.sticker_id).first()
                if sticker:
                    message_data["sticker"] = {
                        "id": sticker.id,
                        "url": sticker.url,
                        "emoji": sticker.emoji
                    }
            elif msg.message_type == "image" and msg.file_url:
                message_data["image_url"] = msg.file_url
            
            formatted_messages.append(message_data)
        
        print(f"📨 Загружено {len(messages)} сообщений")
        return formatted_messages
        
    except Exception as e:
        print(f"❌ Ошибка загрузки сообщений: {e}")
        return JSONResponse(
            status_code=500,
            content={"detail": f"Ошибка загрузки истории сообщений: {str(e)}"}
        )

# Статические файлы для загруженных файлов
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

# Статические файлы фронтенда
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")
    print("✅ Static files mounted successfully")

@app.get("/")
async def read_index():
    return FileResponse(str(frontend_dir / "index.html"))

@app.get("/chat")
async def read_chat():
    return FileResponse(str(frontend_dir / "chat.html"))

# Health check endpoint
@app.get("/health")
async def health_check():
    return {
        "status": "healthy", 
        "service": "DevNet Messenger",
        "timestamp": datetime.utcnow().isoformat()
    }

# Для production на Railway
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=False
    )
    )
