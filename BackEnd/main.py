from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, Form, Request, File, UploadFile, Query, status, Response, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session, relationship, joinedload
from sqlalchemy import desc, func, or_, and_, text, Column, Integer, String, Boolean, DateTime, Text, ForeignKey, JSON, LargeBinary, Float
from sqlalchemy.orm import declarative_base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import json
from datetime import datetime, timedelta
from pathlib import Path
import uvicorn 
import os
import sys
import shutil
import uuid
from typing import Optional, List, Dict, Any, Tuple, Set
import hashlib
import secrets
import asyncio
import time
from io import BytesIO
from PIL import Image
import logging
from pydantic import BaseModel
import random
import string
import base64
import bcrypt
import jwt as pyjwt
from cryptography.fernet import Fernet
import io
import aiofiles
import zipfile
import tarfile
import mimetypes
from typing import Tuple
from concurrent.futures import ThreadPoolExecutor
import threading

# ========== НАСТРОЙКА ЛОГГИРОВАНИЯ ==========

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('devnet_messenger.log')
    ]
)

logger = logging.getLogger(__name__)

# ========== КОНСТАНТЫ И НАСТРОЙКИ ==========

# Получаем настройки из окруженияя
DOMAIN = os.environ.get("DOMAIN", "localhost")
IS_PRODUCTION = os.environ.get("RAILWAY_ENVIRONMENT") is not None or os.environ.get("PRODUCTION") == "true"
SECRET_KEY = os.environ.get("SECRET_KEY", secrets.token_urlsafe(64))
ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY", Fernet.generate_key().decode())
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", 1440))  # 24 часа
REFRESH_TOKEN_EXPIRE_DAYS = int(os.environ.get("REFRESH_TOKEN_EXPIRE_DAYS", 30))  # 30 дней
MAX_UPLOAD_SIZE = int(os.environ.get("MAX_UPLOAD_SIZE", 100 * 1024 * 1024))  # 100 MB
MAX_MESSAGE_LENGTH = int(os.environ.get("MAX_MESSAGE_LENGTH", 10000))
MAX_USERS_PER_GROUP = int(os.environ.get("MAX_USERS_PER_GROUP", 1000))
MAX_SUBSCRIBERS_PER_CHANNEL = int(os.environ.get("MAX_SUBSCRIBERS_PER_CHANNEL", 10000))

logger.info(f"🌍 Domain: {DOMAIN}")
logger.info(f"🚀 Production mode: {IS_PRODUCTION}")
logger.info(f"🔐 Secret key length: {len(SECRET_KEY)}")
logger.info(f"🔑 Encryption key: {ENCRYPTION_KEY[:10]}...")

# ========== БАЗА ДАННЫХ ==========

# Настройка базы данных
SQLALCHEMY_DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./devnet.db")

# Для SQLite нужно специальное подключение
if SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
        echo=False
    )
else:
    # Для PostgreSQL/MySQL
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL, 
        pool_pre_ping=True,
        pool_size=20,
        max_overflow=100,
        echo=False
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    """Dependency для получения сессии БД"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ========== МОДЕЛИ БАЗЫ ДАННЫХ ==========

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    display_name = Column(String(100))
    avatar_url = Column(String(500))
    password_hash = Column(String(255), nullable=False)
    is_online = Column(Boolean, default=False)
    is_guest = Column(Boolean, default=False)
    is_admin = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    is_bot = Column(Boolean, default=False)
    status = Column(String(50), default="online")
    status_message = Column(String(200))
    last_ip = Column(String(45))
    last_user_agent = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = Column(DateTime)
    last_seen = Column(DateTime)
    settings = Column(JSON, default={"theme": "light", "notifications": True, "language": "ru"})
    bio = Column(Text)
    phone = Column(String(20))
    country = Column(String(50))
    timezone = Column(String(50))
    
    # Связи
    sent_messages = relationship("Message", foreign_keys="Message.from_user_id", back_populates="sender")
    received_messages = relationship("Message", foreign_keys="Message.to_user_id", back_populates="receiver")
    owned_groups = relationship("Group", foreign_keys="Group.owner_id", back_populates="owner")
    owned_channels = relationship("Channel", foreign_keys="Channel.owner_id", back_populates="owner")
    group_memberships = relationship("GroupMember", foreign_keys="GroupMember.user_id", back_populates="user", cascade="all, delete-orphan")
    channel_subscriptions = relationship("ChannelSubscription", foreign_keys="ChannelSubscription.user_id", back_populates="user", cascade="all, delete-orphan")
    refresh_tokens = relationship("RefreshToken", foreign_keys="RefreshToken.user_id", back_populates="user", cascade="all, delete-orphan")
    notifications = relationship("Notification", foreign_keys="Notification.user_id", back_populates="user", cascade="all, delete-orphan")
    call_logs = relationship("CallLog", foreign_keys="CallLog.caller_id", back_populates="user", cascade="all, delete-orphan")
    files = relationship("File", foreign_keys="File.user_id", back_populates="user", cascade="all, delete-orphan")
    reactions = relationship("MessageReaction", foreign_keys="MessageReaction.user_id", back_populates="user", cascade="all, delete-orphan")
    polls_voted = relationship("PollVote", foreign_keys="PollVote.user_id", back_populates="user", cascade="all, delete-orphan")
    contacts = relationship("Contact", foreign_keys="Contact.user_id", back_populates="user", cascade="all, delete-orphan")
    contact_of = relationship("Contact", foreign_keys="Contact.contact_id", back_populates="contact", cascade="all, delete-orphan")
    
class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token = Column(String(500), unique=True, index=True, nullable=False)
    device_id = Column(String(100))
    device_name = Column(String(200))
    ip_address = Column(String(45))
    user_agent = Column(Text)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_used = Column(DateTime, default=datetime.utcnow)
    is_revoked = Column(Boolean, default=False)
    
    # Связи
    user = relationship("User", back_populates="refresh_tokens")

class Message(Base):
    __tablename__ = "messages"
    
    id = Column(Integer, primary_key=True, index=True)
    from_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    to_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    group_id = Column(Integer, ForeignKey("groups.id", ondelete="CASCADE"), nullable=True)
    channel_id = Column(Integer, ForeignKey("channels.id", ondelete="CASCADE"), nullable=True)
    reply_to_id = Column(Integer, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    content = Column(Text)
    encrypted_content = Column(LargeBinary)
    message_type = Column(String(20), default="text")
    media_url = Column(String(500))
    media_size = Column(Integer)
    media_width = Column(Integer)
    media_height = Column(Integer)
    media_duration = Column(Integer)
    thumbnail_url = Column(String(500))
    filename = Column(String(255))
    file_size = Column(Integer)
    file_type = Column(String(100))
    reactions_summary = Column(JSON, default=dict)
    is_edited = Column(Boolean, default=False)
    is_deleted = Column(Boolean, default=False)
    is_pinned = Column(Boolean, default=False)
    is_encrypted = Column(Boolean, default=False)
    encryption_key = Column(String(500))
    read_by = Column(JSON, default=list)
    forwarded_from = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    forwarded_message_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime)
    
    # Связи - ВАЖНО: указываем явные foreign_keys
    sender = relationship("User", foreign_keys=[from_user_id], back_populates="sent_messages")
    receiver = relationship("User", foreign_keys=[to_user_id], back_populates="received_messages")
    group = relationship("Group", foreign_keys=[group_id], back_populates="messages")
    channel = relationship("Channel", foreign_keys=[channel_id], back_populates="messages")
    reply_to = relationship("Message", remote_side=[id], backref="replies")
    forwarded_from_user = relationship("User", foreign_keys=[forwarded_from])
    reactions = relationship("MessageReaction", foreign_keys="MessageReaction.message_id", back_populates="message", cascade="all, delete-orphan")
    polls = relationship("Poll", foreign_keys="Poll.message_id", back_populates="message", cascade="all, delete-orphan")
    files = relationship("File", foreign_keys="File.message_id", back_populates="message", cascade="all, delete-orphan")

class Group(Base):
    __tablename__ = "groups"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    avatar_url = Column(String(500))
    banner_url = Column(String(500))
    is_public = Column(Boolean, default=True)
    is_active = Column(Boolean, default=True)
    is_encrypted = Column(Boolean, default=False)
    encryption_key = Column(String(500))
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    members_count = Column(Integer, default=0)
    online_count = Column(Integer, default=0)
    max_members = Column(Integer, default=MAX_USERS_PER_GROUP)
    pinned_message_id = Column(Integer, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    invite_link = Column(String(100), unique=True)
    invite_expires = Column(DateTime)
    settings = Column(JSON, default={
        "allow_photos": True,
        "allow_videos": True,
        "allow_files": True,
        "allow_voice": True,
        "allow_polls": True,
        "allow_invites": True,
        "slow_mode": 0,
        "admin_only_posting": False
    })
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Связи
    owner = relationship("User", foreign_keys=[owner_id], back_populates="owned_groups")
    members = relationship("GroupMember", foreign_keys="GroupMember.group_id", back_populates="group", cascade="all, delete-orphan")
    messages = relationship("Message", foreign_keys="Message.group_id", back_populates="group", cascade="all, delete-orphan")
    pinned_message = relationship("Message", foreign_keys=[pinned_message_id])

class Channel(Base):
    __tablename__ = "channels"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    avatar_url = Column(String(500))
    banner_url = Column(String(500))
    is_public = Column(Boolean, default=True)
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    is_encrypted = Column(Boolean, default=False)
    encryption_key = Column(String(500))
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    subscribers_count = Column(Integer, default=0)
    online_count = Column(Integer, default=0)
    max_subscribers = Column(Integer, default=MAX_SUBSCRIBERS_PER_CHANNEL)
    pinned_message_id = Column(Integer, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    invite_link = Column(String(100), unique=True)
    invite_expires = Column(DateTime)
    settings = Column(JSON, default={
        "allow_comments": False,
        "allow_reactions": True,
        "allow_sharing": True,
        "slow_mode": 0,
        "admin_only_posting": True
    })
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Связи
    owner = relationship("User", foreign_keys=[owner_id], back_populates="owned_channels")
    subscribers = relationship("ChannelSubscription", foreign_keys="ChannelSubscription.channel_id", back_populates="channel", cascade="all, delete-orphan")
    messages = relationship("Message", foreign_keys="Message.channel_id", back_populates="channel", cascade="all, delete-orphan")
    pinned_message = relationship("Message", foreign_keys=[pinned_message_id])

class GroupMember(Base):
    __tablename__ = "group_members"
    
    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("groups.id", ondelete="CASCADE"))
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    role = Column(String(20), default="member")
    permissions = Column(JSON, default={
        "send_messages": True,
        "send_media": True,
        "add_members": False,
        "pin_messages": False,
        "change_group_info": False,
        "delete_messages": False,
        "ban_members": False
    })
    is_banned = Column(Boolean, default=False)
    banned_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    banned_at = Column(DateTime)
    ban_reason = Column(Text)
    joined_at = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime)
    last_message_read_id = Column(Integer, default=0)
    notification_settings = Column(JSON, default={"all_messages": True, "mentions_only": False, "muted": False})
    
    # Связи
    group = relationship("Group", foreign_keys=[group_id], back_populates="members")
    user = relationship("User", foreign_keys=[user_id], back_populates="group_memberships")
    banned_by_user = relationship("User", foreign_keys=[banned_by])

class ChannelSubscription(Base):
    __tablename__ = "channel_subscriptions"
    
    id = Column(Integer, primary_key=True, index=True)
    channel_id = Column(Integer, ForeignKey("channels.id", ondelete="CASCADE"))
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    role = Column(String(20), default="subscriber")
    permissions = Column(JSON, default={
        "view_messages": True,
        "send_reactions": True,
        "send_comments": False
    })
    is_banned = Column(Boolean, default=False)
    banned_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    banned_at = Column(DateTime)
    ban_reason = Column(Text)
    subscribed_at = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime)
    last_message_read_id = Column(Integer, default=0)
    notification_settings = Column(JSON, default={"all_messages": True, "mentions_only": False, "muted": False})
    
    # Связи - ЯВНО указываем foreign_keys
    channel = relationship("Channel", back_populates="subscribers")
    user = relationship("User", foreign_keys=[user_id], back_populates="channel_subscriptions")
    banned_by_user = relationship("User", foreign_keys=[banned_by])

class MessageReaction(Base):
    __tablename__ = "message_reactions"
    
    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(Integer, ForeignKey("messages.id", ondelete="CASCADE"))
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    reaction = Column(String(50), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Связи
    message = relationship("Message", back_populates="reactions")
    user = relationship("User", back_populates="reactions")

class Poll(Base):
    __tablename__ = "polls"
    
    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(Integer, ForeignKey("messages.id", ondelete="CASCADE"), unique=True)
    question = Column(Text, nullable=False)
    options = Column(JSON, nullable=False)
    is_multiple = Column(Boolean, default=False)
    is_anonymous = Column(Boolean, default=True)
    is_closed = Column(Boolean, default=False)
    closes_at = Column(DateTime)
    results = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Связи
    message = relationship("Message", back_populates="polls")
    votes = relationship("PollVote", back_populates="poll", cascade="all, delete-orphan")

class PollVote(Base):
    __tablename__ = "poll_votes"
    
    id = Column(Integer, primary_key=True, index=True)
    poll_id = Column(Integer, ForeignKey("polls.id", ondelete="CASCADE"))
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    option_index = Column(Integer, nullable=False)
    voted_at = Column(DateTime, default=datetime.utcnow)
    
    # Связи
    poll = relationship("Poll", back_populates="votes")
    user = relationship("User", back_populates="polls_voted")

class File(Base):
    __tablename__ = "files"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    message_id = Column(Integer, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    filename = Column(String(255), nullable=False)
    original_filename = Column(String(255))
    file_path = Column(String(500))
    file_url = Column(String(500))
    file_size = Column(Integer)
    file_type = Column(String(100))
    mime_type = Column(String(100))
    is_encrypted = Column(Boolean, default=False)
    encryption_key = Column(String(500))
    hash_md5 = Column(String(32))
    hash_sha256 = Column(String(64))
    thumbnail_url = Column(String(500))
    width = Column(Integer)
    height = Column(Integer)
    duration = Column(Integer)
    download_count = Column(Integer, default=0)
    is_public = Column(Boolean, default=False)
    expires_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Связи
    user = relationship("User", back_populates="files")
    message = relationship("Message", back_populates="files")

class Notification(Base):
    __tablename__ = "notifications"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    type = Column(String(50), nullable=False)
    title = Column(String(200))
    message = Column(Text)
    data = Column(JSON)
    is_read = Column(Boolean, default=False)
    is_important = Column(Boolean, default=False)
    action_url = Column(String(500))
    expires_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Связи
    user = relationship("User", back_populates="notifications")

class Contact(Base):
    __tablename__ = "contacts"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    contact_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    name = Column(String(100))
    phone = Column(String(20))
    email = Column(String(100))
    is_favorite = Column(Boolean, default=False)
    is_blocked = Column(Boolean, default=False)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Связи - ЯВНО указываем foreign_keys
    user = relationship("User", foreign_keys=[user_id], back_populates="contacts")
    contact = relationship("User", foreign_keys=[contact_id], back_populates="contact_of")

class CallLog(Base):
    __tablename__ = "call_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    call_id = Column(String(100), unique=True, index=True)
    caller_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    receiver_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    group_id = Column(Integer, ForeignKey("groups.id", ondelete="CASCADE"), nullable=True)
    channel_id = Column(Integer, ForeignKey("channels.id", ondelete="CASCADE"), nullable=True)
    call_type = Column(String(20), default="audio")
    status = Column(String(20), default="missed")
    start_time = Column(DateTime)
    end_time = Column(DateTime)
    duration = Column(Integer, default=0)
    is_video = Column(Boolean, default=False)
    is_group_call = Column(Boolean, default=False)
    participants = Column(JSON, default=list)
    recording_url = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Связи - ЯВНО указываем foreign_keys
    user = relationship("User", foreign_keys=[caller_id], back_populates="call_logs")
    receiver = relationship("User", foreign_keys=[receiver_id])
    group = relationship("Group")
    channel = relationship("Channel")

class EncryptionKey(Base):
    __tablename__ = "encryption_keys"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    chat_type = Column(String(20))
    chat_id = Column(Integer)
    public_key = Column(Text)
    private_key = Column(Text)
    symmetric_key = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)
    
    # Связи
    user = relationship("User")

class Session(Base):
    __tablename__ = "sessions"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    session_token = Column(String(500), unique=True, index=True)
    device_id = Column(String(100))
    device_name = Column(String(200))
    platform = Column(String(50))
    browser = Column(String(50))
    ip_address = Column(String(45))
    user_agent = Column(Text)
    last_activity = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Связи
    user = relationship("User")

class Report(Base):
    __tablename__ = "reports"
    
    id = Column(Integer, primary_key=True, index=True)
    reporter_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    reported_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    reported_group_id = Column(Integer, ForeignKey("groups.id", ondelete="CASCADE"), nullable=True)
    reported_channel_id = Column(Integer, ForeignKey("channels.id", ondelete="CASCADE"), nullable=True)
    reported_message_id = Column(Integer, ForeignKey("messages.id", ondelete="CASCADE"), nullable=True)
    report_type = Column(String(50))
    reason = Column(Text)
    description = Column(Text)
    status = Column(String(20), default="pending")
    admin_notes = Column(Text)
    resolved_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    resolved_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Связи - ЯВНО указываем foreign_keys
    reporter = relationship("User", foreign_keys=[reporter_id])
    reported_user = relationship("User", foreign_keys=[reported_user_id])
    reported_group = relationship("Group")
    reported_channel = relationship("Channel")
    reported_message = relationship("Message")
    resolver = relationship("User", foreign_keys=[resolved_by])

class AuditLog(Base):
    __tablename__ = "audit_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action = Column(String(100), nullable=False)
    resource_type = Column(String(50))
    resource_id = Column(Integer)
    details = Column(JSON)
    ip_address = Column(String(45))
    user_agent = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Связи
    user = relationship("User")

# Создаем таблицы
def create_tables():
    """Создает таблицы в базе данных"""
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("✅ Database tables created successfully")
    except Exception as e:
        logger.error(f"❌ Error creating database tables: {e}")
        raise

create_tables()

# ========== УТИЛИТЫ И ХЕЛПЕРЫ ==========

class EncryptionHelper:
    def __init__(self):
        self.cipher = Fernet(ENCRYPTION_KEY.encode() if isinstance(ENCRYPTION_KEY, str) else ENCRYPTION_KEY)
    
    def encrypt(self, data: str) -> bytes:
        """Шифрование данных"""
        return self.cipher.encrypt(data.encode())
    
    def decrypt(self, encrypted_data: bytes) -> str:
        """Дешифрование данных"""
        return self.cipher.decrypt(encrypted_data).decode()
    
    def encrypt_file(self, file_path: Path) -> bytes:
        """Шифрование файла"""
        with open(file_path, 'rb') as f:
            data = f.read()
        return self.cipher.encrypt(data)
    
    def decrypt_file(self, encrypted_data: bytes, output_path: Path):
        """Дешифрование файла"""
        decrypted_data = self.cipher.decrypt(encrypted_data)
        with open(output_path, 'wb') as f:
            f.write(decrypted_data)

encryption_helper = EncryptionHelper()

class FileHandler:
    ALLOWED_IMAGE_TYPES = ["image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp", "image/svg+xml"]
    ALLOWED_VIDEO_TYPES = ["video/mp4", "video/webm", "video/ogg", "video/quicktime", "video/x-msvideo"]
    ALLOWED_AUDIO_TYPES = ["audio/mpeg", "audio/ogg", "audio/wav", "audio/webm", "audio/x-m4a", "audio/mp4"]
    ALLOWED_DOCUMENT_TYPES = [
        "application/pdf",
        "text/plain",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-powerpoint",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/rtf",
        "text/csv",
        "application/json",
        "text/html",
        "text/xml"
    ]
    ALLOWED_ARCHIVE_TYPES = [
        "application/zip",
        "application/x-rar-compressed",
        "application/x-tar",
        "application/gzip",
        "application/x-7z-compressed"
    ]
    
    @staticmethod
    def get_file_type(mime_type: str) -> str:
        """Определение типа файла по MIME типу"""
        if mime_type.startswith('image/'):
            return 'image'
        elif mime_type.startswith('video/'):
            return 'video'
        elif mime_type.startswith('audio/'):
            return 'audio'
        elif mime_type in FileHandler.ALLOWED_DOCUMENT_TYPES:
            return 'document'
        elif mime_type in FileHandler.ALLOWED_ARCHIVE_TYPES:
            return 'archive'
        else:
            return 'file'
    
    @staticmethod
    def generate_thumbnail(image_path: Path, max_size: Tuple[int, int] = (300, 300)) -> Optional[BytesIO]:
        """Генерация миниатюры для изображения"""
        try:
            with Image.open(image_path) as img:
                img.thumbnail(max_size)
                
                # Конвертируем в RGB если нужно
                if img.mode in ('RGBA', 'LA'):
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else img)
                    img = background
                
                thumb_buffer = BytesIO()
                img.save(thumb_buffer, format='JPEG', quality=85)
                thumb_buffer.seek(0)
                return thumb_buffer
        except Exception as e:
            logger.error(f"Error generating thumbnail: {e}")
            return None
    
    @staticmethod
    def get_file_hash(file_path: Path) -> Tuple[str, str]:
        """Вычисление хешей файла"""
        md5_hash = hashlib.md5()
        sha256_hash = hashlib.sha256()
        
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                md5_hash.update(chunk)
                sha256_hash.update(chunk)
        
        return md5_hash.hexdigest(), sha256_hash.hexdigest()
    
    @staticmethod
    def is_allowed_file(file: UploadFile) -> Tuple[bool, str]:
        """Проверка разрешен ли файл"""
        # Получаем MIME тип из content_type или расширения файла
        mime_type = file.content_type
        
        # Если content_type не указан, пробуем определить по расширению
        if not mime_type or mime_type == 'application/octet-stream':
            mime_type, _ = mimetypes.guess_type(file.filename)
        
        if not mime_type:
            return False, "Не удалось определить тип файла"
        
        # Проверяем все разрешенные типы
        allowed_types = (
            FileHandler.ALLOWED_IMAGE_TYPES +
            FileHandler.ALLOWED_VIDEO_TYPES +
            FileHandler.ALLOWED_AUDIO_TYPES +
            FileHandler.ALLOWED_DOCUMENT_TYPES +
            FileHandler.ALLOWED_ARCHIVE_TYPES
        )
        
        if mime_type not in allowed_types:
            return False, f"Тип файла {mime_type} не поддерживается"
        
        return True, ""

class PasswordHelper:
    @staticmethod
    def hash_password(password: str) -> str:
        """Хеширование пароля с помощью bcrypt"""
        # Обрезаем пароль если слишком длинный
        password_bytes = password[:72].encode() if len(password) > 72 else password.encode()
        salt = bcrypt.gensalt(rounds=12)
        hashed = bcrypt.hashpw(password_bytes, salt)
        return hashed.decode()
    
    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """Проверка пароля"""
        try:
            password_bytes = plain_password[:72].encode() if len(plain_password) > 72 else plain_password.encode()
            hashed_bytes = hashed_password.encode()
            return bcrypt.checkpw(password_bytes, hashed_bytes)
        except Exception as e:
            logger.error(f"Password verification error: {e}")
            return False
    
    @staticmethod
    def generate_password(length: int = 12) -> str:
        """Генерация случайного пароля"""
        chars = string.ascii_letters + string.digits + "!@#$%^&*"
        return ''.join(secrets.choice(chars) for _ in range(length))

class TokenHelper:
    @staticmethod
    def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
        """Создание JWT access токена"""
        to_encode = data.copy()
        
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        
        to_encode.update({
            "exp": expire,
            "iat": datetime.utcnow(),
            "type": "access",
            "jti": secrets.token_urlsafe(32)
        })
        
        encoded_jwt = pyjwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
        return encoded_jwt
    
    @staticmethod
    def verify_token(token: str) -> Optional[dict]:
        """Проверка JWT токена"""
        try:
            payload = pyjwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            return payload
        except pyjwt.ExpiredSignatureError:
            logger.warning("Token has expired")
            return None
        except pyjwt.InvalidTokenError as e:
            logger.error(f"Invalid token: {e}")
            return None
    
    @staticmethod
    def create_session_token(user_id: int, device_info: Dict[str, Any]) -> str:
        """Создание сессионного токена"""
        token = secrets.token_urlsafe(64)
        return token

class RateLimiter:
    def __init__(self, max_requests: int, time_window: int):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = {}
        self.lock = threading.Lock()
    
    def is_allowed(self, key: str) -> Tuple[bool, int]:
        """Проверка не превышен ли лимит запросов"""
        with self.lock:
            current_time = time.time()
            
            if key not in self.requests:
                self.requests[key] = []
            
            # Удаляем старые записи
            self.requests[key] = [
                req_time for req_time in self.requests[key]
                if current_time - req_time < self.time_window
            ]
            
            if len(self.requests[key]) < self.max_requests:
                self.requests[key].append(current_time)
                return True, 0
            
            # Считаем время до следующего разрешенного запроса
            oldest_request = self.requests[key][0]
            wait_time = self.time_window - (current_time - oldest_request)
            return False, int(wait_time)

# Инициализируем rate limiter
rate_limiter = RateLimiter(max_requests=100, time_window=60)  # 100 запросов в минуту

# ========== АВТОРИЗАЦИЯ И СЕССИИ ==========

def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
    require_auth: bool = True
) -> Optional[User]:
    """Получение текущего пользователя"""
    # Пробуем получить токен из разных источников
    token = None
    
    # 1. Из cookies
    try:
        # Получаем cookies из request
        if hasattr(request, 'cookies'):
            token = request.cookies.get("access_token")
    except Exception as e:
        logger.warning(f"Error getting cookies: {e}")
        pass
    
    # 2. Из заголовка Authorization
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
    
    # 3. Из query параметра
    if not token:
        token = request.query_params.get("token")
    
    if not token:
        if require_auth:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Требуется аутентификация",
                headers={"WWW-Authenticate": "Bearer"},
            )
        else:
            return None
    
    # Проверяем rate limit
    client_ip = request.client.host if request.client else "unknown"
    allowed, wait_time = rate_limiter.is_allowed(f"auth_{client_ip}")
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Слишком много запросов. Попробуйте через {wait_time} секунд"
        )
    
    payload = TokenHelper.verify_token(token)
    if not payload:
        if require_auth:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Недействительный или просроченный токен",
                headers={"WWW-Authenticate": "Bearer"},
            )
        else:
            return None
    
    user_id = payload.get("user_id")
    if not user_id:
        if require_auth:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Неверный формат токена",
            )
        else:
            return None
    
    user = db.query(User).filter(User.id == user_id).first()
    
    if not user:
        if require_auth:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Пользователь не найден"
            )
        else:
            return None
    
    if not user.is_active:
        if require_auth:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Пользователь заблокирован"
            )
        else:
            return None
    
    # Обновляем время последней активности
    user.last_seen = datetime.utcnow()
    
    # Обновляем IP и user agent
    user.last_ip = client_ip
    user.last_user_agent = request.headers.get("User-Agent")
    
    db.commit()
    
    logger.info(f"✅ User authenticated: {user.username} (ID: {user.id})")
    return user

def set_auth_cookies(
    response: Response,
    access_token: str,
    refresh_token: Optional[str] = None
):
    """Установка cookies для аутентификации"""
    # Настройки cookies
    cookie_settings = {
        "httponly": True,
        "samesite": "lax" if IS_PRODUCTION else "none",
        "secure": IS_PRODUCTION,
        "path": "/"
    }
    
    # Добавляем домен если не localhost
    if DOMAIN != "localhost":
        cookie_settings["domain"] = DOMAIN
    
    # Устанавливаем access token cookie
    response.set_cookie(
        key="access_token",
        value=access_token,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        **cookie_settings
    )
    
    # Устанавливаем refresh token cookie если есть
    if refresh_token:
        response.set_cookie(
            key="refresh_token",
            value=refresh_token,
            max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
            **cookie_settings
        )

def clear_auth_cookies(response: Response):
    """Очистка auth cookies"""
    cookie_settings = {
        "path": "/"
    }
    
    if DOMAIN != "localhost":
        cookie_settings["domain"] = DOMAIN
    
    response.delete_cookie("access_token", **cookie_settings)
    response.delete_cookie("refresh_token", **cookie_settings)
    response.delete_cookie("session_token", **cookie_settings)

# ========== СОЗДАНИЕ ТЕСТОВЫХ ДАННЫХ ==========

def create_initial_data():
    """Создание начальных данных в базе"""
    db = SessionLocal()
    try:
        # Проверяем, есть ли уже данные
        users_count = db.query(User).count()
        if users_count > 0:
            logger.info("✅ Database already has data, skipping initial data creation")
            return
        
        logger.info("👑 Создаем администратора...")
        
        # Создаем администратора
        admin_user = User(
            username="admin",
            email="admin@devnet.local",
            display_name="Администратор Системы",
            password_hash=PasswordHelper.hash_password("admin123"),
            is_admin=True,
            is_active=True,
            is_verified=True,
            status="online",
            bio="Системный администратор DevNet Messenger",
            last_login=datetime.utcnow(),
            last_seen=datetime.utcnow(),
            settings={
                "theme": "dark",
                "notifications": True,
                "language": "ru",
                "privacy": "public",
                "auto_download": False
            }
        )
        db.add(admin_user)
        
        # Создаем тестовых пользователей
        test_users = [
            ("alice", "alice@devnet.local", "Алиса", "alice123", "Привет! Я Алиса!", "online"),
            ("bob", "bob@devnet.local", "Боб", "bob123", "Программист и геймер", "online"),
            ("charlie", "charlie@devnet.local", "Чарли", "charlie123", "Дизайнер интерфейсов", "away"),
            ("david", "david@devnet.local", "Давид", "david123", "Люблю путешествия", "offline"),
            ("eve", "eve@devnet.local", "Ева", "eve123", "Фотограф и блогер", "online"),
            ("frank", "frank@devnet.local", "Фрэнк", "frank123", "Системный аналитик", "busy"),
            ("grace", "grace@devnet.local", "Грейс", "grace123", "Менеджер проектов", "online"),
            ("henry", "henry@devnet.local", "Генри", "henry123", "Разработчик игр", "away"),
        ]
        
        for username, email, display_name, password, bio, status in test_users:
            user = User(
                username=username,
                email=email,
                display_name=display_name,
                password_hash=PasswordHelper.hash_password(password),
                is_active=True,
                is_verified=True,
                status=status,
                bio=bio,
                last_login=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                settings={
                    "theme": "light",
                    "notifications": True,
                    "language": "ru"
                }
            )
            db.add(user)
        
        db.commit()
        
        # Получаем всех пользователей для создания связей
        admin = db.query(User).filter(User.username == "admin").first()
        users = db.query(User).filter(User.username.in_([u[0] for u in test_users])).all()
        
        # Создаем общую группу
        logger.info("👥 Создаем общую группу...")
        
        general_group = Group(
            name="Общий чат",
            description="Основной чат для всех пользователей DevNet Messenger",
            is_public=True,
            owner_id=admin.id,
            members_count=len(users) + 1,
            settings={
                "allow_photos": True,
                "allow_videos": True,
                "allow_files": True,
                "allow_voice": True,
                "allow_polls": True,
                "allow_invites": True,
                "slow_mode": 0,
                "admin_only_posting": False
            },
            invite_link=secrets.token_urlsafe(16),
            invite_expires=datetime.utcnow() + timedelta(days=30)
        )
        db.add(general_group)
        db.commit()
        db.refresh(general_group)
        
        # Добавляем всех пользователей в группу
        for user in [admin] + users:
            group_member = GroupMember(
                group_id=general_group.id,
                user_id=user.id,
                role="admin" if user.username == "admin" else "member",
                permissions={
                    "send_messages": True,
                    "send_media": True,
                    "add_members": user.username in ["admin", "alice", "bob"],
                    "pin_messages": user.username in ["admin", "alice"],
                    "change_group_info": user.username == "admin",
                    "delete_messages": user.username in ["admin", "alice", "bob"],
                    "ban_members": user.username == "admin"
                }
            )
            db.add(group_member)
        
        # Создаем тестовый канал
        logger.info("📢 Создаем тестовый канал...")
        
        news_channel = Channel(
            name="Новости проекта",
            description="Официальные новости и анонсы DevNet Messenger",
            is_public=True,
            is_verified=True,
            owner_id=admin.id,
            subscribers_count=len(users) + 1,
            settings={
                "allow_comments": True,
                "allow_reactions": True,
                "allow_sharing": True,
                "slow_mode": 5,
                "admin_only_posting": True
            },
            invite_link=secrets.token_urlsafe(16),
            invite_expires=datetime.utcnow() + timedelta(days=30)
        )
        db.add(news_channel)
        db.commit()
        db.refresh(news_channel)
        
        # Подписываем всех пользователей на канал
        for user in [admin] + users:
            subscription = ChannelSubscription(
                channel_id=news_channel.id,
                user_id=user.id,
                role="admin" if user.username == "admin" else "subscriber",
                permissions={
                    "view_messages": True,
                    "send_reactions": True,
                    "send_comments": user.username in ["admin", "alice", "bob"]
                }
            )
            db.add(subscription)
        
        # Создаем тестовые сообщения
        logger.info("💬 Создаем тестовые сообщения...")
        
        welcome_messages = [
            (admin.id, general_group.id, None, "text", "Добро пожаловать в DevNet Messenger! 🎉", None),
            (users[0].id, general_group.id, None, "text", "Привет всем! Рада быть здесь! 👋", None),
            (users[1].id, general_group.id, None, "text", "Кто хочет поиграть в Counter-Strike? 🎮", None),
            (users[2].id, general_group.id, None, "text", "Работаю над новым дизайном интерфейса ✨", None),
            (users[3].id, general_group.id, None, "text", "Вернулся из отпуска, было классно! 🌴", None),
            (users[4].id, general_group.id, None, "text", "Выложила новые фото в блог 📸", None),
            (admin.id, None, news_channel.id, "text", "🎯 Запуск DevNet Messenger версии 2.0!", None),
            (admin.id, None, news_channel.id, "text", "📢 Добавлена поддержка голосовых сообщений!", None),
            (admin.id, None, news_channel.id, "text", "🔒 Улучшена безопасность и шифрование", None),
        ]
        
        for from_user_id, group_id, channel_id, msg_type, content, media_url in welcome_messages:
            message = Message(
                from_user_id=from_user_id,
                group_id=group_id,
                channel_id=channel_id,
                content=content,
                message_type=msg_type,
                created_at=datetime.utcnow() - timedelta(hours=random.randint(1, 24))
            )
            db.add(message)
        
        # Создаем личные сообщения
        logger.info("💌 Создаем тестовые личные сообщения...")
        
        private_messages = [
            (users[0].id, users[1].id, "Привет, Боб! Как дела?"),
            (users[1].id, users[0].id, "Привет, Алиса! Всё отлично, работаю над проектом."),
            (users[0].id, users[1].id, "Помнишь, мы обсуждали встречу?"),
            (users[1].id, users[0].id, "Да, конечно! Предлагаю в пятницу в 18:00."),
            (admin.id, users[2].id, "Чарли, нужно обсудить новый дизайн."),
            (users[2].id, admin.id, "Готов, у меня есть несколько концептов."),
        ]
        
        for from_user_id, to_user_id, content in private_messages:
            message = Message(
                from_user_id=from_user_id,
                to_user_id=to_user_id,
                content=content,
                message_type="text",
                created_at=datetime.utcnow() - timedelta(hours=random.randint(1, 48))
            )
            db.add(message)
        
        # Создаем контакты
        logger.info("📇 Создаем тестовые контакты...")
        
        for user in users[:3]:
            contact = Contact(
                user_id=admin.id,
                contact_id=user.id,
                name=user.display_name,
                is_favorite=user.username in ["alice", "bob"],
                notes=f"Тестовый контакт {user.username}"
            )
            db.add(contact)
        
        # Создаем тестовый опрос
        logger.info("📊 Создаем тестовый опрос...")
        
        poll_message = Message(
            from_user_id=admin.id,
            group_id=general_group.id,
            content="Какой функционал добавить в следующем обновлении?",
            message_type="poll",
            created_at=datetime.utcnow() - timedelta(hours=2)
        )
        db.add(poll_message)
        db.commit()
        db.refresh(poll_message)
        
        poll = Poll(
            message_id=poll_message.id,
            question="Какой функционал добавить в следующем обновлении?",
            options=[
                "Видеозвонки групповые",
                "Стикеры и GIF",
                "Редактор кода в чате",
                "Интеграция с GitHub",
                "Тёмная тема улучшенная"
            ],
            is_multiple=True,
            is_anonymous=False,
            closes_at=datetime.utcnow() + timedelta(days=7)
        )
        db.add(poll)
        
        db.commit()
        
        logger.info("✅ Начальные данные созданы успешно")
        logger.info("👑 Администратор: admin / admin123")
        logger.info("👤 Тестовые пользователи:")
        for username, _, display_name, password, _, _ in test_users:
            logger.info(f"   - {username} ({display_name}) / {password}")
        
    except Exception as e:
        logger.error(f"❌ Ошибка создания начальных данных: {e}")
        db.rollback()
        raise
    finally:
        db.close()

# Запускаем создание начальных данных
try:
    create_initial_data()
except Exception as e:
    logger.error(f"Failed to create initial data: {e}")

# ========== WEBSOCKET MANAGER ==========

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, WebSocket] = {}
        self.user_connections: Dict[int, List[WebSocket]] = {}
        self.user_devices: Dict[int, Dict[str, Any]] = {}
        self.typing_indicators: Dict[Tuple[str, int], Dict[int, datetime]] = {}
        self.call_rooms: Dict[str, Dict[str, Any]] = {}
        self.lock = asyncio.Lock()  # Используем asyncio.Lock вместо threading.Lock
    
    async def connect(self, websocket: WebSocket, user_id: int, device_id: Optional[str] = None):
        """Подключение пользователя к WebSocket"""
        await websocket.accept()
        
        async with self.lock:
            if user_id not in self.user_connections:
                self.user_connections[user_id] = []
            
            self.user_connections[user_id].append(websocket)
            self.active_connections[id(websocket)] = user_id
            
            if device_id:
                if user_id not in self.user_devices:
                    self.user_devices[user_id] = {}
                self.user_devices[user_id][device_id] = {
                    "connected_at": datetime.utcnow(),
                    "last_activity": datetime.utcnow()
                }
        
        logger.info(f"✅ User {user_id} connected to WebSocket (device: {device_id})")
        
        # Обновляем статус пользователя в БД
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if user:
                user.is_online = True
                user.last_seen = datetime.utcnow()
                db.commit()
                
                # Уведомляем других пользователей
                await self.broadcast_user_status(user_id, True)
        except Exception as e:
            logger.error(f"⚠️ Error updating user status: {e}")
        finally:
            db.close()
        
        # Отправляем информацию о текущем состоянии
        await self.send_user_state(user_id, websocket)
    
    async def disconnect(self, websocket: WebSocket):
        """Отключение пользователя от WebSocket"""
        connection_id = id(websocket)
        
        if connection_id in self.active_connections:
            user_id = self.active_connections[connection_id]
            
            async with self.lock:
                # Удаляем соединение
                if user_id in self.user_connections:
                    if websocket in self.user_connections[user_id]:
                        self.user_connections[user_id].remove(websocket)
                    
                    if not self.user_connections[user_id]:
                        del self.user_connections[user_id]
                        del self.active_connections[connection_id]
                        
                        # Обновляем статус пользователя в БД
                        asyncio.create_task(self.update_user_offline_status(user_id))
                else:
                    del self.active_connections[connection_id]
            
            logger.info(f"📴 User {user_id} disconnected from WebSocket")
    
    async def update_user_offline_status(self, user_id: int):
        """Обновление статуса пользователя при отключении"""
        await asyncio.sleep(5)  # Ждем 5 секунд перед установкой офлайн статуса
        
        async with self.lock:
            if user_id in self.user_connections and self.user_connections[user_id]:
                return  # Пользователь снова подключился
        
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if user:
                user.is_online = False
                user.last_seen = datetime.utcnow()
                db.commit()
                
                # Уведомляем других пользователей
                await self.broadcast_user_status(user_id, False)
        except Exception as e:
            logger.error(f"⚠️ Error updating user status on disconnect: {e}")
        finally:
            db.close()
    
    async def send_to_user(self, user_id: int, message: Dict[str, Any]):
        """Отправка сообщения конкретному пользователю"""
        if user_id in self.user_connections:
            disconnected = []
            
            for websocket in self.user_connections[user_id]:
                try:
                    await websocket.send_json(message)
                    
                    # Обновляем активность устройства
                    async with self.lock:
                        if user_id in self.user_devices:
                            for device_id, device_info in self.user_devices[user_id].items():
                                device_info["last_activity"] = datetime.utcnow()
                except Exception as e:
                    logger.error(f"❌ Error sending to user {user_id}: {e}")
                    disconnected.append(websocket)
            
            # Удаляем отключенные соединения
            for websocket in disconnected:
                await self.disconnect(websocket)
    
    async def broadcast(self, message: Dict[str, Any], exclude_user_id: Optional[int] = None):
        """Широковещательная рассылка всем пользователям"""
        disconnected = []
        
        async with self.lock:
            connections_to_send = []
            
            for user_id, websockets in self.user_connections.items():
                if user_id == exclude_user_id:
                    continue
                
                for websocket in websockets:
                    connections_to_send.append((user_id, websocket))
        
        for user_id, websocket in connections_to_send:
            try:
                await websocket.send_json(message)
                
                # Обновляем активность
                async with self.lock:
                    if user_id in self.user_devices:
                        for device_info in self.user_devices[user_id].values():
                            device_info["last_activity"] = datetime.utcnow()
            except Exception as e:
                logger.error(f"❌ Error broadcasting to user {user_id}: {e}")
                disconnected.append(websocket)
        
        # Удаляем отключенные соединения
        for websocket in disconnected:
            await self.disconnect(websocket)
    
    async def broadcast_to_chat(self, chat_type: str, chat_id: int, message: Dict[str, Any], exclude_user_id: Optional[int] = None):
        """Отправка сообщения всем участникам чата"""
        db = SessionLocal()
        try:
            user_ids = set()
            
            if chat_type == "private":
                user_ids.add(chat_id)
            elif chat_type == "group":
                members = db.query(GroupMember).filter(
                    GroupMember.group_id == chat_id,
                    GroupMember.is_banned == False
                ).all()
                user_ids.update(member.user_id for member in members)
            elif chat_type == "channel":
                subscribers = db.query(ChannelSubscription).filter(
                    ChannelSubscription.channel_id == chat_id,
                    ChannelSubscription.is_banned == False
                ).all()
                user_ids.update(subscriber.user_id for subscriber in subscribers)
            
            if exclude_user_id and exclude_user_id in user_ids:
                user_ids.remove(exclude_user_id)
            
            # Отправляем каждому пользователю
            for user_id in user_ids:
                if user_id in self.user_connections:
                    await self.send_to_user(user_id, message)
                    
        except Exception as e:
            logger.error(f"❌ Error broadcasting to chat: {e}")
        finally:
            db.close()
    
    async def broadcast_user_status(self, user_id: int, is_online: bool):
        """Уведомление о изменении статуса пользователя"""
        message = {
            "type": "user_status",
            "user_id": user_id,
            "is_online": is_online,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        await self.broadcast(message, exclude_user_id=user_id)
    
    async def send_user_state(self, user_id: int, websocket: WebSocket):
        """Отправка текущего состояния пользователю"""
        db = SessionLocal()
        try:
            # Получаем непрочитанные уведомления
            notifications = db.query(Notification).filter(
                Notification.user_id == user_id,
                Notification.is_read == False
            ).order_by(desc(Notification.created_at)).limit(50).all()
            
            # Получаем активные чаты
            user = db.query(User).filter(User.id == user_id).first()
            if user:
                # Отправляем информацию о пользователе
                await websocket.send_json({
                    "type": "user_state",
                    "user": {
                        "id": user.id,
                        "username": user.username,
                        "display_name": user.display_name,
                        "avatar_url": user.avatar_url,
                        "status": user.status,
                        "status_message": user.status_message,
                        "is_online": user.is_online,
                        "settings": user.settings
                    },
                    "notifications": [
                        {
                            "id": n.id,
                            "type": n.type,
                            "title": n.title,
                            "message": n.message,
                            "data": n.data,
                            "is_read": n.is_read,
                            "created_at": n.created_at.isoformat() if n.created_at else None
                        }
                        for n in notifications
                    ],
                    "timestamp": datetime.utcnow().isoformat()
                })
                
        except Exception as e:
            logger.error(f"❌ Error sending user state: {e}")
        finally:
            db.close()
    
    async def update_typing_indicator(self, user_id: int, chat_type: str, chat_id: int, is_typing: bool):
        """Обновление индикатора набора текста"""
        key = (chat_type, chat_id)
        
        async with self.lock:
            if is_typing:
                if key not in self.typing_indicators:
                    self.typing_indicators[key] = {}
                self.typing_indicators[key][user_id] = datetime.utcnow()
            else:
                if key in self.typing_indicators and user_id in self.typing_indicators[key]:
                    del self.typing_indicators[key][user_id]
                    if not self.typing_indicators[key]:
                        del self.typing_indicators[key]
        
        # Отправляем уведомление другим участникам
        typing_message = {
            "type": "typing",
            "chat_type": chat_type,
            "chat_id": chat_id,
            "user_id": user_id,
            "is_typing": is_typing,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        await self.broadcast_to_chat(chat_type, chat_id, typing_message, exclude_user_id=user_id)
    
    def get_typing_users(self, chat_type: str, chat_id: int) -> List[int]:
        """Получение пользователей, которые печатают в чате"""
        key = (chat_type, chat_id)
        
        # Используем обычный with для доступа к словарю
        if key in self.typing_indicators:
            # Удаляем старые записи (старше 10 секунд)
            current_time = datetime.utcnow()
            typing_users = []
            
            for user_id, typing_time in list(self.typing_indicators[key].items()):
                if (current_time - typing_time).total_seconds() > 10:
                    del self.typing_indicators[key][user_id]
                else:
                    typing_users.append(user_id)
            
            if not self.typing_indicators[key]:
                del self.typing_indicators[key]
            
            return typing_users
        
        return []
    
    async def create_call_room(self, call_id: str, initiator_id: int, chat_type: str, chat_id: int, call_type: str = "audio"):
        """Создание комнаты для звонка"""
        async with self.lock:
            self.call_rooms[call_id] = {
                "id": call_id,
                "initiator_id": initiator_id,
                "chat_type": chat_type,
                "chat_id": chat_id,
                "call_type": call_type,
                "participants": [initiator_id],
                "start_time": datetime.utcnow(),
                "status": "waiting",
                "sdp_offers": {},
                "ice_candidates": {}
            }
        
        logger.info(f"📞 Call room created: {call_id}")
        return self.call_rooms[call_id]
    
    async def join_call_room(self, call_id: str, user_id: int):
        """Присоединение к комнате звонка"""
        async with self.lock:
            if call_id in self.call_rooms:
                if user_id not in self.call_rooms[call_id]["participants"]:
                    self.call_rooms[call_id]["participants"].append(user_id)
                
                return self.call_rooms[call_id]
        
        return None
    
    async def leave_call_room(self, call_id: str, user_id: int):
        """Выход из комнаты звонка"""
        async with self.lock:
            if call_id in self.call_rooms:
                if user_id in self.call_rooms[call_id]["participants"]:
                    self.call_rooms[call_id]["participants"].remove(user_id)
                
                # Удаляем комнату если пустая
                if not self.call_rooms[call_id]["participants"]:
                    del self.call_rooms[call_id]
                    logger.info(f"📞 Call room deleted: {call_id}")
    
    def get_call_room(self, call_id: str) -> Optional[Dict[str, Any]]:
        """Получение информации о комнате звонка"""
        return self.call_rooms.get(call_id)
    
    def get_user_devices(self, user_id: int) -> List[Dict[str, Any]]:
        """Получение информации об устройствах пользователя"""
        if user_id in self.user_devices:
            devices = []
            for device_id, device_info in self.user_devices[user_id].items():
                devices.append({
                    "device_id": device_id,
                    "connected_at": device_info["connected_at"].isoformat() if isinstance(device_info["connected_at"], datetime) else device_info["connected_at"],
                    "last_activity": device_info["last_activity"].isoformat() if isinstance(device_info["last_activity"], datetime) else device_info["last_activity"]
                })
            return devices
        return []
    
    def get_online_users(self) -> List[int]:
        """Получение списка онлайн пользователей"""
        return list(self.user_connections.keys())

manager = ConnectionManager()
        
# ========== СОЗДАНИЕ FASTAPI ПРИЛОЖЕНИЯ ==========

app = FastAPI(
    title="DevNet Messenger API",
    description="Full-featured messenger for developers with real-time communication, file sharing, and more",
    version="3.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    contact={
        "name": "DevNet Support",
        "email": "support@devnet.local"
    },
    license_info={
        "name": "MIT",
        "url": "https://opensource.org/licenses/MIT"
    }
)

# Настройка CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:8080", "http://localhost:5173", "https://devnet-messenger.railway.app"] if IS_PRODUCTION else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=600
)

# Создаем директории для загрузок
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

for media_type in ["images", "avatars", "files", "videos", "audios", "documents", "thumbnails", "stickers"]:
    (UPLOAD_DIR / media_type).mkdir(exist_ok=True, parents=True)

logger.info(f"📁 Upload directory: {UPLOAD_DIR}")

# Получаем абсолютный путь к фронтенду
current_dir = Path(__file__).parent
project_root = current_dir.parent
frontend_dir = project_root / "frontend"

logger.info(f"📁 Project root: {project_root}")
logger.info(f"📁 Frontend directory: {frontend_dir}")

# ========== МОДЕЛИ PYDANTIC ДЛЯ ЗАПРОСОВ ==========

class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str
    display_name: Optional[str] = None
    invite_code: Optional[str] = None

class LoginRequest(BaseModel):
    username: str
    password: str
    remember_me: bool = False
    device_id: Optional[str] = None
    device_name: Optional[str] = None

class MessageCreateRequest(BaseModel):
    content: Optional[str] = None
    message_type: str = "text"
    to_user_id: Optional[int] = None
    group_id: Optional[int] = None
    channel_id: Optional[int] = None
    reply_to_id: Optional[int] = None
    forwarded_from: Optional[int] = None
    forwarded_message_id: Optional[int] = None
    is_encrypted: bool = False

class GroupCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    is_public: bool = True
    is_encrypted: bool = False
    settings: Optional[Dict[str, Any]] = None

class ChannelCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    is_public: bool = True
    is_verified: bool = False
    is_encrypted: bool = False
    settings: Optional[Dict[str, Any]] = None

class UserUpdateRequest(BaseModel):
    display_name: Optional[str] = None
    bio: Optional[str] = None
    status: Optional[str] = None
    status_message: Optional[str] = None
    settings: Optional[Dict[str, Any]] = None
    phone: Optional[str] = None
    country: Optional[str] = None
    timezone: Optional[str] = None

class PollCreateRequest(BaseModel):
    question: str
    options: List[str]
    is_multiple: bool = False
    is_anonymous: bool = True
    closes_at: Optional[str] = None

class CallStartRequest(BaseModel):
    call_type: str = "audio"
    to_user_id: Optional[int] = None
    group_id: Optional[int] = None
    channel_id: Optional[int] = None

# ========== HEALTH CHECK И СИСТЕМНЫЕ ЭНДПОИНТЫ ==========

@app.get("/")
async def root():
    """Корневой эндпоинт - должен отдавать frontend"""
    # Проверяем наличие фронтенда
    if frontend_dir.exists():
        index_path = frontend_dir / "index.html"
        if index_path.exists():
            return FileResponse(str(index_path))
    
    # Если фронтенда нет, отдаем информацию об API
    return {
        "message": "DevNet Messenger API",
        "version": "3.0.0",
        "docs": "/api/docs",
        "status": "running",
        "frontend": "not found" if not frontend_dir.exists() else "available",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/health")
async def health_check():
    """Health check эндпоинт"""
    return JSONResponse(
        content={
            "status": "ok",
            "service": "DevNet Messenger",
            "version": "3.0.0",
            "timestamp": datetime.utcnow().isoformat(),
            "uptime": time.time() - app_start_time if 'app_start_time' in globals() else 0
        },
        status_code=200
    )

@app.get("/api/health")
async def api_health_check(db: Session = Depends(get_db)):
    """Проверка здоровья API и базы данных"""
    try:
        # Проверяем подключение к базе данных
        db.execute(text("SELECT 1"))
        
        # Получаем статистику
        users_count = db.query(User).count()
        messages_count = db.query(Message).count()
        groups_count = db.query(Group).count()
        channels_count = db.query(Channel).count()
        
        # Получаем информацию о системе
        import psutil
        import platform
        
        system_info = {
            "platform": platform.platform(),
            "python_version": platform.python_version(),
            "cpu_percent": psutil.cpu_percent(),
            "memory_percent": psutil.virtual_memory().percent,
            "disk_usage": psutil.disk_usage('/').percent
        }
        
        return {
            "status": "healthy",
            "service": "DevNet Messenger",
            "version": "3.0.0",
            "timestamp": datetime.utcnow().isoformat(),
            "database": "connected",
            "production": IS_PRODUCTION,
            "domain": DOMAIN,
            "statistics": {
                "users": users_count,
                "messages": messages_count,
                "groups": groups_count,
                "channels": channels_count,
                "online_users": len(manager.get_online_users())
            },
            "system": system_info
        }
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Service unavailable: {str(e)}"
        )

@app.get("/api/info")
async def get_system_info():
    """Получение информации о системе"""
    return {
        "app": "DevNet Messenger",
        "version": "3.0.0",
        "environment": "production" if IS_PRODUCTION else "development",
        "domain": DOMAIN,
        "features": [
            "real-time messaging",
            "voice and video calls",
            "file sharing",
            "groups and channels",
            "end-to-end encryption",
            "polls and reactions",
            "notifications",
            "contacts management"
        ],
        "limits": {
            "max_upload_size": MAX_UPLOAD_SIZE,
            "max_message_length": MAX_MESSAGE_LENGTH,
            "max_users_per_group": MAX_USERS_PER_GROUP,
            "max_subscribers_per_channel": MAX_SUBSCRIBERS_PER_CHANNEL
        },
        "timestamp": datetime.utcnow().isoformat()
    }

# ========== АВТОРИЗАЦИЯ И РЕГИСТРАЦИЯ ==========

@app.post("/api/register", status_code=status.HTTP_201_CREATED)
async def register_user(
    request: RegisterRequest,
    response: Response,
    db: Session = Depends(get_db)
):
    """Регистрация нового пользователя"""
    logger.info(f"🔵 Регистрация: username={request.username}, email={request.email}")
    
    try:
        # Валидация username
        if len(request.username) < 3:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Имя пользователя должно быть не менее 3 символов"
            )
        
        if not all(c.isalnum() or c in "_-" for c in request.username):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Имя пользователя может содержать только буквы, цифры, дефисы и подчеркивания"
            )
        
        # Проверяем уникальность username
        existing_user = db.query(User).filter(User.username == request.username).first()
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Имя пользователя уже занято"
            )
        
        # Проверяем уникальность email
        existing_email = db.query(User).filter(User.email == request.email).first()
        if existing_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email уже используется"
            )
        
        # Валидация пароля
        if len(request.password) < 8:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Пароль должен быть не менее 8 символов"
            )
        
        if len(request.password) > 128:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Пароль не должен превышать 128 символов"
            )
        
        # Проверка сложности пароля
        has_upper = any(c.isupper() for c in request.password)
        has_lower = any(c.islower() for c in request.password)
        has_digit = any(c.isdigit() for c in request.password)
        
        if not (has_upper and has_lower and has_digit):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Пароль должен содержать хотя бы одну заглавную букву, одну строчную букву и одну цифру"
            )
        
        # Создаем пользователя
        user = User(
            username=request.username,
            email=request.email,
            display_name=request.display_name or request.username,
            password_hash=PasswordHelper.hash_password(request.password),
            is_guest=False,
            is_active=True,
            is_verified=False,
            last_login=datetime.utcnow(),
            last_seen=datetime.utcnow(),
            settings={
                "theme": "auto",
                "notifications": True,
                "language": "ru",
                "privacy": {
                    "online_status": "all",
                    "read_receipts": True,
                    "profile_photo": "all",
                    "last_seen": "all"
                }
            }
        )
        
        db.add(user)
        db.commit()
        db.refresh(user)
        
        logger.info(f"✅ Пользователь создан: {request.username} (ID: {user.id})")
        
        # Создаем токены
        access_token = TokenHelper.create_access_token(
            data={"user_id": user.id, "username": user.username}
        )
        
        # Создаем refresh токен
        refresh_token = secrets.token_urlsafe(64)
        expires_at = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
        
        refresh_token_db = RefreshToken(
            user_id=user.id,
            token=refresh_token,
            expires_at=expires_at
        )
        db.add(refresh_token_db)
        db.commit()
        
        # Устанавливаем cookies
        set_auth_cookies(response, access_token, refresh_token)
        
        # Создаем приветственное уведомление
        welcome_notification = Notification(
            user_id=user.id,
            type="welcome",
            title="Добро пожаловать в DevNet Messenger!",
            message="Спасибо за регистрацию! Начните общаться с друзьями прямо сейчас.",
            data={"action": "explore"},
            is_important=True
        )
        db.add(welcome_notification)
        db.commit()
        
        return {
            "success": True,
            "message": "Регистрация успешна",
            "user": {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "email": user.email,
                "avatar_url": user.avatar_url,
                "is_admin": user.is_admin,
                "is_online": user.is_online,
                "is_verified": user.is_verified,
                "status": user.status,
                "created_at": user.created_at.isoformat() if user.created_at else None
            },
            "tokens": {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Ошибка регистрации: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка регистрации: {str(e)}"
        )

@app.post("/api/login")
async def login_user(
    request: LoginRequest,
    response: Response,
    db: Session = Depends(get_db)
):
    """Вход пользователя"""
    logger.info(f"🔵 Попытка входа: username={request.username}")
    
    try:
        # Проверяем rate limit
        client_ip = "unknown"  # В реальном приложении нужно получить IP из request
        allowed, wait_time = rate_limiter.is_allowed(f"login_{request.username}_{client_ip}")
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Слишком много попыток входа. Попробуйте через {wait_time} секунд"
            )
        
        # Ищем пользователя по username или email
        user = db.query(User).filter(
            or_(
                User.username == request.username,
                User.email == request.username
            )
        ).first()
        
        if not user:
            logger.warning(f"❌ Пользователь не найден: {request.username}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Неверное имя пользователя или пароль"
            )
        
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Пользователь заблокирован"
            )
        
        logger.info(f"🔵 Найден пользователь: {user.username}, проверка пароля...")
        
        # Проверяем пароль
        if not PasswordHelper.verify_password(request.password, user.password_hash):
            logger.warning(f"❌ Неверный пароль для пользователя: {user.username}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Неверное имя пользователя или пароль"
            )
        
        logger.info(f"✅ Успешный вход: {user.username} (ID: {user.id})")
        
        # Обновляем время последнего входа
        user.last_login = datetime.utcnow()
        user.last_seen = datetime.utcnow()
        user.is_online = True
        db.commit()
        
        # Создаем токены
        access_token_expires = timedelta(
            minutes=ACCESS_TOKEN_EXPIRE_MINUTES if not request.remember_me else ACCESS_TOKEN_EXPIRE_MINUTES * 7
        )
        
        access_token = TokenHelper.create_access_token(
            data={"user_id": user.id, "username": user.username},
            expires_delta=access_token_expires
        )
        
        # Создаем refresh токен
        refresh_token = secrets.token_urlsafe(64)
        expires_at = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
        
        refresh_token_db = RefreshToken(
            user_id=user.id,
            token=refresh_token,
            device_id=request.device_id,
            device_name=request.device_name,
            expires_at=expires_at
        )
        db.add(refresh_token_db)
        db.commit()
        
        # Создаем сессию
        session_token = TokenHelper.create_session_token(user.id, {
            "device_id": request.device_id,
            "device_name": request.device_name
        })
        
        session = Session(
            user_id=user.id,
            session_token=session_token,
            device_id=request.device_id,
            device_name=request.device_name,
            platform="web",  # В реальном приложении определять из user-agent
            browser="chrome",  # В реальном приложении определять из user-agent
            expires_at=datetime.utcnow() + timedelta(days=30)
        )
        db.add(session)
        db.commit()
        
        # Устанавливаем cookies
        set_auth_cookies(response, access_token, refresh_token)
        
        # Добавляем session token в cookies
        cookie_settings = {
            "httponly": True,
            "samesite": "lax" if IS_PRODUCTION else "none",
            "secure": IS_PRODUCTION,
            "path": "/"
        }
        
        if DOMAIN != "localhost":
            cookie_settings["domain"] = DOMAIN
        
        response.set_cookie(
            key="session_token",
            value=session_token,
            max_age=30 * 24 * 60 * 60,
            **cookie_settings
        )
        
        return {
            "success": True,
            "message": "Вход выполнен успешно",
            "user": {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "email": user.email,
                "avatar_url": user.avatar_url,
                "is_online": user.is_online,
                "is_admin": user.is_admin,
                "is_verified": user.is_verified,
                "status": user.status,
                "status_message": user.status_message,
                "settings": user.settings,
                "created_at": user.created_at.isoformat() if user.created_at else None,
                "last_login": user.last_login.isoformat() if user.last_login else None
            },
            "tokens": {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "session_token": session_token,
                "expires_in": access_token_expires.total_seconds()
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка входа: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка входа: {str(e)}"
        )

@app.post("/api/auth/refresh")
async def refresh_token(
    request: Request,
    response: Response,
    db: Session = Depends(get_db)
):
    """Обновление access токена с помощью refresh токена"""
    # Получаем refresh токен из cookies
    refresh_token = request.cookies.get("refresh_token")
    
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token не предоставлен"
        )
    
    # Ищем refresh токен в базе
    refresh_token_db = db.query(RefreshToken).filter(
        RefreshToken.token == refresh_token,
        RefreshToken.is_revoked == False,
        RefreshToken.expires_at > datetime.utcnow()
    ).first()
    
    if not refresh_token_db:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Недействительный или просроченный refresh token"
        )
    
    user = db.query(User).filter(User.id == refresh_token_db.user_id).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден или заблокирован"
        )
    
    # Обновляем время последнего использования
    refresh_token_db.last_used = datetime.utcnow()
    
    # Создаем новый access токен
    access_token = TokenHelper.create_access_token(
        data={"user_id": user.id, "username": user.username}
    )
    
    # Создаем новый refresh токен (ротация токенов)
    new_refresh_token = secrets.token_urlsafe(64)
    expires_at = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    
    new_refresh_token_db = RefreshToken(
        user_id=user.id,
        token=new_refresh_token,
        device_id=refresh_token_db.device_id,
        device_name=refresh_token_db.device_name,
        expires_at=expires_at
    )
    db.add(new_refresh_token_db)
    
    # Отмечаем старый токен как отозванный
    refresh_token_db.is_revoked = True
    
    db.commit()
    
    # Устанавливаем новые cookies
    set_auth_cookies(response, access_token, new_refresh_token)
    
    return {
        "success": True,
        "message": "Токены успешно обновлены",
        "tokens": {
            "access_token": access_token,
            "refresh_token": new_refresh_token,
            "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60
        }
    }

@app.get("/api/me")
async def get_current_user_info(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение информации о текущем пользователе"""
    logger.info(f"📊 Запрос информации о пользователе: {user.username}")
    
    # Получаем статистику пользователя
    messages_count = db.query(Message).filter(
        or_(
            Message.from_user_id == user.id,
            Message.to_user_id == user.id
        )
    ).count()
    
    groups_count = db.query(GroupMember).filter(
        GroupMember.user_id == user.id,
        GroupMember.is_banned == False
    ).count()
    
    channels_count = db.query(ChannelSubscription).filter(
        ChannelSubscription.user_id == user.id,
        ChannelSubscription.is_banned == False
    ).count()
    
    contacts_count = db.query(Contact).filter(
        Contact.user_id == user.id,
        Contact.is_blocked == False
    ).count()
    
    return {
        "success": True,
        "user": {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "email": user.email,
            "avatar_url": user.avatar_url,
            "is_online": user.is_online,
            "is_admin": user.is_admin,
            "is_verified": user.is_verified,
            "is_active": user.is_active,
            "status": user.status,
            "status_message": user.status_message,
            "bio": user.bio,
            "phone": user.phone,
            "country": user.country,
            "timezone": user.timezone,
            "settings": user.settings,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "updated_at": user.updated_at.isoformat() if user.updated_at else None,
            "last_login": user.last_login.isoformat() if user.last_login else None,
            "last_seen": user.last_seen.isoformat() if user.last_seen else None
        },
        "statistics": {
            "messages": messages_count,
            "groups": groups_count,
            "channels": channels_count,
            "contacts": contacts_count
        }
    }

@app.post("/api/auth/logout")
async def logout_user(
    response: Response,
    request: Request,
    user: Optional[User] = Depends(lambda request=Request: get_current_user(request, require_auth=False)),
    db: Session = Depends(get_db)
):
    """Выход пользователя"""
    logger.info(f"🚪 Выход пользователя: {user.username if user else 'unknown'}")
    
    try:
        if user:
            # Обновляем статус пользователя
            user.is_online = False
            user.last_seen = datetime.utcnow()
            
            # Отзываем refresh токен если есть
            refresh_token = request.cookies.get("refresh_token")
            if refresh_token:
                refresh_token_db = db.query(RefreshToken).filter(
                    RefreshToken.token == refresh_token
                ).first()
                
                if refresh_token_db:
                    refresh_token_db.is_revoked = True
            
            # Отмечаем сессию как неактивную
            session_token = request.cookies.get("session_token")
            if session_token:
                session = db.query(Session).filter(
                    Session.session_token == session_token
                ).first()
                
                if session:
                    session.expires_at = datetime.utcnow()
        
        db.commit()
        
    except Exception as e:
        logger.error(f"⚠️ Ошибка при выходе: {e}")
        db.rollback()
    
    # Очищаем cookies
    clear_auth_cookies(response)
    
    return {
        "success": True,
        "message": "Выход выполнен успешно"
    }

@app.get("/api/auth/check")
async def check_auth(
    user: Optional[User] = Depends(lambda request=Request: get_current_user(request, require_auth=False))
):
    """Проверка авторизации"""
    if user:
        return {
            "success": True,
            "authenticated": True,
            "user": {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "avatar_url": user.avatar_url,
                "is_online": user.is_online,
                "is_admin": user.is_admin,
                "is_verified": user.is_verified,
                "status": user.status
            }
        }
    else:
        return {
            "success": True,
            "authenticated": False,
            "message": "Не авторизован"
        }

@app.get("/api/auth/devices")
async def get_user_devices(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение списка устройств пользователя"""
    # Активные устройства через WebSocket
    active_devices = manager.get_user_devices(user.id)
    
    # Устройства из базы данных
    refresh_tokens = db.query(RefreshToken).filter(
        RefreshToken.user_id == user.id,
        RefreshToken.is_revoked == False,
        RefreshToken.expires_at > datetime.utcnow()
    ).order_by(desc(RefreshToken.created_at)).all()
    
    sessions = db.query(Session).filter(
        Session.user_id == user.id,
        Session.expires_at > datetime.utcnow()
    ).order_by(desc(Session.created_at)).all()
    
    devices = []
    
    # Объединяем информацию
    for rt in refresh_tokens:
        device_info = {
            "type": "refresh_token",
            "device_id": rt.device_id,
            "device_name": rt.device_name,
            "created_at": rt.created_at.isoformat(),
            "last_used": rt.last_used.isoformat() if rt.last_used else None,
            "expires_at": rt.expires_at.isoformat(),
            "is_active": any(
                dev.get("device_id") == rt.device_id 
                for dev in active_devices
            )
        }
        devices.append(device_info)
    
    for session in sessions:
        device_info = {
            "type": "session",
            "device_id": session.device_id,
            "device_name": session.device_name,
            "platform": session.platform,
            "browser": session.browser,
            "created_at": session.created_at.isoformat(),
            "last_activity": session.last_activity.isoformat(),
            "expires_at": session.expires_at.isoformat(),
            "is_active": any(
                dev.get("device_id") == session.device_id 
                for dev in active_devices
            )
        }
        devices.append(device_info)
    
    return {
        "success": True,
        "devices": devices
    }

@app.post("/api/auth/devices/{device_id}/revoke")
async def revoke_device(
    device_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Отзыв устройства"""
    # Отзываем refresh токены для устройства
    refresh_tokens = db.query(RefreshToken).filter(
        RefreshToken.user_id == user.id,
        RefreshToken.device_id == device_id,
        RefreshToken.is_revoked == False
    ).all()
    
    for rt in refresh_tokens:
        rt.is_revoked = True
    
    # Истекаем сессии для устройства
    sessions = db.query(Session).filter(
        Session.user_id == user.id,
        Session.device_id == device_id,
        Session.expires_at > datetime.utcnow()
    ).all()
    
    for session in sessions:
        session.expires_at = datetime.utcnow()
    
    db.commit()
    
    return {
        "success": True,
        "message": "Устройство отозвано"
    }

# ========== ПОЛЬЗОВАТЕЛИ ==========

@app.get("/api/users")
async def get_users(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    online_only: bool = Query(False),
    search: Optional[str] = Query(None),
    exclude_current: bool = Query(True),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение списка пользователей"""
    try:
        query = db.query(User).filter(User.is_active == True)
        
        if exclude_current:
            query = query.filter(User.id != user.id)
        
        if online_only:
            query = query.filter(User.is_online == True)
        
        if search and search.strip():
            search_filter = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    User.username.ilike(search_filter),
                    User.display_name.ilike(search_filter),
                    User.email.ilike(search_filter),
                    User.bio.ilike(search_filter)
                )
            )
        
        total = query.count()
        users = query.order_by(
            desc(User.is_online),
            desc(User.last_seen),
            User.display_name,
            User.username
        ).offset((page - 1) * limit).limit(limit).all()
        
        users_data = []
        for user_item in users:
            # Проверяем, есть ли в контактах
            is_contact = db.query(Contact).filter(
                Contact.user_id == user.id,
                Contact.contact_id == user_item.id,
                Contact.is_blocked == False
            ).first() is not None
            
            # Проверяем, заблокирован ли
            is_blocked = db.query(Contact).filter(
                Contact.user_id == user.id,
                Contact.contact_id == user_item.id,
                Contact.is_blocked == True
            ).first() is not None
            
            users_data.append({
                "id": user_item.id,
                "username": user_item.username,
                "display_name": user_item.display_name or user_item.username,
                "avatar_url": user_item.avatar_url,
                "is_online": user_item.is_online,
                "is_admin": user_item.is_admin,
                "is_verified": user_item.is_verified,
                "status": user_item.status,
                "status_message": user_item.status_message,
                "bio": user_item.bio,
                "is_contact": is_contact,
                "is_blocked": is_blocked,
                "last_seen": user_item.last_seen.isoformat() if user_item.last_seen else None,
                "created_at": user_item.created_at.isoformat() if user_item.created_at else None
            })
        
        return {
            "success": True,
            "users": users_data,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "pages": (total + limit - 1) // limit
            }
        }
        
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки пользователей: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка загрузки пользователей: {str(e)}"
        )

@app.get("/api/users/{user_id}")
async def get_user_by_id(
    user_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение информации о конкретном пользователе"""
    try:
        user_item = db.query(User).filter(
            User.id == user_id,
            User.is_active == True
        ).first()
        
        if not user_item:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Пользователь не найден"
            )
        
        # Проверяем настройки приватности
        can_see_online = True
        can_see_last_seen = True
        can_see_profile = True
        
        if user_item.settings and "privacy" in user_item.settings:
            privacy = user_item.settings["privacy"]
            
            if privacy.get("online_status") == "contacts":
                # Проверяем, есть ли в контактах
                is_contact = db.query(Contact).filter(
                    Contact.user_id == user_item.id,
                    Contact.contact_id == user.id,
                    Contact.is_blocked == False
                ).first() is not None
                can_see_online = is_contact
            
            if privacy.get("last_seen") == "contacts":
                is_contact = db.query(Contact).filter(
                    Contact.user_id == user_item.id,
                    Contact.contact_id == user.id,
                    Contact.is_blocked == False
                ).first() is not None
                can_see_last_seen = is_contact
            
            if privacy.get("profile_photo") == "contacts":
                is_contact = db.query(Contact).filter(
                    Contact.user_id == user_item.id,
                    Contact.contact_id == user.id,
                    Contact.is_blocked == False
                ).first() is not None
                can_see_profile = is_contact
        
        # Проверяем, есть ли общие чаты
        common_chats = False
        common_messages = db.query(Message).filter(
            or_(
                and_(Message.from_user_id == user.id, Message.to_user_id == user_id),
                and_(Message.from_user_id == user_id, Message.to_user_id == user.id)
            )
        ).first()
        
        if common_messages:
            common_chats = True
        
        # Проверяем, есть ли в контактах
        is_contact = db.query(Contact).filter(
            Contact.user_id == user.id,
            Contact.contact_id == user_id,
            Contact.is_blocked == False
        ).first() is not None
        
        # Проверяем, заблокирован ли
        is_blocked = db.query(Contact).filter(
            Contact.user_id == user.id,
            Contact.contact_id == user_id,
            Contact.is_blocked == True
        ).first() is not None
        
        user_data = {
            "id": user_item.id,
            "username": user_item.username,
            "display_name": user_item.display_name or user_item.username,
            "avatar_url": user_item.avatar_url if can_see_profile else None,
            "is_online": user_item.is_online if can_see_online else None,
            "is_admin": user_item.is_admin,
            "is_verified": user_item.is_verified,
            "status": user_item.status,
            "status_message": user_item.status_message,
            "bio": user_item.bio,
            "is_contact": is_contact,
            "is_blocked": is_blocked,
            "last_seen": user_item.last_seen.isoformat() if user_item.last_seen and can_see_last_seen else None,
            "created_at": user_item.created_at.isoformat() if user_item.created_at else None
        }
        
        return {
            "success": True,
            "user": user_data,
            "common_chats": common_chats,
            "privacy": {
                "can_see_online": can_see_online,
                "can_see_last_seen": can_see_last_seen,
                "can_see_profile": can_see_profile
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки пользователя: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка загрузки пользователя: {str(e)}"
        )

@app.put("/api/users/profile")
async def update_user_profile(
    request: UserUpdateRequest,
    avatar: Optional[UploadFile] = None,
    banner: Optional[UploadFile] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Обновление профиля пользователя"""
    try:
        if request.display_name:
            user.display_name = request.display_name.strip() or user.username
        
        if request.bio is not None:
            user.bio = request.bio
        
        if request.status:
            allowed_statuses = ["online", "away", "busy", "offline"]
            if request.status in allowed_statuses:
                user.status = request.status
        
        if request.status_message is not None:
            user.status_message = request.status_message
        
        if request.settings:
            # Объединяем настройки
            if user.settings:
                user.settings.update(request.settings)
            else:
                user.settings = request.settings
        
        if request.phone is not None:
            user.phone = request.phone
        
        if request.country is not None:
            user.country = request.country
        
        if request.timezone is not None:
            user.timezone = request.timezone
        
        # Обработка аватара
        if avatar:
            allowed_types = ["image/jpeg", "image/png", "image/webp", "image/gif"]
            
            if avatar.content_type not in allowed_types:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Неподдерживаемый формат изображения"
                )
            
            # Проверяем размер файла
            file_size = 0
            avatar.file.seek(0, 2)
            file_size = avatar.file.tell()
            avatar.file.seek(0)
            
            if file_size > 10 * 1024 * 1024:  # 10 MB
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Размер файла не должен превышать 10 MB"
                )
            
            # Генерируем имя файла
            file_ext = avatar.filename.split('.')[-1] if '.' in avatar.filename else 'jpg'
            filename = f"avatar_{user.id}_{uuid.uuid4()}.{file_ext}"
            filepath = UPLOAD_DIR / "avatars" / filename
            
            # Сохраняем файл
            with open(filepath, "wb") as buffer:
                shutil.copyfileobj(avatar.file, buffer)
            
            # Создаем миниатюру
            thumb_buffer = FileHandler.generate_thumbnail(filepath)
            if thumb_buffer:
                thumb_filename = f"thumb_{filename}"
                thumb_path = UPLOAD_DIR / "thumbnails" / thumb_filename
                with open(thumb_path, "wb") as f:
                    f.write(thumb_buffer.getvalue())
            
            user.avatar_url = f"/uploads/avatars/{filename}"
        
        # Обработка баннера
        if banner:
            allowed_types = ["image/jpeg", "image/png", "image/webp"]
            
            if banner.content_type not in allowed_types:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Неподдерживаемый формат изображения для баннера"
                )
            
            # Проверяем размер файла
            file_size = 0
            banner.file.seek(0, 2)
            file_size = banner.file.tell()
            banner.file.seek(0)
            
            if file_size > 20 * 1024 * 1024:  # 20 MB
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Размер баннера не должен превышать 20 MB"
                )
            
            # Генерируем имя файла
            file_ext = banner.filename.split('.')[-1] if '.' in banner.filename else 'jpg'
            filename = f"banner_{user.id}_{uuid.uuid4()}.{file_ext}"
            filepath = UPLOAD_DIR / "images" / filename
            
            # Сохраняем файл
            with open(filepath, "wb") as buffer:
                shutil.copyfileobj(banner.file, buffer)
            
            # TODO: Можно добавить обработку баннера (изменение размера и т.д.)
        
        user.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(user)
        
        # Уведомляем об обновлении профиля через WebSocket
        update_message = {
            "type": "profile_updated",
            "user_id": user.id,
            "user": {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "avatar_url": user.avatar_url,
                "status": user.status,
                "status_message": user.status_message
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
        await manager.broadcast(update_message, exclude_user_id=user.id)
        
        return {
            "success": True,
            "message": "Профиль обновлен",
            "user": {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "avatar_url": user.avatar_url,
                "status": user.status,
                "status_message": user.status_message,
                "bio": user.bio,
                "settings": user.settings,
                "updated_at": user.updated_at.isoformat() if user.updated_at else None
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Ошибка обновления профиля: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка обновления профиля: {str(e)}"
        )

@app.post("/api/users/{user_id}/block")
async def block_user(
    user_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Блокировка пользователя"""
    try:
        if user_id == user.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Нельзя заблокировать самого себя"
            )
        
        target_user = db.query(User).filter(
            User.id == user_id,
            User.is_active == True
        ).first()
        
        if not target_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Пользователь не найден"
            )
        
        # Проверяем, есть ли уже контакт
        contact = db.query(Contact).filter(
            Contact.user_id == user.id,
            Contact.contact_id == user_id
        ).first()
        
        if contact:
            contact.is_blocked = True
            contact.updated_at = datetime.utcnow()
        else:
            contact = Contact(
                user_id=user.id,
                contact_id=user_id,
                name=target_user.display_name or target_user.username,
                is_blocked=True
            )
            db.add(contact)
        
        db.commit()
        
        return {
            "success": True,
            "message": f"Пользователь {target_user.username} заблокирован"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Ошибка блокировки пользователя: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка блокировки пользователя: {str(e)}"
        )

@app.post("/api/users/{user_id}/unblock")
async def unblock_user(
    user_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Разблокировка пользователя"""
    try:
        contact = db.query(Contact).filter(
            Contact.user_id == user.id,
            Contact.contact_id == user_id,
            Contact.is_blocked == True
        ).first()
        
        if not contact:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Пользователь не найден в заблокированных"
            )
        
        contact.is_blocked = False
        contact.updated_at = datetime.utcnow()
        db.commit()
        
        target_user = db.query(User).filter(User.id == user_id).first()
        
        return {
            "success": True,
            "message": f"Пользователь {target_user.username if target_user else 'unknown'} разблокирован"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Ошибка разблокировки пользователя: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка разблокировки пользователя: {str(e)}"
        )

# ========== СООБЩЕНИЯ ==========

@app.get("/api/messages")
async def get_messages(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    chat_type: Optional[str] = Query(None),
    chat_id: Optional[int] = Query(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение последних сообщений пользователя"""
    try:
        query = db.query(Message).filter(Message.is_deleted == False)
        
        # Фильтрация по типу чата
        if chat_type and chat_id:
            if chat_type == "private":
                query = query.filter(
                    or_(
                        and_(Message.from_user_id == user.id, Message.to_user_id == chat_id),
                        and_(Message.from_user_id == chat_id, Message.to_user_id == user.id)
                    )
                )
            elif chat_type == "group":
                query = query.filter(Message.group_id == chat_id)
            elif chat_type == "channel":
                query = query.filter(Message.channel_id == chat_id)
        
        # Если не указан чат, получаем все сообщения пользователя
        if not chat_type or not chat_id:
            query = query.filter(
                or_(
                    Message.from_user_id == user.id,
                    Message.to_user_id == user.id,
                    Message.group_id.in_(
                        db.query(GroupMember.group_id).filter(
                            GroupMember.user_id == user.id,
                            GroupMember.is_banned == False
                        )
                    ),
                    Message.channel_id.in_(
                        db.query(ChannelSubscription.channel_id).filter(
                            ChannelSubscription.user_id == user.id,
                            ChannelSubscription.is_banned == False
                        )
                    )
                )
            )
        
        total = query.count()
        messages = query.order_by(desc(Message.created_at)) \
                       .offset((page - 1) * limit) \
                       .limit(limit) \
                       .all()
        
        messages_data = []
        for msg in messages:
            sender = None
            if msg.from_user_id:
                sender = db.query(User).filter(User.id == msg.from_user_id).first()
            
            # Определяем тип чата
            msg_chat_type = "private"
            msg_chat_id = msg.to_user_id if msg.from_user_id == user.id else msg.from_user_id
            
            if msg.group_id:
                msg_chat_type = "group"
                msg_chat_id = msg.group_id
            elif msg.channel_id:
                msg_chat_type = "channel"
                msg_chat_id = msg.channel_id
            
            # Получаем информацию о пересланном сообщении
            forwarded_message_info = None
            if msg.forwarded_message_id and msg.forwarded_from:
                forwarded_user = db.query(User).filter(User.id == msg.forwarded_from).first()
                if forwarded_user:
                    forwarded_message_info = {
                        "from_user_id": msg.forwarded_from,
                        "from_username": forwarded_user.username,
                        "from_display_name": forwarded_user.display_name,
                        "message_id": msg.forwarded_message_id
                    }
            
            # Получаем информацию о сообщении, на которое ответили
            reply_to_info = None
            if msg.reply_to_id:
                replied_msg = db.query(Message).filter(Message.id == msg.reply_to_id).first()
                if replied_msg:
                    replied_sender = db.query(User).filter(User.id == replied_msg.from_user_id).first()
                    reply_to_info = {
                        "message_id": replied_msg.id,
                        "content": replied_msg.content[:100] + "..." if len(replied_msg.content or "") > 100 else replied_msg.content,
                        "sender_id": replied_sender.id if replied_sender else None,
                        "sender_username": replied_sender.username if replied_sender else None,
                        "sender_display_name": replied_sender.display_name if replied_sender else None
                    }
            
            messages_data.append({
                "id": msg.id,
                "content": msg.content,
                "type": msg.message_type,
                "media_url": msg.media_url,
                "thumbnail_url": msg.thumbnail_url,
                "media_size": msg.media_size,
                "media_width": msg.media_width,
                "media_height": msg.media_height,
                "media_duration": msg.media_duration,
                "filename": msg.filename,
                "file_size": msg.file_size,
                "file_type": msg.file_type,
                "is_my_message": msg.from_user_id == user.id,
                "is_edited": msg.is_edited,
                "is_pinned": msg.is_pinned,
                "is_encrypted": msg.is_encrypted,
                "chat_type": msg_chat_type,
                "chat_id": msg_chat_id,
                "from_user_id": msg.from_user_id,
                "to_user_id": msg.to_user_id,
                "group_id": msg.group_id,
                "channel_id": msg.channel_id,
                "reply_to": reply_to_info,
                "forwarded_from": forwarded_message_info,
                "reactions": msg.reactions_summary or {},
                "read_by": msg.read_by or [],
                "sender": {
                    "id": sender.id if sender else None,
                    "username": sender.username if sender else "System",
                    "display_name": sender.display_name if sender else None,
                    "avatar_url": sender.avatar_url if sender else None,
                    "is_online": sender.is_online if sender else False,
                    "is_verified": sender.is_verified if sender else False
                } if sender else {"username": "System"},
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
                "updated_at": msg.updated_at.isoformat() if msg.updated_at else None
            })
        
        return {
            "success": True,
            "messages": messages_data,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "pages": (total + limit - 1) // limit
            }
        }
        
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки сообщений: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка загрузки сообщений: {str(e)}"
        )

@app.get("/api/messages/chat/{chat_type}/{chat_id}")
async def get_chat_messages(
    chat_type: str,
    chat_id: int,
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=500),
    before: Optional[str] = Query(None),
    after: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение сообщений для чата с пагинацией и поиском"""
    try:
        query = db.query(Message).filter(Message.is_deleted == False)
        
        if chat_type == "private":
            # Личные сообщения с пользователем
            other_user = db.query(User).filter(
                User.id == chat_id,
                User.is_active == True
            ).first()
            
            if not other_user:
                raise HTTPException(status_code=404, detail="Пользователь не найден")
            
            # Проверяем, не заблокирован ли пользователь
            is_blocked = db.query(Contact).filter(
                Contact.user_id == user.id,
                Contact.contact_id == chat_id,
                Contact.is_blocked == True
            ).first() is not None
            
            if is_blocked:
                raise HTTPException(status_code=403, detail="Пользователь заблокирован")
            
            query = query.filter(
                or_(
                    and_(Message.from_user_id == user.id, Message.to_user_id == chat_id),
                    and_(Message.from_user_id == chat_id, Message.to_user_id == user.id)
                )
            )
            
        elif chat_type == "group":
            # Сообщения группы
            group = db.query(Group).filter(
                Group.id == chat_id,
                Group.is_active == True
            ).first()
            
            if not group:
                raise HTTPException(status_code=404, detail="Группа не найдена")
            
            # Проверяем доступ
            if not group.is_public:
                membership = db.query(GroupMember).filter(
                    GroupMember.group_id == chat_id,
                    GroupMember.user_id == user.id,
                    GroupMember.is_banned == False
                ).first()
                
                if not membership:
                    raise HTTPException(status_code=403, detail="Вы не состоите в этой группе")
            
            query = query.filter(Message.group_id == chat_id)
            
        elif chat_type == "channel":
            # Сообщения канала
            channel = db.query(Channel).filter(
                Channel.id == chat_id,
                Channel.is_active == True
            ).first()
            
            if not channel:
                raise HTTPException(status_code=404, detail="Канал не найден")
            
            # Проверяем доступ
            if not channel.is_public:
                subscription = db.query(ChannelSubscription).filter(
                    ChannelSubscription.channel_id == chat_id,
                    ChannelSubscription.user_id == user.id,
                    ChannelSubscription.is_banned == False
                ).first()
                
                if not subscription:
                    raise HTTPException(status_code=403, detail="Вы не подписаны на этот канал")
            
            query = query.filter(Message.channel_id == chat_id)
            
        else:
            raise HTTPException(status_code=400, detail="Неверный тип чата")
        
        # Фильтрация по времени
        if before:
            try:
                before_time = datetime.fromisoformat(before.replace('Z', '+00:00'))
                query = query.filter(Message.created_at < before_time)
            except:
                pass
        
        if after:
            try:
                after_time = datetime.fromisoformat(after.replace('Z', '+00:00'))
                query = query.filter(Message.created_at > after_time)
            except:
                pass
        
        # Поиск по содержимому
        if search and search.strip():
            search_filter = f"%{search.strip()}%"
            query = query.filter(Message.content.ilike(search_filter))
        
        total = query.count()
        messages = query.order_by(desc(Message.created_at)) \
                       .offset((page - 1) * limit) \
                       .limit(limit) \
                       .all()
        
        messages_data = []
        for msg in messages:
            sender = None
            if msg.from_user_id:
                sender = db.query(User).filter(User.id == msg.from_user_id).first()
            
            # Получаем информацию о пересланном сообщении
            forwarded_message_info = None
            if msg.forwarded_message_id and msg.forwarded_from:
                forwarded_user = db.query(User).filter(User.id == msg.forwarded_from).first()
                if forwarded_user:
                    forwarded_message_info = {
                        "from_user_id": msg.forwarded_from,
                        "from_username": forwarded_user.username,
                        "from_display_name": forwarded_user.display_name,
                        "message_id": msg.forwarded_message_id
                    }
            
            # Получаем информацию о сообщении, на которое ответили
            reply_to_info = None
            if msg.reply_to_id:
                replied_msg = db.query(Message).filter(Message.id == msg.reply_to_id).first()
                if replied_msg:
                    replied_sender = db.query(User).filter(User.id == replied_msg.from_user_id).first()
                    reply_to_info = {
                        "message_id": replied_msg.id,
                        "content": replied_msg.content[:100] + "..." if len(replied_msg.content or "") > 100 else replied_msg.content,
                        "sender_id": replied_sender.id if replied_sender else None,
                        "sender_username": replied_sender.username if replied_sender else None,
                        "sender_display_name": replied_sender.display_name if replied_sender else None
                    }
            
            # Получаем реакции
            reactions = db.query(MessageReaction).filter(
                MessageReaction.message_id == msg.id
            ).all()
            
            reactions_summary = {}
            for reaction in reactions:
                if reaction.reaction not in reactions_summary:
                    reactions_summary[reaction.reaction] = {
                        "count": 0,
                        "users": []
                    }
                reactions_summary[reaction.reaction]["count"] += 1
                reactions_summary[reaction.reaction]["users"].append(reaction.user_id)
            
            messages_data.append({
                "id": msg.id,
                "content": msg.content,
                "type": msg.message_type,
                "media_url": msg.media_url,
                "thumbnail_url": msg.thumbnail_url,
                "media_size": msg.media_size,
                "media_width": msg.media_width,
                "media_height": msg.media_height,
                "media_duration": msg.media_duration,
                "filename": msg.filename,
                "file_size": msg.file_size,
                "file_type": msg.file_type,
                "is_my_message": msg.from_user_id == user.id,
                "is_edited": msg.is_edited,
                "is_pinned": msg.is_pinned,
                "is_encrypted": msg.is_encrypted,
                "from_user_id": msg.from_user_id,
                "to_user_id": msg.to_user_id,
                "group_id": msg.group_id,
                "channel_id": msg.channel_id,
                "reply_to": reply_to_info,
                "forwarded_from": forwarded_message_info,
                "reactions": reactions_summary,
                "read_by": msg.read_by or [],
                "sender": {
                    "id": sender.id if sender else None,
                    "username": sender.username if sender else None,
                    "display_name": sender.display_name if sender else None,
                    "avatar_url": sender.avatar_url if sender else None,
                    "is_online": sender.is_online if sender else False,
                    "is_verified": sender.is_verified if sender else False
                } if sender else None,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
                "updated_at": msg.updated_at.isoformat() if msg.updated_at else None
            })
        
        messages_data.reverse()  # Чтобы старые сообщения были в начале
        
        # Получаем информацию о чате
        chat_info = None
        if chat_type == "private" and other_user:
            # Проверяем настройки приватности
            can_see_online = True
            can_see_last_seen = True
            
            if other_user.settings and "privacy" in other_user.settings:
                privacy = other_user.settings["privacy"]
                
                if privacy.get("online_status") == "contacts":
                    # Проверяем, есть ли в контактах
                    is_contact = db.query(Contact).filter(
                        Contact.user_id == other_user.id,
                        Contact.contact_id == user.id,
                        Contact.is_blocked == False
                    ).first() is not None
                    can_see_online = is_contact
                
                if privacy.get("last_seen") == "contacts":
                    is_contact = db.query(Contact).filter(
                        Contact.user_id == other_user.id,
                        Contact.contact_id == user.id,
                        Contact.is_blocked == False
                    ).first() is not None
                    can_see_last_seen = is_contact
            
            chat_info = {
                "type": "private",
                "id": other_user.id,
                "name": other_user.display_name or other_user.username,
                "avatar_url": other_user.avatar_url,
                "is_online": other_user.is_online if can_see_online else None,
                "is_verified": other_user.is_verified,
                "status": other_user.status,
                "status_message": other_user.status_message,
                "last_seen": other_user.last_seen.isoformat() if other_user.last_seen and can_see_last_seen else None,
                "bio": other_user.bio
            }
        elif chat_type == "group" and group:
            chat_info = {
                "type": "group",
                "id": group.id,
                "name": group.name,
                "avatar_url": group.avatar_url,
                "banner_url": group.banner_url,
                "description": group.description,
                "is_public": group.is_public,
                "is_encrypted": group.is_encrypted,
                "owner_id": group.owner_id,
                "members_count": group.members_count,
                "online_count": group.online_count,
                "settings": group.settings,
                "pinned_message_id": group.pinned_message_id
            }
        elif chat_type == "channel" and channel:
            chat_info = {
                "type": "channel",
                "id": channel.id,
                "name": channel.name,
                "avatar_url": channel.avatar_url,
                "banner_url": channel.banner_url,
                "description": channel.description,
                "is_public": channel.is_public,
                "is_verified": channel.is_verified,
                "is_encrypted": channel.is_encrypted,
                "owner_id": channel.owner_id,
                "subscribers_count": channel.subscribers_count,
                "online_count": channel.online_count,
                "settings": channel.settings,
                "pinned_message_id": channel.pinned_message_id
            }
        
        return {
            "success": True,
            "chat_info": chat_info,
            "messages": messages_data,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "pages": (total + limit - 1) // limit,
                "has_more": total > page * limit
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки сообщений: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка загрузки сообщений: {str(e)}"
        )

@app.post("/api/messages")
async def create_message(
    content: Optional[str] = Form(None),
    message_type: str = Form("text"),
    to_user_id: Optional[int] = Form(None),
    group_id: Optional[int] = Form(None),
    channel_id: Optional[int] = Form(None),
    reply_to_id: Optional[int] = Form(None),
    forwarded_from: Optional[int] = Form(None),
    forwarded_message_id: Optional[int] = Form(None),
    is_encrypted: bool = Form(False),
    media: Optional[UploadFile] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Создание нового сообщения"""
    try:
        content = content.strip() if content else ""
        media_url = None
        media_size = None
        media_width = None
        media_height = None
        media_duration = None
        thumbnail_url = None
        filename = None
        file_size = None
        file_type = None
        
        if not content and not media:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Сообщение не может быть пустым"
            )
        
        # Проверяем получателя
        chat_type = None
        if to_user_id:
            chat_type = "private"
            recipient = db.query(User).filter(
                User.id == to_user_id,
                User.is_active == True
            ).first()
            
            if not recipient:
                raise HTTPException(status_code=404, detail="Получатель не найден")
            
            if to_user_id == user.id:
                raise HTTPException(status_code=400, detail="Нельзя отправлять сообщения самому себе")
            
            # Проверяем, не заблокирован ли пользователь
            is_blocked = db.query(Contact).filter(
                or_(
                    and_(Contact.user_id == user.id, Contact.contact_id == to_user_id, Contact.is_blocked == True),
                    and_(Contact.user_id == to_user_id, Contact.contact_id == user.id, Contact.is_blocked == True)
                )
            ).first() is not None
            
            if is_blocked:
                raise HTTPException(status_code=403, detail="Нельзя отправлять сообщения заблокированному пользователю")
                
        elif group_id:
            chat_type = "group"
            group = db.query(Group).filter(
                Group.id == group_id,
                Group.is_active == True
            ).first()
            
            if not group:
                raise HTTPException(status_code=404, detail="Группа не найдена")
            
            # Проверяем доступ
            membership = db.query(GroupMember).filter(
                GroupMember.group_id == group_id,
                GroupMember.user_id == user.id,
                GroupMember.is_banned == False
            ).first()
            
            if not membership and not group.is_public:
                raise HTTPException(status_code=403, detail="Вы не состоите в этой группе")
            
            # Проверяем права на отправку сообщений
            if membership and not membership.permissions.get("send_messages", True):
                raise HTTPException(status_code=403, detail="У вас нет прав на отправку сообщений в этой группе")
            
            # Проверяем slow mode
            if group.settings and group.settings.get("slow_mode", 0) > 0:
                # Проверяем время последнего сообщения
                last_message = db.query(Message).filter(
                    Message.group_id == group_id,
                    Message.from_user_id == user.id
                ).order_by(desc(Message.created_at)).first()
                
                if last_message:
                    time_diff = (datetime.utcnow() - last_message.created_at).total_seconds()
                    slow_mode_seconds = group.settings.get("slow_mode", 0)
                    
                    if time_diff < slow_mode_seconds:
                        wait_time = slow_mode_seconds - int(time_diff)
                        raise HTTPException(
                            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                            detail=f"Slow mode активен. Подождите {wait_time} секунд"
                        )
            
            # Проверяем, разрешено ли отправлять медиа
            if media and group.settings:
                media_type = media.content_type or ""
                
                if media_type.startswith('image/') and not group.settings.get("allow_photos", True):
                    raise HTTPException(status_code=403, detail="Отправка фото запрещена в этой группе")
                
                if media_type.startswith('video/') and not group.settings.get("allow_videos", True):
                    raise HTTPException(status_code=403, detail="Отправка видео запрещена в этой группе")
                
                if media_type.startswith('audio/') and not group.settings.get("allow_voice", True):
                    raise HTTPException(status_code=403, detail="Отправка аудио запрещена в этой группе")
                    
        elif channel_id:
            chat_type = "channel"
            channel = db.query(Channel).filter(
                Channel.id == channel_id,
                Channel.is_active == True
            ).first()
            
            if not channel:
                raise HTTPException(status_code=404, detail="Канал не найден")
            
            # Проверяем доступ
            subscription = db.query(ChannelSubscription).filter(
                ChannelSubscription.channel_id == channel_id,
                ChannelSubscription.user_id == user.id,
                ChannelSubscription.is_banned == False
            ).first()
            
            if not subscription and not channel.is_public:
                raise HTTPException(status_code=403, detail="Вы не подписаны на этот канал")
            
            # Проверяем права на отправку сообщений (в каналах обычно только владелец и админы могут писать)
            if channel.settings and channel.settings.get("admin_only_posting", True):
                if user.id != channel.owner_id:
                    if not subscription or subscription.role not in ["admin", "moderator"]:
                        raise HTTPException(status_code=403, detail="Только администраторы могут отправлять сообщения в этот канал")
        else:
            raise HTTPException(status_code=400, detail="Не указан получатель")
        
        # Проверяем reply_to_id
        if reply_to_id:
            replied_message = db.query(Message).filter(
                Message.id == reply_to_id,
                Message.is_deleted == False
            ).first()
            
            if not replied_message:
                raise HTTPException(status_code=404, detail="Сообщение для ответа не найдено")
            
            # Проверяем, что сообщение находится в том же чате
            if chat_type == "private":
                if not (
                    (replied_message.from_user_id == user.id and replied_message.to_user_id == to_user_id) or
                    (replied_message.from_user_id == to_user_id and replied_message.to_user_id == user.id)
                ):
                    raise HTTPException(status_code=400, detail="Нельзя ответить на сообщение из другого чата")
            elif chat_type == "group":
                if replied_message.group_id != group_id:
                    raise HTTPException(status_code=400, detail="Нельзя ответить на сообщение из другой группы")
            elif chat_type == "channel":
                if replied_message.channel_id != channel_id:
                    raise HTTPException(status_code=400, detail="Нельзя ответить на сообщение из другого канала")
        
        # Обработка медиа файла
        if media:
            # Проверяем размер файла
            file_size = 0
            media.file.seek(0, 2)
            file_size = media.file.tell()
            media.file.seek(0)
            
            if file_size > MAX_UPLOAD_SIZE:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Размер файла не должен превышать {MAX_UPLOAD_SIZE // (1024*1024)} MB"
                )
            
            # Проверяем тип файла
            mime_type = media.content_type or mimetypes.guess_type(media.filename)[0]
            is_allowed, error_msg = FileHandler.is_allowed_file(media)
            
            if not is_allowed:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=error_msg
                )
            
            filename = media.filename
            file_type = FileHandler.get_file_type(mime_type)
            
            # Определяем тип сообщения
            if mime_type.startswith('image/'):
                message_type = "image"
                subdir = "images"
            elif mime_type.startswith('video/'):
                message_type = "video"
                subdir = "videos"
            elif mime_type.startswith('audio/'):
                message_type = "audio"
                subdir = "audios"
            else:
                message_type = "file"
                subdir = "files"
            
            # Генерируем уникальное имя файла
            file_ext = media.filename.split('.')[-1] if '.' in media.filename else 'bin'
            unique_filename = f"{uuid.uuid4()}.{file_ext}"
            filepath = UPLOAD_DIR / subdir / unique_filename
            
            # Сохраняем файл
            with open(filepath, "wb") as buffer:
                shutil.copyfileobj(media.file, buffer)
            
            media_url = f"/uploads/{subdir}/{unique_filename}"
            media_size = file_size
            
            # Для изображений и видео создаем миниатюру
            if mime_type.startswith('image/'):
                try:
                    with Image.open(filepath) as img:
                        media_width, media_height = img.size
                    
                    # Создаем миниатюру
                    thumb_buffer = FileHandler.generate_thumbnail(filepath)
                    if thumb_buffer:
                        thumb_filename = f"thumb_{unique_filename}"
                        thumb_path = UPLOAD_DIR / "thumbnails" / thumb_filename
                        with open(thumb_path, "wb") as f:
                            f.write(thumb_buffer.getvalue())
                        thumbnail_url = f"/uploads/thumbnails/{thumb_filename}"
                except Exception as e:
                    logger.warning(f"Не удалось обработать изображение: {e}")
            
            elif mime_type.startswith('video/'):
                # Для видео можно добавить извлечение информации с помощью ffmpeg
                # Пока просто указываем тип
                thumbnail_url = None  # Можно добавить генерацию thumbnail для видео
            
            # Вычисляем хеши файла
            md5_hash, sha256_hash = FileHandler.get_file_hash(filepath)
            
            # Сохраняем информацию о файле в базу
            file_record = File(
                user_id=user.id,
                filename=unique_filename,
                original_filename=filename,
                file_path=str(filepath),
                file_url=media_url,
                file_size=file_size,
                file_type=file_type,
                mime_type=mime_type,
                width=media_width,
                height=media_height,
                duration=media_duration,
                hash_md5=md5_hash,
                hash_sha256=sha256_hash,
                thumbnail_url=thumbnail_url,
                is_public=(chat_type in ["group", "channel"])  # В группах и каналах файлы публичные
            )
            db.add(file_record)
        
        # Шифрование контента если нужно
        encrypted_content = None
        encryption_key = None
        
        if is_encrypted and content:
            try:
                encrypted_content = encryption_helper.encrypt(content)
                encryption_key = secrets.token_urlsafe(32)
                content = ""  # Очищаем открытый текст
            except Exception as e:
                logger.error(f"Ошибка шифрования: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Ошибка шифрования сообщения"
                )
        
        # Создаем сообщение
        message = Message(
            from_user_id=user.id,
            to_user_id=to_user_id,
            group_id=group_id,
            channel_id=channel_id,
            reply_to_id=reply_to_id,
            content=content,
            encrypted_content=encrypted_content,
            message_type=message_type,
            media_url=media_url,
            media_size=media_size,
            media_width=media_width,
            media_height=media_height,
            media_duration=media_duration,
            thumbnail_url=thumbnail_url,
            filename=filename,
            file_size=file_size,
            file_type=file_type,
            is_encrypted=is_encrypted,
            encryption_key=encryption_key,
            forwarded_from=forwarded_from,
            forwarded_message_id=forwarded_message_id,
            reactions_summary={},
            read_by=[user.id]  # Отправитель сразу прочитал свое сообщение
        )
        
        db.add(message)
        db.commit()
        db.refresh(message)
        
        # Связываем файл с сообщением если есть
        if media and 'file_record' in locals():
            file_record.message_id = message.id
            db.commit()
        
        # Получаем информацию об отправителе
        sender = db.query(User).filter(User.id == user.id).first()
        
        # Подготавливаем данные для WebSocket
        ws_message = {
            "type": "message",
            "chat_type": chat_type,
            "chat_id": to_user_id or group_id or channel_id,
            "message": {
                "id": message.id,
                "content": message.content,
                "type": message.message_type,
                "media_url": message.media_url,
                "thumbnail_url": message.thumbnail_url,
                "filename": message.filename,
                "file_size": message.file_size,
                "file_type": message.file_type,
                "is_my_message": False,
                "is_edited": False,
                "is_pinned": False,
                "is_encrypted": message.is_encrypted,
                "from_user_id": message.from_user_id,
                "to_user_id": message.to_user_id,
                "group_id": message.group_id,
                "channel_id": message.channel_id,
                "reply_to_id": message.reply_to_id,
                "forwarded_from": message.forwarded_from,
                "forwarded_message_id": message.forwarded_message_id,
                "reactions": message.reactions_summary or {},
                "read_by": message.read_by or [],
                "sender": {
                    "id": sender.id,
                    "username": sender.username,
                    "display_name": sender.display_name,
                    "avatar_url": sender.avatar_url,
                    "is_online": sender.is_online,
                    "is_verified": sender.is_verified
                } if sender else None,
                "created_at": message.created_at.isoformat() if message.created_at else datetime.utcnow().isoformat(),
                "updated_at": message.updated_at.isoformat() if message.updated_at else None
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Отправляем через WebSocket
        if chat_type == "private":
            # Отправляем отправителю подтверждение
            await manager.send_to_user(user.id, {
                **ws_message,
                "type": "message_sent",
                "message_id": message.id
            })
            
            # Отправляем получателю
            if to_user_id != user.id:
                await manager.send_to_user(to_user_id, ws_message)
                
        elif chat_type == "group":
            # Отправляем всем участникам группы
            await manager.broadcast_to_chat("group", group_id, ws_message, exclude_user_id=user.id)
            
            # Отправляем подтверждение отправителю
            await manager.send_to_user(user.id, {
                **ws_message,
                "type": "message_sent",
                "message_id": message.id
            })
            
        elif chat_type == "channel":
            # Отправляем всем подписчикам канала
            await manager.broadcast_to_chat("channel", channel_id, ws_message, exclude_user_id=user.id)
            
            # Отправляем подтверждение отправителю
            await manager.send_to_user(user.id, {
                **ws_message,
                "type": "message_sent",
                "message_id": message.id
            })
        
        return {
            "success": True,
            "message": "Сообщение отправлено",
            "data": {
                "id": message.id,
                "content": message.content,
                "type": message.message_type,
                "media_url": message.media_url,
                "thumbnail_url": message.thumbnail_url,
                "filename": message.filename,
                "is_encrypted": message.is_encrypted,
                "chat_type": chat_type,
                "chat_id": to_user_id or group_id or channel_id,
                "reply_to_id": message.reply_to_id,
                "created_at": message.created_at.isoformat() if message.created_at else None
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Ошибка отправки сообщения: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка отправки сообщения: {str(e)}"
        )

@app.put("/api/messages/{message_id}")
async def update_message(
    message_id: int,
    content: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Редактирование сообщения"""
    try:
        message = db.query(Message).filter(
            Message.id == message_id,
            Message.from_user_id == user.id,
            Message.is_deleted == False
        ).first()
        
        if not message:
            raise HTTPException(status_code=404, detail="Сообщение не найдено")
        
        # Проверяем, что прошло не слишком много времени
        time_diff = datetime.utcnow() - message.created_at
        if time_diff.total_seconds() > 24 * 3600:  # 24 часа
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Сообщение можно редактировать только в течение 24 часов"
            )
        
        message.content = content.strip()
        message.is_edited = True
        message.updated_at = datetime.utcnow()
        db.commit()
        
        # Уведомляем через WebSocket
        ws_message = {
            "type": "message_updated",
            "message_id": message.id,
            "content": message.content,
            "updated_at": message.updated_at.isoformat()
        }
        
        # Определяем чат и отправляем уведомление
        if message.to_user_id:
            # Личное сообщение
            participants = [message.from_user_id, message.to_user_id]
            for participant in participants:
                if participant in manager.user_connections:
                    await manager.send_to_user(participant, ws_message)
        elif message.group_id:
            # Групповое сообщение
            await manager.broadcast_to_chat("group", message.group_id, ws_message)
        elif message.channel_id:
            # Сообщение в канале
            await manager.broadcast_to_chat("channel", message.channel_id, ws_message)
        
        return {
            "success": True,
            "message": "Сообщение обновлено",
            "data": {
                "id": message.id,
                "content": message.content,
                "is_edited": message.is_edited,
                "updated_at": message.updated_at.isoformat()
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Ошибка обновления сообщения: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка обновления сообщения: {str(e)}"
        )

@app.delete("/api/messages/{message_id}")
async def delete_message(
    message_id: int,
    for_everyone: bool = Query(False),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Удаление сообщения"""
    try:
        message = db.query(Message).filter(
            Message.id == message_id
        ).first()
        
        if not message:
            raise HTTPException(status_code=404, detail="Сообщение не найдено")
        
        # Проверяем права
        can_delete = False
        
        if message.from_user_id == user.id:
            can_delete = True
        elif message.group_id:
            # В группе могут удалять админы и модераторы
            membership = db.query(GroupMember).filter(
                GroupMember.group_id == message.group_id,
                GroupMember.user_id == user.id,
                GroupMember.is_banned == False
            ).first()
            
            if membership and membership.permissions.get("delete_messages", False):
                can_delete = True
            
            # Владелец группы может удалять любые сообщения
            group = db.query(Group).filter(Group.id == message.group_id).first()
            if group and group.owner_id == user.id:
                can_delete = True
        elif message.channel_id:
            # В канале могут удалять админы
            channel = db.query(Channel).filter(Channel.id == message.channel_id).first()
            if channel and channel.owner_id == user.id:
                can_delete = True
        
        if not can_delete:
            raise HTTPException(status_code=403, detail="Нет прав на удаление сообщения")
        
        if for_everyone:
            # Удаление для всех
            message.is_deleted = True
            message.content = "Сообщение удалено"
            message.media_url = None
            message.filename = None
            message.deleted_at = datetime.utcnow()
        else:
            # Удаление только для себя (в личных сообщениях)
            if message.to_user_id:
                # Помечаем как прочитанное если это личное сообщение
                if user.id not in (message.read_by or []):
                    if not message.read_by:
                        message.read_by = []
                    message.read_by.append(user.id)
            # TODO: Реализовать скрытие сообщения только для определенного пользователя
        
        message.updated_at = datetime.utcnow()
        db.commit()
        
        # Уведомляем через WebSocket если удалено для всех
        if for_everyone:
            ws_message = {
                "type": "message_deleted",
                "message_id": message.id,
                "for_everyone": True
            }
            
            # Определяем чат и отправляем уведомление
            if message.to_user_id:
                # Личное сообщение
                participants = [message.from_user_id, message.to_user_id]
                for participant in participants:
                    if participant in manager.user_connections:
                        await manager.send_to_user(participant, ws_message)
            elif message.group_id:
                # Групповое сообщение
                await manager.broadcast_to_chat("group", message.group_id, ws_message)
            elif message.channel_id:
                # Сообщение в канале
                await manager.broadcast_to_chat("channel", message.channel_id, ws_message)
        
        return {
            "success": True,
            "message": "Сообщение удалено" + (" для всех" if for_everyone else " для вас")
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Ошибка удаления сообщения: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка удаления сообщения: {str(e)}"
        )

@app.post("/api/messages/{message_id}/read")
async def mark_message_as_read(
    message_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Пометка сообщения как прочитанного"""
    try:
        message = db.query(Message).filter(
            Message.id == message_id,
            Message.is_deleted == False
        ).first()
        
        if not message:
            raise HTTPException(status_code=404, detail="Сообщение не найдено")
        
        # Проверяем, имеет ли пользователь доступ к сообщению
        has_access = False
        
        if message.to_user_id == user.id:
            has_access = True
        elif message.group_id:
            membership = db.query(GroupMember).filter(
                GroupMember.group_id == message.group_id,
                GroupMember.user_id == user.id,
                GroupMember.is_banned == False
            ).first()
            has_access = membership is not None
        elif message.channel_id:
            subscription = db.query(ChannelSubscription).filter(
                ChannelSubscription.channel_id == message.channel_id,
                ChannelSubscription.user_id == user.id,
                ChannelSubscription.is_banned == False
            ).first()
            has_access = subscription is not None
        
        if not has_access:
            raise HTTPException(status_code=403, detail="Нет доступа к сообщению")
        
        # Добавляем пользователя в список прочитавших
        if not message.read_by:
            message.read_by = []
        
        if user.id not in message.read_by:
            message.read_by.append(user.id)
            db.commit()
            
            # Уведомляем отправителя о прочтении (для личных сообщений)
            if message.to_user_id and message.from_user_id != user.id:
                ws_message = {
                    "type": "message_read",
                    "message_id": message.id,
                    "reader_id": user.id,
                    "timestamp": datetime.utcnow().isoformat()
                }
                
                if message.from_user_id in manager.user_connections:
                    await manager.send_to_user(message.from_user_id, ws_message)
        
        return {
            "success": True,
            "message": "Сообщение помечено как прочитанное"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Ошибка пометки сообщения как прочитанного: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка пометки сообщения как прочитанного: {str(e)}"
        )

@app.post("/api/messages/{message_id}/reaction")
async def add_message_reaction(
    message_id: int,
    reaction: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Добавление реакции к сообщению"""
    try:
        message = db.query(Message).filter(
            Message.id == message_id,
            Message.is_deleted == False
        ).first()
        
        if not message:
            raise HTTPException(status_code=404, detail="Сообщение не найдено")
        
        # Проверяем доступ к сообщению
        can_react = False
        
        if message.to_user_id:
            # Личное сообщение
            if user.id in [message.from_user_id, message.to_user_id]:
                can_react = True
        elif message.group_id:
            # Групповое сообщение
            membership = db.query(GroupMember).filter(
                GroupMember.group_id == message.group_id,
                GroupMember.user_id == user.id,
                GroupMember.is_banned == False
            ).first()
            
            if membership:
                # Проверяем настройки группы
                group = db.query(Group).filter(Group.id == message.group_id).first()
                if group and group.settings.get("allow_reactions", True):
                    can_react = True
        elif message.channel_id:
            # Сообщение в канале
            subscription = db.query(ChannelSubscription).filter(
                ChannelSubscription.channel_id == message.channel_id,
                ChannelSubscription.user_id == user.id,
                ChannelSubscription.is_banned == False
            ).first()
            
            if subscription:
                # Проверяем настройки канала
                channel = db.query(Channel).filter(Channel.id == message.channel_id).first()
                if channel and channel.settings.get("allow_reactions", True):
                    can_react = True
        
        if not can_react:
            raise HTTPException(status_code=403, detail="Нет доступа к сообщению или реакции запрещены")
        
        # Проверяем, есть ли уже такая реакция от пользователя
        existing_reaction = db.query(MessageReaction).filter(
            MessageReaction.message_id == message_id,
            MessageReaction.user_id == user.id,
            MessageReaction.reaction == reaction
        ).first()
        
        if existing_reaction:
            # Удаляем реакцию
            db.delete(existing_reaction)
            action = "removed"
        else:
            # Добавляем новую реакцию
            new_reaction = MessageReaction(
                message_id=message_id,
                user_id=user.id,
                reaction=reaction
            )
            db.add(new_reaction)
            action = "added"
        
        db.commit()
        
        # Пересчитываем сводку реакций
        reactions = db.query(MessageReaction).filter(
            MessageReaction.message_id == message_id
        ).all()
        
        reactions_summary = {}
        for r in reactions:
            if r.reaction not in reactions_summary:
                reactions_summary[r.reaction] = {
                    "count": 0,
                    "users": []
                }
            reactions_summary[r.reaction]["count"] += 1
            reactions_summary[r.reaction]["users"].append(r.user_id)
        
        message.reactions_summary = reactions_summary
        message.updated_at = datetime.utcnow()
        db.commit()
        
        # Уведомляем через WebSocket
        ws_message = {
            "type": "reaction_update",
            "message_id": message.id,
            "reactions": reactions_summary,
            "user_id": user.id,
            "reaction": reaction,
            "action": action,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Определяем чат и отправляем уведомление
        if message.to_user_id:
            # Личное сообщение
            participants = [message.from_user_id, message.to_user_id]
            for participant in participants:
                if participant in manager.user_connections:
                    await manager.send_to_user(participant, ws_message)
        elif message.group_id:
            # Групповое сообщение
            await manager.broadcast_to_chat("group", message.group_id, ws_message)
        elif message.channel_id:
            # Сообщение в канале
            await manager.broadcast_to_chat("channel", message.channel_id, ws_message)
        
        return {
            "success": True,
            "message": f"Реакция {action}",
            "reactions": reactions_summary,
            "action": action
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Ошибка добавления реакции: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка добавления реакции: {str(e)}"
        )

@app.post("/api/messages/{message_id}/pin")
async def pin_message(
    message_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Закрепление сообщения"""
    try:
        message = db.query(Message).filter(
            Message.id == message_id,
            Message.is_deleted == False
        ).first()
        
        if not message:
            raise HTTPException(status_code=404, detail="Сообщение не найдено")
        
        # Проверяем права
        can_pin = False
        
        if message.group_id:
            # В группе могут закреплять админы и модераторы
            membership = db.query(GroupMember).filter(
                GroupMember.group_id == message.group_id,
                GroupMember.user_id == user.id,
                GroupMember.is_banned == False
            ).first()
            
            if membership and membership.permissions.get("pin_messages", False):
                can_pin = True
            
            # Владелец группы может закреплять
            group = db.query(Group).filter(Group.id == message.group_id).first()
            if group and group.owner_id == user.id:
                can_pin = True
        
        elif message.channel_id:
            # В канале могут закреплять админы
            channel = db.query(Channel).filter(Channel.id == message.channel_id).first()
            if channel and channel.owner_id == user.id:
                can_pin = True
            
            subscription = db.query(ChannelSubscription).filter(
                ChannelSubscription.channel_id == message.channel_id,
                ChannelSubscription.user_id == user.id,
                ChannelSubscription.is_banned == False
            ).first()
            
            if subscription and subscription.role in ["admin", "moderator"]:
                can_pin = True
        
        if not can_pin:
            raise HTTPException(status_code=403, detail="Нет прав на закрепление сообщения")
        
        # Снимаем закрепление с предыдущего сообщения если есть
        if message.group_id:
            group = db.query(Group).filter(Group.id == message.group_id).first()
            if group and group.pinned_message_id:
                prev_pinned = db.query(Message).filter(Message.id == group.pinned_message_id).first()
                if prev_pinned:
                    prev_pinned.is_pinned = False
            group.pinned_message_id = message_id
        
        elif message.channel_id:
            channel = db.query(Channel).filter(Channel.id == message.channel_id).first()
            if channel and channel.pinned_message_id:
                prev_pinned = db.query(Message).filter(Message.id == channel.pinned_message_id).first()
                if prev_pinned:
                    prev_pinned.is_pinned = False
            channel.pinned_message_id = message_id
        
        message.is_pinned = True
        message.updated_at = datetime.utcnow()
        db.commit()
        
        # Уведомляем через WebSocket
        ws_message = {
            "type": "message_pinned",
            "message_id": message.id,
            "pinned_by": user.id,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        if message.group_id:
            await manager.broadcast_to_chat("group", message.group_id, ws_message)
        elif message.channel_id:
            await manager.broadcast_to_chat("channel", message.channel_id, ws_message)
        
        return {
            "success": True,
            "message": "Сообщение закреплено"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Ошибка закрепления сообщения: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка закрепления сообщения: {str(e)}"
        )

@app.post("/api/messages/{message_id}/unpin")
async def unpin_message(
    message_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Открепление сообщения"""
    try:
        message = db.query(Message).filter(
            Message.id == message_id,
            Message.is_deleted == False,
            Message.is_pinned == True
        ).first()
        
        if not message:
            raise HTTPException(status_code=404, detail="Закрепленное сообщение не найдено")
        
        # Проверяем права (аналогично закреплению)
        can_unpin = False
        
        if message.group_id:
            membership = db.query(GroupMember).filter(
                GroupMember.group_id == message.group_id,
                GroupMember.user_id == user.id,
                GroupMember.is_banned == False
            ).first()
            
            if membership and membership.permissions.get("pin_messages", False):
                can_unpin = True
            
            group = db.query(Group).filter(Group.id == message.group_id).first()
            if group and group.owner_id == user.id:
                can_unpin = True
        
        elif message.channel_id:
            channel = db.query(Channel).filter(Channel.id == message.channel_id).first()
            if channel and channel.owner_id == user.id:
                can_unpin = True
            
            subscription = db.query(ChannelSubscription).filter(
                ChannelSubscription.channel_id == message.channel_id,
                ChannelSubscription.user_id == user.id,
                ChannelSubscription.is_banned == False
            ).first()
            
            if subscription and subscription.role in ["admin", "moderator"]:
                can_unpin = True
        
        if not can_unpin:
            raise HTTPException(status_code=403, detail="Нет прав на открепление сообщения")
        
        # Обновляем группу или канал
        if message.group_id:
            group = db.query(Group).filter(Group.id == message.group_id).first()
            if group and group.pinned_message_id == message_id:
                group.pinned_message_id = None
        
        elif message.channel_id:
            channel = db.query(Channel).filter(Channel.id == message.channel_id).first()
            if channel and channel.pinned_message_id == message_id:
                channel.pinned_message_id = None
        
        message.is_pinned = False
        message.updated_at = datetime.utcnow()
        db.commit()
        
        # Уведомляем через WebSocket
        ws_message = {
            "type": "message_unpinned",
            "message_id": message.id,
            "unpinned_by": user.id,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        if message.group_id:
            await manager.broadcast_to_chat("group", message.group_id, ws_message)
        elif message.channel_id:
            await manager.broadcast_to_chat("channel", message.channel_id, ws_message)
        
        return {
            "success": True,
            "message": "Сообщение откреплено"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Ошибка открепления сообщения: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка открепления сообщения: {str(e)}"
        )

# ========== ГРУППЫ ==========

@app.get("/api/groups")
async def get_groups(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    search: Optional[str] = Query(None),
    only_my: bool = Query(False),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение списка групп"""
    try:
        query = db.query(Group).filter(Group.is_active == True)
        
        if only_my:
            # Только группы, в которых состоит пользователь
            user_group_ids = db.query(GroupMember.group_id).filter(
                GroupMember.user_id == user.id,
                GroupMember.is_banned == False
            ).subquery()
            
            query = query.filter(Group.id.in_(user_group_ids))
        else:
            # Публичные группы или группы, в которых состоит пользователь
            user_group_ids = db.query(GroupMember.group_id).filter(
                GroupMember.user_id == user.id,
                GroupMember.is_banned == False
            ).subquery()
            
            query = query.filter(
                or_(
                    Group.is_public == True,
                    Group.id.in_(user_group_ids)
                )
            )
        
        if search and search.strip():
            search_filter = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    Group.name.ilike(search_filter),
                    Group.description.ilike(search_filter)
                )
            )
        
        total = query.count()
        groups = query.order_by(desc(Group.created_at)) \
                      .offset((page - 1) * limit) \
                      .limit(limit) \
                      .all()
        
        groups_data = []
        for group in groups:
            # Проверяем, состоит ли пользователь в группе
            membership = db.query(GroupMember).filter(
                GroupMember.group_id == group.id,
                GroupMember.user_id == user.id,
                GroupMember.is_banned == False
            ).first()
            
            is_member = membership is not None
            is_owner = group.owner_id == user.id
            
            # Получаем последнее сообщение
            last_message = db.query(Message).filter(
                Message.group_id == group.id,
                Message.is_deleted == False
            ).order_by(desc(Message.created_at)).first()
            
            # Считаем количество онлайн участников
            online_members = db.query(GroupMember).join(User).filter(
                GroupMember.group_id == group.id,
                GroupMember.is_banned == False,
                User.is_online == True
            ).count()
            
            group.online_count = online_members
            db.commit()
            
            groups_data.append({
                "id": group.id,
                "name": group.name,
                "description": group.description,
                "avatar_url": group.avatar_url,
                "banner_url": group.banner_url,
                "is_public": group.is_public,
                "is_encrypted": group.is_encrypted,
                "owner_id": group.owner_id,
                "members_count": group.members_count,
                "online_count": online_members,
                "max_members": group.max_members,
                "is_member": is_member,
                "is_owner": is_owner,
                "role": membership.role if membership else None,
                "permissions": membership.permissions if membership else None,
                "last_message": {
                    "id": last_message.id if last_message else None,
                    "content": last_message.content if last_message else None,
                    "type": last_message.message_type if last_message else None,
                    "timestamp": last_message.created_at.isoformat() if last_message else None,
                    "sender_id": last_message.from_user_id if last_message else None
                } if last_message else None,
                "pinned_message_id": group.pinned_message_id,
                "settings": group.settings,
                "invite_link": group.invite_link,
                "invite_expires": group.invite_expires.isoformat() if group.invite_expires else None,
                "created_at": group.created_at.isoformat() if group.created_at else None,
                "updated_at": group.updated_at.isoformat() if group.updated_at else None
            })
        
        return {
            "success": True,
            "groups": groups_data,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "pages": (total + limit - 1) // limit
            }
        }
        
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки групп: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка загрузки групп: {str(e)}"
        )

@app.post("/api/groups")
async def create_group(
    request: GroupCreateRequest,
    avatar: Optional[UploadFile] = None,
    banner: Optional[UploadFile] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Создание новой группы"""
    try:
        if not request.name or len(request.name.strip()) < 3:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Название группы должно быть не менее 3 символов"
            )
        
        name = request.name.strip()
        
        # Проверяем, существует ли группа с таким именем
        existing_group = db.query(Group).filter(
            func.lower(Group.name) == func.lower(name),
            Group.is_active == True
        ).first()
        
        if existing_group:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Группа с таким названием уже существует"
            )
        
        # Обработка аватара
        avatar_url = None
        if avatar:
            allowed_types = ["image/jpeg", "image/png", "image/webp", "image/gif"]
            
            if avatar.content_type not in allowed_types:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Неподдерживаемый формат изображения для аватара"
                )
            
            # Проверяем размер файла
            file_size = 0
            avatar.file.seek(0, 2)
            file_size = avatar.file.tell()
            avatar.file.seek(0)
            
            if file_size > 5 * 1024 * 1024:  # 5 MB
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Размер аватара не должен превышать 5 MB"
                )
            
            file_ext = avatar.filename.split('.')[-1] if '.' in avatar.filename else 'jpg'
            filename = f"group_avatar_{uuid.uuid4()}.{file_ext}"
            filepath = UPLOAD_DIR / "avatars" / filename
            
            with open(filepath, "wb") as buffer:
                shutil.copyfileobj(avatar.file, buffer)
            
            avatar_url = f"/uploads/avatars/{filename}"
        
        # Обработка баннера
        banner_url = None
        if banner:
            allowed_types = ["image/jpeg", "image/png", "image/webp"]
            
            if banner.content_type not in allowed_types:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Неподдерживаемый формат изображения для баннера"
                )
            
            file_size = 0
            banner.file.seek(0, 2)
            file_size = banner.file.tell()
            banner.file.seek(0)
            
            if file_size > 10 * 1024 * 1024:  # 10 MB
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Размер баннера не должен превышать 10 MB"
                )
            
            file_ext = banner.filename.split('.')[-1] if '.' in banner.filename else 'jpg'
            filename = f"group_banner_{uuid.uuid4()}.{file_ext}"
            filepath = UPLOAD_DIR / "images" / filename
            
            with open(filepath, "wb") as buffer:
                shutil.copyfileobj(banner.file, buffer)
            
            banner_url = f"/uploads/images/{filename}"
        
        # Настройки по умолчанию
        default_settings = {
            "allow_photos": True,
            "allow_videos": True,
            "allow_files": True,
            "allow_voice": True,
            "allow_polls": True,
            "allow_invites": True,
            "slow_mode": 0,
            "admin_only_posting": False,
            "allow_reactions": True
        }
        
        if request.settings:
            default_settings.update(request.settings)
        
        # Создаем группу
        group = Group(
            name=name,
            description=request.description.strip() if request.description else None,
            avatar_url=avatar_url,
            banner_url=banner_url,
            is_public=request.is_public,
            is_encrypted=request.is_encrypted,
            owner_id=user.id,
            members_count=1,
            online_count=1,
            max_members=MAX_USERS_PER_GROUP,
            settings=default_settings,
            invite_link=secrets.token_urlsafe(16),
            invite_expires=datetime.utcnow() + timedelta(days=30)
        )
        
        db.add(group)
        db.commit()
        db.refresh(group)
        
        # Добавляем создателя в группу
        group_member = GroupMember(
            group_id=group.id,
            user_id=user.id,
            role="admin",
            permissions={
                "send_messages": True,
                "send_media": True,
                "add_members": True,
                "pin_messages": True,
                "change_group_info": True,
                "delete_messages": True,
                "ban_members": True
            }
        )
        db.add(group_member)
        db.commit()
        
        # Создаем приветственное сообщение
        welcome_message = Message(
            from_user_id=user.id,
            group_id=group.id,
            content=f"Группа '{name}' создана! Добро пожаловать!",
            message_type="system"
        )
        db.add(welcome_message)
        db.commit()
        
        return {
            "success": True,
            "message": "Группа создана успешно",
            "group": {
                "id": group.id,
                "name": group.name,
                "description": group.description,
                "avatar_url": group.avatar_url,
                "banner_url": group.banner_url,
                "is_public": group.is_public,
                "is_encrypted": group.is_encrypted,
                "owner_id": group.owner_id,
                "members_count": group.members_count,
                "online_count": group.online_count,
                "invite_link": group.invite_link,
                "settings": group.settings,
                "created_at": group.created_at.isoformat() if group.created_at else None
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Ошибка создания группы: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка создания группы: {str(e)}"
        )

@app.get("/api/groups/{group_id}")
async def get_group_by_id(
    group_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение информации о группе"""
    try:
        group = db.query(Group).filter(
            Group.id == group_id,
            Group.is_active == True
        ).first()
        
        if not group:
            raise HTTPException(status_code=404, detail="Группа не найдена")
        
        # Проверяем доступ
        membership = db.query(GroupMember).filter(
            GroupMember.group_id == group_id,
            GroupMember.user_id == user.id,
            GroupMember.is_banned == False
        ).first()
        
        is_member = membership is not None
        is_owner = group.owner_id == user.id
        
        if not group.is_public and not is_member and not is_owner:
            raise HTTPException(status_code=403, detail="У вас нет доступа к этой группе")
        
        # Получаем участников
        members = db.query(User).join(GroupMember).filter(
            GroupMember.group_id == group_id,
            GroupMember.is_banned == False
        ).order_by(
            desc(GroupMember.role == "admin"),
            desc(GroupMember.role == "moderator"),
            User.display_name,
            User.username
        ).all()
        
        members_data = []
        for member in members:
            member_info = db.query(GroupMember).filter(
                GroupMember.group_id == group_id,
                GroupMember.user_id == member.id
            ).first()
            
            members_data.append({
                "id": member.id,
                "username": member.username,
                "display_name": member.display_name,
                "avatar_url": member.avatar_url,
                "is_online": member.is_online,
                "is_verified": member.is_verified,
                "role": member_info.role if member_info else "member",
                "permissions": member_info.permissions if member_info else None,
                "joined_at": member_info.joined_at.isoformat() if member_info and member_info.joined_at else None,
                "last_seen": member.last_seen.isoformat() if member.last_seen else None
            })
        
        # Получаем закрепленное сообщение если есть
        pinned_message = None
        if group.pinned_message_id:
            pinned_msg = db.query(Message).filter(
                Message.id == group.pinned_message_id,
                Message.is_deleted == False
            ).first()
            
            if pinned_msg:
                pinned_sender = db.query(User).filter(User.id == pinned_msg.from_user_id).first()
                pinned_message = {
                    "id": pinned_msg.id,
                    "content": pinned_msg.content,
                    "type": pinned_msg.message_type,
                    "sender": {
                        "id": pinned_sender.id if pinned_sender else None,
                        "username": pinned_sender.username if pinned_sender else None,
                        "display_name": pinned_sender.display_name if pinned_sender else None
                    } if pinned_sender else None,
                    "created_at": pinned_msg.created_at.isoformat() if pinned_msg.created_at else None
                }
        
        # Получаем последние сообщения
        last_messages = db.query(Message).filter(
            Message.group_id == group_id,
            Message.is_deleted == False
        ).order_by(desc(Message.created_at)).limit(20).all()
        
        messages_data = []
        for msg in last_messages:
            sender = db.query(User).filter(User.id == msg.from_user_id).first()
            messages_data.append({
                "id": msg.id,
                "content": msg.content,
                "type": msg.message_type,
                "media_url": msg.media_url,
                "is_my_message": msg.from_user_id == user.id,
                "sender": {
                    "id": sender.id if sender else None,
                    "username": sender.username if sender else None,
                    "display_name": sender.display_name if sender else None,
                    "avatar_url": sender.avatar_url if sender else None
                } if sender else None,
                "created_at": msg.created_at.isoformat() if msg.created_at else None
            })
        
        messages_data.reverse()
        
        # Считаем количество онлайн участников
        online_count = db.query(GroupMember).join(User).filter(
            GroupMember.group_id == group_id,
            GroupMember.is_banned == False,
            User.is_online == True
        ).count()
        
        group.online_count = online_count
        db.commit()
        
        return {
            "success": True,
            "group": {
                "id": group.id,
                "name": group.name,
                "description": group.description,
                "avatar_url": group.avatar_url,
                "banner_url": group.banner_url,
                "is_public": group.is_public,
                "is_encrypted": group.is_encrypted,
                "owner_id": group.owner_id,
                "members_count": group.members_count,
                "online_count": online_count,
                "max_members": group.max_members,
                "is_member": is_member,
                "is_owner": is_owner,
                "role": membership.role if membership else None,
                "permissions": membership.permissions if membership else None,
                "members": members_data,
                "pinned_message": pinned_message,
                "last_messages": messages_data,
                "settings": group.settings,
                "invite_link": group.invite_link,
                "invite_expires": group.invite_expires.isoformat() if group.invite_expires else None,
                "created_at": group.created_at.isoformat() if group.created_at else None,
                "updated_at": group.updated_at.isoformat() if group.updated_at else None
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки группы: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка загрузки группы: {str(e)}"
        )

@app.put("/api/groups/{group_id}")
async def update_group(
    group_id: int,
    name: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    is_public: Optional[bool] = Form(None),
    avatar: Optional[UploadFile] = None,
    banner: Optional[UploadFile] = None,
    settings: Optional[str] = Form(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Обновление информации о группе"""
    try:
        group = db.query(Group).filter(
            Group.id == group_id,
            Group.is_active == True
        ).first()
        
        if not group:
            raise HTTPException(status_code=404, detail="Группа не найдена")
        
        # Проверяем права
        membership = db.query(GroupMember).filter(
            GroupMember.group_id == group_id,
            GroupMember.user_id == user.id,
            GroupMember.is_banned == False
        ).first()
        
        is_owner = group.owner_id == user.id
        can_change_info = (membership and membership.permissions.get("change_group_info", False)) or is_owner
        
        if not can_change_info:
            raise HTTPException(status_code=403, detail="Нет прав на изменение информации о группе")
        
        # Обновляем название
        if name is not None:
            name = name.strip()
            if len(name) < 3:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Название группы должно быть не менее 3 символов"
                )
            
            # Проверяем уникальность названия
            existing_group = db.query(Group).filter(
                func.lower(Group.name) == func.lower(name),
                Group.id != group_id,
                Group.is_active == True
            ).first()
            
            if existing_group:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Группа с таким названием уже существует"
                )
            
            group.name = name
        
        # Обновляем описание
        if description is not None:
            group.description = description.strip() if description else None
        
        # Обновляем публичность
        if is_public is not None:
            group.is_public = is_public
        
        # Обработка аватара
        if avatar:
            allowed_types = ["image/jpeg", "image/png", "image/webp", "image/gif"]
            
            if avatar.content_type not in allowed_types:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Неподдерживаемый формат изображения для аватара"
                )
            
            file_size = 0
            avatar.file.seek(0, 2)
            file_size = avatar.file.tell()
            avatar.file.seek(0)
            
            if file_size > 5 * 1024 * 1024:  # 5 MB
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Размер аватара не должен превышать 5 MB"
                )
            
            file_ext = avatar.filename.split('.')[-1] if '.' in avatar.filename else 'jpg'
            filename = f"group_avatar_{group_id}_{uuid.uuid4()}.{file_ext}"
            filepath = UPLOAD_DIR / "avatars" / filename
            
            with open(filepath, "wb") as buffer:
                shutil.copyfileobj(avatar.file, buffer)
            
            group.avatar_url = f"/uploads/avatars/{filename}"
        
        # Обработка баннера
        if banner:
            allowed_types = ["image/jpeg", "image/png", "image/webp"]
            
            if banner.content_type not in allowed_types:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Неподдерживаемый формат изображения для баннера"
                )
            
            file_size = 0
            banner.file.seek(0, 2)
            file_size = banner.file.tell()
            banner.file.seek(0)
            
            if file_size > 10 * 1024 * 1024:  # 10 MB
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Размер баннера не должен превышать 10 MB"
                )
            
            file_ext = banner.filename.split('.')[-1] if '.' in banner.filename else 'jpg'
            filename = f"group_banner_{group_id}_{uuid.uuid4()}.{file_ext}"
            filepath = UPLOAD_DIR / "images" / filename
            
            with open(filepath, "wb") as buffer:
                shutil.copyfileobj(banner.file, buffer)
            
            group.banner_url = f"/uploads/images/{filename}"
        
        # Обновляем настройки
        if settings is not None:
            try:
                settings_dict = json.loads(settings)
                if group.settings:
                    group.settings.update(settings_dict)
                else:
                    group.settings = settings_dict
            except:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Неверный формат настроек"
                )
        
        group.updated_at = datetime.utcnow()
        db.commit()
        
        # Уведомляем участников группы об изменении
        ws_message = {
            "type": "group_updated",
            "group_id": group.id,
            "updated_by": user.id,
            "changes": {
                "name": name if name is not None else None,
                "description": description if description is not None else None,
                "is_public": is_public if is_public is not None else None,
                "avatar_updated": avatar is not None,
                "banner_updated": banner is not None,
                "settings_updated": settings is not None
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
        await manager.broadcast_to_chat("group", group_id, ws_message)
        
        return {
            "success": True,
            "message": "Информация о группе обновлена",
            "group": {
                "id": group.id,
                "name": group.name,
                "description": group.description,
                "avatar_url": group.avatar_url,
                "banner_url": group.banner_url,
                "is_public": group.is_public,
                "settings": group.settings,
                "updated_at": group.updated_at.isoformat() if group.updated_at else None
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Ошибка обновления группы: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка обновления группы: {str(e)}"
        )

@app.post("/api/groups/{group_id}/join")
async def join_group(
    group_id: int,
    invite_code: Optional[str] = Query(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Вступление в группу"""
    try:
        group = db.query(Group).filter(
            Group.id == group_id,
            Group.is_active == True
        ).first()
        
        if not group:
            raise HTTPException(status_code=404, detail="Группа не найдена")
        
        # Проверяем, состоит ли уже в группе
        existing_member = db.query(GroupMember).filter(
            GroupMember.group_id == group_id,
            GroupMember.user_id == user.id
        ).first()
        
        if existing_member:
            if existing_member.is_banned:
                raise HTTPException(status_code=403, detail="Вы забанены в этой группе")
            else:
                raise HTTPException(status_code=400, detail="Вы уже состоите в этой группе")
        
        # Проверяем, не превышен ли лимит участников
        if group.members_count >= group.max_members:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Достигнут максимальный лимит участников в группе"
            )
        
        # Проверяем приглашение если группа приватная
        if not group.is_public:
            if not invite_code or invite_code != group.invite_link:
                raise HTTPException(status_code=403, detail="Неверный код приглашения")
            
            # Проверяем срок действия приглашения
            if group.invite_expires and group.invite_expires < datetime.utcnow():
                raise HTTPException(status_code=403, detail="Срок действия приглашения истек")
        
        # Добавляем в группу
        group_member = GroupMember(
            group_id=group_id,
            user_id=user.id,
            role="member",
            permissions={
                "send_messages": group.settings.get("admin_only_posting", False) is False,
                "send_media": True,
                "add_members": False,
                "pin_messages": False,
                "change_group_info": False,
                "delete_messages": False,
                "ban_members": False
            }
        )
        db.add(group_member)
        
        # Обновляем счетчик участников
        group.members_count += 1
        group.updated_at = datetime.utcnow()
        db.commit()
        
        # Создаем системное сообщение о вступлении
        system_message = Message(
            from_user_id=None,  # Системное сообщение
            group_id=group_id,
            content=f"Пользователь {user.display_name or user.username} присоединился к группе",
            message_type="system"
        )
        db.add(system_message)
        db.commit()
        
        # Уведомляем участников группы
        ws_message = {
            "type": "group_member_joined",
            "group_id": group_id,
            "user": {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "avatar_url": user.avatar_url
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
        await manager.broadcast_to_chat("group", group_id, ws_message, exclude_user_id=user.id)
        
        # Отправляем информацию о группе новому участнику
        await manager.send_to_user(user.id, {
            "type": "group_joined",
            "group_id": group_id,
            "group": {
                "id": group.id,
                "name": group.name,
                "description": group.description,
                "avatar_url": group.avatar_url,
                "members_count": group.members_count
            },
            "timestamp": datetime.utcnow().isoformat()
        })
        
        return {
            "success": True,
            "message": "Вы успешно присоединились к группе",
            "group": {
                "id": group.id,
                "name": group.name,
                "members_count": group.members_count
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Ошибка вступления в группу: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка вступления в группу: {str(e)}"
        )

@app.post("/api/groups/{group_id}/leave")
async def leave_group(
    group_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Выход из группы"""
    try:
        group = db.query(Group).filter(
            Group.id == group_id,
            Group.is_active == True
        ).first()
        
        if not group:
            raise HTTPException(status_code=404, detail="Группа не найдена")
        
        # Проверяем, состоит ли в группе
        membership = db.query(GroupMember).filter(
            GroupMember.group_id == group_id,
            GroupMember.user_id == user.id,
            GroupMember.is_banned == False
        ).first()
        
        if not membership:
            raise HTTPException(status_code=400, detail="Вы не состоите в этой группе")
        
        # Нельзя выйти если ты владелец
        if group.owner_id == user.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Владелец не может выйти из группы. Сначала передайте владение или удалите группу."
            )
        
        # Удаляем из группы
        db.delete(membership)
        
        # Обновляем счетчик участников
        if group.members_count > 0:
            group.members_count -= 1
        group.updated_at = datetime.utcnow()
        
        # Создаем системное сообщение о выходе
        system_message = Message(
            from_user_id=None,
            group_id=group_id,
            content=f"Пользователь {user.display_name or user.username} покинул группу",
            message_type="system"
        )
        db.add(system_message)
        
        db.commit()
        
        # Уведомляем участников группы
        ws_message = {
            "type": "group_member_left",
            "group_id": group_id,
            "user_id": user.id,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        await manager.broadcast_to_chat("group", group_id, ws_message)
        
        return {
            "success": True,
            "message": "Вы вышли из группы"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Ошибка выхода из группы: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка выхода из группы: {str(e)}"
        )

@app.post("/api/groups/{group_id}/invite")
async def generate_group_invite(
    group_id: int,
    expires_hours: int = Query(24, ge=1, le=720),  # От 1 часа до 30 дней
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Генерация пригласительной ссылки для группы"""
    try:
        group = db.query(Group).filter(
            Group.id == group_id,
            Group.is_active == True
        ).first()
        
        if not group:
            raise HTTPException(status_code=404, detail="Группа не найдена")
        
        # Проверяем права
        membership = db.query(GroupMember).filter(
            GroupMember.group_id == group_id,
            GroupMember.user_id == user.id,
            GroupMember.is_banned == False
        ).first()
        
        is_owner = group.owner_id == user.id
        can_invite = (membership and membership.permissions.get("add_members", False)) or is_owner
        
        if not can_invite:
            raise HTTPException(status_code=403, detail="Нет прав на создание приглашений")
        
        # Проверяем настройки группы
        if not group.settings.get("allow_invites", True):
            raise HTTPException(status_code=403, detail="Приглашения запрещены в этой группе")
        
        # Генерируем новую ссылку
        invite_link = secrets.token_urlsafe(16)
        invite_expires = datetime.utcnow() + timedelta(hours=expires_hours)
        
        group.invite_link = invite_link
        group.invite_expires = invite_expires
        group.updated_at = datetime.utcnow()
        db.commit()
        
        return {
            "success": True,
            "message": "Пригласительная ссылка создана",
            "invite": {
                "link": invite_link,
                "expires_at": invite_expires.isoformat(),
                "group_id": group.id,
                "group_name": group.name
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Ошибка создания приглашения: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка создания приглашения: {str(e)}"
        )

@app.get("/api/groups/{group_id}/members")
async def get_group_members(
    group_id: int,
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=500),
    search: Optional[str] = Query(None),
    role: Optional[str] = Query(None),
    online_only: bool = Query(False),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение списка участников группы"""
    try:
        group = db.query(Group).filter(
            Group.id == group_id,
            Group.is_active == True
        ).first()
        
        if not group:
            raise HTTPException(status_code=404, detail="Группа не найдена")
        
        # Проверяем доступ
        membership = db.query(GroupMember).filter(
            GroupMember.group_id == group_id,
            GroupMember.user_id == user.id,
            GroupMember.is_banned == False
        ).first()
        
        if not membership and not group.is_public:
            raise HTTPException(status_code=403, detail="У вас нет доступа к этой группе")
        
        # Запрос участников
        query = db.query(User).join(GroupMember).filter(
            GroupMember.group_id == group_id,
            GroupMember.is_banned == False
        )
        
        if search and search.strip():
            search_filter = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    User.username.ilike(search_filter),
                    User.display_name.ilike(search_filter),
                    User.email.ilike(search_filter)
                )
            )
        
        if role:
            query = query.filter(GroupMember.role == role)
        
        if online_only:
            query = query.filter(User.is_online == True)
        
        total = query.count()
        members = query.order_by(
            desc(GroupMember.role == "admin"),
            desc(GroupMember.role == "moderator"),
            desc(User.is_online),
            User.display_name,
            User.username
        ).offset((page - 1) * limit).limit(limit).all()
        
        members_data = []
        for member in members:
            member_info = db.query(GroupMember).filter(
                GroupMember.group_id == group_id,
                GroupMember.user_id == member.id
            ).first()
            
            members_data.append({
                "id": member.id,
                "username": member.username,
                "display_name": member.display_name,
                "avatar_url": member.avatar_url,
                "is_online": member.is_online,
                "is_verified": member.is_verified,
                "role": member_info.role if member_info else "member",
                "permissions": member_info.permissions if member_info else None,
                "joined_at": member_info.joined_at.isoformat() if member_info and member_info.joined_at else None,
                "last_seen": member.last_seen.isoformat() if member.last_seen else None
            })
        
        return {
            "success": True,
            "members": members_data,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "pages": (total + limit - 1) // limit
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки участников группы: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка загрузки участников группы: {str(e)}"
        )

@app.post("/api/groups/{group_id}/members/{member_id}/role")
async def update_group_member_role(
    group_id: int,
    member_id: int,
    role: str = Form(...),
    permissions: Optional[str] = Form(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Изменение роли участника группы"""
    try:
        if member_id == user.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Нельзя изменить свою собственную роль"
            )
        
        group = db.query(Group).filter(
            Group.id == group_id,
            Group.is_active == True
        ).first()
        
        if not group:
            raise HTTPException(status_code=404, detail="Группа не найдена")
        
        # Проверяем права текущего пользователя
        current_membership = db.query(GroupMember).filter(
            GroupMember.group_id == group_id,
            GroupMember.user_id == user.id,
            GroupMember.is_banned == False
        ).first()
        
        if not current_membership:
            raise HTTPException(status_code=403, detail="Вы не состоите в этой группе")
        
        # Только владелец или админы с правами могут менять роли
        is_owner = group.owner_id == user.id
        can_manage_roles = (current_membership.permissions.get("ban_members", False) or 
                           current_membership.role == "admin") or is_owner
        
        if not can_manage_roles:
            raise HTTPException(status_code=403, detail="Нет прав на управление ролями")
        
        # Находим участника
        target_membership = db.query(GroupMember).filter(
            GroupMember.group_id == group_id,
            GroupMember.user_id == member_id,
            GroupMember.is_banned == False
        ).first()
        
        if not target_membership:
            raise HTTPException(status_code=404, detail="Участник не найден")
        
        # Нельзя изменить роль владельца
        if group.owner_id == member_id:
            raise HTTPException(status_code=403, detail="Нельзя изменить роль владельца группы")
        
        # Проверяем, что текущий пользователь имеет право изменять роль этого участника
        if target_membership.role == "admin" and not is_owner:
            raise HTTPException(status_code=403, detail="Только владелец может изменять роль администратора")
        
        allowed_roles = ["member", "moderator", "admin"]
        if role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Неверная роль. Допустимые значения: {', '.join(allowed_roles)}"
            )
        
        # Обновляем роль
        old_role = target_membership.role
        target_membership.role = role
        
        # Обновляем права если указаны
        if permissions:
            try:
                permissions_dict = json.loads(permissions)
                if target_membership.permissions:
                    target_membership.permissions.update(permissions_dict)
                else:
                    target_membership.permissions = permissions_dict
            except:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Неверный формат прав"
                )
        else:
            # Устанавливаем права по умолчанию для роли
            if role == "admin":
                target_membership.permissions = {
                    "send_messages": True,
                    "send_media": True,
                    "add_members": True,
                    "pin_messages": True,
                    "change_group_info": True,
                    "delete_messages": True,
                    "ban_members": True
                }
            elif role == "moderator":
                target_membership.permissions = {
                    "send_messages": True,
                    "send_media": True,
                    "add_members": True,
                    "pin_messages": True,
                    "change_group_info": False,
                    "delete_messages": True,
                    "ban_members": True
                }
            else:  # member
                target_membership.permissions = {
                    "send_messages": not group.settings.get("admin_only_posting", False),
                    "send_media": True,
                    "add_members": False,
                    "pin_messages": False,
                    "change_group_info": False,
                    "delete_messages": False,
                    "ban_members": False
                }
        
        db.commit()
        
        # Создаем системное сообщение
        target_user = db.query(User).filter(User.id == member_id).first()
        if target_user:
            system_message = Message(
                from_user_id=None,
                group_id=group_id,
                content=f"Пользователь {user.display_name or user.username} изменил роль {target_user.display_name or target_user.username} с '{old_role}' на '{role}'",
                message_type="system"
            )
            db.add(system_message)
            db.commit()
        
        # Уведомляем участников группы
        ws_message = {
            "type": "group_member_role_updated",
            "group_id": group_id,
            "member_id": member_id,
            "old_role": old_role,
            "new_role": role,
            "updated_by": user.id,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        await manager.broadcast_to_chat("group", group_id, ws_message)
        
        return {
            "success": True,
            "message": f"Роль участника изменена на '{role}'"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Ошибка изменения роли участника: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка изменения роли участника: {str(e)}"
        )

@app.post("/api/groups/{group_id}/members/{member_id}/ban")
async def ban_group_member(
    group_id: int,
    member_id: int,
    reason: Optional[str] = Form(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Бан участника группы"""
    try:
        if member_id == user.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Нельзя забанить самого себя"
            )
        
        group = db.query(Group).filter(
            Group.id == group_id,
            Group.is_active == True
        ).first()
        
        if not group:
            raise HTTPException(status_code=404, detail="Группа не найдена")
        
        # Проверяем права текущего пользователя
        current_membership = db.query(GroupMember).filter(
            GroupMember.group_id == group_id,
            GroupMember.user_id == user.id,
            GroupMember.is_banned == False
        ).first()
        
        if not current_membership:
            raise HTTPException(status_code=403, detail="Вы не состоите в этой группе")
        
        # Только владелец или админы с правами могут банить
        is_owner = group.owner_id == user.id
        can_ban = current_membership.permissions.get("ban_members", False) or is_owner
        
        if not can_ban:
            raise HTTPException(status_code=403, detail="Нет прав на бан участников")
        
        # Находим участника
        target_membership = db.query(GroupMember).filter(
            GroupMember.group_id == group_id,
            GroupMember.user_id == member_id
        ).first()
        
        if not target_membership:
            raise HTTPException(status_code=404, detail="Участник не найден")
        
        # Нельзя забанить владельца
        if group.owner_id == member_id:
            raise HTTPException(status_code=403, detail="Нельзя забанить владельца группы")
        
        # Проверяем, что текущий пользователь имеет право забанить этого участника
        if target_membership.role == "admin" and not is_owner:
            raise HTTPException(status_code=403, detail="Только владелец может забанить администратора")
        
        if target_membership.is_banned:
            raise HTTPException(status_code=400, detail="Участник уже забанен")
        
        # Баним участника
        target_membership.is_banned = True
        target_membership.banned_by = user.id
        target_membership.banned_at = datetime.utcnow()
        target_membership.ban_reason = reason
        
        # Уменьшаем счетчик участников
        if group.members_count > 0:
            group.members_count -= 1
        group.updated_at = datetime.utcnow()
        
        db.commit()
        
        # Создаем системное сообщение
        target_user = db.query(User).filter(User.id == member_id).first()
        if target_user:
            ban_message = f"Пользователь {target_user.display_name or target_user.username} забанен"
            if reason:
                ban_message += f" по причине: {reason}"
            
            system_message = Message(
                from_user_id=None,
                group_id=group_id,
                content=ban_message,
                message_type="system"
            )
            db.add(system_message)
            db.commit()
        
        # Уведомляем участников группы
        ws_message = {
            "type": "group_member_banned",
            "group_id": group_id,
            "member_id": member_id,
            "banned_by": user.id,
            "reason": reason,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        await manager.broadcast_to_chat("group", group_id, ws_message)
        
        # Уведомляем забаненного пользователя
        await manager.send_to_user(member_id, {
            "type": "you_were_banned",
            "group_id": group_id,
            "group_name": group.name,
            "reason": reason,
            "banned_by": user.id,
            "timestamp": datetime.utcnow().isoformat()
        })
        
        return {
            "success": True,
            "message": "Участник забанен"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Ошибка бана участника: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка бана участника: {str(e)}"
        )

@app.post("/api/groups/{group_id}/members/{member_id}/unban")
async def unban_group_member(
    group_id: int,
    member_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Разбан участника группы"""
    try:
        group = db.query(Group).filter(
            Group.id == group_id,
            Group.is_active == True
        ).first()
        
        if not group:
            raise HTTPException(status_code=404, detail="Группа не найдена")
        
        # Проверяем права текущего пользователя
        current_membership = db.query(GroupMember).filter(
            GroupMember.group_id == group_id,
            GroupMember.user_id == user.id,
            GroupMember.is_banned == False
        ).first()
        
        if not current_membership:
            raise HTTPException(status_code=403, detail="Вы не состоите в этой группе")
        
        # Только владелец или админы с правами могут разбанивать
        is_owner = group.owner_id == user.id
        can_unban = current_membership.permissions.get("ban_members", False) or is_owner
        
        if not can_unban:
            raise HTTPException(status_code=403, detail="Нет прав на разбан участников")
        
        # Находим участника
        target_membership = db.query(GroupMember).filter(
            GroupMember.group_id == group_id,
            GroupMember.user_id == member_id,
            GroupMember.is_banned == True
        ).first()
        
        if not target_membership:
            raise HTTPException(status_code=404, detail="Забаненный участник не найден")
        
        # Разбаниваем участника
        target_membership.is_banned = False
        target_membership.banned_by = None
        target_membership.banned_at = None
        target_membership.ban_reason = None
        
        # Увеличиваем счетчик участников
        group.members_count += 1
        group.updated_at = datetime.utcnow()
        
        db.commit()
        
        # Создаем системное сообщение
        target_user = db.query(User).filter(User.id == member_id).first()
        if target_user:
            system_message = Message(
                from_user_id=None,
                group_id=group_id,
                content=f"Пользователь {target_user.display_name or target_user.username} разбанен",
                message_type="system"
            )
            db.add(system_message)
            db.commit()
        
        # Уведомляем участников группы
        ws_message = {
            "type": "group_member_unbanned",
            "group_id": group_id,
            "member_id": member_id,
            "unbanned_by": user.id,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        await manager.broadcast_to_chat("group", group_id, ws_message)
        
        # Уведомляем разбаненного пользователя
        await manager.send_to_user(member_id, {
            "type": "you_were_unbanned",
            "group_id": group_id,
            "group_name": group.name,
            "unbanned_by": user.id,
            "timestamp": datetime.utcnow().isoformat()
        })
        
        return {
            "success": True,
            "message": "Участник разбанен"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Ошибка разбана участника: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка разбана участника: {str(e)}"
        )

@app.post("/api/groups/{group_id}/transfer")
async def transfer_group_ownership(
    group_id: int,
    new_owner_id: int = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Передача владения группой"""
    try:
        if new_owner_id == user.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Вы уже являетесь владельцем группы"
            )
        
        group = db.query(Group).filter(
            Group.id == group_id,
            Group.is_active == True
        ).first()
        
        if not group:
            raise HTTPException(status_code=404, detail="Группа не найдена")
        
        # Проверяем, что текущий пользователь является владельцем
        if group.owner_id != user.id:
            raise HTTPException(status_code=403, detail="Только владелец может передать группу")
        
        # Проверяем, что новый владелец состоит в группе
        new_owner_membership = db.query(GroupMember).filter(
            GroupMember.group_id == group_id,
            GroupMember.user_id == new_owner_id,
            GroupMember.is_banned == False
        ).first()
        
        if not new_owner_membership:
            raise HTTPException(status_code=404, detail="Новый владелец не состоит в группе")
        
        # Получаем информацию о новом владельце
        new_owner = db.query(User).filter(User.id == new_owner_id).first()
        if not new_owner:
            raise HTTPException(status_code=404, detail="Новый владелец не найден")
        
        old_owner = db.query(User).filter(User.id == user.id).first()
        
        # Меняем владельца
        group.owner_id = new_owner_id
        group.updated_at = datetime.utcnow()
        
        # Обновляем роли
        # Старый владелец становится администратором
        old_owner_membership = db.query(GroupMember).filter(
            GroupMember.group_id == group_id,
            GroupMember.user_id == user.id
        ).first()
        
        if old_owner_membership:
            old_owner_membership.role = "admin"
            old_owner_membership.permissions = {
                "send_messages": True,
                "send_media": True,
                "add_members": True,
                "pin_messages": True,
                "change_group_info": True,
                "delete_messages": True,
                "ban_members": True
            }
        
        # Новый владелец становится владельцем (роль admin с полными правами)
        new_owner_membership.role = "admin"
        new_owner_membership.permissions = {
            "send_messages": True,
            "send_media": True,
            "add_members": True,
            "pin_messages": True,
            "change_group_info": True,
            "delete_messages": True,
            "ban_members": True
        }
        
        db.commit()
        
        # Создаем системное сообщение
        system_message = Message(
            from_user_id=None,
            group_id=group_id,
            content=f"Владение группой передано от {old_owner.display_name or old_owner.username} к {new_owner.display_name or new_owner.username}",
            message_type="system"
        )
        db.add(system_message)
        db.commit()
        
        # Уведомляем участников группы
        ws_message = {
            "type": "group_ownership_transferred",
            "group_id": group_id,
            "old_owner_id": user.id,
            "new_owner_id": new_owner_id,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        await manager.broadcast_to_chat("group", group_id, ws_message)
        
        return {
            "success": True,
            "message": "Владение группой успешно передано"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Ошибка передачи владения группой: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка передачи владения группой: {str(e)}"
        )

@app.delete("/api/groups/{group_id}")
async def delete_group(
    group_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Удаление группы"""
    try:
        group = db.query(Group).filter(
            Group.id == group_id,
            Group.is_active == True
        ).first()
        
        if not group:
            raise HTTPException(status_code=404, detail="Группа не найдена")
        
        # Проверяем, что пользователь является владельцем
        if group.owner_id != user.id:
            raise HTTPException(status_code=403, detail="Только владелец может удалить группу")
        
        # Мягкое удаление (деактивация)
        group.is_active = False
        group.updated_at = datetime.utcnow()
        db.commit()
        
        # Уведомляем участников группы
        ws_message = {
            "type": "group_deleted",
            "group_id": group_id,
            "deleted_by": user.id,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        await manager.broadcast_to_chat("group", group_id, ws_message)
        
        return {
            "success": True,
            "message": "Группа удалена"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Ошибка удаления группы: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка удаления группы: {str(e)}"
        )

# ========== КАНАЛЫ ==========

@app.get("/api/channels")
async def get_channels(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    search: Optional[str] = Query(None),
    only_my: bool = Query(False),
    verified_only: bool = Query(False),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение списка каналов"""
    try:
        query = db.query(Channel).filter(Channel.is_active == True)
        
        if only_my:
            # Только каналы, на которые подписан пользователь
            user_channel_ids = db.query(ChannelSubscription.channel_id).filter(
                ChannelSubscription.user_id == user.id,
                ChannelSubscription.is_banned == False
            ).subquery()
            
            query = query.filter(Channel.id.in_(user_channel_ids))
        else:
            # Публичные каналы или каналы, на которые подписан пользователь
            user_channel_ids = db.query(ChannelSubscription.channel_id).filter(
                ChannelSubscription.user_id == user.id,
                ChannelSubscription.is_banned == False
            ).subquery()
            
            query = query.filter(
                or_(
                    Channel.is_public == True,
                    Channel.id.in_(user_channel_ids)
                )
            )
        
        if verified_only:
            query = query.filter(Channel.is_verified == True)
        
        if search and search.strip():
            search_filter = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    Channel.name.ilike(search_filter),
                    Channel.description.ilike(search_filter)
                )
            )
        
        total = query.count()
        channels = query.order_by(
            desc(Channel.is_verified),
            desc(Channel.subscribers_count),
            desc(Channel.created_at)
        ).offset((page - 1) * limit).limit(limit).all()
        
        channels_data = []
        for channel in channels:
            # Проверяем, подписан ли пользователь на канал
            subscription = db.query(ChannelSubscription).filter(
                ChannelSubscription.channel_id == channel.id,
                ChannelSubscription.user_id == user.id,
                ChannelSubscription.is_banned == False
            ).first()
            
            is_subscribed = subscription is not None
            is_owner = channel.owner_id == user.id
            
            # Получаем последнее сообщение
            last_message = db.query(Message).filter(
                Message.channel_id == channel.id,
                Message.is_deleted == False
            ).order_by(desc(Message.created_at)).first()
            
            # Считаем количество онлайн подписчиков
            online_subscribers = db.query(ChannelSubscription).join(User).filter(
                ChannelSubscription.channel_id == channel.id,
                ChannelSubscription.is_banned == False,
                User.is_online == True
            ).count()
            
            channel.online_count = online_subscribers
            db.commit()
            
            channels_data.append({
                "id": channel.id,
                "name": channel.name,
                "description": channel.description,
                "avatar_url": channel.avatar_url,
                "banner_url": channel.banner_url,
                "is_public": channel.is_public,
                "is_verified": channel.is_verified,
                "is_encrypted": channel.is_encrypted,
                "owner_id": channel.owner_id,
                "subscribers_count": channel.subscribers_count,
                "online_count": online_subscribers,
                "max_subscribers": channel.max_subscribers,
                "is_subscribed": is_subscribed,
                "is_owner": is_owner,
                "role": subscription.role if subscription else None,
                "permissions": subscription.permissions if subscription else None,
                "last_message": {
                    "id": last_message.id if last_message else None,
                    "content": last_message.content if last_message else None,
                    "type": last_message.message_type if last_message else None,
                    "timestamp": last_message.created_at.isoformat() if last_message else None
                } if last_message else None,
                "pinned_message_id": channel.pinned_message_id,
                "settings": channel.settings,
                "invite_link": channel.invite_link,
                "invite_expires": channel.invite_expires.isoformat() if channel.invite_expires else None,
                "created_at": channel.created_at.isoformat() if channel.created_at else None,
                "updated_at": channel.updated_at.isoformat() if channel.updated_at else None
            })
        
        return {
            "success": True,
            "channels": channels_data,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "pages": (total + limit - 1) // limit
            }
        }
        
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки каналов: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка загрузки каналов: {str(e)}"
        )

@app.post("/api/channels")
async def create_channel(
    request: ChannelCreateRequest,
    avatar: Optional[UploadFile] = None,
    banner: Optional[UploadFile] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Создание нового канала"""
    try:
        if not request.name or len(request.name.strip()) < 3:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Название канала должно быть не менее 3 символов"
            )
        
        name = request.name.strip()
        
        # Проверяем, существует ли канал с таким именем
        existing_channel = db.query(Channel).filter(
            func.lower(Channel.name) == func.lower(name),
            Channel.is_active == True
        ).first()
        
        if existing_channel:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Канал с таким названием уже существует"
            )
        
        # Обработка аватара
        avatar_url = None
        if avatar:
            allowed_types = ["image/jpeg", "image/png", "image/webp", "image/gif"]
            
            if avatar.content_type not in allowed_types:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Неподдерживаемый формат изображения для аватара"
                )
            
            file_size = 0
            avatar.file.seek(0, 2)
            file_size = avatar.file.tell()
            avatar.file.seek(0)
            
            if file_size > 5 * 1024 * 1024:  # 5 MB
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Размер аватара не должен превышать 5 MB"
                )
            
            file_ext = avatar.filename.split('.')[-1] if '.' in avatar.filename else 'jpg'
            filename = f"channel_avatar_{uuid.uuid4()}.{file_ext}"
            filepath = UPLOAD_DIR / "avatars" / filename
            
            with open(filepath, "wb") as buffer:
                shutil.copyfileobj(avatar.file, buffer)
            
            avatar_url = f"/uploads/avatars/{filename}"
        
        # Обработка баннера
        banner_url = None
        if banner:
            allowed_types = ["image/jpeg", "image/png", "image/webp"]
            
            if banner.content_type not in allowed_types:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Неподдерживаемый формат изображения для баннера"
                )
            
            file_size = 0
            banner.file.seek(0, 2)
            file_size = banner.file.tell()
            banner.file.seek(0)
            
            if file_size > 10 * 1024 * 1024:  # 10 MB
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Размер баннера не должен превышать 10 MB"
                )
            
            file_ext = banner.filename.split('.')[-1] if '.' in banner.filename else 'jpg'
            filename = f"channel_banner_{uuid.uuid4()}.{file_ext}"
            filepath = UPLOAD_DIR / "images" / filename
            
            with open(filepath, "wb") as buffer:
                shutil.copyfileobj(banner.file, buffer)
            
            banner_url = f"/uploads/images/{filename}"
        
        # Настройки по умолчанию
        default_settings = {
            "allow_comments": False,
            "allow_reactions": True,
            "allow_sharing": True,
            "slow_mode": 0,
            "admin_only_posting": True
        }
        
        if request.settings:
            default_settings.update(request.settings)
        
        # Создаем канал
        channel = Channel(
            name=name,
            description=request.description.strip() if request.description else None,
            avatar_url=avatar_url,
            banner_url=banner_url,
            is_public=request.is_public,
            is_verified=request.is_verified,
            is_encrypted=request.is_encrypted,
            owner_id=user.id,
            subscribers_count=1,
            online_count=1,
            max_subscribers=MAX_SUBSCRIBERS_PER_CHANNEL,
            settings=default_settings,
            invite_link=secrets.token_urlsafe(16),
            invite_expires=datetime.utcnow() + timedelta(days=30)
        )
        
        db.add(channel)
        db.commit()
        db.refresh(channel)
        
        # Добавляем создателя в подписчики
        subscription = ChannelSubscription(
            channel_id=channel.id,
            user_id=user.id,
            role="admin",
            permissions={
                "view_messages": True,
                "send_reactions": True,
                "send_comments": True
            }
        )
        db.add(subscription)
        db.commit()
        
        # Создаем приветственное сообщение
        welcome_message = Message(
            from_user_id=user.id,
            channel_id=channel.id,
            content=f"Канал '{name}' создан! Добро пожаловать!",
            message_type="system"
        )
        db.add(welcome_message)
        db.commit()
        
        return {
            "success": True,
            "message": "Канал создан успешно",
            "channel": {
                "id": channel.id,
                "name": channel.name,
                "description": channel.description,
                "avatar_url": channel.avatar_url,
                "banner_url": channel.banner_url,
                "is_public": channel.is_public,
                "is_verified": channel.is_verified,
                "is_encrypted": channel.is_encrypted,
                "owner_id": channel.owner_id,
                "subscribers_count": channel.subscribers_count,
                "online_count": channel.online_count,
                "invite_link": channel.invite_link,
                "settings": channel.settings,
                "created_at": channel.created_at.isoformat() if channel.created_at else None
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Ошибка создания канала: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка создания канала: {str(e)}"
        )

@app.get("/api/channels/{channel_id}")
async def get_channel_by_id(
    channel_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение информации о канале"""
    try:
        channel = db.query(Channel).filter(
            Channel.id == channel_id,
            Channel.is_active == True
        ).first()
        
        if not channel:
            raise HTTPException(status_code=404, detail="Канал не найден")
        
        # Проверяем доступ
        subscription = db.query(ChannelSubscription).filter(
            ChannelSubscription.channel_id == channel_id,
            ChannelSubscription.user_id == user.id,
            ChannelSubscription.is_banned == False
        ).first()
        
        is_subscribed = subscription is not None
        is_owner = channel.owner_id == user.id
        
        if not channel.is_public and not is_subscribed and not is_owner:
            raise HTTPException(status_code=403, detail="У вас нет доступа к этому каналу")
        
        # Получаем владельца
        owner = db.query(User).filter(User.id == channel.owner_id).first()
        
        # Получаем закрепленное сообщение если есть
        pinned_message = None
        if channel.pinned_message_id:
            pinned_msg = db.query(Message).filter(
                Message.id == channel.pinned_message_id,
                Message.is_deleted == False
            ).first()
            
            if pinned_msg:
                pinned_sender = db.query(User).filter(User.id == pinned_msg.from_user_id).first()
                pinned_message = {
                    "id": pinned_msg.id,
                    "content": pinned_msg.content,
                    "type": pinned_msg.message_type,
                    "sender": {
                        "id": pinned_sender.id if pinned_sender else None,
                        "username": pinned_sender.username if pinned_sender else None,
                        "display_name": pinned_sender.display_name if pinned_sender else None
                    } if pinned_sender else None,
                    "created_at": pinned_msg.created_at.isoformat() if pinned_msg.created_at else None
                }
        
        # Получаем последние сообщения
        last_messages = db.query(Message).filter(
            Message.channel_id == channel_id,
            Message.is_deleted == False
        ).order_by(desc(Message.created_at)).limit(20).all()
        
        messages_data = []
        for msg in last_messages:
            sender = db.query(User).filter(User.id == msg.from_user_id).first()
            messages_data.append({
                "id": msg.id,
                "content": msg.content,
                "type": msg.message_type,
                "media_url": msg.media_url,
                "sender": {
                    "id": sender.id if sender else None,
                    "username": sender.username if sender else None,
                    "display_name": sender.display_name if sender else None,
                    "avatar_url": sender.avatar_url if sender else None
                } if sender else None,
                "created_at": msg.created_at.isoformat() if msg.created_at else None
            })
        
        messages_data.reverse()
        
        # Считаем количество онлайн подписчиков
        online_count = db.query(ChannelSubscription).join(User).filter(
            ChannelSubscription.channel_id == channel_id,
            ChannelSubscription.is_banned == False,
            User.is_online == True
        ).count()
        
        channel.online_count = online_count
        db.commit()
        
        return {
            "success": True,
            "channel": {
                "id": channel.id,
                "name": channel.name,
                "description": channel.description,
                "avatar_url": channel.avatar_url,
                "banner_url": channel.banner_url,
                "is_public": channel.is_public,
                "is_verified": channel.is_verified,
                "is_encrypted": channel.is_encrypted,
                "owner": {
                    "id": owner.id if owner else None,
                    "username": owner.username if owner else None,
                    "display_name": owner.display_name if owner else None,
                    "avatar_url": owner.avatar_url if owner else None,
                    "is_verified": owner.is_verified if owner else False
                } if owner else None,
                "subscribers_count": channel.subscribers_count,
                "online_count": online_count,
                "max_subscribers": channel.max_subscribers,
                "is_subscribed": is_subscribed,
                "is_owner": is_owner,
                "role": subscription.role if subscription else None,
                "permissions": subscription.permissions if subscription else None,
                "pinned_message": pinned_message,
                "last_messages": messages_data,
                "settings": channel.settings,
                "invite_link": channel.invite_link,
                "invite_expires": channel.invite_expires.isoformat() if channel.invite_expires else None,
                "created_at": channel.created_at.isoformat() if channel.created_at else None,
                "updated_at": channel.updated_at.isoformat() if channel.updated_at else None
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки канала: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка загрузки канала: {str(e)}"
        )

@app.put("/api/channels/{channel_id}")
async def update_channel(
    channel_id: int,
    name: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    is_public: Optional[bool] = Form(None),
    is_verified: Optional[bool] = Form(None),
    avatar: Optional[UploadFile] = None,
    banner: Optional[UploadFile] = None,
    settings: Optional[str] = Form(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Обновление информации о канале"""
    try:
        channel = db.query(Channel).filter(
            Channel.id == channel_id,
            Channel.is_active == True
        ).first()
        
        if not channel:
            raise HTTPException(status_code=404, detail="Канал не найден")
        
        # Проверяем права
        if channel.owner_id != user.id:
            raise HTTPException(status_code=403, detail="Только владелец может изменять канал")
        
        # Обновляем название
        if name is not None:
            name = name.strip()
            if len(name) < 3:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Название канала должно быть не менее 3 символов"
                )
            
            # Проверяем уникальность названия
            existing_channel = db.query(Channel).filter(
                func.lower(Channel.name) == func.lower(name),
                Channel.id != channel_id,
                Channel.is_active == True
            ).first()
            
            if existing_channel:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Канал с таким названием уже существует"
                )
            
            channel.name = name
        
        # Обновляем описание
        if description is not None:
            channel.description = description.strip() if description else None
        
        # Обновляем публичность
        if is_public is not None:
            channel.is_public = is_public
        
        # Обновляем статус верификации (только для админов)
        if is_verified is not None:
            if user.is_admin:
                channel.is_verified = is_verified
            else:
                raise HTTPException(status_code=403, detail="Только администраторы могут изменять статус верификации")
        
        # Обработка аватара
        if avatar:
            allowed_types = ["image/jpeg", "image/png", "image/webp", "image/gif"]
            
            if avatar.content_type not in allowed_types:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Неподдерживаемый формат изображения для аватара"
                )
            
            file_size = 0
            avatar.file.seek(0, 2)
            file_size = avatar.file.tell()
            avatar.file.seek(0)
            
            if file_size > 5 * 1024 * 1024:  # 5 MB
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Размер аватара не должен превышать 5 MB"
                )
            
            file_ext = avatar.filename.split('.')[-1] if '.' in avatar.filename else 'jpg'
            filename = f"channel_avatar_{channel_id}_{uuid.uuid4()}.{file_ext}"
            filepath = UPLOAD_DIR / "avatars" / filename
            
            with open(filepath, "wb") as buffer:
                shutil.copyfileobj(avatar.file, buffer)
            
            channel.avatar_url = f"/uploads/avatars/{filename}"
        
        # Обработка баннера
        if banner:
            allowed_types = ["image/jpeg", "image/png", "image/webp"]
            
            if banner.content_type not in allowed_types:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Неподдерживаемый формат изображения для баннера"
                )
            
            file_size = 0
            banner.file.seek(0, 2)
            file_size = banner.file.tell()
            banner.file.seek(0)
            
            if file_size > 10 * 1024 * 1024:  # 10 MB
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Размер баннера не должен превышать 10 MB"
                )
            
            file_ext = banner.filename.split('.')[-1] if '.' in banner.filename else 'jpg'
            filename = f"channel_banner_{channel_id}_{uuid.uuid4()}.{file_ext}"
            filepath = UPLOAD_DIR / "images" / filename
            
            with open(filepath, "wb") as buffer:
                shutil.copyfileobj(banner.file, buffer)
            
            channel.banner_url = f"/uploads/images/{filename}"
        
        # Обновляем настройки
        if settings is not None:
            try:
                settings_dict = json.loads(settings)
                if channel.settings:
                    channel.settings.update(settings_dict)
                else:
                    channel.settings = settings_dict
            except:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Неверный формат настроек"
                )
        
        channel.updated_at = datetime.utcnow()
        db.commit()
        
        # Уведомляем подписчиков канала об изменении
        ws_message = {
            "type": "channel_updated",
            "channel_id": channel.id,
            "updated_by": user.id,
            "changes": {
                "name": name if name is not None else None,
                "description": description if description is not None else None,
                "is_public": is_public if is_public is not None else None,
                "is_verified": is_verified if is_verified is not None else None,
                "avatar_updated": avatar is not None,
                "banner_updated": banner is not None,
                "settings_updated": settings is not None
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
        await manager.broadcast_to_chat("channel", channel_id, ws_message)
        
        return {
            "success": True,
            "message": "Информация о канале обновлена",
            "channel": {
                "id": channel.id,
                "name": channel.name,
                "description": channel.description,
                "avatar_url": channel.avatar_url,
                "banner_url": channel.banner_url,
                "is_public": channel.is_public,
                "is_verified": channel.is_verified,
                "settings": channel.settings,
                "updated_at": channel.updated_at.isoformat() if channel.updated_at else None
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Ошибка обновления канала: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка обновления канала: {str(e)}"
        )

@app.post("/api/channels/{channel_id}/subscribe")
async def subscribe_to_channel(
    channel_id: int,
    invite_code: Optional[str] = Query(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Подписка на канал"""
    try:
        channel = db.query(Channel).filter(
            Channel.id == channel_id,
            Channel.is_active == True
        ).first()
        
        if not channel:
            raise HTTPException(status_code=404, detail="Канал не найден")
        
        # Проверяем, подписан ли уже
        existing_subscription = db.query(ChannelSubscription).filter(
            ChannelSubscription.channel_id == channel_id,
            ChannelSubscription.user_id == user.id
        ).first()
        
        if existing_subscription:
            if existing_subscription.is_banned:
                raise HTTPException(status_code=403, detail="Вы забанены в этом канале")
            else:
                raise HTTPException(status_code=400, detail="Вы уже подписаны на этот канал")
        
        # Проверяем, не превышен ли лимит подписчиков
        if channel.subscribers_count >= channel.max_subscribers:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Достигнут максимальный лимит подписчиков в канале"
            )
        
        # Проверяем приглашение если канал приватный
        if not channel.is_public:
            if not invite_code or invite_code != channel.invite_link:
                raise HTTPException(status_code=403, detail="Неверный код приглашения")
            
            # Проверяем срок действия приглашения
            if channel.invite_expires and channel.invite_expires < datetime.utcnow():
                raise HTTPException(status_code=403, detail="Срок действия приглашения истек")
        
        # Подписываемся
        subscription = ChannelSubscription(
            channel_id=channel_id,
            user_id=user.id,
            role="subscriber",
            permissions={
                "view_messages": True,
                "send_reactions": channel.settings.get("allow_reactions", True),
                "send_comments": channel.settings.get("allow_comments", False)
            }
        )
        db.add(subscription)
        
        # Обновляем счетчик подписчиков
        channel.subscribers_count += 1
        channel.updated_at = datetime.utcnow()
        db.commit()
        
        # Создаем системное сообщение о подписке
        system_message = Message(
            from_user_id=None,
            channel_id=channel_id,
            content=f"Новый подписчик: {user.display_name or user.username}",
            message_type="system"
        )
        db.add(system_message)
        db.commit()
        
        # Уведомляем владельца канала
        ws_message = {
            "type": "channel_new_subscriber",
            "channel_id": channel_id,
            "user": {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "avatar_url": user.avatar_url
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
        if channel.owner_id in manager.user_connections:
            await manager.send_to_user(channel.owner_id, ws_message)
        
        # Отправляем информацию о канале новому подписчику
        await manager.send_to_user(user.id, {
            "type": "channel_subscribed",
            "channel_id": channel_id,
            "channel": {
                "id": channel.id,
                "name": channel.name,
                "description": channel.description,
                "avatar_url": channel.avatar_url,
                "subscribers_count": channel.subscribers_count
            },
            "timestamp": datetime.utcnow().isoformat()
        })
        
        return {
            "success": True,
            "message": "Вы успешно подписались на канал",
            "channel": {
                "id": channel.id,
                "name": channel.name,
                "subscribers_count": channel.subscribers_count
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Ошибка подписки на канал: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка подписки на канал: {str(e)}"
        )

@app.post("/api/channels/{channel_id}/unsubscribe")
async def unsubscribe_from_channel(
    channel_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Отписка от канала"""
    try:
        channel = db.query(Channel).filter(
            Channel.id == channel_id,
            Channel.is_active == True
        ).first()
        
        if not channel:
            raise HTTPException(status_code=404, detail="Канал не найден")
        
        # Проверяем, подписан ли
        subscription = db.query(ChannelSubscription).filter(
            ChannelSubscription.channel_id == channel_id,
            ChannelSubscription.user_id == user.id,
            ChannelSubscription.is_banned == False
        ).first()
        
        if not subscription:
            raise HTTPException(status_code=400, detail="Вы не подписаны на этот канал")
        
        # Нельзя отписаться если ты владелец
        if channel.owner_id == user.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Владелец не может отписаться от канала. Удалите канал или передайте владение."
            )
        
        # Удаляем подписку
        db.delete(subscription)
        
        # Обновляем счетчик подписчиков
        if channel.subscribers_count > 0:
            channel.subscribers_count -= 1
        channel.updated_at = datetime.utcnow()
        
        # Создаем системное сообщение об отписке
        system_message = Message(
            from_user_id=None,
            channel_id=channel_id,
            content=f"Пользователь {user.display_name or user.username} отписался от канала",
            message_type="system"
        )
        db.add(system_message)
        
        db.commit()
        
        # Уведомляем владельца канала
        ws_message = {
            "type": "channel_subscriber_left",
            "channel_id": channel_id,
            "user_id": user.id,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        if channel.owner_id in manager.user_connections:
            await manager.send_to_user(channel.owner_id, ws_message)
        
        return {
            "success": True,
            "message": "Вы отписались от канала"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Ошибка отписки от канала: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка отписки от канала: {str(e)}"
        )

@app.post("/api/channels/{channel_id}/invite")
async def generate_channel_invite(
    channel_id: int,
    expires_hours: int = Query(24, ge=1, le=720),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Генерация пригласительной ссылки для канала"""
    try:
        channel = db.query(Channel).filter(
            Channel.id == channel_id,
            Channel.is_active == True
        ).first()
        
        if not channel:
            raise HTTPException(status_code=404, detail="Канал не найден")
        
        # Проверяем права (только владелец может создавать приглашения)
        if channel.owner_id != user.id:
            raise HTTPException(status_code=403, detail="Только владелец может создавать приглашения")
        
        # Генерируем новую ссылку
        invite_link = secrets.token_urlsafe(16)
        invite_expires = datetime.utcnow() + timedelta(hours=expires_hours)
        
        channel.invite_link = invite_link
        channel.invite_expires = invite_expires
        channel.updated_at = datetime.utcnow()
        db.commit()
        
        return {
            "success": True,
            "message": "Пригласительная ссылка создана",
            "invite": {
                "link": invite_link,
                "expires_at": invite_expires.isoformat(),
                "channel_id": channel.id,
                "channel_name": channel.name
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Ошибка создания приглашения: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка создания приглашения: {str(e)}"
        )

@app.get("/api/channels/{channel_id}/subscribers")
async def get_channel_subscribers(
    channel_id: int,
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=500),
    search: Optional[str] = Query(None),
    role: Optional[str] = Query(None),
    online_only: bool = Query(False),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение списка подписчиков канала"""
    try:
        channel = db.query(Channel).filter(
            Channel.id == channel_id,
            Channel.is_active == True
        ).first()
        
        if not channel:
            raise HTTPException(status_code=404, detail="Канал не найден")
        
        # Проверяем доступ
        subscription = db.query(ChannelSubscription).filter(
            ChannelSubscription.channel_id == channel_id,
            ChannelSubscription.user_id == user.id,
            ChannelSubscription.is_banned == False
        ).first()
        
        if not subscription and not channel.is_public:
            raise HTTPException(status_code=403, detail="У вас нет доступа к этому каналу")
        
        # Запрос подписчиков
        query = db.query(User).join(ChannelSubscription).filter(
            ChannelSubscription.channel_id == channel_id,
            ChannelSubscription.is_banned == False
        )
        
        if search and search.strip():
            search_filter = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    User.username.ilike(search_filter),
                    User.display_name.ilike(search_filter),
                    User.email.ilike(search_filter)
                )
            )
        
        if role:
            query = query.filter(ChannelSubscription.role == role)
        
        if online_only:
            query = query.filter(User.is_online == True)
        
        total = query.count()
        subscribers = query.order_by(
            desc(ChannelSubscription.role == "admin"),
            desc(ChannelSubscription.role == "moderator"),
            desc(User.is_online),
            User.display_name,
            User.username
        ).offset((page - 1) * limit).limit(limit).all()
        
        subscribers_data = []
        for subscriber in subscribers:
            sub_info = db.query(ChannelSubscription).filter(
                ChannelSubscription.channel_id == channel_id,
                ChannelSubscription.user_id == subscriber.id
            ).first()
            
            subscribers_data.append({
                "id": subscriber.id,
                "username": subscriber.username,
                "display_name": subscriber.display_name,
                "avatar_url": subscriber.avatar_url,
                "is_online": subscriber.is_online,
                "is_verified": subscriber.is_verified,
                "role": sub_info.role if sub_info else "subscriber",
                "permissions": sub_info.permissions if sub_info else None,
                "subscribed_at": sub_info.subscribed_at.isoformat() if sub_info and sub_info.subscribed_at else None,
                "last_seen": subscriber.last_seen.isoformat() if subscriber.last_seen else None
            })
        
        return {
            "success": True,
            "subscribers": subscribers_data,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "pages": (total + limit - 1) // limit
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки подписчиков канала: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка загрузки подписчиков канала: {str(e)}"
        )

@app.post("/api/channels/{channel_id}/subscribers/{subscriber_id}/role")
async def update_channel_subscriber_role(
    channel_id: int,
    subscriber_id: int,
    role: str = Form(...),
    permissions: Optional[str] = Form(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Изменение роли подписчика канала"""
    try:
        if subscriber_id == user.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Нельзя изменить свою собственную роль"
            )
        
        channel = db.query(Channel).filter(
            Channel.id == channel_id,
            Channel.is_active == True
        ).first()
        
        if not channel:
            raise HTTPException(status_code=404, detail="Канал не найден")
        
        # Проверяем права текущего пользователя
        if channel.owner_id != user.id:
            raise HTTPException(status_code=403, detail="Только владелец может изменять роли")
        
        # Находим подписчика
        target_subscription = db.query(ChannelSubscription).filter(
            ChannelSubscription.channel_id == channel_id,
            ChannelSubscription.user_id == subscriber_id,
            ChannelSubscription.is_banned == False
        ).first()
        
        if not target_subscription:
            raise HTTPException(status_code=404, detail="Подписчик не найден")
        
        allowed_roles = ["subscriber", "moderator", "admin"]
        if role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Неверная роль. Допустимые значения: {', '.join(allowed_roles)}"
            )
        
        # Обновляем роль
        old_role = target_subscription.role
        target_subscription.role = role
        
        # Обновляем права если указаны
        if permissions:
            try:
                permissions_dict = json.loads(permissions)
                if target_subscription.permissions:
                    target_subscription.permissions.update(permissions_dict)
                else:
                    target_subscription.permissions = permissions_dict
            except:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Неверный формат прав"
                )
        else:
            # Устанавливаем права по умолчанию для роли
            if role == "admin":
                target_subscription.permissions = {
                    "view_messages": True,
                    "send_reactions": True,
                    "send_comments": True
                }
            elif role == "moderator":
                target_subscription.permissions = {
                    "view_messages": True,
                    "send_reactions": True,
                    "send_comments": True
                }
            else:  # subscriber
                target_subscription.permissions = {
                    "view_messages": True,
                    "send_reactions": channel.settings.get("allow_reactions", True),
                    "send_comments": channel.settings.get("allow_comments", False)
                }
        
        db.commit()
        
        # Создаем системное сообщение
        target_user = db.query(User).filter(User.id == subscriber_id).first()
        if target_user:
            system_message = Message(
                from_user_id=None,
                channel_id=channel_id,
                content=f"Роль подписчика {target_user.display_name or target_user.username} изменена с '{old_role}' на '{role}'",
                message_type="system"
            )
            db.add(system_message)
            db.commit()
        
        # Уведомляем подписчиков канала
        ws_message = {
            "type": "channel_subscriber_role_updated",
            "channel_id": channel_id,
            "subscriber_id": subscriber_id,
            "old_role": old_role,
            "new_role": role,
            "updated_by": user.id,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        await manager.broadcast_to_chat("channel", channel_id, ws_message)
        
        return {
            "success": True,
            "message": f"Роль подписчика изменена на '{role}'"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Ошибка изменения роли подписчика: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка изменения роли подписчика: {str(e)}"
        )

@app.post("/api/channels/{channel_id}/subscribers/{subscriber_id}/ban")
async def ban_channel_subscriber(
    channel_id: int,
    subscriber_id: int,
    reason: Optional[str] = Form(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Бан подписчика канала"""
    try:
        if subscriber_id == user.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Нельзя забанить самого себя"
            )
        
        channel = db.query(Channel).filter(
            Channel.id == channel_id,
            Channel.is_active == True
        ).first()
        
        if not channel:
            raise HTTPException(status_code=404, detail="Канал не найден")
        
        # Проверяем права текущего пользователя
        if channel.owner_id != user.id:
            # Проверяем, является ли пользователь администратором или модератором
            user_subscription = db.query(ChannelSubscription).filter(
                ChannelSubscription.channel_id == channel_id,
                ChannelSubscription.user_id == user.id,
                ChannelSubscription.is_banned == False
            ).first()
            
            if not user_subscription or user_subscription.role not in ["admin", "moderator"]:
                raise HTTPException(status_code=403, detail="Нет прав на бан подписчиков")
        
        # Находим подписчика
        target_subscription = db.query(ChannelSubscription).filter(
            ChannelSubscription.channel_id == channel_id,
            ChannelSubscription.user_id == subscriber_id
        ).first()
        
        if not target_subscription:
            raise HTTPException(status_code=404, detail="Подписчик не найден")
        
        if target_subscription.is_banned:
            raise HTTPException(status_code=400, detail="Подписчик уже забанен")
        
        # Нельзя забанить владельца
        if channel.owner_id == subscriber_id:
            raise HTTPException(status_code=403, detail="Нельзя забанить владельца канала")
        
        # Проверяем, что текущий пользователь имеет право забанить этого подписчика
        if target_subscription.role == "admin" and channel.owner_id != user.id:
            raise HTTPException(status_code=403, detail="Только владелец может забанить администратора")
        
        # Баним подписчика
        target_subscription.is_banned = True
        target_subscription.banned_by = user.id
        target_subscription.banned_at = datetime.utcnow()
        target_subscription.ban_reason = reason
        
        # Уменьшаем счетчик подписчиков
        if channel.subscribers_count > 0:
            channel.subscribers_count -= 1
        channel.updated_at = datetime.utcnow()
        
        db.commit()
        
        # Создаем системное сообщение
        target_user = db.query(User).filter(User.id == subscriber_id).first()
        if target_user:
            ban_message = f"Подписчик {target_user.display_name or target_user.username} забанен"
            if reason:
                ban_message += f" по причине: {reason}"
            
            system_message = Message(
                from_user_id=None,
                channel_id=channel_id,
                content=ban_message,
                message_type="system"
            )
            db.add(system_message)
            db.commit()
        
        # Уведомляем подписчиков канала
        ws_message = {
            "type": "channel_subscriber_banned",
            "channel_id": channel_id,
            "subscriber_id": subscriber_id,
            "banned_by": user.id,
            "reason": reason,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        await manager.broadcast_to_chat("channel", channel_id, ws_message)
        
        # Уведомляем забаненного пользователя
        await manager.send_to_user(subscriber_id, {
            "type": "you_were_banned_from_channel",
            "channel_id": channel_id,
            "channel_name": channel.name,
            "reason": reason,
            "banned_by": user.id,
            "timestamp": datetime.utcnow().isoformat()
        })
        
        return {
            "success": True,
            "message": "Подписчик забанен"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Ошибка бана подписчика: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка бана подписчика: {str(e)}"
        )

@app.post("/api/channels/{channel_id}/subscribers/{subscriber_id}/unban")
async def unban_channel_subscriber(
    channel_id: int,
    subscriber_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Разбан подписчика канала"""
    try:
        channel = db.query(Channel).filter(
            Channel.id == channel_id,
            Channel.is_active == True
        ).first()
        
        if not channel:
            raise HTTPException(status_code=404, detail="Канал не найден")
        
        # Проверяем права текущего пользователя
        if channel.owner_id != user.id:
            # Проверяем, является ли пользователь администратором или модератором
            user_subscription = db.query(ChannelSubscription).filter(
                ChannelSubscription.channel_id == channel_id,
                ChannelSubscription.user_id == user.id,
                ChannelSubscription.is_banned == False
            ).first()
            
            if not user_subscription or user_subscription.role not in ["admin", "moderator"]:
                raise HTTPException(status_code=403, detail="Нет прав на разбан подписчиков")
        
        # Находим подписчика
        target_subscription = db.query(ChannelSubscription).filter(
            ChannelSubscription.channel_id == channel_id,
            ChannelSubscription.user_id == subscriber_id,
            ChannelSubscription.is_banned == True
        ).first()
        
        if not target_subscription:
            raise HTTPException(status_code=404, detail="Забаненный подписчик не найден")
        
        # Разбаниваем подписчика
        target_subscription.is_banned = False
        target_subscription.banned_by = None
        target_subscription.banned_at = None
        target_subscription.ban_reason = None
        
        # Увеличиваем счетчик подписчиков
        channel.subscribers_count += 1
        channel.updated_at = datetime.utcnow()
        
        db.commit()
        
        # Создаем системное сообщение
        target_user = db.query(User).filter(User.id == subscriber_id).first()
        if target_user:
            system_message = Message(
                from_user_id=None,
                channel_id=channel_id,
                content=f"Подписчик {target_user.display_name or target_user.username} разбанен",
                message_type="system"
            )
            db.add(system_message)
            db.commit()
        
        # Уведомляем подписчиков канала
        ws_message = {
            "type": "channel_subscriber_unbanned",
            "channel_id": channel_id,
            "subscriber_id": subscriber_id,
            "unbanned_by": user.id,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        await manager.broadcast_to_chat("channel", channel_id, ws_message)
        
        # Уведомляем разбаненного пользователя
        await manager.send_to_user(subscriber_id, {
            "type": "you_were_unbanned_from_channel",
            "channel_id": channel_id,
            "channel_name": channel.name,
            "unbanned_by": user.id,
            "timestamp": datetime.utcnow().isoformat()
        })
        
        return {
            "success": True,
            "message": "Подписчик разбанен"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Ошибка разбана подписчика: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка разбана подписчика: {str(e)}"
        )

@app.post("/api/channels/{channel_id}/transfer")
async def transfer_channel_ownership(
    channel_id: int,
    new_owner_id: int = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Передача владения каналом"""
    try:
        if new_owner_id == user.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Вы уже являетесь владельцем канала"
            )
        
        channel = db.query(Channel).filter(
            Channel.id == channel_id,
            Channel.is_active == True
        ).first()
        
        if not channel:
            raise HTTPException(status_code=404, detail="Канал не найден")
        
        # Проверяем, что текущий пользователь является владельцем
        if channel.owner_id != user.id:
            raise HTTPException(status_code=403, detail="Только владелец может передать канал")
        
        # Проверяем, что новый владелец подписан на канал
        new_owner_subscription = db.query(ChannelSubscription).filter(
            ChannelSubscription.channel_id == channel_id,
            ChannelSubscription.user_id == new_owner_id,
            ChannelSubscription.is_banned == False
        ).first()
        
        if not new_owner_subscription:
            raise HTTPException(status_code=404, detail="Новый владелец не подписан на канал")
        
        # Получаем информацию о новом владельце
        new_owner = db.query(User).filter(User.id == new_owner_id).first()
        if not new_owner:
            raise HTTPException(status_code=404, detail="Новый владелец не найден")
        
        old_owner = db.query(User).filter(User.id == user.id).first()
        
        # Меняем владельца
        channel.owner_id = new_owner_id
        channel.updated_at = datetime.utcnow()
        
        # Обновляем роли
        # Старый владелец становится администратором
        old_owner_subscription = db.query(ChannelSubscription).filter(
            ChannelSubscription.channel_id == channel_id,
            ChannelSubscription.user_id == user.id
        ).first()
        
        if old_owner_subscription:
            old_owner_subscription.role = "admin"
            old_owner_subscription.permissions = {
                "view_messages": True,
                "send_reactions": True,
                "send_comments": True
            }
        
        # Новый владелец становится владельцем (роль admin)
        new_owner_subscription.role = "admin"
        new_owner_subscription.permissions = {
            "view_messages": True,
            "send_reactions": True,
            "send_comments": True
        }
        
        db.commit()
        
        # Создаем системное сообщение
        system_message = Message(
            from_user_id=None,
            channel_id=channel_id,
            content=f"Владение каналом передано от {old_owner.display_name or old_owner.username} к {new_owner.display_name or new_owner.username}",
            message_type="system"
        )
        db.add(system_message)
        db.commit()
        
        # Уведомляем подписчиков канала
        ws_message = {
            "type": "channel_ownership_transferred",
            "channel_id": channel_id,
            "old_owner_id": user.id,
            "new_owner_id": new_owner_id,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        await manager.broadcast_to_chat("channel", channel_id, ws_message)
        
        return {
            "success": True,
            "message": "Владение каналом успешно передано"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Ошибка передачи владения каналом: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка передачи владения каналом: {str(e)}"
        )

@app.delete("/api/channels/{channel_id}")
async def delete_channel(
    channel_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Удаление канала"""
    try:
        channel = db.query(Channel).filter(
            Channel.id == channel_id,
            Channel.is_active == True
        ).first()
        
        if not channel:
            raise HTTPException(status_code=404, detail="Канал не найден")
        
        # Проверяем, что пользователь является владельцем
        if channel.owner_id != user.id:
            raise HTTPException(status_code=403, detail="Только владелец может удалить канал")
        
        # Мягкое удаление (деактивация)
        channel.is_active = False
        channel.updated_at = datetime.utcnow()
        db.commit()
        
        # Уведомляем подписчиков канала
        ws_message = {
            "type": "channel_deleted",
            "channel_id": channel_id,
            "deleted_by": user.id,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        await manager.broadcast_to_chat("channel", channel_id, ws_message)
        
        return {
            "success": True,
            "message": "Канал удален"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Ошибка удаления канала: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка удаления канала: {str(e)}"
        )

# ========== ЧАТЫ ==========

@app.get("/api/chats/all")
async def get_all_chats(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение всех чатов пользователя"""
    try:
        all_chats = []
        
        # Личные чаты (пользователи, с которыми есть переписка)
        private_chats = []
        
        # Получаем пользователей, с которыми есть переписка
        chat_partners_query = db.query(Message.from_user_id).filter(
            Message.to_user_id == user.id,
            Message.is_deleted == False
        ).union(
            db.query(Message.to_user_id).filter(
                Message.from_user_id == user.id,
                Message.is_deleted == False
            )
        ).distinct()
        
        chat_partners = [row[0] for row in chat_partners_query.all() if row[0] is not None]
        
        for partner_id in chat_partners:
            if partner_id == user.id:
                continue
                
            partner = db.query(User).filter(
                User.id == partner_id,
                User.is_active == True
            ).first()
            
            if not partner:
                continue
            
            # Проверяем, не заблокирован ли пользователь
            is_blocked = db.query(Contact).filter(
                Contact.user_id == user.id,
                Contact.contact_id == partner_id,
                Contact.is_blocked == True
            ).first() is not None
            
            if is_blocked:
                continue
            
            # Получаем последнее сообщение
            last_message = db.query(Message).filter(
                or_(
                    and_(Message.from_user_id == user.id, Message.to_user_id == partner_id),
                    and_(Message.from_user_id == partner_id, Message.to_user_id == user.id)
                ),
                Message.is_deleted == False
            ).order_by(desc(Message.created_at)).first()
            
            # Считаем непрочитанные сообщения
            unread_count = db.query(Message).filter(
                Message.from_user_id == partner_id,
                Message.to_user_id == user.id,
                Message.is_deleted == False
            ).count()  # В реальном приложении нужно хранить статус прочтения
            
            # Проверяем настройки приватности партнера
            can_see_online = True
            can_see_last_seen = True
            
            if partner.settings and "privacy" in partner.settings:
                privacy = partner.settings["privacy"]
                
                if privacy.get("online_status") == "contacts":
                    # Проверяем, есть ли в контактах
                    is_contact = db.query(Contact).filter(
                        Contact.user_id == partner.id,
                        Contact.contact_id == user.id,
                        Contact.is_blocked == False
                    ).first() is not None
                    can_see_online = is_contact
                
                if privacy.get("last_seen") == "contacts":
                    is_contact = db.query(Contact).filter(
                        Contact.user_id == partner.id,
                        Contact.contact_id == user.id,
                        Contact.is_blocked == False
                    ).first() is not None
                    can_see_last_seen = is_contact
            
            private_chats.append({
                "id": partner.id,
                "type": "private",
                "name": partner.display_name or partner.username,
                "avatar_url": partner.avatar_url,
                "is_online": partner.is_online if can_see_online else None,
                "is_verified": partner.is_verified,
                "last_seen": partner.last_seen.isoformat() if partner.last_seen and can_see_last_seen else None,
                "last_message": {
                    "content": last_message.content if last_message else None,
                    "type": last_message.message_type if last_message else None,
                    "timestamp": last_message.created_at.isoformat() if last_message else None,
                    "is_my_message": last_message.from_user_id == user.id if last_message else False
                } if last_message else None,
                "unread_count": unread_count
            })
        
        # Групповые чаты
        group_chats = []
        user_groups = db.query(Group).join(GroupMember).filter(
            GroupMember.user_id == user.id,
            GroupMember.is_banned == False,
            Group.is_active == True
        ).all()
        
        for group in user_groups:
            last_message = db.query(Message).filter(
                Message.group_id == group.id,
                Message.is_deleted == False
            ).order_by(desc(Message.created_at)).first()
            
            # Считаем количество непрочитанных сообщений
            membership = db.query(GroupMember).filter(
                GroupMember.group_id == group.id,
                GroupMember.user_id == user.id
            ).first()
            
            last_read_id = membership.last_message_read_id if membership else 0
            unread_count = db.query(Message).filter(
                Message.group_id == group.id,
                Message.id > last_read_id,
                Message.is_deleted == False
            ).count()
            
            group_chats.append({
                "id": group.id,
                "type": "group",
                "name": group.name,
                "avatar_url": group.avatar_url,
                "members_count": group.members_count,
                "online_count": group.online_count,
                "last_message": {
                    "content": last_message.content if last_message else None,
                    "type": last_message.message_type if last_message else None,
                    "timestamp": last_message.created_at.isoformat() if last_message else None,
                    "sender_id": last_message.from_user_id if last_message else None
                } if last_message else None,
                "unread_count": unread_count,
                "is_encrypted": group.is_encrypted,
                "is_public": group.is_public
            })
        
        # Каналы
        channel_chats = []
        user_channels = db.query(Channel).join(ChannelSubscription).filter(
            ChannelSubscription.user_id == user.id,
            ChannelSubscription.is_banned == False,
            Channel.is_active == True
        ).all()
        
        for channel in user_channels:
            last_message = db.query(Message).filter(
                Message.channel_id == channel.id,
                Message.is_deleted == False
            ).order_by(desc(Message.created_at)).first()
            
            # Считаем количество непрочитанных сообщений
            subscription = db.query(ChannelSubscription).filter(
                ChannelSubscription.channel_id == channel.id,
                ChannelSubscription.user_id == user.id
            ).first()
            
            last_read_id = subscription.last_message_read_id if subscription else 0
            unread_count = db.query(Message).filter(
                Message.channel_id == channel.id,
                Message.id > last_read_id,
                Message.is_deleted == False
            ).count()
            
            channel_chats.append({
                "id": channel.id,
                "type": "channel",
                "name": channel.name,
                "avatar_url": channel.avatar_url,
                "subscribers_count": channel.subscribers_count,
                "online_count": channel.online_count,
                "last_message": {
                    "content": last_message.content if last_message else None,
                    "type": last_message.message_type if last_message else None,
                    "timestamp": last_message.created_at.isoformat() if last_message else None
                } if last_message else None,
                "unread_count": unread_count,
                "is_encrypted": channel.is_encrypted,
                "is_public": channel.is_public,
                "is_verified": channel.is_verified
            })
        
        # Объединяем все чаты
        all_chats = private_chats + group_chats + channel_chats
        
        # Сортируем по времени последнего сообщения
        def get_chat_timestamp(chat):
            if chat.get('last_message') and chat['last_message'].get('timestamp'):
                try:
                    return datetime.fromisoformat(chat['last_message']['timestamp'].replace('Z', '+00:00'))
                except:
                    return datetime.min
            return datetime.min
        
        all_chats.sort(key=get_chat_timestamp, reverse=True)
        
        return {
            "success": True,
            "chats": all_chats,
            "count": len(all_chats),
            "stats": {
                "private": len(private_chats),
                "groups": len(group_chats),
                "channels": len(channel_chats)
            }
        }
        
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки чатов: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка загрузки чатов: {str(e)}"
        )

@app.get("/api/chats/search")
async def search_chats(
    query: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Поиск по чатам"""
    try:
        search_filter = f"%{query.strip()}%"
        results = []
        
        # Поиск пользователей
        users = db.query(User).filter(
            User.is_active == True,
            User.id != user.id,
            or_(
                User.username.ilike(search_filter),
                User.display_name.ilike(search_filter)
            )
        ).limit(limit).all()
        
        for user_item in users:
            # Проверяем, не заблокирован ли
            is_blocked = db.query(Contact).filter(
                Contact.user_id == user.id,
                Contact.contact_id == user_item.id,
                Contact.is_blocked == True
            ).first() is not None
            
            if is_blocked:
                continue
            
            results.append({
                "type": "user",
                "id": user_item.id,
                "name": user_item.display_name or user_item.username,
                "avatar_url": user_item.avatar_url,
                "is_online": user_item.is_online,
                "is_verified": user_item.is_verified,
                "bio": user_item.bio
            })
        
        # Поиск групп
        groups = db.query(Group).filter(
            Group.is_active == True,
            or_(
                Group.name.ilike(search_filter),
                Group.description.ilike(search_filter)
            )
        ).limit(limit).all()
        
        for group in groups:
            # Проверяем доступ
            membership = db.query(GroupMember).filter(
                GroupMember.group_id == group.id,
                GroupMember.user_id == user.id,
                GroupMember.is_banned == False
            ).first()
            
            if not group.is_public and not membership:
                continue
            
            results.append({
                "type": "group",
                "id": group.id,
                "name": group.name,
                "avatar_url": group.avatar_url,
                "description": group.description,
                "members_count": group.members_count,
                "is_public": group.is_public,
                "is_member": membership is not None
            })
        
        # Поиск каналов
        channels = db.query(Channel).filter(
            Channel.is_active == True,
            or_(
                Channel.name.ilike(search_filter),
                Channel.description.ilike(search_filter)
            )
        ).limit(limit).all()
        
        for channel in channels:
            # Проверяем доступ
            subscription = db.query(ChannelSubscription).filter(
                ChannelSubscription.channel_id == channel.id,
                ChannelSubscription.user_id == user.id,
                ChannelSubscription.is_banned == False
            ).first()
            
            if not channel.is_public and not subscription:
                continue
            
            results.append({
                "type": "channel",
                "id": channel.id,
                "name": channel.name,
                "avatar_url": channel.avatar_url,
                "description": channel.description,
                "subscribers_count": channel.subscribers_count,
                "is_public": channel.is_public,
                "is_verified": channel.is_verified,
                "is_subscribed": subscription is not None
            })
        
        return {
            "success": True,
            "query": query,
            "results": results,
            "count": len(results)
        }
        
    except Exception as e:
        logger.error(f"❌ Ошибка поиска: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка поиска: {str(e)}"
        )

# ========== КОНТАКТЫ ==========

@app.get("/api/contacts")
async def get_contacts(
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=500),
    search: Optional[str] = Query(None),
    favorites_only: bool = Query(False),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение списка контактов"""
    try:
        query = db.query(Contact).filter(
            Contact.user_id == user.id,
            Contact.is_blocked == False
        )
        
        if favorites_only:
            query = query.filter(Contact.is_favorite == True)
        
        if search and search.strip():
            search_filter = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    Contact.name.ilike(search_filter),
                    Contact.phone.ilike(search_filter),
                    Contact.email.ilike(search_filter),
                    Contact.notes.ilike(search_filter)
                )
            )
        
        total = query.count()
        contacts = query.order_by(
            desc(Contact.is_favorite),
            Contact.name,
            Contact.created_at
        ).offset((page - 1) * limit).limit(limit).all()
        
        contacts_data = []
        for contact in contacts:
            # Получаем информацию о пользователе если contact_id указан
            contact_user = None
            if contact.contact_id:
                contact_user = db.query(User).filter(
                    User.id == contact.contact_id,
                    User.is_active == True
                ).first()
            
            contacts_data.append({
                "id": contact.id,
                "contact_id": contact.contact_id,
                "name": contact.name or (contact_user.display_name if contact_user else None),
                "phone": contact.phone,
                "email": contact.email,
                "is_favorite": contact.is_favorite,
                "notes": contact.notes,
                "user": {
                    "id": contact_user.id if contact_user else None,
                    "username": contact_user.username if contact_user else None,
                    "display_name": contact_user.display_name if contact_user else None,
                    "avatar_url": contact_user.avatar_url if contact_user else None,
                    "is_online": contact_user.is_online if contact_user else None,
                    "is_verified": contact_user.is_verified if contact_user else None,
                    "status": contact_user.status if contact_user else None
                } if contact_user else None,
                "created_at": contact.created_at.isoformat() if contact.created_at else None,
                "updated_at": contact.updated_at.isoformat() if contact.updated_at else None
            })
        
        return {
            "success": True,
            "contacts": contacts_data,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "pages": (total + limit - 1) // limit
            }
        }
        
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки контактов: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка загрузки контактов: {str(e)}"
        )

@app.post("/api/contacts")
async def add_contact(
    contact_id: Optional[int] = Form(None),
    name: Optional[str] = Form(None),
    phone: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    is_favorite: bool = Form(False),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Добавление контакта"""
    try:
        if not contact_id and not name and not phone and not email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Необходимо указать хотя бы один идентификатор контакта (ID пользователя, имя, телефон или email)"
            )
        
        # Если указан contact_id, проверяем существование пользователя
        contact_user = None
        if contact_id:
            if contact_id == user.id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Нельзя добавить самого себя в контакты"
                )
            
            contact_user = db.query(User).filter(
                User.id == contact_id,
                User.is_active == True
            ).first()
            
            if not contact_user:
                raise HTTPException(status_code=404, detail="Пользователь не найден")
            
            # Проверяем, не заблокирован ли
            is_blocked = db.query(Contact).filter(
                Contact.user_id == user.id,
                Contact.contact_id == contact_id,
                Contact.is_blocked == True
            ).first() is not None
            
            if is_blocked:
                raise HTTPException(status_code=403, detail="Пользователь заблокирован")
        
        # Проверяем, не добавлен ли уже контакт
        existing_contact = None
        if contact_id:
            existing_contact = db.query(Contact).filter(
                Contact.user_id == user.id,
                Contact.contact_id == contact_id,
                Contact.is_blocked == False
            ).first()
        elif phone:
            existing_contact = db.query(Contact).filter(
                Contact.user_id == user.id,
                Contact.phone == phone,
                Contact.is_blocked == False
            ).first()
        elif email:
            existing_contact = db.query(Contact).filter(
                Contact.user_id == user.id,
                Contact.email == email,
                Contact.is_blocked == False
            ).first()
        
        if existing_contact:
            raise HTTPException(status_code=400, detail="Контакт уже существует")
        
        # Создаем контакт
        contact = Contact(
            user_id=user.id,
            contact_id=contact_id,
            name=name or (contact_user.display_name if contact_user else None),
            phone=phone,
            email=email,
            notes=notes,
            is_favorite=is_favorite
        )
        
        db.add(contact)
        db.commit()
        db.refresh(contact)
        
        # Уведомляем пользователя если contact_id указан
        if contact_id and contact_user:
            await manager.send_to_user(contact_id, {
                "type": "added_to_contacts",
                "added_by": user.id,
                "added_by_name": user.display_name or user.username,
                "timestamp": datetime.utcnow().isoformat()
            })
        
        return {
            "success": True,
            "message": "Контакт добавлен",
            "contact": {
                "id": contact.id,
                "contact_id": contact.contact_id,
                "name": contact.name,
                "phone": contact.phone,
                "email": contact.email,
                "is_favorite": contact.is_favorite,
                "notes": contact.notes
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Ошибка добавления контакта: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка добавления контакта: {str(e)}"
        )

@app.put("/api/contacts/{contact_id}")
async def update_contact(
    contact_id: int,
    name: Optional[str] = Form(None),
    phone: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    is_favorite: Optional[bool] = Form(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Обновление контакта"""
    try:
        contact = db.query(Contact).filter(
            Contact.id == contact_id,
            Contact.user_id == user.id,
            Contact.is_blocked == False
        ).first()
        
        if not contact:
            raise HTTPException(status_code=404, detail="Контакт не найден")
        
        if name is not None:
            contact.name = name
        
        if phone is not None:
            contact.phone = phone
        
        if email is not None:
            contact.email = email
        
        if notes is not None:
            contact.notes = notes
        
        if is_favorite is not None:
            contact.is_favorite = is_favorite
        
        contact.updated_at = datetime.utcnow()
        db.commit()
        
        return {
            "success": True,
            "message": "Контакт обновлен",
            "contact": {
                "id": contact.id,
                "contact_id": contact.contact_id,
                "name": contact.name,
                "phone": contact.phone,
                "email": contact.email,
                "is_favorite": contact.is_favorite,
                "notes": contact.notes,
                "updated_at": contact.updated_at.isoformat() if contact.updated_at else None
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Ошибка обновления контакта: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка обновления контакта: {str(e)}"
        )

@app.delete("/api/contacts/{contact_id}")
async def delete_contact(
    contact_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Удаление контакта"""
    try:
        contact = db.query(Contact).filter(
            Contact.id == contact_id,
            Contact.user_id == user.id
        ).first()
        
        if not contact:
            raise HTTPException(status_code=404, detail="Контакт не найден")
        
        db.delete(contact)
        db.commit()
        
        return {
            "success": True,
            "message": "Контакт удален"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Ошибка удаления контакта: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка удаления контакта: {str(e)}"
        )

@app.get("/api/contacts/blocked")
async def get_blocked_contacts(
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение списка заблокированных контактов"""
    try:
        query = db.query(Contact).filter(
            Contact.user_id == user.id,
            Contact.is_blocked == True
        )
        
        total = query.count()
        contacts = query.order_by(desc(Contact.updated_at)) \
                       .offset((page - 1) * limit) \
                       .limit(limit) \
                       .all()
        
        contacts_data = []
        for contact in contacts:
            # Получаем информацию о пользователе если contact_id указан
            contact_user = None
            if contact.contact_id:
                contact_user = db.query(User).filter(User.id == contact.contact_id).first()
            
            contacts_data.append({
                "id": contact.id,
                "contact_id": contact.contact_id,
                "name": contact.name or (contact_user.display_name if contact_user else None),
                "phone": contact.phone,
                "email": contact.email,
                "notes": contact.notes,
                "user": {
                    "id": contact_user.id if contact_user else None,
                    "username": contact_user.username if contact_user else None,
                    "display_name": contact_user.display_name if contact_user else None,
                    "avatar_url": contact_user.avatar_url if contact_user else None
                } if contact_user else None,
                "created_at": contact.created_at.isoformat() if contact.created_at else None,
                "updated_at": contact.updated_at.isoformat() if contact.updated_at else None
            })
        
        return {
            "success": True,
            "contacts": contacts_data,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "pages": (total + limit - 1) // limit
            }
        }
        
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки заблокированных контактов: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка загрузки заблокированных контактов: {str(e)}"
        )

# ========== ОПРОСЫ ==========

@app.post("/api/polls")
async def create_poll(
    request: PollCreateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Создание опроса"""
    try:
        if not request.question or len(request.question.strip()) < 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Вопрос опроса не может быть пустым"
            )
        
        if not request.options or len(request.options) < 2:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Опрос должен содержать хотя бы 2 варианта ответа"
            )
        
        if len(request.options) > 10:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Опрос не может содержать более 10 вариантов ответа"
            )
        
        # Проверяем, что все варианты ответа не пустые
        for i, option in enumerate(request.options):
            if not option or len(option.strip()) < 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Вариант ответа #{i+1} не может быть пустым"
                )
        
        # Создаем сообщение с опросом
        message = Message(
            from_user_id=user.id,
            content=request.question,
            message_type="poll",
            created_at=datetime.utcnow()
        )
        
        db.add(message)
        db.commit()
        db.refresh(message)
        
        # Создаем опрос
        closes_at = None
        if request.closes_at:
            try:
                closes_at = datetime.fromisoformat(request.closes_at.replace('Z', '+00:00'))
            except:
                pass
        
        poll = Poll(
            message_id=message.id,
            question=request.question,
            options=request.options,
            is_multiple=request.is_multiple,
            is_anonymous=request.is_anonymous,
            closes_at=closes_at,
            results={str(i): 0 for i in range(len(request.options))}
        )
        
        db.add(poll)
        db.commit()
        db.refresh(poll)
        
        return {
            "success": True,
            "message": "Опрос создан",
            "poll": {
                "id": poll.id,
                "message_id": poll.message_id,
                "question": poll.question,
                "options": poll.options,
                "is_multiple": poll.is_multiple,
                "is_anonymous": poll.is_anonymous,
                "is_closed": poll.is_closed,
                "closes_at": poll.closes_at.isoformat() if poll.closes_at else None,
                "results": poll.results,
                "created_at": poll.created_at.isoformat() if poll.created_at else None
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Ошибка создания опроса: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка создания опроса: {str(e)}"
        )

@app.get("/api/polls/{poll_id}")
async def get_poll(
    poll_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение информации об опросе"""
    try:
        poll = db.query(Poll).filter(Poll.id == poll_id).first()
        
        if not poll:
            raise HTTPException(status_code=404, detail="Опрос не найден")
        
        # Получаем сообщение
        message = db.query(Message).filter(Message.id == poll.message_id).first()
        if not message:
            raise HTTPException(status_code=404, detail="Сообщение с опросом не найдено")
        
        # Проверяем доступ к сообщению
        has_access = False
        
        if message.to_user_id:
            if user.id in [message.from_user_id, message.to_user_id]:
                has_access = True
        elif message.group_id:
            membership = db.query(GroupMember).filter(
                GroupMember.group_id == message.group_id,
                GroupMember.user_id == user.id,
                GroupMember.is_banned == False
            ).first()
            has_access = membership is not None
        elif message.channel_id:
            subscription = db.query(ChannelSubscription).filter(
                ChannelSubscription.channel_id == message.channel_id,
                ChannelSubscription.user_id == user.id,
                ChannelSubscription.is_banned == False
            ).first()
            has_access = subscription is not None
        
        if not has_access:
            raise HTTPException(status_code=403, detail="Нет доступа к опросу")
        
        # Проверяем, голосовал ли пользователь
        user_votes = []
        if not poll.is_anonymous:
            votes = db.query(PollVote).filter(
                PollVote.poll_id == poll_id,
                PollVote.user_id == user.id
            ).all()
            user_votes = [vote.option_index for vote in votes]
        
        # Подготавливаем результаты
        total_votes = sum(poll.results.values()) if poll.results else 0
        results_percentage = {}
        
        if total_votes > 0:
            for option_index, count in poll.results.items():
                percentage = (count / total_votes) * 100
                results_percentage[option_index] = round(percentage, 1)
        
        return {
            "success": True,
            "poll": {
                "id": poll.id,
                "message_id": poll.message_id,
                "question": poll.question,
                "options": poll.options,
                "is_multiple": poll.is_multiple,
                "is_anonymous": poll.is_anonymous,
                "is_closed": poll.is_closed,
                "closes_at": poll.closes_at.isoformat() if poll.closes_at else None,
                "results": poll.results,
                "results_percentage": results_percentage,
                "total_votes": total_votes,
                "user_votes": user_votes,
                "created_at": poll.created_at.isoformat() if poll.created_at else None,
                "updated_at": poll.updated_at.isoformat() if poll.updated_at else None
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки опроса: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка загрузки опроса: {str(e)}"
        )

@app.post("/api/polls/{poll_id}/vote")
async def vote_in_poll(
    poll_id: int,
    option_index: int = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Голосование в опросе"""
    try:
        poll = db.query(Poll).filter(Poll.id == poll_id).first()
        
        if not poll:
            raise HTTPException(status_code=404, detail="Опрос не найден")
        
        # Проверяем, закрыт ли опрос
        if poll.is_closed:
            raise HTTPException(status_code=400, detail="Опрос закрыт")
        
        # Проверяем срок действия
        if poll.closes_at and poll.closes_at < datetime.utcnow():
            poll.is_closed = True
            db.commit()
            raise HTTPException(status_code=400, detail="Время голосования истекло")
        
        # Проверяем, существует ли такой вариант ответа
        if option_index < 0 or option_index >= len(poll.options):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Неверный вариант ответа"
            )
        
        # Получаем сообщение
        message = db.query(Message).filter(Message.id == poll.message_id).first()
        if not message:
            raise HTTPException(status_code=404, detail="Сообщение с опросом не найдено")
        
        # Проверяем доступ к сообщению
        has_access = False
        
        if message.to_user_id:
            if user.id in [message.from_user_id, message.to_user_id]:
                has_access = True
        elif message.group_id:
            membership = db.query(GroupMember).filter(
                GroupMember.group_id == message.group_id,
                GroupMember.user_id == user.id,
                GroupMember.is_banned == False
            ).first()
            has_access = membership is not None
        elif message.channel_id:
            subscription = db.query(ChannelSubscription).filter(
                ChannelSubscription.channel_id == message.channel_id,
                ChannelSubscription.user_id == user.id,
                ChannelSubscription.is_banned == False
            ).first()
            has_access = subscription is not None
        
        if not has_access:
            raise HTTPException(status_code=403, detail="Нет доступа к опросу")
        
        # Проверяем, голосовал ли уже пользователь
        existing_vote = db.query(PollVote).filter(
            PollVote.poll_id == poll_id,
            PollVote.user_id == user.id,
            PollVote.option_index == option_index
        ).first()
        
        if existing_vote:
            # Удаляем голос
            db.delete(existing_vote)
            
            # Обновляем результаты
            if poll.results and str(option_index) in poll.results:
                poll.results[str(option_index)] -= 1
                if poll.results[str(option_index)] < 0:
                    poll.results[str(option_index)] = 0
            
            action = "removed"
        else:
            # Для одиночного выбора удаляем предыдущие голоса
            if not poll.is_multiple:
                old_votes = db.query(PollVote).filter(
                    PollVote.poll_id == poll_id,
                    PollVote.user_id == user.id
                ).all()
                
                for old_vote in old_votes:
                    # Уменьшаем счетчик для старого варианта
                    if poll.results and str(old_vote.option_index) in poll.results:
                        poll.results[str(old_vote.option_index)] -= 1
                        if poll.results[str(old_vote.option_index)] < 0:
                            poll.results[str(old_vote.option_index)] = 0
                    
                    db.delete(old_vote)
            
            # Добавляем новый голос
            new_vote = PollVote(
                poll_id=poll_id,
                user_id=user.id,
                option_index=option_index
            )
            db.add(new_vote)
            
            # Обновляем результаты
            if not poll.results:
                poll.results = {}
            
            if str(option_index) not in poll.results:
                poll.results[str(option_index)] = 0
            
            poll.results[str(option_index)] += 1
            action = "added"
        
        poll.updated_at = datetime.utcnow()
        db.commit()
        
        # Подготавливаем результаты для отправки
        total_votes = sum(poll.results.values()) if poll.results else 0
        results_percentage = {}
        
        if total_votes > 0:
            for opt_index, count in poll.results.items():
                percentage = (count / total_votes) * 100
                results_percentage[opt_index] = round(percentage, 1)
        
        # Уведомляем участников чата об обновлении опроса
        ws_message = {
            "type": "poll_updated",
            "poll_id": poll_id,
            "message_id": poll.message_id,
            "results": poll.results,
            "results_percentage": results_percentage,
            "total_votes": total_votes,
            "updated_by": user.id,
            "action": action,
            "option_index": option_index,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Определяем чат и отправляем уведомление
        if message.to_user_id:
            # Личное сообщение
            participants = [message.from_user_id, message.to_user_id]
            for participant in participants:
                if participant in manager.user_connections:
                    await manager.send_to_user(participant, ws_message)
        elif message.group_id:
            # Групповое сообщение
            await manager.broadcast_to_chat("group", message.group_id, ws_message)
        elif message.channel_id:
            # Сообщение в канале
            await manager.broadcast_to_chat("channel", message.channel_id, ws_message)
        
        return {
            "success": True,
            "message": f"Голос {action}",
            "poll": {
                "id": poll.id,
                "results": poll.results,
                "results_percentage": results_percentage,
                "total_votes": total_votes,
                "action": action,
                "option_index": option_index
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Ошибка голосования в опросе: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка голосования в опросе: {str(e)}"
        )

@app.post("/api/polls/{poll_id}/close")
async def close_poll(
    poll_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Закрытие опроса"""
    try:
        poll = db.query(Poll).filter(Poll.id == poll_id).first()
        
        if not poll:
            raise HTTPException(status_code=404, detail="Опрос не найден")
        
        # Получаем сообщение
        message = db.query(Message).filter(Message.id == poll.message_id).first()
        if not message:
            raise HTTPException(status_code=404, detail="Сообщение с опросом не найдено")
        
        # Проверяем права (только создатель опроса может его закрыть)
        if message.from_user_id != user.id:
            raise HTTPException(status_code=403, detail="Только создатель опроса может его закрыть")
        
        if poll.is_closed:
            raise HTTPException(status_code=400, detail="Опрос уже закрыт")
        
        poll.is_closed = True
        poll.updated_at = datetime.utcnow()
        db.commit()
        
        # Уведомляем участников чата
        ws_message = {
            "type": "poll_closed",
            "poll_id": poll_id,
            "message_id": poll.message_id,
            "closed_by": user.id,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Определяем чат и отправляем уведомление
        if message.to_user_id:
            # Личное сообщение
            participants = [message.from_user_id, message.to_user_id]
            for participant in participants:
                if participant in manager.user_connections:
                    await manager.send_to_user(participant, ws_message)
        elif message.group_id:
            # Групповое сообщение
            await manager.broadcast_to_chat("group", message.group_id, ws_message)
        elif message.channel_id:
            # Сообщение в канале
            await manager.broadcast_to_chat("channel", message.channel_id, ws_message)
        
        return {
            "success": True,
            "message": "Опрос закрыт"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Ошибка закрытия опроса: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка закрытия опроса: {str(e)}"
        )

# ========== УВЕДОМЛЕНИЯ ==========

@app.get("/api/notifications")
async def get_notifications(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    unread_only: bool = Query(False),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение уведомлений пользователя"""
    try:
        query = db.query(Notification).filter(Notification.user_id == user.id)
        
        if unread_only:
            query = query.filter(Notification.is_read == False)
        
        total = query.count()
        notifications = query.order_by(desc(Notification.created_at)) \
                            .offset((page - 1) * limit) \
                            .limit(limit) \
                            .all()
        
        notifications_data = []
        for notification in notifications:
            notifications_data.append({
                "id": notification.id,
                "type": notification.type,
                "title": notification.title,
                "message": notification.message,
                "data": notification.data,
                "is_read": notification.is_read,
                "is_important": notification.is_important,
                "action_url": notification.action_url,
                "expires_at": notification.expires_at.isoformat() if notification.expires_at else None,
                "created_at": notification.created_at.isoformat() if notification.created_at else None
            })
        
        return {
            "success": True,
            "notifications": notifications_data,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "pages": (total + limit - 1) // limit
            }
        }
        
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки уведомлений: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка загрузки уведомлений: {str(e)}"
        )

@app.post("/api/notifications/{notification_id}/read")
async def mark_notification_as_read(
    notification_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Пометка уведомления как прочитанного"""
    try:
        notification = db.query(Notification).filter(
            Notification.id == notification_id,
            Notification.user_id == user.id
        ).first()
        
        if not notification:
            raise HTTPException(status_code=404, detail="Уведомление не найдено")
        
        if notification.is_read:
            raise HTTPException(status_code=400, detail="Уведомление уже прочитано")
        
        notification.is_read = True
        db.commit()
        
        return {
            "success": True,
            "message": "Уведомление помечено как прочитанное"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Ошибка пометки уведомления как прочитанного: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка пометки уведомления как прочитанного: {str(e)}"
        )

@app.post("/api/notifications/read-all")
async def mark_all_notifications_as_read(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Пометка всех уведомлений как прочитанных"""
    try:
        notifications = db.query(Notification).filter(
            Notification.user_id == user.id,
            Notification.is_read == False
        ).all()
        
        for notification in notifications:
            notification.is_read = True
        
        db.commit()
        
        return {
            "success": True,
            "message": f"Все уведомления ({len(notifications)}) помечены как прочитанные"
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Ошибка пометки всех уведомлений как прочитанных: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка пометки всех уведомлений как прочитанных: {str(e)}"
        )

@app.delete("/api/notifications/{notification_id}")
async def delete_notification(
    notification_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Удаление уведомления"""
    try:
        notification = db.query(Notification).filter(
            Notification.id == notification_id,
            Notification.user_id == user.id
        ).first()
        
        if not notification:
            raise HTTPException(status_code=404, detail="Уведомление не найдено")
        
        db.delete(notification)
        db.commit()
        
        return {
            "success": True,
            "message": "Уведомление удалено"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Ошибка удаления уведомления: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка удаления уведомления: {str(e)}"
        )

# ========== ФАЙЛЫ ==========

@app.post("/api/upload")
async def upload_file(
    file: UploadFile = File(),
    is_public: bool = Form(False),
    expires_hours: Optional[int] = Form(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Загрузка файла"""
    try:
        if not file:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Файл не предоставлен"
            )
        
        # Проверяем размер файла
        file_size = 0
        file.file.seek(0, 2)
        file_size = file.file.tell()
        file.file.seek(0)
        
        if file_size > MAX_UPLOAD_SIZE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Размер файла не должен превышать {MAX_UPLOAD_SIZE // (1024*1024)} MB"
            )
        
        # Проверяем тип файла
        mime_type = file.content_type or mimetypes.guess_type(file.filename)[0]
        is_allowed, error_msg = FileHandler.is_allowed_file(file)
        
        if not is_allowed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_msg
            )
        
        filename = file.filename
        file_type = FileHandler.get_file_type(mime_type)
        
        # Определяем поддиректорию
        if mime_type.startswith('image/'):
            subdir = "images"
        elif mime_type.startswith('video/'):
            subdir = "videos"
        elif mime_type.startswith('audio/'):
            subdir = "audios"
        elif mime_type in FileHandler.ALLOWED_DOCUMENT_TYPES:
            subdir = "documents"
        elif mime_type in FileHandler.ALLOWED_ARCHIVE_TYPES:
            subdir = "archives"
        else:
            subdir = "files"
        
        # Генерируем уникальное имя файла
        file_ext = filename.split('.')[-1] if '.' in filename else 'bin'
        unique_filename = f"{uuid.uuid4()}.{file_ext}"
        filepath = UPLOAD_DIR / subdir / unique_filename
        
        # Сохраняем файл
        with open(filepath, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        file_url = f"/uploads/{subdir}/{unique_filename}"
        
        # Вычисляем хеши файла
        md5_hash, sha256_hash = FileHandler.get_file_hash(filepath)
        
        # Для изображений создаем миниатюру
        thumbnail_url = None
        width = None
        height = None
        
        if mime_type.startswith('image/'):
            try:
                with Image.open(filepath) as img:
                    width, height = img.size
                
                # Создаем миниатюру
                thumb_buffer = FileHandler.generate_thumbnail(filepath)
                if thumb_buffer:
                    thumb_filename = f"thumb_{unique_filename}"
                    thumb_path = UPLOAD_DIR / "thumbnails" / thumb_filename
                    with open(thumb_path, "wb") as f:
                        f.write(thumb_buffer.getvalue())
                    thumbnail_url = f"/uploads/thumbnails/{thumb_filename}"
            except Exception as e:
                logger.warning(f"Не удалось обработать изображение: {e}")
        
        # Срок действия файла
        expires_at = None
        if expires_hours:
            expires_at = datetime.utcnow() + timedelta(hours=expires_hours)
        
        # Сохраняем информацию о файле в базу
        file_record = File(
            user_id=user.id,
            filename=unique_filename,
            original_filename=filename,
            file_path=str(filepath),
            file_url=file_url,
            file_size=file_size,
            file_type=file_type,
            mime_type=mime_type,
            width=width,
            height=height,
            hash_md5=md5_hash,
            hash_sha256=sha256_hash,
            thumbnail_url=thumbnail_url,
            is_public=is_public,
            expires_at=expires_at
        )
        db.add(file_record)
        db.commit()
        db.refresh(file_record)
        
        return {
            "success": True,
            "message": "Файл загружен успешно",
            "file": {
                "id": file_record.id,
                "filename": filename,
                "original_filename": filename,
                "url": file_url,
                "thumbnail_url": thumbnail_url,
                "size": file_size,
                "type": file_type,
                "mime_type": mime_type,
                "width": width,
                "height": height,
                "is_public": is_public,
                "expires_at": expires_at.isoformat() if expires_at else None,
                "created_at": file_record.created_at.isoformat() if file_record.created_at else None
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки файла: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка загрузки файла: {str(e)}"
        )

@app.get("/api/files")
async def get_files(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    file_type: Optional[str] = Query(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение списка файлов пользователя"""
    try:
        query = db.query(File).filter(
            File.user_id == user.id,
            File.expires_at > datetime.utcnow()
        )
        
        if file_type:
            query = query.filter(File.file_type == file_type)
        
        total = query.count()
        files = query.order_by(desc(File.created_at)) \
                    .offset((page - 1) * limit) \
                    .limit(limit) \
                    .all()
        
        files_data = []
        for file_item in files:
            files_data.append({
                "id": file_item.id,
                "filename": file_item.original_filename or file_item.filename,
                "url": file_item.file_url,
                "thumbnail_url": file_item.thumbnail_url,
                "size": file_item.file_size,
                "type": file_item.file_type,
                "mime_type": file_item.mime_type,
                "width": file_item.width,
                "height": file_item.height,
                "duration": file_item.duration,
                "is_public": file_item.is_public,
                "download_count": file_item.download_count,
                "expires_at": file_item.expires_at.isoformat() if file_item.expires_at else None,
                "created_at": file_item.created_at.isoformat() if file_item.created_at else None
            })
        
        return {
            "success": True,
            "files": files_data,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "pages": (total + limit - 1) // limit
            }
        }
        
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки файлов: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка загрузки файлов: {str(e)}"
        )

@app.get("/api/files/{file_id}")
async def get_file_info(
    file_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение информации о файле"""
    try:
        file_item = db.query(File).filter(File.id == file_id).first()
        
        if not file_item:
            raise HTTPException(status_code=404, detail="Файл не найден")
        
        # Проверяем доступ
        if file_item.user_id != user.id and not file_item.is_public:
            raise HTTPException(status_code=403, detail="Нет доступа к файлу")
        
        # Проверяем срок действия
        if file_item.expires_at and file_item.expires_at < datetime.utcnow():
            raise HTTPException(status_code=410, detail="Срок действия файла истек")
        
        # Увеличиваем счетчик загрузок
        file_item.download_count += 1
        db.commit()
        
        return {
            "success": True,
            "file": {
                "id": file_item.id,
                "filename": file_item.original_filename or file_item.filename,
                "url": file_item.file_url,
                "thumbnail_url": file_item.thumbnail_url,
                "size": file_item.file_size,
                "type": file_item.file_type,
                "mime_type": file_item.mime_type,
                "width": file_item.width,
                "height": file_item.height,
                "duration": file_item.duration,
                "is_public": file_item.is_public,
                "download_count": file_item.download_count,
                "expires_at": file_item.expires_at.isoformat() if file_item.expires_at else None,
                "created_at": file_item.created_at.isoformat() if file_item.created_at else None
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки информации о файле: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка загрузки информации о файле: {str(e)}"
        )

@app.delete("/api/files/{file_id}")
async def delete_file(
    file_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Удаление файла"""
    try:
        file_item = db.query(File).filter(File.id == file_id).first()
        
        if not file_item:
            raise HTTPException(status_code=404, detail="Файл не найден")
        
        # Проверяем права
        if file_item.user_id != user.id:
            raise HTTPException(status_code=403, detail="Нет прав на удаление файла")
        
        # Удаляем файл с диска
        try:
            file_path = Path(file_item.file_path)
            if file_path.exists():
                file_path.unlink()
            
            # Удаляем миниатюру если есть
            if file_item.thumbnail_url:
                thumb_path = UPLOAD_DIR / "thumbnails" / file_item.filename
                if thumb_path.exists():
                    thumb_path.unlink()
        except Exception as e:
            logger.warning(f"Не удалось удалить файл с диска: {e}")
        
        # Удаляем запись из базы
        db.delete(file_item)
        db.commit()
        
        return {
            "success": True,
            "message": "Файл удален"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Ошибка удаления файла: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка удаления файла: {str(e)}"
        )

# ========== WEB SOCKET ==========

@app.websocket("/ws/{user_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    user_id: int,
    token: Optional[str] = None,
    device_id: Optional[str] = None
):
    """WebSocket endpoint для реального времени"""
    # Проверяем авторизацию
    db = SessionLocal()
    try:
        user = db.query(User).filter(
            User.id == user_id,
            User.is_active == True
        ).first()
        
        if not user:
            await websocket.close(code=1008)
            return
        
        # Если передан токен, проверяем его
        if token:
            payload = TokenHelper.verify_token(token)
            if not payload or payload.get("user_id") != user_id:
                await websocket.close(code=1008)
                return
        
        # Подключаем пользователя
        await manager.connect(websocket, user_id, device_id)
        
        try:
            while True:
                data = await websocket.receive_json()
                await handle_websocket_message(data, user_id, db)
                
        except WebSocketDisconnect:
            logger.info(f"📴 User disconnected: {user_id}")
            manager.disconnect(websocket)
        except Exception as e:
            logger.error(f"❌ WebSocket error: {e}")
            manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"❌ WebSocket auth error: {e}")
        await websocket.close(code=1011)
    finally:
        db.close()

async def handle_websocket_message(data: Dict[str, Any], user_id: int, db: Session):
    """Обработка сообщений WebSocket"""
    message_type = data.get("type")
    
    if message_type == "typing":
        await handle_typing_indicator(data, user_id, db)
    elif message_type == "ping":
        # Ответ на ping
        await manager.send_to_user(user_id, {"type": "pong", "timestamp": datetime.utcnow().isoformat()})
    elif message_type == "call_offer":
        await handle_call_offer(data, user_id, db)
    elif message_type == "call_answer":
        await handle_call_answer(data, user_id, db)
    elif message_type == "ice_candidate":
        await handle_ice_candidate(data, user_id)
    elif message_type == "call_end":
        await handle_call_end(data, user_id, db)
    else:
        logger.warning(f"⚠️ Unknown WebSocket message type: {message_type}")

async def handle_typing_indicator(data: Dict[str, Any], user_id: int, db: Session):
    """Обработка индикатора набора текста"""
    chat_type = data.get("chat_type")
    chat_id = data.get("chat_id")
    is_typing = data.get("is_typing", True)
    
    # Проверяем доступ к чату
    has_access = False
    
    if chat_type == "private":
        # Проверяем, не заблокирован ли пользователь
        is_blocked = db.query(Contact).filter(
            Contact.user_id == chat_id,
            Contact.contact_id == user_id,
            Contact.is_blocked == True
        ).first() is not None
        
        if not is_blocked:
            has_access = True
    elif chat_type == "group":
        membership = db.query(GroupMember).filter(
            GroupMember.group_id == chat_id,
            GroupMember.user_id == user_id,
            GroupMember.is_banned == False
        ).first()
        has_access = membership is not None
    elif chat_type == "channel":
        subscription = db.query(ChannelSubscription).filter(
            ChannelSubscription.channel_id == chat_id,
            ChannelSubscription.user_id == user_id,
            ChannelSubscription.is_banned == False
        ).first()
        has_access = subscription is not None
    
    if not has_access:
        return
    
    await manager.update_typing_indicator(user_id, chat_type, chat_id, is_typing)

async def handle_call_offer(data: Dict[str, Any], user_id: int, db: Session):
    """Обработка предложения звонка"""
    call_type = data.get("call_type", "audio")
    to_user_id = data.get("to_user_id")
    group_id = data.get("group_id")
    channel_id = data.get("channel_id")
    offer = data.get("offer")
    
    # Генерируем ID звонка
    call_id = secrets.token_urlsafe(16)
    
    # Определяем тип чата
    chat_type = "private"
    chat_id = to_user_id
    
    if group_id:
        chat_type = "group"
        chat_id = group_id
    elif channel_id:
        chat_type = "channel"
        chat_id = channel_id
    
    # Создаем комнату для звонка
    call_room = await manager.create_call_room(call_id, user_id, chat_type, chat_id, call_type)
    
    if not call_room:
        return
    
    # Сохраняем SDP offer
    call_room["sdp_offers"][user_id] = offer
    
    # Отправляем предложение другим участникам
    call_message = {
        "type": "call_offer",
        "call_id": call_id,
        "call_type": call_type,
        "from_user_id": user_id,
        "offer": offer,
        "chat_type": chat_type,
        "chat_id": chat_id,
        "timestamp": datetime.utcnow().isoformat()
    }
    
    if chat_type == "private":
        # Отправляем конкретному пользователю
        await manager.send_to_user(to_user_id, call_message)
    elif chat_type == "group":
        # Отправляем всем участникам группы кроме инициатора
        await manager.broadcast_to_chat("group", group_id, call_message, exclude_user_id=user_id)
    elif chat_type == "channel":
        # Отправляем всем подписчикам канала кроме инициатора
        await manager.broadcast_to_chat("channel", channel_id, call_message, exclude_user_id=user_id)

async def handle_call_answer(data: Dict[str, Any], user_id: int, db: Session):
    """Обработка ответа на звонок"""
    call_id = data.get("call_id")
    answer = data.get("answer")
    
    call_room = manager.get_call_room(call_id)
    if not call_room:
        return
    
    # Сохраняем SDP answer
    call_room["sdp_offers"][user_id] = answer
    
    # Отправляем ответ инициатору звонка
    answer_message = {
        "type": "call_answer",
        "call_id": call_id,
        "from_user_id": user_id,
        "answer": answer,
        "timestamp": datetime.utcnow().isoformat()
    }
    
    await manager.send_to_user(call_room["initiator_id"], answer_message)

async def handle_ice_candidate(data: Dict[str, Any], user_id: int):
    """Обработка ICE кандидата"""
    call_id = data.get("call_id")
    candidate = data.get("candidate")
    
    call_room = manager.get_call_room(call_id)
    if not call_room:
        return
    
    # Отправляем ICE кандидата другим участникам звонка
    ice_message = {
        "type": "ice_candidate",
        "call_id": call_id,
        "from_user_id": user_id,
        "candidate": candidate,
        "timestamp": datetime.utcnow().isoformat()
    }
    
    for participant_id in call_room["participants"]:
        if participant_id != user_id:
            await manager.send_to_user(participant_id, ice_message)

async def handle_call_end(data: Dict[str, Any], user_id: int, db: Session):
    """Обработка завершения звонка"""
    call_id = data.get("call_id")
    reason = data.get("reason", "ended")
    
    call_room = manager.get_call_room(call_id)
    if not call_room:
        return
    
    # Создаем запись о звонке в базе данных
    try:
        call_log = CallLog(
            call_id=call_id,
            caller_id=call_room["initiator_id"],
            call_type=call_room["call_type"],
            status="completed" if reason == "ended" else "missed",
            start_time=call_room["start_time"],
            end_time=datetime.utcnow(),
            duration=int((datetime.utcnow() - call_room["start_time"]).total_seconds()),
            is_video=call_room["call_type"] == "video",
            is_group_call=call_room["chat_type"] in ["group", "channel"],
            participants=call_room["participants"]
        )
        
        if call_room["chat_type"] == "private":
            call_log.receiver_id = call_room["chat_id"]
        elif call_room["chat_type"] == "group":
            call_log.group_id = call_room["chat_id"]
        elif call_room["chat_type"] == "channel":
            call_log.channel_id = call_room["chat_id"]
        
        db.add(call_log)
        db.commit()
    except Exception as e:
        logger.error(f"Ошибка сохранения лога звонка: {e}")
    
    # Отправляем уведомление о завершении звонка
    end_message = {
        "type": "call_end",
        "call_id": call_id,
        "from_user_id": user_id,
        "reason": reason,
        "timestamp": datetime.utcnow().isoformat()
    }
    
    for participant_id in call_room["participants"]:
        if participant_id != user_id:
            await manager.send_to_user(participant_id, end_message)
    
    # Удаляем комнату звонка
    await manager.leave_call_room(call_id, user_id)

# ========== СТАТИЧЕСКИЕ ФАЙЛЫ И СТРАНИЦЫ ==========

# Проверяем существование фронтенда
if frontend_dir.exists():
    logger.info(f"✅ Frontend found: {frontend_dir}")
    
    # Явные маршруты для основных страниц
    @app.get("/")
    async def serve_home():
        """Главная страница"""
        index_path = frontend_dir / "index.html"
        if index_path.exists():
            return FileResponse(str(index_path))
        
        # Если index.html не найден, отдаем простую страницу
        return HTMLResponse("""
        <!DOCTYPE html>
        <html>
        <head>
            <title>DevNet Messenger</title>
            <style>
                body {
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
                    margin: 0;
                    padding: 0;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    min-height: 100vh;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                }
                .container {
                    background: white;
                    border-radius: 20px;
                    padding: 40px;
                    max-width: 600px;
                    box-shadow: 0 20px 60px rgba(0,0,0,0.3);
                    text-align: center;
                }
                h1 {
                    color: #333;
                    margin-bottom: 20px;
                }
                p {
                    color: #666;
                    line-height: 1.6;
                    margin-bottom: 30px;
                }
                .links {
                    display: flex;
                    gap: 15px;
                    justify-content: center;
                    flex-wrap: wrap;
                }
                .btn {
                    padding: 12px 24px;
                    border-radius: 50px;
                    text-decoration: none;
                    font-weight: 600;
                    transition: all 0.3s ease;
                }
                .btn-primary {
                    background: #667eea;
                    color: white;
                }
                .btn-secondary {
                    background: #f1f5f9;
                    color: #475569;
                }
                .btn:hover {
                    transform: translateY(-2px);
                    box-shadow: 0 10px 20px rgba(0,0,0,0.2);
                }
                .error {
                    background: #fee;
                    border: 1px solid #fcc;
                    border-radius: 10px;
                    padding: 20px;
                    margin: 20px 0;
                }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>DevNet Messenger</h1>
                <p>Полнофункциональный мессенджер для разработчиков с поддержкой реального времени, голосовых и видеозвонков, обмена файлами и многого другого.</p>
                
                <div class="error">
                    <h2>⚠️ index.html не найден</h2>
                    <p>Файл index.html не найден в директории frontend. Пожалуйста, проверьте вашу сборку фронтенда.</p>
                </div>
                
                <div class="links">
                    <a href="/api/docs" class="btn btn-primary">API Документация</a>
                    <a href="/api/health" class="btn btn-secondary">Статус системы</a>
                    <a href="/chat" class="btn btn-secondary">Чат</a>
                </div>
                
                <p style="margin-top: 30px; font-size: 14px; color: #94a3b8;">
                    Версия 3.0.0 | DevNet Messenger API
                </p>
            </div>
        </body>
        </html>
        """)
    
    @app.get("/chat")
    async def serve_chat():
        """Страница чата"""
        chat_path = frontend_dir / "chat.html"
        if chat_path.exists():
            return FileResponse(str(chat_path))
        
        # Если chat.html не найден
        return HTMLResponse("""
        <!DOCTYPE html>
        <html>
        <head>
            <title>DevNet Chat</title>
            <style>
                body {
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
                    margin: 0;
                    padding: 0;
                    background: #f8fafc;
                    min-height: 100vh;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                }
                .container {
                    background: white;
                    border-radius: 20px;
                    padding: 40px;
                    max-width: 600px;
                    box-shadow: 0 10px 40px rgba(0,0,0,0.1);
                    text-align: center;
                }
                h1 {
                    color: #333;
                    margin-bottom: 20px;
                }
                p {
                    color: #666;
                    line-height: 1.6;
                    margin-bottom: 30px;
                }
                .error {
                    background: #fef3c7;
                    border: 1px solid #fbbf24;
                    border-radius: 10px;
                    padding: 20px;
                    margin: 20px 0;
                }
                .btn {
                    display: inline-block;
                    padding: 12px 24px;
                    background: #3b82f6;
                    color: white;
                    text-decoration: none;
                    border-radius: 50px;
                    font-weight: 600;
                    transition: all 0.3s ease;
                }
                .btn:hover {
                    background: #2563eb;
                    transform: translateY(-2px);
                    box-shadow: 0 10px 20px rgba(37, 99, 235, 0.3);
                }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>DevNet Chat</h1>
                <div class="error">
                    <h2>⚠️ chat.html не найден</h2>
                    <p>Файл chat.html не найден в директории frontend. Вы можете использовать API для доступа к функционалу чата.</p>
                </div>
                <p>Для доступа к чату используйте WebSocket подключение или REST API.</p>
                <a href="/" class="btn">На главную</a>
            </div>
        </body>
        </html>
        """)
    
    # Монтируем статику
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")
    
    # Обработчик для остальных статических файлов
    @app.get("/{path:path}")
    async def serve_static_files(path: str):
        """Сервит статические файлы"""
        # Игнорируем API маршруты
        if path.startswith("api/"):
            return JSONResponse(
                status_code=404,
                content={"detail": "API endpoint not found"}
            )
        
        file_path = frontend_dir / path
        
        # Если это путь к файлу, отдаем его
        if file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))
        
        # Если это директория или файл не найден, возвращаем index.html
        index_path = frontend_dir / "index.html"
        if index_path.exists():
            return FileResponse(str(index_path))
        
        return JSONResponse(
            status_code=404,
            content={"detail": "File not found"}
        )
        
else:
    logger.warning(f"⚠️ Frontend not found: {frontend_dir}")
    
    @app.get("/")
    async def serve_index():
        return HTMLResponse("""
        <!DOCTYPE html>
        <html>
        <head>
            <title>DevNet Messenger</title>
            <style>
                body {
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
                    margin: 0;
                    padding: 0;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    min-height: 100vh;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                }
                .container {
                    background: white;
                    border-radius: 20px;
                    padding: 40px;
                    max-width: 600px;
                    box-shadow: 0 20px 60px rgba(0,0,0,0.3);
                    text-align: center;
                }
                h1 {
                    color: #333;
                    margin-bottom: 20px;
                }
                p {
                    color: #666;
                    line-height: 1.6;
                    margin-bottom: 30px;
                }
                .warning {
                    background: #fef3c7;
                    border: 1px solid #fbbf24;
                    border-radius: 10px;
                    padding: 20px;
                    margin: 20px 0;
                }
                .links {
                    display: flex;
                    gap: 15px;
                    justify-content: center;
                    flex-wrap: wrap;
                }
                .btn {
                    padding: 12px 24px;
                    border-radius: 50px;
                    text-decoration: none;
                    font-weight: 600;
                    transition: all 0.3s ease;
                }
                .btn-primary {
                    background: #667eea;
                    color: white;
                }
                .btn-secondary {
                    background: #f1f5f9;
                    color: #475569;
                }
                .btn:hover {
                    transform: translateY(-2px);
                    box-shadow: 0 10px 20px rgba(0,0,0,0.2);
                }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>DevNet Messenger API</h1>
                <p>Full-featured messenger for developers with real-time communication, file sharing, and more.</p>
                
                <div class="warning">
                    <h2>⚠️ Frontend не найден</h2>
                    <p>Директория frontend не найдена. API работает, но фронтенд недоступен.</p>
                    <p>Проверьте путь: <code>""" + str(frontend_dir) + """</code></p>
                </div>
                
                <div class="links">
                    <a href="/api/docs" class="btn btn-primary">API Документация</a>
                    <a href="/api/health" class="btn btn-secondary">Статус системы</a>
                    <a href="/api/info" class="btn btn-secondary">Информация</a>
                </div>
                
                <p style="margin-top: 30px; font-size: 14px; color: #94a3b8;">
                    Версия 3.0.0 | DevNet Messenger API
                </p>
            </div>
        </body>
        </html>
        """)
    
    @app.get("/chat")
    async def serve_chat_fallback():
        return RedirectResponse("/")

# Монтируем директорию загрузок
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

# ========== ЗАПУСК СЕРВЕРА ==========

app_start_time = time.time()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    
    print("=" * 60)
    print("🚀 DevNet Messenger API запущен!")
    print(f"📡 Порт: {port}")
    print(f"🌍 Домен: {DOMAIN}")
    print(f"🔧 Режим: {'Production' if IS_PRODUCTION else 'Development'}")
    print(f"🔐 Secret key: {SECRET_KEY[:10]}...")
    print(f"🔑 Encryption: {'Enabled' if ENCRYPTION_KEY else 'Disabled'}")
    print(f"📁 Директория загрузок: {UPLOAD_DIR}")
    print(f"📁 Директория фронтенда: {frontend_dir}")
    print(f"🔗 Главная страница: http://localhost:{port}/")
    print(f"💬 Чат: http://localhost:{port}/chat")
    print(f"📖 API документация: http://localhost:{port}/api/docs")
    print(f"⚡ WebSocket: ws://localhost:{port}/ws/{{user_id}}")
    print("\n👑 Тестовые пользователи:")
    print("   - admin / admin123 (Администратор)")
    print("   - alice / alice123 (Алиса)")
    print("   - bob / bob123 (Боб)")
    print("   - charlie / charlie123 (Чарли)")
    print("   - david / david123 (Давид)")
    print("   - eve / eve123 (Ева)")
    print("   - frank / frank123 (Фрэнк)")
    print("   - grace / grace123 (Грейс)")
    print("   - henry / henry123 (Генри)")
    print("\n📊 Основные эндпоинты:")
    print("   - GET  /api/health          - Проверка здоровья")
    print("   - POST /api/register        - Регистрация")
    print("   - POST /api/login           - Вход")
    print("   - GET  /api/me              - Информация о пользователе")
    print("   - GET  /api/users           - Список пользователей")
    print("   - GET  /api/chats/all       - Все чаты пользователя")
    print("   - GET  /api/messages        - Сообщения")
    print("   - POST /api/messages        - Отправка сообщения")
    print("   - GET  /api/groups          - Группы")
    print("   - GET  /api/channels        - Каналы")
    print("=" * 60)
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=not IS_PRODUCTION,
        log_level="info"
            )
