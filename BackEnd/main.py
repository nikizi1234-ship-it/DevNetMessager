from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, Form, Request, File, UploadFile, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc
import json
from datetime import datetime, timedelta
from pathlib import Path
import uvicorn 
import os
import sys
import shutil
import uuid
from typing import Optional
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

# Монтируем статические файлы фронтенда
if frontend_dir.exists():
    print(f"✅ Frontend found: {frontend_dir}")
    # Монтируем директорию фронтенда как статическую
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")
    # Также монтируем отдельно для стилей
    app.mount("/css", StaticFiles(directory=str(frontend_dir)), name="css")
    # Монтируем корень фронтенда для HTML файлов
    app.mount("/frontend", StaticFiles(directory=str(frontend_dir)), name="frontend")
else:
    print(f"⚠️  Frontend not found: {frontend_dir}")
    # Создаем минимальный фронтенд если его нет
    frontend_dir.mkdir(exist_ok=True)

# Монтируем директорию загрузок
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

# ========== API ENDPOINTS ==========

@app.get("/")
async def root():
    """Перенаправление на главную страницу"""
    return RedirectResponse("/index.html")

@app.get("/index.html")
async def serve_index():
    """Сервим index.html из фронтенд директории"""
    index_path = frontend_dir / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    else:
        # Если файла нет, возвращаем простую страницу
        return HTMLResponse("""
        <!DOCTYPE html>
        <html>
        <head>
            <title>DevNet Messenger</title>
            <link rel="stylesheet" href="/css/style.css">
            <style>
                body { font-family: Arial, sans-serif; margin: 0; padding: 0; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; }
                .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
                header { background: white; padding: 20px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); margin-bottom: 30px; }
                h1 { color: #667eea; margin: 0; font-size: 2.5em; }
                .nav { display: flex; gap: 20px; margin-top: 20px; }
                .nav a { padding: 10px 20px; background: #667eea; color: white; text-decoration: none; border-radius: 5px; transition: background 0.3s; }
                .nav a:hover { background: #764ba2; }
                .dashboard { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
                .card { background: white; padding: 25px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
                .card h2 { color: #333; margin-top: 0; }
                .status-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-top: 20px; }
                .status-item { background: #f8f9fa; padding: 15px; border-radius: 8px; border-left: 4px solid #667eea; }
                .status-item .label { font-weight: bold; color: #666; font-size: 0.9em; }
                .status-item .value { font-size: 1.2em; margin-top: 5px; }
                .actions { margin-top: 30px; }
                .test-buttons { display: flex; gap: 10px; flex-wrap: wrap; }
                .test-btn { padding: 12px 24px; border: none; border-radius: 6px; cursor: pointer; font-weight: bold; transition: all 0.3s; }
                .test-btn.health { background: #10b981; color: white; }
                .test-btn.debug { background: #3b82f6; color: white; }
                .test-btn:hover { opacity: 0.9; transform: translateY(-2px); }
                #testResult { margin-top: 20px; padding: 15px; background: #f1f5f9; border-radius: 8px; font-family: monospace; white-space: pre-wrap; }
                @media (max-width: 768px) {
                    .dashboard { grid-template-columns: 1fr; }
                }
            </style>
        </head>
        <body>
            <div class="container">
                <header>
                    <h1>🚀 DevNet Messenger</h1>
                    <p>Простой и быстрый мессенджер для разработчиков</p>
                    <div class="nav">
                        <a href="/chat.html">💬 Чат</a>
                        <a href="/api/docs">📖 API документация</a>
                        <a href="/api/health">🔧 Проверка здоровья</a>
                        <a href="/api/debug">🛠️ Отладка</a>
                    </div>
                </header>
                
                <div class="dashboard">
                    <div class="card">
                        <h2>Статус системы</h2>
                        <div class="status-grid">
                            <div class="status-item">
                                <div class="label">Статус</div>
                                <div class="value" id="statusText">Проверка...</div>
                            </div>
                            <div class="status-item">
                                <div class="label">Версия</div>
                                <div class="value">1.0.0</div>
                            </div>
                            <div class="status-item">
                                <div class="label">Время сервера</div>
                                <div class="value" id="serverTime">Загрузка...</div>
                            </div>
                            <div class="status-item">
                                <div class="label">База данных</div>
                                <div class="value" id="dbType">Загрузка...</div>
                            </div>
                        </div>
                        
                        <div class="actions">
                            <h3>Проверка подключения</h3>
                            <div class="test-buttons">
                                <button class="test-btn health" onclick="testHealth()">Test Health</button>
                                <button class="test-btn debug" onclick="testDebug()">Test Debug</button>
                            </div>
                            <div id="testResult"></div>
                        </div>
                    </div>
                    
                    <div class="card">
                        <h2>Быстрый доступ</h2>
                        <div style="display: grid; gap: 15px;">
                            <a href="/chat.html" style="display: block; padding: 15px; background: #667eea; color: white; text-decoration: none; border-radius: 8px; text-align: center;">
                                <h3 style="margin: 0;">💬 Перейти в чат</h3>
                                <p style="margin: 5px 0 0 0; opacity: 0.9;">Общайтесь в реальном времени</p>
                            </a>
                            <a href="/api/docs" style="display: block; padding: 15px; background: #10b981; color: white; text-decoration: none; border-radius: 8px; text-align: center;">
                                <h3 style="margin: 0;">📖 API документация</h3>
                                <p style="margin: 5px 0 0 0; opacity: 0.9;">Полная документация API</p>
                            </a>
                            <div style="padding: 15px; background: #f8f9fa; border-radius: 8px;">
                                <h3 style="margin: 0;">👑 Тестовый аккаунт</h3>
                                <p style="margin: 5px 0 0 0;"><strong>Логин:</strong> admin</p>
                                <p style="margin: 5px 0 0 0;"><strong>Пароль:</strong> admin123</p>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            
            <script>
                // Обновление времени сервера
                function updateServerTime() {
                    const now = new Date();
                    const options = { 
                        year: 'numeric', 
                        month: '2-digit', 
                        day: '2-digit',
                        hour: '2-digit',
                        minute: '2-digit',
                        second: '2-digit'
                    };
                    document.getElementById('serverTime').textContent = now.toLocaleDateString('ru-RU', options);
                }
                
                // Проверка здоровья системы
                async function testHealth() {
                    try {
                        const response = await fetch('/api/health');
                        const data = await response.json();
                        document.getElementById('testResult').textContent = JSON.stringify(data, null, 2);
                        document.getElementById('statusText').textContent = '✅ Работает';
                        document.getElementById('dbType').textContent = data.database || 'sqlite';
                    } catch (error) {
                        document.getElementById('testResult').textContent = '❌ Ошибка: ' + error;
                        document.getElementById('statusText').textContent = '❌ Ошибка';
                    }
                }
                
                // Проверка отладки
                async function testDebug() {
                    try {
                        const response = await fetch('/api/debug');
                        const data = await response.json();
                        document.getElementById('testResult').textContent = JSON.stringify(data, null, 2);
                    } catch (error) {
                        document.getElementById('testResult').textContent = '❌ Ошибка: ' + error;
                    }
                }
                
                // Инициализация
                document.addEventListener('DOMContentLoaded', function() {
                    updateServerTime();
                    setInterval(updateServerTime, 1000);
                    testHealth(); // Автоматически проверяем здоровье при загрузке
                });
            </script>
        </body>
        </html>
        """)

@app.get("/chat.html")
async def serve_chat():
    """Сервим chat.html из фронтенд директории"""
    chat_path = frontend_dir / "chat.html"
    if chat_path.exists():
        return FileResponse(str(chat_path))
    else:
        # Если файла нет, возвращаем простой чат
        return HTMLResponse("""
        <!DOCTYPE html>
        <html>
        <head>
            <title>DevNet Chat</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 0; padding: 0; background: #f5f5f5; }
                .container { max-width: 1200px; margin: 0 auto; padding: 20px; display: flex; gap: 20px; }
                .sidebar { width: 300px; background: white; border-radius: 10px; padding: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
                .chat-area { flex: 1; display: flex; flex-direction: column; }
                .chat-header { background: white; padding: 20px; border-radius: 10px 10px 0 0; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
                .messages-container { flex: 1; background: white; padding: 20px; overflow-y: auto; max-height: 600px; }
                .message-input { display: flex; gap: 10px; padding: 20px; background: white; border-radius: 0 0 10px 10px; box-shadow: 0 -2px 4px rgba(0,0,0,0.1); }
                #messages { display: flex; flex-direction: column; gap: 10px; }
                .message { padding: 12px 16px; border-radius: 10px; max-width: 70%; }
                .message.sent { background: #667eea; color: white; align-self: flex-end; }
                .message.received { background: #e5e7eb; color: #333; align-self: flex-start; }
                input[type="text"] { flex: 1; padding: 12px; border: 1px solid #ddd; border-radius: 6px; }
                button { padding: 12px 24px; background: #667eea; color: white; border: none; border-radius: 6px; cursor: pointer; }
                button:hover { background: #764ba2; }
                #auth { background: white; padding: 30px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); margin-bottom: 20px; }
                .user-list { margin-top: 20px; }
                .user-item { padding: 10px; border-bottom: 1px solid #eee; display: flex; align-items: center; gap: 10px; }
                .online-dot { width: 8px; height: 8px; background: #10b981; border-radius: 50%; }
                .offline-dot { width: 8px; height: 8px; background: #9ca3af; border-radius: 50%; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="sidebar">
                    <div id="auth">
                        <h2>Вход в систему</h2>
                        <div style="display: flex; flex-direction: column; gap: 10px;">
                            <input type="text" id="username" placeholder="Логин" value="admin">
                            <input type="password" id="password" placeholder="Пароль" value="admin123">
                            <button onclick="login()">Войти</button>
                        </div>
                        <p style="margin-top: 15px; font-size: 0.9em; color: #666;">
                            Нет аккаунта? <a href="javascript:void(0)" onclick="showRegister()">Зарегистрироваться</a>
                        </p>
                    </div>
                    
                    <div class="user-list">
                        <h3>Пользователи онлайн</h3>
                        <div id="onlineUsers"></div>
                    </div>
                </div>
                
                <div class="chat-area">
                    <div class="chat-header">
                        <h2>💬 Общий чат</h2>
                        <div id="userInfo" style="display: none;">
                            Вы вошли как: <span id="currentUsername"></span>
                        </div>
                    </div>
                    
                    <div class="messages-container">
                        <div id="messages"></div>
                    </div>
                    
                    <div class="message-input">
                        <input type="text" id="messageInput" placeholder="Введите сообщение..." disabled>
                        <button id="sendButton" onclick="sendMessage()" disabled>Отправить</button>
                    </div>
                </div>
            </div>
            
            <script>
                let ws = null;
                let currentUser = null;
                
                async function login() {
                    const username = document.getElementById('username').value;
                    const password = document.getElementById('password').value;
                    
                    if (!username || !password) {
                        alert('Введите логин и пароль');
                        return;
                    }
                    
                    const formData = new FormData();
                    formData.append('username', username);
                    formData.append('password', password);
                    
                    try {
                        const response = await fetch('/api/auth/login', {
                            method: 'POST',
                            body: new URLSearchParams({
                                username: username,
                                password: password
                            })
                        });
                        
                        if (response.ok) {
                            const data = await response.json();
                            currentUser = data.user;
                            
                            // Обновляем интерфейс
                            document.getElementById('auth').style.display = 'none';
                            document.getElementById('userInfo').style.display = 'block';
                            document.getElementById('currentUsername').textContent = currentUser.username;
                            document.getElementById('messageInput').disabled = false;
                            document.getElementById('sendButton').disabled = false;
                            
                            // Подключаем WebSocket
                            connectWebSocket();
                            
                            // Загружаем сообщения
                            loadMessages();
                            
                            // Загружаем пользователей
                            loadUsers();
                            
                        } else {
                            const error = await response.json();
                            alert('Ошибка входа: ' + (error.detail || 'Неверные данные'));
                        }
                    } catch (error) {
                        alert('Ошибка сети: ' + error);
                    }
                }
                
                function connectWebSocket() {
                    if (!currentUser) return;
                    
                    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
                    const wsUrl = `${protocol}//${window.location.host}/ws/${currentUser.id}`;
                    ws = new WebSocket(wsUrl);
                    
                    ws.onopen = function() {
                        console.log('WebSocket подключен');
                    };
                    
                    ws.onmessage = function(event) {
                        const data = JSON.parse(event.data);
                        addMessage(data.from_user_id, data.content, false);
                    };
                    
                    ws.onclose = function() {
                        console.log('WebSocket отключен');
                        setTimeout(connectWebSocket, 3000);
                    };
                }
                
                async function loadMessages() {
                    try {
                        const response = await fetch('/api/messages?limit=50');
                        const data = await response.json();
                        
                        if (data.success && data.messages) {
                            const messagesDiv = document.getElementById('messages');
                            messagesDiv.innerHTML = '';
                            
                            data.messages.forEach(msg => {
                                const isMe = msg.sender && msg.sender.id === currentUser.id;
                                addMessage(msg.sender?.username || 'System', msg.content, isMe);
                            });
                            
                            // Прокручиваем вниз
                            messagesDiv.scrollTop = messagesDiv.scrollHeight;
                        }
                    } catch (error) {
                        console.error('Ошибка загрузки сообщений:', error);
                    }
                }
                
                async function loadUsers() {
                    try {
                        const response = await fetch('/api/users');
                        const data = await response.json();
                        
                        if (data.success && data.users) {
                            const onlineUsersDiv = document.getElementById('onlineUsers');
                            onlineUsersDiv.innerHTML = '';
                            
                            data.users.forEach(user => {
                                const userDiv = document.createElement('div');
                                userDiv.className = 'user-item';
                                userDiv.innerHTML = `
                                    <div class="${user.is_online ? 'online-dot' : 'offline-dot'}"></div>
                                    <div>
                                        <strong>${user.display_name || user.username}</strong>
                                        <div style="font-size: 0.8em; color: #666;">${user.username}</div>
                                    </div>
                                `;
                                onlineUsersDiv.appendChild(userDiv);
                            });
                        }
                    } catch (error) {
                        console.error('Ошибка загрузки пользователей:', error);
                    }
                }
                
                function sendMessage() {
                    const messageInput = document.getElementById('messageInput');
                    const message = messageInput.value.trim();
                    
                    if (!message || !ws) return;
                    
                    if (ws.readyState === WebSocket.OPEN) {
                        ws.send(JSON.stringify({
                            type: 'message',
                            content: message
                        }));
                        
                        addMessage(currentUser.username, message, true);
                        messageInput.value = '';
                    }
                }
                
                function addMessage(sender, text, isMe) {
                    const messagesDiv = document.getElementById('messages');
                    const messageDiv = document.createElement('div');
                    messageDiv.className = `message ${isMe ? 'sent' : 'received'}`;
                    messageDiv.innerHTML = `
                        <div><strong>${sender}:</strong></div>
                        <div>${text}</div>
                        <div style="font-size: 0.8em; opacity: 0.7; margin-top: 5px;">
                            ${new Date().toLocaleTimeString()}
                        </div>
                    `;
                    messagesDiv.appendChild(messageDiv);
                    messagesDiv.scrollTop = messagesDiv.scrollHeight;
                }
                
                // Ввод по Enter
                document.getElementById('messageInput').addEventListener('keypress', function(e) {
                    if (e.key === 'Enter') {
                        sendMessage();
                    }
                });
                
                function showRegister() {
                    const username = prompt('Введите имя пользователя:');
                    const password = prompt('Введите пароль:');
                    const email = prompt('Введите email:');
                    
                    if (username && password && email) {
                        fetch('/api/auth/register', {
                            method: 'POST',
                            body: new URLSearchParams({
                                username: username,
                                password: password,
                                email: email
                            })
                        })
                        .then(response => response.json())
                        .then(data => {
                            if (data.success) {
                                alert('Регистрация успешна! Теперь войдите в систему.');
                                document.getElementById('username').value = username;
                                document.getElementById('password').value = password;
                            } else {
                                alert('Ошибка регистрации: ' + (data.detail || 'Неизвестная ошибка'));
                            }
                        })
                        .catch(error => alert('Ошибка сети: ' + error));
                    }
                }
            </script>
        </body>
        </html>
        """)

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
        
        # Обрезаем пароль если слишком длинный
        password_to_hash = password[:72] if len(password) > 72 else password
        
        # Создаем пользователя
        user = User(
            username=username,
            email=email,
            display_name=display_name or username,
            password_hash=get_password_hash(password_to_hash)
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
                        
    except WebSocketDisconnect:
        print(f"📴 User disconnected: {user_id}")
        manager.disconnect(user_id)

# ========== СЕРВИС СТАТИЧЕСКИХ ФАЙЛОВ ==========

@app.get("/{filename:path}")
async def serve_static_files(filename: str):
    """Сервит статические файлы из фронтенд директории"""
    # Проверяем безопасность пути
    safe_path = Path(filename).name
    
    # Пробуем найти файл во фронтенд директории
    file_path = frontend_dir / safe_path
    
    if file_path.exists() and file_path.is_file():
        return FileResponse(str(file_path))
    
    # Если файл не найден, проверяем стандартные расширения
    if "." not in safe_path:
        # Пробуем добавить .html
        html_path = frontend_dir / f"{safe_path}.html"
        if html_path.exists():
            return FileResponse(str(html_path))
    
    # Если ничего не найдено, возвращаем 404
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
    print(f"💬 Чат: http://localhost:{port}/chat.html")
    print("👑 Тестовый пользователь: admin / admin123")
    print("=" * 50)
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=False
    )
