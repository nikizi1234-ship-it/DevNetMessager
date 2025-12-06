from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, Enum as SQLEnum, JSON, func
from sqlalchemy.orm import relationship
import enum
from database import Base  # Импортируем Base из database.py

# Типы чатов
class ChatType(enum.Enum):
    PRIVATE = "private"
    GROUP = "group"
    CHANNEL = "channel"

# Типы сообщений
class MessageType(enum.Enum):
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    FILE = "file"
    VOICE = "voice"
    STICKER = "sticker"
    LOCATION = "location"

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    display_name = Column(String(100))
    avatar_url = Column(String(500))
    bio = Column(Text)
    password_hash = Column(String(255), nullable=False)
    is_online = Column(Boolean, default=False)
    is_guest = Column(Boolean, default=False)
    is_admin = Column(Boolean, default=False)
    is_banned = Column(Boolean, default=False)
    last_login = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())
    
    # Новые поля для совместимости
    owner_id = Column(Integer, nullable=True)
    subscribers_count = Column(Integer, default=0)
    members_count = Column(Integer, default=0)
    name = Column(String(100), nullable=True)
    
    # Связи
    messages_sent = relationship("Message", foreign_keys="Message.from_user_id", back_populates="sender")
    messages_received = relationship("Message", foreign_keys="Message.to_user_id", back_populates="receiver")
    created_groups = relationship("Group", foreign_keys="Group.owner_id", back_populates="creator")
    created_channels = relationship("Channel", foreign_keys="Channel.owner_id", back_populates="creator")
    subscriptions = relationship("Subscription", back_populates="user")

class Group(Base):
    __tablename__ = "groups"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    avatar_url = Column(String(500))
    is_public = Column(Boolean, default=True)
    owner_id = Column(Integer, ForeignKey("users.id"))
    members_count = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())
    last_activity = Column(DateTime, server_default=func.now())
    
    # Связи
    creator = relationship("User", foreign_keys=[owner_id], back_populates="created_groups")
    members = relationship("GroupMember", back_populates="group", cascade="all, delete-orphan")
    messages = relationship("Message", back_populates="group")

class Channel(Base):
    __tablename__ = "channels"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    avatar_url = Column(String(500))
    is_public = Column(Boolean, default=True)
    owner_id = Column(Integer, ForeignKey("users.id"))
    subscribers_count = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())
    last_activity = Column(DateTime, server_default=func.now())
    
    # Связи
    creator = relationship("User", foreign_keys=[owner_id], back_populates="created_channels")
    subscribers = relationship("Subscription", back_populates="channel", cascade="all, delete-orphan")
    messages = relationship("Message", back_populates="channel")

class Subscription(Base):
    __tablename__ = "subscriptions"
    
    id = Column(Integer, primary_key=True, index=True)
    channel_id = Column(Integer, ForeignKey("channels.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    role = Column(String(20), default="subscriber")
    created_at = Column(DateTime, server_default=func.now())
    
    # Связи
    channel = relationship("Channel", back_populates="subscribers")
    user = relationship("User", back_populates="subscriptions")

class GroupMember(Base):
    __tablename__ = "group_members"
    
    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    role = Column(String(20), default="member")
    created_at = Column(DateTime, server_default=func.now())
    
    # Связи
    group = relationship("Group", back_populates="members")
    user = relationship("User")

class Message(Base):
    __tablename__ = "messages"
    
    id = Column(Integer, primary_key=True, index=True)
    from_user_id = Column(Integer, ForeignKey("users.id"))
    to_user_id = Column(Integer, ForeignKey("users.id"))
    group_id = Column(Integer, ForeignKey("groups.id"))
    channel_id = Column(Integer, ForeignKey("channels.id"))
    content = Column(Text)
    message_type = Column(String(20), default="text")
    media_url = Column(String(500))
    media_size = Column(Integer)
    filename = Column(String(255))
    reply_to_id = Column(Integer, ForeignKey("messages.id"))
    created_at = Column(DateTime, server_default=func.now())
    
    # Новые поля для реакций и прочего
    reactions = Column(JSON, default=dict)
    is_edited = Column(Boolean, default=False)
    is_pinned = Column(Boolean, default=False)
    
    # Связи
    sender = relationship("User", foreign_keys=[from_user_id], back_populates="messages_sent")
    receiver = relationship("User", foreign_keys=[to_user_id], back_populates="messages_received")
    group = relationship("Group", back_populates="messages")
    channel = relationship("Channel", back_populates="messages")
    reply_to = relationship("Message", remote_side=[id])

class Reaction(Base):
    __tablename__ = "reactions"
    
    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(Integer, ForeignKey("messages.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    emoji = Column(String(10), nullable=False)
    created_at = Column(DateTime, server_default=func.now())

class File(Base):
    __tablename__ = "files"
    
    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(255), nullable=False)
    original_filename = Column(String(255))
    file_type = Column(String(50))
    file_size = Column(Integer)
    uploaded_by = Column(Integer, ForeignKey("users.id"))
    url = Column(String(500), nullable=False)
    created_at = Column(DateTime, server_default=func.now())

class Notification(Base):
    __tablename__ = "notifications"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    type = Column(String(50))
    title = Column(String(255))
    content = Column(Text)
    data = Column(JSON)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())
