from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import json
import os
from datetime import datetime
from pathlib import Path

app = FastAPI(title="DevNet Messenger")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Получаем пути
current_dir = Path(__file__).parent
project_root = current_dir.parent
frontend_dir = project_root / "frontend"

print(f"📁 Project root: {project_root}")
print(f"📁 Frontend directory: {frontend_dir}")
print(f"📁 Current directory: {current_dir}")

# WebSocket менеджер
class ConnectionManager:
    def __init__(self):
        self.active_connections = {}

    async def connect(self, websocket: WebSocket, user_id: int):
        await websocket.accept()
        self.active_connections[user_id] = websocket
        print(f"✅ User {user_id} connected")

    def disconnect(self, user_id: int):
        if user_id in self.active_connections:
            del self.active_connections[user_id]
            print(f"✅ User {user_id} disconnected")

    async def send_personal_message(self, message: str, user_id: int):
        if user_id in self.active_connections:
            await self.active_connections[user_id].send_text(message)

manager = ConnectionManager()

# Проверяем существование frontend директории
if frontend_dir.exists():
    print(f"✅ Frontend directory exists: {frontend_dir}")
    
    # Монтируем статические файлы
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")
    
    # Обслуживаем chat.html
    @app.get("/")
    async def serve_chat():
        chat_file = frontend_dir / "chat.html"
        if chat_file.exists():
            print(f"✅ Serving chat.html from {chat_file}")
            return FileResponse(str(chat_file))
        else:
            print(f"❌ chat.html not found at {chat_file}")
            return HTMLResponse(content="<h1>Chat page not found</h1>")
    
    @app.get("/chat")
    async def serve_chat_page():
        chat_file = frontend_dir / "chat.html"
        if chat_file.exists():
            return FileResponse(str(chat_file))
        return HTMLResponse(content="<h1>Chat page not found</h1>")
    
    @app.get("/test-frontend")
    async def test_frontend():
        chat_file = frontend_dir / "chat.html"
        if chat_file.exists():
            return {"status": "found", "path": str(chat_file)}
        return {"status": "not_found", "path": str(chat_file)}
    
else:
    print(f"❌ Frontend directory not found: {frontend_dir}")
    
    @app.get("/")
    async def root():
        return {"message": "DevNet Messenger API", "status": "running", "frontend": "not_found"}
    
    @app.get("/chat")
    async def chat_page():
        return {"message": "Frontend not deployed", "status": "use_api"}

# API endpoints
@app.get("/health")
async def health_check():
    return {
        "status": "healthy", 
        "service": "DevNet Messenger",
        "timestamp": datetime.utcnow().isoformat(),
        "port": os.environ.get("PORT", "8000"),
        "frontend_exists": frontend_dir.exists()
    }

@app.get("/api/status")
async def api_status():
    return {
        "status": "online",
        "users_connected": len(manager.active_connections),
        "timestamp": datetime.utcnow().isoformat(),
        "frontend": "available" if frontend_dir.exists() else "not_available"
    }

@app.post("/api/auto-login")
async def auto_login(request: Request):
    return JSONResponse({
        "success": True,
        "user": {
            "id": 1,
            "username": "guest_user",
            "display_name": "Guest User",
            "is_guest": True
        },
        "message": "Guest account created"
    })

@app.get("/api/users")
async def get_users():
    return {
        "users": [
            {
                "id": 1,
                "username": "user1",
                "display_name": "User One",
                "is_online": True,
                "avatar": "U1"
            },
            {
                "id": 2,
                "username": "user2",
                "display_name": "User Two",
                "is_online": False,
                "avatar": "U2"
            },
            {
                "id": 3,
                "username": "user3",
                "display_name": "User Three",
                "is_online": True,
                "avatar": "U3"
            },
            {
                "id": 4,
                "username": "alice",
                "display_name": "Alice Smith",
                "is_online": True,
                "avatar": "AS"
            },
            {
                "id": 5,
                "username": "bob",
                "display_name": "Bob Johnson",
                "is_online": False,
                "avatar": "BJ"
            }
        ]
    }

@app.get("/api/chats")
async def get_chats():
    return {
        "groups": [
            {
                "id": 1,
                "name": "DevNet Team",
                "description": "Team of developers",
                "type": "group",
                "members_count": 5,
                "avatar": "👥"
            },
            {
                "id": 2,
                "name": "Secret Project",
                "description": "Top secret development",
                "type": "group",
                "members_count": 3,
                "avatar": "🔒"
            }
        ],
        "channels": [
            {
                "id": 3,
                "name": "Tech News",
                "description": "Latest technology updates",
                "type": "channel",
                "members_count": 12,
                "avatar": "📢"
            },
            {
                "id": 4,
                "name": "Announcements",
                "description": "Important announcements",
                "type": "channel",
                "members_count": 8,
                "avatar": "📢"
            }
        ],
        "private_chats": [
            {
                "id": 1,
                "name": "User Two",
                "type": "private",
                "username": "user2",
                "is_online": False,
                "avatar": "U2"
            },
            {
                "id": 2,
                "name": "Alice Smith",
                "type": "private",
                "username": "alice",
                "is_online": True,
                "avatar": "AS"
            }
        ]
    }

@app.get("/api/messages/{user_id}")
async def get_messages(user_id: int):
    # Тестовые сообщения
    return [
        {
            "id": 1,
            "from_user_id": user_id,
            "to_user_id": 1,
            "content": "Привет! Как дела?",
            "type": "text",
            "timestamp": "2023-12-03T10:00:00Z",
            "is_my_message": True
        },
        {
            "id": 2,
            "from_user_id": 1,
            "to_user_id": user_id,
            "content": "Привет! Все отлично, работаю над новым проектом!",
            "type": "text",
            "timestamp": "2023-12-03T10:01:00Z",
            "is_my_message": False
        },
        {
            "id": 3,
            "from_user_id": user_id,
            "to_user_id": 1,
            "content": "Круто! А что за проект?",
            "type": "text",
            "timestamp": "2023-12-03T10:02:00Z",
            "is_my_message": True
        }
    ]

# WebSocket endpoint
@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: int):
    await manager.connect(websocket, user_id)
    
    try:
        while True:
            data = await websocket.receive_text()
            try:
                message_data = json.loads(data)
                print(f"📨 Received from user {user_id}: {message_data}")
                
                # Определяем тип сообщения
                message_type = message_data.get("type", "message")
                
                if message_type == "message":
                    response = {
                        "type": "message_received",
                        "id": message_data.get("id", 1),
                        "from_user_id": user_id,
                        "to_user_id": message_data.get("to_user_id"),
                        "content": message_data.get("content", ""),
                        "timestamp": datetime.utcnow().isoformat(),
                        "status": "delivered"
                    }
                    
                    # Отправляем ответ
                    await websocket.send_text(json.dumps(response))
                    
                    # Если есть получатель, отправляем ему
                    to_user_id = message_data.get("to_user_id")
                    if to_user_id and to_user_id != user_id:
                        await manager.send_personal_message(
                            json.dumps({
                                "type": "message",
                                "id": response["id"],
                                "from_user_id": user_id,
                                "content": message_data.get("content", ""),
                                "timestamp": response["timestamp"]
                            }),
                            to_user_id
                        )
                
                elif message_type == "typing":
                    # Индикатор набора текста
                    to_user_id = message_data.get("to_user_id")
                    is_typing = message_data.get("is_typing", False)
                    
                    if to_user_id and to_user_id != user_id:
                        await manager.send_personal_message(
                            json.dumps({
                                "type": "typing",
                                "from_user_id": user_id,
                                "is_typing": is_typing
                            }),
                            to_user_id
                        )
                
                elif message_type == "test":
                    await websocket.send_text(json.dumps({
                        "type": "test_response",
                        "message": "WebSocket работает!",
                        "timestamp": datetime.utcnow().isoformat()
                    }))
                
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": "Invalid JSON format"
                }))
                
    except WebSocketDisconnect:
        manager.disconnect(user_id)
    except Exception as e:
        print(f"❌ WebSocket error: {e}")
        manager.disconnect(user_id)

print(f"🚀 Server starting on port {os.environ.get('PORT', 8000)}")

# Для локального запуска
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=False
    )
