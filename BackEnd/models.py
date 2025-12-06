from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, Enum, JSON, func
from sqlalchemy.orm import relationship
from database import Base

# Типы сообщений
class MessageType(enum.Enum):
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    FILE = "file"

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    display_name = Column(String(100))
    avatar_url = Column(String(500))
    password_hash = Column(String(255), nullable=False)
    is_online = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())
    
    # Новые поля для совместимости
    owner_id = Column(Integer, nullable=True)  # Для групп/каналов
    subscribers_count = Column(Integer, default=0)  # Для каналов
    members_count = Column(Integer, default=0)  # Для групп
    name = Column(String(100), nullable=True)  # Для групп/каналов
    
    # Связи
    messages_sent = relationship("Message", foreign_keys="Message.from_user_id", back_populates="sender")
    messages_received = relationship("Message", foreign_keys="Message.to_user_id", back_populates="receiver")

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
    
    # Связи
    creator = relationship("User", foreign_keys=[owner_id])
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
    
    # Связи
    creator = relationship("User", foreign_keys=[owner_id])
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
    user = relationship("User")

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
    
    # Новое поле для реакций
    reactions = Column(JSON, default=dict)
    
    # Связи
    sender = relationship("User", foreign_keys=[from_user_id], back_populates="messages_sent")
    receiver = relationship("User", foreign_keys=[to_user_id], back_populates="messages_received")
    group = relationship("Group", back_populates="messages")
    channel = relationship("Channel", back_populates="messages")
    reply_to = relationship("Message", remote_side=[id])
