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
            # Проверяем, есть ли
