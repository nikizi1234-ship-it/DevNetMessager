from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
import os

SECRET_KEY = os.getenv("SECRET_KEY", "devnet-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 7

# Настройка CryptContext с правильными параметрами
pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__max_password_length=72,  # Явно указываем ограничение
    bcrypt__default_rounds=12  # Оптимальное количество раундов для баланса безопасности/производительности
)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Проверяет пароль с безопасным сравнением"""
    try:
        return pwd_context.verify(plain_password[:72], hashed_password)  # Обрезаем до 72 байт
    except Exception:
        return False

def get_password_hash(password: str) -> str:
    """Хэширует пароль с безопасной обрезкой"""
    # Bcrypt имеет ограничение 72 байта, обрезаем для безопасности
    truncated_password = password[:72]
    return pwd_context.hash(truncated_password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Создает JWT токен"""
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    
    to_encode.update({"exp": expire})
    
    try:
        encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
        return encoded_jwt
    except JWTError as e:
        raise ValueError(f"Ошибка создания токена: {str(e)}")

def verify_token(token: str) -> Optional[dict]:
    """Проверяет и декодирует JWT токен"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None
