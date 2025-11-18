import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Настройка подключения к базе данных
# Для Railway используем DATABASE_URL, для локальной разработки - SQLite
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./devnet.db")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Создаем движок
engine = create_engine(DATABASE_URL)

# Для SQLite добавляем специальные параметры
if "sqlite" in DATABASE_URL:
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False}
    )

# Создаем фабрику сессий
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Зависимость для получения сессии базы данных
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

print("✅ Database engine and session created successfully!")