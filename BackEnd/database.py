from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os

# В Railway используем SQLite в постоянной директории /data
# чтобы файл не терялся при перезапусках
if os.environ.get("RAILWAY_ENVIRONMENT"):
    # В Railway
    SQLITE_PATH = "/data/devnet.db"
    print("🚂 Running on Railway, using persistent storage at /data/")
else:
    # Локально
    SQLITE_PATH = "./devnet.db"
    print("💻 Running locally")

DATABASE_URL = f"sqlite:///{SQLITE_PATH}"
print(f"🔧 Database URL: {DATABASE_URL}")

# Создаем директорию если не существует (для Railway)
if SQLITE_PATH.startswith("/data/"):
    os.makedirs(os.path.dirname(SQLITE_PATH), exist_ok=True)

try:
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        pool_pre_ping=True
    )
    print("✅ SQLite database engine created successfully")
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
