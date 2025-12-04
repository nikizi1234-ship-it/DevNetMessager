from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, status, Form, Request, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
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

# Добавляем путь для импорта модулей
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from websocket_manager import manager
    from database import engine, SessionLocal, get_db
    from models import Base, User, Message, Group, GroupMember, File as FileModel
    from auth import create_access_token, verify_token, ACCESS_TOKEN_EXPIRE_MINUTES, verify_password, get_password_hash
    print("✅ All modules imported successfully")
except ImportError as e:
    print(f"❌ Import error: {e}")
    raise

# ========== ИНИЦИАЛИЗАЦИЯ ==========

# Создаем таблицы в базе данных
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="DevNet Messenger",
    description="Современный мессенджер с поддержкой групп, изображений и WebSocket",
    version="2.0.0"
)

# Настройка CORS для фронтенда
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Разрешаем все источники (для разработки)
    allow_methods=["*"],  # Разрешаем все методы
    allow_headers=["*"],  # Разрешаем все заголовки
    allow_credentials=True,
)

# Создаем директории для загрузок
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)
(UPLOAD_DIR / "images").mkdir(exist_ok=True)
(UPLOAD_DIR / "files").mkdir(exist_ok=True)

print(f"📁 Upload directories created at: {UPLOAD_DIR}")

# Получаем абсолютный путь к фронтенду
current_dir = Path(__file__).parent
project_root = current_dir.parent
frontend_dir = project_root / "frontend"

print(f"📁 Project root: {project_root}")
print(f"📁 Frontend directory: {frontend_dir}")

# Проверяем существование фронтенда
if frontend_dir.exists():
    print(f"✅ Frontend found: {frontend_dir}")
    print(f"📁 Files in frontend: {os.listdir(frontend_dir)}")
    
    # Монтируем статические файлы
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")
    print("✅ Static files mounted")
else:
    print(f"⚠️  Frontend not found at: {frontend_dir}")

# Монтируем директорию загрузок
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

# ========== ФУНКЦИИ ДЛЯ СОЗДАНИЯ ТЕСТОВЫХ ДАННЫХ ==========

def create_initial_data():
    """Создает тестовые данные при первом запуске"""
    db = SessionLocal()
    try:
        # Проверяем есть ли уже пользователи
        existing_users = db.query(User).count()
        
        if existing_users == 0:
            print("👥 Creating initial test users...")
            
            test_users = [
                User(
                    username="user1",
                    email="user1@example.com",
                    display_name="Alice Johnson",
                    password_hash=get_password_hash("password123"),
                    is_online=False,
                    is_guest=False
                ),
                User(
                    username="user2", 
                    email="user2@example.com",
                    display_name="Bob Smith", 
                    password_hash=get_password_hash("password123"),
                    is_online=False,
                    is_guest=False
                ),
                User(
                    username="user3",
                    email="user3@example.com",
                    display_name="Charlie Brown",
                    password_hash=get_password_hash("password123"),
                    is_online=False,
                    is_guest=False
                ),
                User(
                    username="eva",
                    email="eva@example.com",
                    display_name="Eva Davis",
                    password_hash=get_password_hash("password123"),
                    is_online=False,
                    is_guest=False
                ),
                User(
                    username="david",
                    email="david@example.com",
                    display_name="David Wilson",
                    password_hash=get_password_hash("password123"),
                    is_online=False,
                    is_guest=False
                )
            ]
            
            for user in test_users:
                db.add(user)
            
            db.commit()
            print("✅ Test users created successfully!")
            
            # Создаем тестовую группу
            print("👥 Creating test group...")
            
            group = Group(
                name="DevNet Team",
                description="Команда разработчиков DevNet Messenger",
                created_by=1
            )
            db.add(group)
            db.commit()
            db.refresh(group)
            
            # Добавляем пользователей в группу
            for user_id in [1, 2, 3]:
                group_member = GroupMember(
                    group_id=group.id,
                    user_id=user_id
                )
                db.add(group_member)
            
            db.commit()
            print("✅ Test group created!")
            
            # Создаем тестовые сообщения
            print("💬 Creating test messages...")
            
            test_messages = [
                Message(
                    from_user_id=1,
                    to_user_id=2,
                    content="Привет! Как дела?",
                    message_type="text"
                ),
                Message(
                    from_user_id=2,
                    to_user_id=1,
                    content="Привет! Все отлично, работаю над проектом.",
                    message_type="text"
                ),
                Message(
                    from_user_id=1,
                    to_user_id=2,
                    content="Супер! Какой проект?",
                    message_type="text"
                ),
                Message(
                    from_user_id=2,
                    to_user_id=1,
                    content="Разрабатываю мессенджер на FastAPI и WebSocket!",
                    message_type="text"
                )
            ]
            
            for message in test_messages:
                db.add(message)
            
            db.commit()
            print("✅ Test messages created!")
            
        else:
            print(f"✅ Database already has {existing_users} users")
            
    except Exception as e:
        print(f"❌ Error creating initial data: {e}")
        db.rollback()
    finally:
        db.close()

# Создаем данные при запуске
create_initial_data()

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
    user = db.query(User).filter(User.id == user_id).first()
    return user

def generate_guest_username() -> str:
    """Генерирует уникальное имя для гостя"""
    adjectives = ["Быстрый", "Умный", "Яркий", "Смелый", "Ловкий", "Храбрый", "Мудрый", "Сильный"]
    nouns = ["Тигр", "Орел", "Волк", "Лев", "Медведь", "Сокол", "Ястреб", "Феникс"]
    
    adjective = random.choice(adjectives)
    noun = random.choice(nouns)
    number = random.randint(100, 999)
    
    return f"{adjective}_{noun}_{number}"

# ========== API ENDPOINTS ==========

# ========== АУТЕНТИФИКАЦИЯ ==========

@app.post("/api/auto-login")
async def auto_login(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Автоматически создает гостевой аккаунт или возвращает существующий
    
    Эта функция:
    1. Проверяет, есть ли у пользователя валидный токен
    2. Если есть - возвращает информацию о пользователе
    3. Если нет - создает нового гостевого пользователя
    4. Устанавливает токен в cookies
    """
    try:
        print("🔧 Auto-login attempt")
        
        # Проверяем, есть ли уже валидный токен
        token = request.cookies.get("access_token")
        if token:
            payload = verify_token(token)
            if payload:
                user_id = payload.get("user_id")
                user = db.query(User).filter(User.id == user_id).first()
                if user:
                    print(f"✅ Returning existing user: {user.username}")
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
        
        # Создаем нового гостевого пользователя
        username = generate_guest_username()
        display_name = f"Гость {random.randint(1000, 9999)}"
        email = f"{username}@guest.devnet.com"
        
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
            is_guest=True  # Помечаем как гостя
        )
        
        db.add(user)
        db.commit()
        db.refresh(user)
        
        print(f"✅ New guest user created: {user.username}")
        
        # Создаем токен на 7 дней
        access_token_expires = timedelta(days=7)
        access_token = create_access_token(
            data={
                "sub": user.username,
                "user_id": user.id,
                "is_guest": True,
                "exp": datetime.utcnow() + access_token_expires
            }
        )
        
        response_data = {
            "success": True,
            "user": {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "is_guest": user.is_guest
            },
            "message": "Гостевой аккаунт создан"
        }
        
        response = JSONResponse(response_data)
        
        # Устанавливаем токен в cookie
        response.set_cookie(
            key="access_token",
            value=access_token,
            httponly=True,  # Защита от XSS
            max_age=7 * 24 * 60 * 60,  # 7 дней
            secure=request.url.scheme == "https",  # Только HTTPS в production
            samesite="lax"  # Защита от CSRF
        )
        
        return response
        
    except Exception as e:
        print(f"❌ Auto-login error: {e}")
        return JSONResponse(
            status_code=500,
            content={"detail": f"Ошибка создания аккаунта: {str(e)}"}
        )

@app.post("/api/register")
async def register(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    display_name: str = Form(None),
    db: Session = Depends(get_db)
):
    """Регистрация нового пользователя"""
    try:
        print(f"🔧 Registration attempt: {username}")
        
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
            is_guest=False  # Полноценный пользователь
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
        
        print(f"✅ User {username} registered successfully!")
        
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
        print(f"❌ Registration error: {e}")
        return JSONResponse(
            status_code=500,
            content={"detail": f"Ошибка сервера: {str(e)}"}
        )

@app.post("/api/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    """Вход существующего пользователя"""
    try:
        print(f"🔧 Login attempt: {username}")
        
        user = db.query(User).filter(User.username == username).first()
        
        if not user or not verify_password(password, user.password_hash):
            return JSONResponse(
                status_code=401,
                content={"detail": "Неверное имя пользователя или пароль"}
            )
        
        # Обновляем время последнего входа
        user.last_login = datetime.utcnow()
        user.is_online = True
        user.is_guest = False  # Превращаем гостя в полноценного пользователя
        db.commit()
        
        # Создаем токен
        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={"sub": user.username, "user_id": user.id, "is_guest": False},
            expires_delta=access_token_expires
        )
        
        print(f"✅ User {username} logged in!")
        
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
        print(f"❌ Login error: {e}")
        return JSONResponse(
            status_code=500,
            content={"detail": f"Ошибка сервера: {str(e)}"}
        )

@app.post("/api/logout")
async def logout(request: Request, db: Session = Depends(get_db)):
    """Выход пользователя"""
    try:
        token = request.cookies.get("access_token")
        if token:
            payload = verify_token(token)
            if payload:
                user_id = payload.get("user_id")
                user = db.query(User).filter(User.id == user_id).first()
                if user:
                    user.is_online = False
                    db.commit()
                    print(f"✅ User {user.username} logged out")
        
        response = JSONResponse({"success": True, "message": "Выход выполнен успешно"})
        response.delete_cookie("access_token")
        return response
        
    except Exception as e:
        print(f"❌ Logout error: {e}")
        return JSONResponse(
            status_code=500,
            content={"detail": f"Ошибка выхода: {str(e)}"}
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
            raise HTTPException(status_code=401, detail="Требуется аутентификация")
        
        payload = verify_token(token)
        if not payload:
            raise HTTPException(status_code=401, detail="Недействительный токен")
        
        user_id = payload.get("user_id")
        user = db.query(User).filter(User.id == user_id).first()
        
        if not user:
            raise HTTPException(status_code=401, detail="Пользователь не найден")
        
        return {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "display_name": user.display_name,
            "is_online": user.is_online or False,
            "is_guest": user.is_guest or False,
            "last_login": user.last_login.isoformat() if user.last_login else None,
            "created_at": user.created_at.isoformat() if user.created_at else None
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка сервера: {str(e)}")

# ========== ПОЛЬЗОВАТЕЛИ ==========

@app.get("/api/users")
async def get_all_users(
    request: Request,
    db: Session = Depends(get_db)
):
    """Получение списка всех пользователей"""
    try:
        token = request.cookies.get("access_token")
        if not token:
            raise HTTPException(status_code=401, detail="Требуется аутентификация")
        
        payload = verify_token(token)
        if not payload:
            raise HTTPException(status_code=401, detail="Недействительный токен")
        
        current_user_id = payload.get("user_id")
        users = db.query(User).filter(User.id != current_user_id).all()
        
        return {
            "total_users": len(users),
            "current_user_id": current_user_id,
            "users": [
                {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                    "display_name": user.display_name,
                    "is_online": user.is_online or False,
                    "is_guest": user.is_guest or False,
                    "last_login": user.last_login.isoformat() if user.last_login else None,
                    "created_at": user.created_at.isoformat() if user.created_at else None
                }
                for user in users
            ]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка сервера: {str(e)}")

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
            raise HTTPException(status_code=401, detail="Требуется аутентификация")
        
        payload = verify_token(token)
        if not payload:
            raise HTTPException(status_code=401, detail="Недействительный токен")
        
        user_id = payload.get("user_id")
        
        print(f"🔧 Creating group '{name}' by user {user_id}")
        
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
            content={"detail": f"Ошибка создания группы: {str(e)}"}
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
            raise HTTPException(status_code=401, detail="Требуется аутентификация")
        
        payload = verify_token(token)
        if not payload:
            raise HTTPException(status_code=401, detail="Недействительный токен")
        
        user_id = payload.get("user_id")
        
        # Получаем группы, в которых состоит пользователь
        groups = db.query(Group).join(GroupMember).filter(GroupMember.user_id == user_id).all()
        
        groups_data = []
        for group in groups:
            # Получаем количество участников
            members_count = db.query(GroupMember).filter(GroupMember.group_id == group.id).count()
            
            # Получаем последнее сообщение в группе
            last_message = db.query(Message).filter(Message.group_id == group.id)\
                .order_by(Message.created_at.desc()).first()
            
            groups_data.append({
                "id": group.id,
                "name": group.name,
                "description": group.description,
                "created_by": group.created_by,
                "created_at": group.created_at.isoformat() if group.created_at else None,
                "members_count": members_count,
                "last_message": {
                    "content": last_message.content if last_message else None,
                    "timestamp": last_message.created_at.isoformat() if last_message else None
                } if last_message else None
            })
        
        return {
            "groups": groups_data,
            "total_groups": len(groups_data)
        }
        
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"detail": f"Ошибка загрузки групп: {str(e)}"}
        )

@app.get("/api/chats")
async def get_all_chats(
    request: Request,
    db: Session = Depends(get_db)
):
    """Получение всех чатов пользователя (личные + группы)"""
    try:
        token = request.cookies.get("access_token")
        if not token:
            raise HTTPException(status_code=401, detail="Требуется аутентификация")
        
        payload = verify_token(token)
        if not payload:
            raise HTTPException(status_code=401, detail="Недействительный токен")
        
        current_user_id = payload.get("user_id")
        
        # Получаем личные чаты (пользователи, с которыми есть переписка)
        users_with_messages = db.query(User).filter(User.id != current_user_id).all()
        private_chats = []
        
        for user in users_with_messages:
            # Проверяем, есть ли сообщения между пользователями
            messages_count = db.query(Message).filter(
                or_(
                    and_(Message.from_user_id == current_user_id, Message.to_user_id == user.id),
                    and_(Message.from_user_id == user.id, Message.to_user_id == current_user_id)
                )
            ).count()
            
            if messages_count > 0:
                # Получаем последнее сообщение
                last_message = db.query(Message).filter(
                    or_(
                        and_(Message.from_user_id == current_user_id, Message.to_user_id == user.id),
                        and_(Message.from_user_id == user.id, Message.to_user_id == current_user_id)
                    )
                ).order_by(Message.created_at.desc()).first()
                
                private_chats.append({
                    "id": user.id,
                    "name": user.display_name,
                    "type": "private",
                    "username": user.username,
                    "is_online": user.is_online,
                    "last_login": user.last_login.isoformat() if user.last_login else None,
                    "last_message": {
                        "content": last_message.content if last_message else None,
                        "timestamp": last_message.created_at.isoformat() if last_message else None,
                        "is_my_message": last_message.from_user_id == current_user_id if last_message else None
                    } if last_message else None
                })
        
        # Получаем группы
        groups = db.query(Group).join(GroupMember).filter(GroupMember.user_id == current_user_id).all()
        group_chats = []
        
        for group in groups:
            members_count = db.query(GroupMember).filter(GroupMember.group_id == group.id).count()
            
            # Получаем последнее сообщение в группе
            last_message = db.query(Message).filter(Message.group_id == group.id)\
                .order_by(Message.created_at.desc()).first()
            
            group_chats.append({
                "id": group.id,
                "name": group.name,
                "description": group.description,
                "type": "group",
                "members_count": members_count,
                "created_at": group.created_at.isoformat() if group.created_at else None,
                "last_message": {
                    "content": last_message.content if last_message else None,
                    "timestamp": last_message.created_at.isoformat() if last_message else None
                } if last_message else None
            })
        
        return {
            "private_chats": private_chats,
            "group_chats": group_chats,
            "total_chats": len(private_chats) + len(group_chats)
        }
        
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"detail": f"Ошибка загрузки чатов: {str(e)}"}
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
        
        print(f"📨 Loaded {len(messages)} messages between users {user_id} and {other_user_id}")
        
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
        print(f"❌ Error loading messages: {e}")
        return JSONResponse(
            status_code=500,
            content={"detail": f"Ошибка загрузки истории сообщений: {str(e)}"}
        )

@app.get("/api/group-messages/{group_id}")
async def get_group_messages(
    group_id: int,
    db: Session = Depends(get_db)
):
    """Получение истории сообщений в группе"""
    try:
        messages = db.query(Message).filter(Message.group_id == group_id)\
            .order_by(Message.created_at.asc()).all()
        
        print(f"📨 Loaded {len(messages)} messages for group {group_id}")
        
        return [
            {
                "id": msg.id,
                "from_user_id": msg.from_user_id,
                "content": msg.content,
                "type": msg.message_type,
                "file_url": msg.file_url,
                "timestamp": msg.created_at.isoformat()
            }
            for msg in messages
        ]
        
    except Exception as e:
        print(f"❌ Error loading group messages: {e}")
        return JSONResponse(
            status_code=500,
            content={"detail": f"Ошибка загрузки групповых сообщений: {str(e)}"}
        )

# ========== ЗАГРУЗКА ФАЙЛОВ ==========

@app.post("/api/upload")
async def upload_file(
    file: UploadFile = File(...),
    request: Request = None,
    db: Session = Depends(get_db)
):
    """Загрузка файла (изображения или документа)"""
    try:
        # Проверяем авторизацию
        token = request.cookies.get("access_token") if request else None
        if not token:
            raise HTTPException(status_code=401, detail="Требуется аутентификация")
        
        payload = verify_token(token)
        if not payload:
            raise HTTPException(status_code=401, detail="Недействительный токен")
        
        user_id = payload.get("user_id")
        
        print(f"📤 Uploading file: {file.filename} by user {user_id}")
        
        # Определяем тип файла
        file_type = "file"
        if file.content_type.startswith("image/"):
            file_type = "image"
        elif file.content_type.startswith("video/"):
            file_type = "video"
        elif file.content_type.startswith("audio/"):
            file_type = "audio"
        
        # Проверяем размер файла (максимум 10MB)
        MAX_SIZE = 10 * 1024 * 1024  # 10MB
        file.file.seek(0, 2)  # Перемещаемся в конец файла
        file_size = file.file.tell()
        file.file.seek(0)  # Возвращаемся в начало
        
        if file_size > MAX_SIZE:
            return JSONResponse(
                status_code=400,
                content={"detail": f"Файл слишком большой. Максимальный размер: {MAX_SIZE/1024/1024}MB"}
            )
        
        # Генерируем уникальное имя файла
        file_extension = file.filename.split('.')[-1] if '.' in file.filename else ''
        unique_filename = f"{uuid.uuid4()}.{file_extension}"
        
        # Определяем путь для сохранения
        save_dir = UPLOAD_DIR / f"{file_type}s"
        save_dir.mkdir(exist_ok=True)
        save_path = save_dir / unique_filename
        
        # Сохраняем файл
        with open(save_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # Сохраняем информацию в базу данных
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
        
        print(f"✅ File uploaded successfully: {db_file.url}")
        
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
        print(f"❌ File upload error: {e}")
        return JSONResponse(
            status_code=500,
            content={"detail": f"Ошибка загрузки файла: {str(e)}"}
        )

# ========== WEB SOCKET ==========

@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: int):
    """
    WebSocket endpoint для реального времени
    
    Обрабатывает:
    1. Подключение пользователя
    2. Текстовые сообщения
    3. Сообщения с файлами
    4. Индикаторы набора текста
    5. Отключение пользователя
    """
    await manager.connect(websocket, user_id)
    
    # Обновляем статус пользователя как онлайн
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            user.is_online = True
            user.last_login = datetime.utcnow()
            db.commit()
            print(f"✅ User {user.username} connected (ID: {user_id})")
    except Exception as e:
        print(f"❌ Error updating user status: {e}")
    finally:
        db.close()
    
    try:
        while True:
            # Получаем сообщение от клиента
            data = await websocket.receive_text()
            message_data = json.loads(data)
            message_type = message_data.get("type", "message")
            
            print(f"📨 Received {message_type} from user {user_id}: {message_data}")
            
            # Обрабатываем разные типы сообщений
            if message_type == "message":
                await handle_text_message(message_data, user_id)
            elif message_type == "file_message":
                await handle_file_message(message_data, user_id)
            elif message_type == "typing":
                await handle_typing_indicator(message_data, user_id)
            elif message_type == "group_message":
                await handle_group_message(message_data, user_id)
                
    except WebSocketDisconnect:
        print(f"📴 User {user_id} disconnected")
        
        # Обновляем статус пользователя как офлайн
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if user:
                user.is_online = False
                db.commit()
                print(f"✅ User {user.username} marked as offline")
        except Exception as e:
            print(f"❌ Error updating user status: {e}")
        finally:
            db.close()
        
        # Удаляем соединение
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
        
        # Сохраняем в базу данных
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
        # Отправляем в группу
        elif group_id:
            # Получаем всех участников группы
            members = db.query(GroupMember).filter(GroupMember.group_id == group_id).all()
            for member in members:
                if member.user_id != sender_id:  # Не отправляем отправителю
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
        
        # Подтверждение отправки отправителю
        await manager.send_personal_message(
            json.dumps({
                "type": "message_sent",
                "id": db_message.id,
                "timestamp": db_message.created_at.isoformat()
            }),
            sender_id
        )
        
        print(f"✅ Message sent from {sender_id}")
        
    except Exception as e:
        db.rollback()
        print(f"❌ Error handling text message: {e}")
    finally:
        db.close()

async def handle_file_message(message_data: dict, sender_id: int):
    """Обработка сообщений с файлами"""
    db = SessionLocal()
    try:
        receiver_id = message_data.get("to_user_id")
        group_id = message_data.get("group_id")
        file_url = message_data.get("file_url")
        content = message_data.get("content", "").strip()
        
        if not file_url:
            return
        
        # Сохраняем в базу данных
        db_message = Message(
            from_user_id=sender_id,
            to_user_id=receiver_id,
            group_id=group_id,
            content=content,
            message_type="file",
            file_url=file_url
        )
        
        db.add(db_message)
        db.commit()
        db.refresh(db_message)
        
        # Отправляем получателю
        if receiver_id:
            await manager.send_personal_message(
                json.dumps({
                    "type": "file_message",
                    "id": db_message.id,
                    "from_user_id": sender_id,
                    "to_user_id": receiver_id,
                    "content": content,
                    "file_url": file_url,
                    "timestamp": db_message.created_at.isoformat()
                }),
                receiver_id
            )
        # Отправляем в группу
        elif group_id:
            members = db.query(GroupMember).filter(GroupMember.group_id == group_id).all()
            for member in members:
                if member.user_id != sender_id:
                    await manager.send_personal_message(
                        json.dumps({
                            "type": "group_file_message",
                            "id": db_message.id,
                            "group_id": group_id,
                            "from_user_id": sender_id,
                            "content": content,
                            "file_url": file_url,
                            "timestamp": db_message.created_at.isoformat()
                        }),
                        member.user_id
                    )
        
        # Подтверждение отправки
        await manager.send_personal_message(
            json.dumps({
                "type": "message_sent",
                "id": db_message.id,
                "timestamp": db_message.created_at.isoformat()
            }),
            sender_id
        )
        
        print(f"✅ File message sent from {sender_id}")
        
    except Exception as e:
        db.rollback()
        print(f"❌ Error handling file message: {e}")
    finally:
        db.close()

async def handle_typing_indicator(message_data: dict, sender_id: int):
    """Обработка индикатора набора текста"""
    receiver_id = message_data.get("to_user_id")
    group_id = message_data.get("group_id")
    is_typing = message_data.get("is_typing", False)
    
    # Отправляем индикатор получателю
    if receiver_id:
        await manager.send_personal_message(
            json.dumps({
                "type": "typing",
                "from_user_id": sender_id,
                "is_typing": is_typing
            }),
            receiver_id
        )
    # Отправляем в группу
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

# ========== ФРОНТЕНД ==========

@app.get("/")
async def serve_frontend():
    """Главная страница - отдает фронтенд"""
    if frontend_dir.exists():
        # Пробуем найти index.html
        index_file = frontend_dir / "index.html"
        if index_file.exists():
            print(f"✅ Serving index.html from {index_file}")
            return FileResponse(str(index_file))
        
        # Пробуем найти chat.html
        chat_file = frontend_dir / "chat.html"
        if chat_file.exists():
            print(f"✅ Serving chat.html from {chat_file}")
            return FileResponse(str(chat_file))
    
    print("❌ No frontend files found")
    return HTMLResponse("""
        <html>
            <head><title>DevNet Messenger</title></head>
            <body style="background: #0f0f0f; color: white; font-family: sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh;">
                <div style="text-align: center;">
                    <h1>DevNet Messenger API</h1>
                    <p>API is running successfully!</p>
                    <p>Frontend files not found. Please upload chat.html to frontend/ directory.</p>
                    <div style="margin-top: 20px;">
                        <a href="/health" style="color: #10a37f;">Check Health</a> | 
                        <a href="/api/test" style="color: #10a37f;">Test API</a>
                    </div>
                </div>
            </body>
        </html>
    """)

@app.get("/chat")
async def serve_chat():
    """Страница чата"""
    if frontend_dir.exists() and (frontend_dir / "chat.html").exists():
        chat_file = frontend_dir / "chat.html"
        print(f"✅ Serving chat.html from {chat_file}")
        return FileResponse(str(chat_file))
    
    return HTMLResponse("""
        <html>
            <head><title>Chat Not Found</title></head>
            <body style="background: #0f0f0f; color: white; font-family: sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh;">
                <div style="text-align: center;">
                    <h1>Chat Interface Not Found</h1>
                    <p>Please ensure chat.html exists in frontend/ directory.</p>
                    <a href="/" style="color: #10a37f;">Go Back</a>
                </div>
            </body>
        </html>
    """)

# ========== HEALTH & TESTING ==========

@app.get("/health")
async def health_check():
    """Проверка здоровья приложения"""
    return {
        "status": "healthy",
        "service": "DevNet Messenger",
        "version": "2.0.0",
        "timestamp": datetime.utcnow().isoformat(),
        "features": {
            "websocket": True,
            "file_upload": True,
            "groups": True,
            "auto_login": True
        },
        "database": "connected",
        "frontend_available": frontend_dir.exists()
    }

@app.get("/api/test")
async def api_test():
    """Тестовый endpoint для проверки API"""
    return {
        "status": "success",
        "message": "API is working correctly",
        "endpoints": {
            "auth": ["/api/auto-login", "/api/register", "/api/login", "/api/logout", "/api/me"],
            "users": ["/api/users"],
            "groups": ["/api/groups"],
            "chats": ["/api/chats"],
            "messages": ["/api/messages/{user_id}/{other_user_id}", "/api/group-messages/{group_id}"],
            "files": ["/api/upload"],
            "websocket": ["/ws/{user_id}"],
            "health": ["/health", "/api/test"]
        },
        "timestamp": datetime.utcnow().isoformat()
    }

# ========== ЗАПУСК СЕРВЕРА ==========

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"🚀 Starting DevNet Messenger on port {port}")
    print(f"📁 Frontend directory: {'Found' if frontend_dir.exists() else 'Not found'}")
    print(f"📁 Upload directory: {UPLOAD_DIR}")
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=False
    )
