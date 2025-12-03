import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Попробуем PostgreSQL, если нет - SQLite
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./devnet_messenger.db")

# Если это PostgreSQL URL, заменим начало для SQLAlchemy
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

try:
    engine = create_engine(DATABASE_URL)
    print(f"✅ Database engine created: {DATABASE_URL}")
except Exception as e:
    print(f"❌ Failed to connect to database: {e}")
    print(f"🔧 Fallback to SQLite: sqlite:///./devnet_messenger.db")
    DATABASE_URL = "sqlite:///./devnet_messenger.db"
    engine = create_engine(
        DATABASE_URL, connect_args={"check_same_thread": False}
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
