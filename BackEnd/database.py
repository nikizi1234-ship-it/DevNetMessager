import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import re

def parse_database_url(database_url):
    """Парсит DATABASE_URL и исправляет проблему с портом"""
    if not database_url:
        return "sqlite:///./devnet_messenger.db"
    
    # Заменяем postgres:// на postgresql://
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    
    # Если порт указан как 'port', заменяем на стандартный 5432
    if 'port' in database_url:
        database_url = re.sub(r':port', ':5432', database_url)
    
    return database_url

# Получаем и парсим URL базы данных
DATABASE_URL = parse_database_url(os.environ.get("DATABASE_URL"))

print(f"🔧 Database URL: {DATABASE_URL}")

# Создаем движок базы данных
try:
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
        pool_pre_ping=True,  # Проверка соединения перед использованием
        echo=False  # Убрать в продакшене для производительности
    )
    
    # Тестируем подключение
    with engine.connect() as conn:
        print("✅ Database connection successful!")
        
except Exception as e:
    print(f"❌ Database connection failed: {e}")
    # Fallback to SQLite
    DATABASE_URL = "sqlite:///./devnet_messenger.db"
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False}
    )
    print(f"🔧 Fallback to SQLite: {DATABASE_URL}")

# Создаем фабрику сессий
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Базовый класс для моделей
Base = declarative_base()

# Зависимость для получения сессии базы данных
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

print("✅ Database engine and session created successfully!")
