from fastapi import WebSocket
from typing import Dict, List

class ConnectionManager:
    def __init__(self):
        # Храним активные соединения: {user_id: [websocket1, websocket2]}
        self.active_connections: Dict[int, List[WebSocket]] = {}
    
    async def connect(self, websocket: WebSocket, user_id: int):
        """Принимает новое WebSocket соединение"""
        await websocket.accept()
        
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        
        # Добавляем соединение в список
        if websocket not in self.active_connections[user_id]:
            self.active_connections[user_id].append(websocket)
            print(f"✅ User {user_id} connected. Total connections: {len(self.active_connections[user_id])}")
    
    def disconnect(self, user_id: int):
        """Удаляет все соединения пользователя"""
        if user_id in self.active_connections:
            del self.active_connections[user_id]
            print(f"✅ User {user_id} disconnected")
    
    async def send_personal_message(self, message: str, user_id: int):
        """Отправляет сообщение конкретному пользователю"""
        if user_id in self.active_connections:
            for websocket in self.active_connections[user_id]:
                try:
                    await websocket.send_text(message)
                except Exception as e:
                    print(f"❌ Error sending message to user {user_id}: {e}")
    
    async def broadcast(self, message: str, exclude_user_id: int = None):
        """Отправляет сообщение всем подключенным пользователям, кроме указанного"""
        for user_id, connections in self.active_connections.items():
            if user_id == exclude_user_id:
                continue
            for websocket in connections:
                try:
                    await websocket.send_text(message)
                except:
                    pass

# Создаем глобальный менеджер соединений
manager = ConnectionManager()
