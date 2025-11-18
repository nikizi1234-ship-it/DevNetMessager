from typing import Dict, List
import json

class ConnectionManager:
    def __init__(self):
        # ██████████████████████████████████████████████████████████████████████████
        # СЛОВАРЬ ДЛЯ ХРАНЕНИЯ АКТИВНЫХ СОЕДИНЕНИЙ:
        # { user_id: websocket_object }
        # ██████████████████████████████████████████████████████████████████████████
        self.active_connections: Dict[int, any] = {}
    
    async def connect(self, websocket, user_id: int):
        # ██████████████████████████████████████████████████████████████████████████
        # ПОДКЛЮЧЕНИЕ НОВОГО ПОЛЬЗОВАТЕЛЯ:
        # 1. Принимаем WebSocket соединение
        # 2. Сохраняем в словарь активных соединений
        # ██████████████████████████████████████████████████████████████████████████
        await websocket.accept()  # Принимаем соединение от клиента
        self.active_connections[user_id] = websocket  # Сохраняем соединение
        print(f"User {user_id} connected. Total: {len(self.active_connections)}")
    
    def disconnect(self, user_id: int):
        # ██████████████████████████████████████████████████████████████████████████
        # ОТКЛЮЧЕНИЕ ПОЛЬЗОВАТЕЛЯ:
        # Удаляем его из словаря активных соединений
        # ██████████████████████████████████████████████████████████████████████████
        if user_id in self.active_connections:
            del self.active_connections[user_id]
            print(f"User {user_id} disconnected. Total: {len(self.active_connections)}")
    
    async def send_personal_message(self, message: str, user_id: int):
        # ██████████████████████████████████████████████████████████████████████████
        # ОТПРАВКА ЛИЧНОГО СООБЩЕНИЯ КОНКРЕТНОМУ ПОЛЬЗОВАТЕЛЮ:
        # 1. Проверяем, онлайн ли пользователь
        # 2. Если онлайн - отправляем сообщение через WebSocket
        # ██████████████████████████████████████████████████████████████████████████
        if user_id in self.active_connections:
            await self.active_connections[user_id].send_text(message)
    
    async def broadcast(self, message: str):
        # ██████████████████████████████████████████████████████████████████████████
        # РАССЫЛКА СООБЩЕНИЯ ВСЕМ ПОДКЛЮЧЕННЫМ ПОЛЬЗОВАТЕЛЯМ:
        # Проходим по всем активным соединениям и отправляем сообщение
        # ██████████████████████████████████████████████████████████████████████████
        for connection in self.active_connections.values():
            await connection.send_text(message)

# ██████████████████████████████████████████████████████████████████████████
# СОЗДАЕМ ЕДИНСТВЕННЫЙ ЭКЗЕМПЛЯР МЕНЕДЖЕРА (SINGLETON)
# Чтобы все части приложения использовали один и тот же менеджер
# ██████████████████████████████████████████████████████████████████████████
manager = ConnectionManager()