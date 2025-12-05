from fastapi import FastAPI, Request, Form, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from datetime import datetime
from pathlib import Path
import uvicorn
import os
import sys
import json

# Добавляем путь для импорта модулей
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

print("🚀 Starting DevNet Messenger...")

# ========== СОЗДАНИЕ БАЗЫ ДАННЫХ ПРОСТОЙ СПОСОБ ==========

import sqlite3
import hashlib
import secrets

# Определяем путь к БД
if os.environ.get("RAILWAY_ENVIRONMENT"):
    DB_PATH = ":memory:"  # In-memory для Railway
    print("🚂 Running on Railway - using IN-MEMORY SQLite")
else:
    DB_PATH = "devnet.db"
    print("💻 Running locally - using file SQLite")

# Создаем подключение к БД
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# Создаем таблицы
cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        email TEXT UNIQUE NOT NULL,
        display_name TEXT,
        password_hash TEXT NOT NULL,
        avatar_url TEXT,
        is_online BOOLEAN DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
''')

cursor.execute('''
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        from_user_id INTEGER,
        to_user_id INTEGER,
        content TEXT,
        message_type TEXT DEFAULT 'text',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (from_user_id) REFERENCES users (id),
        FOREIGN KEY (to_user_id) REFERENCES users (id)
    )
''')

cursor.execute('''
    CREATE TABLE IF NOT EXISTS groups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT,
        avatar_url TEXT,
        is_public BOOLEAN DEFAULT 1,
        created_by INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (created_by) REFERENCES users (id)
    )
''')

# Создаем администратора если его нет
cursor.execute("SELECT * FROM users WHERE username = 'admin'")
if not cursor.fetchone():
    password_hash = hashlib.sha256("admin123".encode()).hexdigest()
    cursor.execute(
        "INSERT INTO users (username, email, display_name, password_hash) VALUES (?, ?, ?, ?)",
        ("admin", "admin@devnet.local", "Администратор", password_hash)
    )
    print("👑 Admin user created: admin / admin123")

conn.commit()
print("✅ Database initialized successfully")

# ========== СОЗДАНИЕ FASTAPI ПРИЛОЖЕНИЯ ==========

app = FastAPI(
    title="DevNet Messenger",
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

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========

def get_password_hash(password):
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(plain_password, hashed_password):
    return get_password_hash(plain_password) == hashed_password

def create_access_token(user_id):
    return f"token_{user_id}_{secrets.token_hex(16)}"

def verify_token(token):
    try:
        parts = token.split("_")
        if len(parts) >= 2 and parts[0] == "token":
            return {"user_id": int(parts[1])}
    except:
        return None
    return None

# ========== API ENDPOINTS ==========

@app.get("/")
async def root():
    return RedirectResponse("/index.html")

@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "DevNet Messenger",
        "version": "1.0.0",
        "timestamp": datetime.utcnow().isoformat(),
        "database": "sqlite",
        "railway": bool(os.environ.get("RAILWAY_ENVIRONMENT"))
    }

@app.get("/api/debug")
async def debug_info():
    return {
        "railway_env": os.environ.get("RAILWAY_ENVIRONMENT"),
        "port": os.environ.get("PORT", 8000),
        "database": "in-memory" if DB_PATH == ":memory:" else "file",
        "upload_dir": str(UPLOAD_DIR),
        "current_time": datetime.utcnow().isoformat()
    }

# ========== АУТЕНТИФИКАЦИЯ ==========

@app.post("/api/auth/register")
async def register_user(
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    display_name: str = Form(None)
):
    try:
        # Проверяем уникальность username
        cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail="Имя пользователя уже занято")
        
        # Проверяем уникальность email
        cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail="Email уже используется")
        
        # Проверяем пароль
        if len(password) < 6:
            raise HTTPException(status_code=400, detail="Пароль должен быть не менее 6 символов")
        
        # Создаем пользователя
        password_hash = get_password_hash(password)
        cursor.execute(
            "INSERT INTO users (username, email, display_name, password_hash) VALUES (?, ?, ?, ?)",
            (username, email, display_name or username, password_hash)
        )
        conn.commit()
        
        user_id = cursor.lastrowid
        
        # Создаем токен
        access_token = create_access_token(user_id)
        
        response = JSONResponse(content={
            "success": True,
            "user": {
                "id": user_id,
                "username": username,
                "display_name": display_name or username,
                "email": email
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
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Ошибка регистрации: {str(e)}")

@app.post("/api/auth/login")
async def login_user(
    username: str = Form(...),
    password: str = Form(...)
):
    try:
        cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
        user = cursor.fetchone()
        
        if not user or not verify_password(password, user["password_hash"]):
            raise HTTPException(status_code=401, detail="Неверное имя пользователя или пароль")
        
        # Создаем токен
        access_token = create_access_token(user["id"])
        
        response = JSONResponse(content={
            "success": True,
            "user": {
                "id": user["id"],
                "username": user["username"],
                "display_name": user["display_name"],
                "email": user["email"],
                "avatar_url": user["avatar_url"]
            },
            "access_token": access_token
        })
        
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
async def get_current_user_info(request: Request):
    try:
        token = request.cookies.get("access_token")
        if not token:
            raise HTTPException(status_code=401, detail="Требуется аутентификация")
        
        payload = verify_token(token)
        if not payload:
            raise HTTPException(status_code=401, detail="Недействительный токен")
        
        user_id = payload.get("user_id")
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        user = cursor.fetchone()
        
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        
        return {
            "success": True,
            "user": {
                "id": user["id"],
                "username": user["username"],
                "display_name": user["display_name"],
                "email": user["email"],
                "avatar_url": user["avatar_url"],
                "is_online": bool(user["is_online"]),
                "created_at": user["created_at"]
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка загрузки пользователя: {str(e)}")

# ========== ПОЛЬЗОВАТЕЛИ ==========

@app.get("/api/users")
async def get_users():
    try:
        cursor.execute("SELECT id, username, display_name, avatar_url, is_online, created_at FROM users ORDER BY username")
        users = cursor.fetchall()
        
        users_data = []
        for user in users:
            users_data.append({
                "id": user["id"],
                "username": user["username"],
                "display_name": user["display_name"],
                "avatar_url": user["avatar_url"],
                "is_online": bool(user["is_online"]),
                "created_at": user["created_at"]
            })
        
        return {
            "success": True,
            "users": users_data,
            "count": len(users_data)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка загрузки пользователей: {str(e)}")

# ========== СООБЩЕНИЯ ==========

@app.get("/api/messages")
async def get_messages():
    try:
        cursor.execute('''
            SELECT m.*, u.username, u.display_name 
            FROM messages m 
            LEFT JOIN users u ON m.from_user_id = u.id 
            ORDER BY m.created_at DESC 
            LIMIT 50
        ''')
        messages = cursor.fetchall()
        
        messages_data = []
        for msg in messages:
            messages_data.append({
                "id": msg["id"],
                "content": msg["content"],
                "type": msg["message_type"],
                "sender": {
                    "id": msg["from_user_id"],
                    "username": msg["username"],
                    "display_name": msg["display_name"]
                } if msg["from_user_id"] else {"username": "System"},
                "created_at": msg["created_at"]
            })
        
        return {
            "success": True,
            "messages": messages_data,
            "count": len(messages_data)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка загрузки сообщений: {str(e)}")

# ========== WEB SOCKET ==========

class ConnectionManager:
    def __init__(self):
        self.active_connections = {}
    
    async def connect(self, websocket, user_id: int):
        await websocket.accept()
        self.active_connections[user_id] = websocket
        
        # Обновляем статус пользователя
        cursor.execute("UPDATE users SET is_online = 1 WHERE id = ?", (user_id,))
        conn.commit()
    
    def disconnect(self, user_id: int):
        if user_id in self.active_connections:
            del self.active_connections[user_id]
        
        # Обновляем статус пользователя
        cursor.execute("UPDATE users SET is_online = 0 WHERE id = ?", (user_id,))
        conn.commit()
    
    async def send_personal_message(self, message: str, user_id: int):
        if user_id in self.active_connections:
            await self.active_connections[user_id].send_text(message)

manager = ConnectionManager()

@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: int):
    await manager.connect(websocket, user_id)
    
    try:
        while True:
            data = await websocket.receive_text()
            message_data = json.loads(data)
            
            if message_data.get("type") == "message":
                content = message_data.get("content", "").strip()
                if content:
                    # Сохраняем сообщение
                    cursor.execute(
                        "INSERT INTO messages (from_user_id, content) VALUES (?, ?)",
                        (user_id, content)
                    )
                    conn.commit()
                    
                    message_id = cursor.lastrowid
                    
                    # Получаем информацию об отправителе
                    cursor.execute("SELECT username, display_name FROM users WHERE id = ?", (user_id,))
                    sender = cursor.fetchone()
                    
                    # Отправляем всем подключенным
                    message = {
                        "type": "message",
                        "id": message_id,
                        "from_user_id": user_id,
                        "from_username": sender["username"] if sender else "Unknown",
                        "from_display_name": sender["display_name"] if sender else "Unknown",
                        "content": content,
                        "timestamp": datetime.utcnow().isoformat()
                    }
                    
                    for uid, ws in manager.active_connections.items():
                        if uid != user_id:
                            await ws.send_text(json.dumps(message))
                    
                    # Подтверждение отправителю
                    await websocket.send_text(json.dumps({
                        "type": "message_sent",
                        "id": message_id,
                        "timestamp": datetime.utcnow().isoformat()
                    }))
                    
    except WebSocketDisconnect:
        print(f"📴 User disconnected: {user_id}")
        manager.disconnect(user_id)
    except Exception as e:
        print(f"❌ WebSocket error: {e}")
        manager.disconnect(user_id)

# ========== СТАТИЧЕСКИЕ СТРАНИЦЫ ==========

@app.get("/index.html")
async def serve_index():
    html = """
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
                transition: transform 0.3s;
            }
            .btn-primary {
                background: white;
                color: #667eea;
            }
            .btn:hover {
                transform: translateY(-2px);
            }
            .status {
                text-align: center;
                margin-top: 30px;
                padding: 15px;
                background: rgba(255, 255, 255, 0.2);
                border-radius: 10px;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🚀 DevNet Messenger</h1>
            <p style="text-align: center; font-size: 1.2em;">
                Простой и быстрый мессенджер для разработчиков
            </p>
            
            <div class="status" id="status">
                Проверка соединения...
            </div>
            
            <div class="buttons">
                <button class="btn btn-primary" onclick="window.location.href='/chat'">
                    💬 Перейти в чат
                </button>
                <button class="btn btn-primary" onclick="window.location.href='/test'">
                    🔧 Тест функций
                </button>
                <button class="btn btn-primary" onclick="window.location.href='/api/docs'">
                    📖 API Документация
                </button>
            </div>
        </div>
        
        <script>
            async function checkStatus() {
                try {
                    const response = await fetch('/api/health');
                    const data = await response.json();
                    document.getElementById('status').innerHTML = 
                        `✅ Система работает<br>Версия: ${data.version}<br>Время: ${new Date(data.timestamp).toLocaleTimeString()}`;
                } catch (error) {
                    document.getElementById('status').innerHTML = '❌ Ошибка подключения к серверу';
                }
            }
            
            checkStatus();
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

@app.get("/chat")
async def serve_chat():
    html = """
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
            input {
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
            .message {
                margin-bottom: 15px;
                padding: 10px;
                background: white;
                border-radius: 5px;
                border: 1px solid #eee;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>DevNet Chat</h1>
                <p>Real-time messaging</p>
            </div>
            
            <div id="auth-section" style="padding: 40px; text-align: center;">
                <h2>Вход в систему</h2>
                <div style="max-width: 300px; margin: 0 auto;">
                    <input type="text" id="username" placeholder="Имя пользователя" style="width: 100%; margin-bottom: 10px;">
                    <input type="password" id="password" placeholder="Пароль" style="width: 100%; margin-bottom: 10px;">
                    <button onclick="login()">Войти</button>
                    <button onclick="window.location.href='/'">На главную</button>
                    <p style="margin-top: 20px; font-size: 0.9em; color: #666;">
                        Тестовый пользователь: admin / admin123
                    </p>
                </div>
            </div>
            
            <div id="chat-section" style="display: none;">
                <div class="chat-container">
                    <div class="sidebar">
                        <h3>Пользователи онлайн</h3>
                        <div id="users-list"></div>
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
                const username = document.getElementById('username').value;
                const password = document.getElementById('password').value;
                
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
                    loadUsers();
                    connectWebSocket();
                    loadMessages();
                } else {
                    alert('Ошибка входа');
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
            
            async function loadMessages() {
                const response = await fetch('/api/messages');
                if (response.ok) {
                    const data = await response.json();
                    const container = document.getElementById('messages-container');
                    container.innerHTML = '';
                    
                    data.messages.reverse().forEach(msg => {
                        displayMessage(msg);
                    });
                    
                    container.scrollTop = container.scrollHeight;
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
            
            function displayMessage(msg) {
                const container = document.getElementById('messages-container');
                const messageDiv = document.createElement('div');
                messageDiv.className = 'message';
                
                const time = new Date(msg.timestamp || Date.now()).toLocaleTimeString();
                messageDiv.innerHTML = `
                    <div style="display: flex; justify-content: space-between; margin-bottom: 5px; font-size: 0.9em; color: #666;">
                        <strong>${msg.from_display_name || msg.sender?.display_name || 'User'}</strong>
                        <span>${time}</span>
                    </div>
                    <div>${msg.content}</div>
                `;
                
                container.appendChild(messageDiv);
                container.scrollTop = container.scrollHeight;
            }
            
            function logout() {
                document.cookie = 'access_token=; Max-Age=0; path=/';
                if (ws) ws.close();
                window.location.reload();
            }
            
            // Автоматический вход если уже авторизован
            window.onload = async function() {
                const response = await fetch('/api/auth/me');
                if (response.ok) {
                    const data = await response.json();
                    currentUser = data.user;
                    document.getElementById('auth-section').style.display = 'none';
                    document.getElementById('chat-section').style.display = 'block';
                    loadUsers();
                    connectWebSocket();
                    loadMessages();
                }
            };
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

@app.get("/test")
async def test_page():
    html = """
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>DevNet - Test Page</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 0; padding: 20px; background: #f0f2f5; }
            .container { max-width: 800px; margin: 0 auto; }
            .test-card { background: white; padding: 20px; margin-bottom: 20px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
            button { padding: 10px 20px; background: #667eea; color: white; border: none; border-radius: 5px; cursor: pointer; margin-right: 10px; }
            .success { color: green; }
            .error { color: red; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🔧 DevNet Messenger - Test Page</h1>
            
            <div class="test-card">
                <h2>Проверка подключения</h2>
                <button onclick="testHealth()">Test Health</button>
                <button onclick="testDebug()">Test Debug</button>
                <div id="result"></div>
            </div>
            
            <div class="test-card">
                <h2>Действия</h2>
                <button onclick="window.location.href='/'">🏠 Главная</button>
                <button onclick="window.location.href='/chat'">💬 Чат</button>
                <button onclick="window.location.href='/api/docs'">📖 API Docs</button>
            </div>
            
            <div class="test-card">
                <h2>Статус системы</h2>
                <div id="system-status">Загрузка...</div>
            </div>
        </div>
        
        <script>
            async function testHealth() {
                const resultEl = document.getElementById('result');
                try {
                    const response = await fetch('/api/health');
                    const data = await response.json();
                    resultEl.innerHTML = `<pre class="success">${JSON.stringify(data, null, 2)}</pre>`;
                } catch (error) {
                    resultEl.innerHTML = `<pre class="error">${error}</pre>`;
                }
            }
            
            async function testDebug() {
                const resultEl = document.getElementById('result');
                try {
                    const response = await fetch('/api/debug');
                    const data = await response.json();
                    resultEl.innerHTML = `<pre class="success">${JSON.stringify(data, null, 2)}</pre>`;
                } catch (error) {
                    resultEl.innerHTML = `<pre class="error">${error}</pre>`;
                }
            }
            
            async function loadSystemStatus() {
                const statusEl = document.getElementById('system-status');
                try {
                    const response = await fetch('/api/health');
                    const data = await response.json();
                    statusEl.innerHTML = `
                        <p><strong>Статус:</strong> <span style="color: green">✅ Работает</span></p>
                        <p><strong>Версия:</strong> ${data.version}</p>
                        <p><strong>Время сервера:</strong> ${new Date(data.timestamp).toLocaleString()}</p>
                        <p><strong>Railway:</strong> ${data.railway ? 'Да' : 'Нет'}</p>
                        <p><strong>База данных:</strong> ${data.database}</p>
                    `;
                } catch (error) {
                    statusEl.innerHTML = `<p style="color: red">❌ Ошибка: ${error}</p>`;
                }
            }
            
            window.onload = loadSystemStatus;
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

# ========== ЗАПУСК СЕРВЕРА ==========

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print("=" * 50)
    print(f"🚀 DevNet Messenger запущен на порту {port}")
    print(f"📁 Директория: {UPLOAD_DIR}")
    print(f"🔗 API: http://localhost:{port}/api/docs")
    print(f"💬 Чат: http://localhost:{port}/chat")
    print(f"🔧 Тест: http://localhost:{port}/test")
    print("👑 Тестовый пользователь: admin / admin123")
    print("=" * 50)
    
    uvicorn.run(app, host="0.0.0.0", port=port)
