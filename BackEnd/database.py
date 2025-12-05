from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os

# Создаем Base здесь, чтобы импортировать во всех файлах
Base = declarative_base()

# Определяем среду выполнения
IS_RAILWAY = os.environ.get("RAILWAY_ENVIRONMENT") is not None

# Выбираем БД в зависимости от среды
if IS_RAILWAY:
    DATABASE_URL = "sqlite:///:memory:"
    print("🚂 Running on Railway - using IN-MEMORY SQLite")
    print("⚠️  WARNING: All data will be lost on app restart!")
else:
    DATABASE_URL = "sqlite:///./devnet.db"
    print("💻 Running locally - using file-based SQLite")

print(f"🔧 Database URL: {DATABASE_URL}")

try:
    if DATABASE_URL == "sqlite:///:memory:":
        # In-memory SQLite для Railway
        engine = create_engine(
            DATABASE_URL,
            connect_args={"check_same_thread": False},
            echo=False
        )
        print("✅ In-memory SQLite engine created")
    else:
        # Файловая SQLite для локальной разработки
        engine = create_engine(
            DATABASE_URL,
            connect_args={"check_same_thread": False},
            echo=True
        )
        print("✅ File-based SQLite engine created")
        
except Exception as e:
    print(f"❌ Database connection failed: {e}")
    raise

# Создаем сессию для работы с базой
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Функция для получения сессии БД
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Функция для инициализации базы данных
def init_database():
    """Создает все таблицы в базе данных"""
    try:
        # Импортируем модели здесь, после создания Base
        from models import (
            User, Group, Channel, Subscription, 
            GroupMember, Message, Reaction, File, Notification
        )
        
        # Создаем все таблицы
        Base.metadata.create_all(bind=engine)
        print("✅ Database tables created successfully")
        
    except Exception as e:
        print(f"❌ Error initializing database: {e}")
        raise
