from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, status, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import and_
import json
from datetime import datetime, timedelta
from pathlib import Path
import uvicorn 
import os

from websocket_manager import manager
from database import engine, SessionLocal, get_db
from models import Base, User, Message
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

# Получаем абсолютный путь к frontend
current_dir = Path(__file__).parent
frontend_dir = current_dir.parent / "frontend"

print(f"📁 Frontend directory: {frontend_dir}")

# Функция для создания тестовых пользователей при запуске
def create_initial_users():
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
                )
            ]
            
            for user in test_users:
                db.add(user)
            
            db.commit()
            print("✅ Тестовые пользователи созданы!")
        else:
            print(f"✅ В базе уже есть {existing_users} пользователей")
            
    except Exception as e:
        print(f"❌ Ошибка создания пользователей: {e}")
        db.rollback()
    finally:
        db.close()

# Создаем пользователей при запуске
create_initial_users()

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
            is_online=False
        )
        
        db.add(db_user)
        db.commit()
        db.refresh(db_user)
        
        # Создаем токен
        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={"sub": db_user.username, "user_id": db_user.id}, expires_delta=access_token_expires
        )
        
        print(f"✅ Пользователь {username} успешно зарегистрирован!")
        
        response = JSONResponse({
            "success": True,
            "user_id": db_user.id,
            "username": db_user.username,
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
        db.commit()
        
        # Создаем токен
        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={"sub": user.username, "user_id": user.id}, expires_delta=access_token_expires
        )
        
        print(f"✅ Пользователь {username} вошел в систему!")
        
        response = JSONResponse({
            "success": True,
            "user_id": user.id,
            "username": user.username,
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

# Выход пользователя
@app.post("/api/logout")
async def logout(request: Request, db: Session = Depends(get_db)):
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
                    print(f"✅ Пользователь {user.username} вышел из системы")
        
        response = JSONResponse({"success": True, "message": "Выход выполнен успешно"})
        response.delete_cookie("access_token")
        return response
        
    except Exception as e:
        print(f"❌ Ошибка выхода: {e}")
        return JSONResponse(
            status_code=500,
            content={"detail": f"Ошибка выхода: {str(e)}"}
        )

# Получение информации о текущем пользователе
@app.get("/api/me")
async def get_current_user_info(request: Request, db: Session = Depends(get_db)):
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
            "last_login": user.last_login.isoformat() if user.last_login else None,
            "created_at": user.created_at.isoformat() if user.created_at else None
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка сервера: {str(e)}")

# Простой тест регистрации через GET
@app.get("/api/test_register")
async def test_register(db: Session = Depends(get_db)):
    try:
        # Создаем дополнительных тестовых пользователей
        test_users = [
            User(
                username="testuser",
                email="test@example.com",
                display_name="Test User",
                password_hash=get_password_hash("test123"),
                is_online=False
            ),
            User(
                username="developer",
                email="dev@example.com", 
                display_name="Developer",
                password_hash=get_password_hash("dev123"),
                is_online=False
            )
        ]
        
        for user in test_users:
            # Проверяем нет ли уже такого пользователя
            existing = db.query(User).filter(User.username == user.username).first()
            if not existing:
                db.add(user)
        
        db.commit()
        
        return {
            "success": True,
            "message": "Тестовые пользователи созданы! Пароли: test123 / dev123"
        }
        
    except Exception as e:
        return {"error": str(e)}

# Получение всех пользователей
@app.get("/api/users")
async def get_all_users(request: Request, db: Session = Depends(get_db)):
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

# Получение информации о конкретном пользователе
@app.get("/api/users/{user_id}")
async def get_user(user_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        token = request.cookies.get("access_token")
        if not token:
            raise HTTPException(status_code=401, detail="Требуется аутентификация")
        
        payload = verify_token(token)
        if not payload:
            raise HTTPException(status_code=401, detail="Недействительный токен")
        
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return JSONResponse(
                status_code=404,
                content={"detail": "Пользователь не найден"}
            )
        
        return {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "display_name": user.display_name,
            "is_online": user.is_online or False,
            "last_login": user.last_login.isoformat() if user.last_login else None,
            "created_at": user.created_at.isoformat() if user.created_at else None
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка сервера: {str(e)}")

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
            
            # Сохраняем в базу данных
            db = SessionLocal()
            try:
                # Проверяем существует ли получатель
                receiver = db.query(User).filter(User.id == message_data["to_user_id"]).first()
                if not receiver:
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "message": "Пользователь не найден"
                    }))
                    continue
                
                db_message = Message(
                    from_user_id=user_id,
                    to_user_id=message_data["to_user_id"],
                    content=message_data["content"],
                    message_type=message_data.get("type", "text")
                )
                db.add(db_message)
                db.commit()
                db.refresh(db_message)
                
                # Отправляем получателю если он онлайн
                await manager.send_personal_message(
                    json.dumps({
                        "type": "message",
                        "id": db_message.id,
                        "from_user_id": user_id,
                        "to_user_id": message_data["to_user_id"],
                        "content": message_data["content"],
                        "timestamp": db_message.created_at.isoformat()
                    }),
                    message_data["to_user_id"]
                )
                
                # Подтверждение отправки отправителю
                await websocket.send_text(json.dumps({
                    "type": "message_sent",
                    "id": db_message.id,
                    "to_user_id": message_data["to_user_id"],
                    "timestamp": db_message.created_at.isoformat()
                }))
                
            except Exception as e:
                db.rollback()
                print(f"❌ Database error: {e}")
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": f"Ошибка отправки: {str(e)}"
                }))
            finally:
                db.close()
                
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

# API для получения истории сообщений
@app.get("/api/messages/{user_id}/{other_user_id}")
async def get_message_history(user_id: int, other_user_id: int, db: Session = Depends(get_db)):
    try:
        messages = db.query(Message).filter(
            ((Message.from_user_id == user_id) & (Message.to_user_id == other_user_id)) |
            ((Message.from_user_id == other_user_id) & (Message.to_user_id == user_id))
        ).order_by(Message.created_at.asc()).all()
        
        print(f"📨 Загружено {len(messages)} сообщений между пользователями {user_id} и {other_user_id}")
        
        return [
            {
                "id": msg.id,
                "from_user_id": msg.from_user_id,
                "to_user_id": msg.to_user_id,
                "content": msg.content,
                "type": msg.message_type,
                "timestamp": msg.created_at.isoformat(),
                "is_my_message": msg.from_user_id == user_id
            }
            for msg in messages
        ]
        
    except Exception as e:
        print(f"❌ Ошибка загрузки сообщений: {e}")
        return JSONResponse(
            status_code=500,
            content={"detail": f"Ошибка загрузки истории сообщений: {str(e)}"}
        )

# API для удаления истории чата (только для меня)
@app.delete("/api/messages/for-me/{user_id}/{other_user_id}")
async def delete_chat_history_for_me(
    user_id: int, 
    other_user_id: int, 
    db: Session = Depends(get_db)
):
    try:
        print(f"🗑️ Удаление истории чата для пользователя {user_id} с {other_user_id}")
        
        # Удаляем только сообщения, где текущий пользователь является отправителем
        deleted_count = db.query(Message).filter(
            (Message.from_user_id == user_id) & (Message.to_user_id == other_user_id)
        ).delete()
        
        db.commit()
        
        print(f"✅ Удалено {deleted_count} сообщений (только для меня)")
        
        return {
            "success": True,
            "deleted_count": deleted_count,
            "deleted_for": "me",
            "message": f"История чата удалена для вас ({deleted_count} сообщений)"
        }
        
    except Exception as e:
        db.rollback()
        print(f"❌ Ошибка удаления чата: {e}")
        return JSONResponse(
            status_code=500,
            content={"detail": f"Ошибка удаления чата: {str(e)}"}
        )

# API для удаления истории чата (для всех)
@app.delete("/api/messages/for-all/{user_id}/{other_user_id}")
async def delete_chat_history_for_all(
    user_id: int, 
    other_user_id: int, 
    db: Session = Depends(get_db)
):
    try:
        print(f"🗑️ Удаление истории чата для всех между {user_id} и {other_user_id}")
        
        # Удаляем все сообщения между пользователями
        deleted_count = db.query(Message).filter(
            ((Message.from_user_id == user_id) & (Message.to_user_id == other_user_id)) |
            ((Message.from_user_id == other_user_id) & (Message.to_user_id == user_id))
        ).delete()
        
        db.commit()
        
        print(f"✅ Удалено {deleted_count} сообщений (для всех)")
        
        # Отправляем уведомление другому пользователю через WebSocket если он онлайн
        await manager.send_personal_message(
            json.dumps({
                "type": "chat_deleted",
                "deleted_by": user_id,
                "message": "История чата была удалена"
            }),
            other_user_id
        )
        
        return {
            "success": True,
            "deleted_count": deleted_count,
            "deleted_for": "all",
            "message": f"История чата удалена для всех участников ({deleted_count} сообщений)"
        }
        
    except Exception as e:
        db.rollback()
        print(f"❌ Ошибка удаления чата: {e}")
        return JSONResponse(
            status_code=500,
            content={"detail": f"Ошибка удаления чата: {str(e)}"}
        )

# API для удаления одного сообщения
@app.delete("/api/message/{message_id}")
async def delete_message(message_id: int, db: Session = Depends(get_db)):
    try:
        message_id = int(message_id)
        message = db.query(Message).filter(Message.id == message_id).first()
        if not message:
            return JSONResponse(
                status_code=404,
                content={"detail": "Сообщение не найдено"}
            )
        
        db.delete(message)
        db.commit()
        
        return {
            "success": True,
            "message": "Сообщение удалено"
        }
        
    except ValueError:
        return JSONResponse(
            status_code=400,
            content={"detail": "Неверный ID сообщения"}
        )
    except Exception as e:
        db.rollback()
        return JSONResponse(
            status_code=500,
            content={"detail": f"Ошибка удаления сообщения: {str(e)}"}
        )

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
