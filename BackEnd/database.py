from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os

# Определяем среду выполнения
IS_RAILWAY = os.environ.get("RAILWAY_ENVIRONMENT") is not None
IS_PRODUCTION = os.environ.get("ENVIRONMENT") == "production"

# Выбираем БД в зависимости от среды
if IS_RAILWAY:
    # На Railway используем in-memory SQLite
    DATABASE_URL = "sqlite:///:memory:"
    print("🚂 Running on Railway - using IN-MEMORY SQLite")
    print("⚠️  WARNING: All data will be lost on app restart!")
else:
    # Локально используем файловую SQLite
    DATABASE_URL = "sqlite:///./devnet.db"
    print("💻 Running locally - using file-based SQLite")

print(f"🔧 Database URL: {DATABASE_URL}")

try:
    if DATABASE_URL == "sqlite:///:memory:":
        # In-memory SQLite для Railway
        engine = create_engine(
            DATABASE_URL,
            connect_args={"check_same_thread": False},
            echo=False  # Отключаем логи SQL для производительности
        )
        print("✅ In-memory SQLite engine created")
    else:
        # Файловая SQLite для локальной разработки
        engine = create_engine(
            DATABASE_URL,
            connect_args={"check_same_thread": False},
            echo=True  # Включаем логи для отладки
        )
        print("✅ File-based SQLite engine created")
        
except Exception as e:
    print(f"❌ Database connection failed: {e}")
    raise

# Создаем сессию для работы с базой
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Базовый класс для моделей
Base = declarative_base()

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
        # Импортируем модели чтобы SQLAlchemy их зарегистрировал
        from models import (
            User, Message, Group, GroupMember, Channel, 
            Subscription, File, Reaction, Notification
        )
        
        # Создаем все таблицы
        Base.metadata.create_all(bind=engine)
        print("✅ Database tables created successfully")
        
    except Exception as e:
        print(f"⚠️  Error importing models: {e}")
        try:
            # Пытаемся создать таблицы без импорта моделей
            Base.metadata.create_all(bind=engine)
            print("✅ Database tables created successfully (without models import)")
        except Exception as e2:
            print(f"❌ Error creating tables: {e2}")
