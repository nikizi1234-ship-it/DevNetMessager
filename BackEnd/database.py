from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os

# Пробуем PostgreSQL из Railway, если нет - используем SQLite
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./devnet.db")

# Исправляем URL для SQLAlchemy (Railway использует postgres://, а нужно postgresql://)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

print(f"🔧 Database URL: {DATABASE_URL}")

try:
    # Пытаемся подключиться к базе
    engine = create_engine(DATABASE_URL)
    print("✅ Database engine created successfully")
except Exception as e:
    print(f"❌ Database connection failed: {e}")
    print("🔧 Fallback to SQLite: sqlite:///./devnet.db")
    # Используем SQLite как резервный вариант
    DATABASE_URL = "sqlite:///./devnet.db"
    engine = create_engine(
        DATABASE_URL, 
        connect_args={"check_same_thread": False}
    )

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
