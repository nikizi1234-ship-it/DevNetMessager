from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from enum import Enum as PyEnum
from database import Base

# Типы чатов
class ChatType(PyEnum):
    PRIVATE = "private"
    GROUP = "group"
    CHANNEL = "channel"

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    display_name = Column(String(100))
    password_hash = Column(String(255), nullable=False)
    is_online = Column(Boolean, default=False)
    is_guest = Column(Boolean, default=False)
    last_login = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())
    
    # Связи
    messages_sent = relationship("Message", foreign_keys="Message.from_user_id", back_populates="sender")
    messages_received = relationship("Message", foreign_keys="Message.to_user_id", back_populates="receiver")
    created_groups = relationship("Group", back_populates="creator")
    created_channels = relationship("Channel", back_populates="creator")

class Chat(Base):
    """Базовый класс для всех типов чатов"""
    __tablename__ = "chats"
    
    id = Column(Integer, primary_key=True, index=True)
    chat_type = Column(String(20), nullable=False)  # private, group, channel
    name = Column(String(100), nullable=False)
    description = Column(Text)
    avatar_url = Column(String(500))
    is_public = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    
    # Полиморфная связь
    __mapper_args__ = {
        'polymorphic_identity': 'chat',
        'polymorphic_on': chat_type
    }

class PrivateChat(Chat):
    """Личный чат между двумя пользователями"""
    __tablename__ = "private_chats"
    
    id = Column(Integer, ForeignKey('chats.id'), primary_key=True)
    user1_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    user2_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    
    # Связи
    user1 = relationship("User", foreign_keys=[user1_id])
    user2 = relationship("User", foreign_keys=[user2_id])
    
    __mapper_args__ = {
        'polymorphic_identity': 'private',
    }

class Group(Chat):
    """Групповой чат с участниками"""
    __tablename__ = "groups"
    
    id = Column(Integer, ForeignKey('chats.id'), primary_key=True)
    created_by = Column(Integer, ForeignKey('users.id'), nullable=False)
    max_members = Column(Integer, default=1000)
    
    # Связи
    creator = relationship("User", back_populates="created_groups")
    members = relationship("GroupMember", back_populates="group")
    
    __mapper_args__ = {
        'polymorphic_identity': 'group',
    }

class Channel(Chat):
    """Канал (только админы пишут, все читают)"""
    __tablename__ = "channels"
    
    id = Column(Integer, ForeignKey('chats.id'), primary_key=True)
    created_by = Column(Integer, ForeignKey('users.id'), nullable=False)
    is_official = Column(Boolean, default=False)  # Официальный канал DevNet
    admin_only = Column(Boolean, default=True)  # Только админы могут писать
    
    # Связи
    creator = relationship("User", back_populates="created_channels")
    admins = relationship("ChannelAdmin", back_populates="channel")
    subscribers = relationship("ChannelSubscriber", back_populates="channel")
    
    __mapper_args__ = {
        'polymorphic_identity': 'channel',
    }

class GroupMember(Base):
    __tablename__ = "group_members"
    
    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey('groups.id'), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    role = Column(String(20), default="member")  # member, admin, creator
    joined_at = Column(DateTime, server_default=func.now())
    
    # Связи
    group = relationship("Group", back_populates="members")
    user = relationship("User")

class ChannelAdmin(Base):
    __tablename__ = "channel_admins"
    
    id = Column(Integer, primary_key=True, index=True)
    channel_id = Column(Integer, ForeignKey('channels.id'), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    added_at = Column(DateTime, server_default=func.now())
    
    # Связи
    channel = relationship("Channel", back_populates="admins")
    user = relationship("User")

class ChannelSubscriber(Base):
    __tablename__ = "channel_subscribers"
    
    id = Column(Integer, primary_key=True, index=True)
    channel_id = Column(Integer, ForeignKey('channels.id'), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    joined_at = Column(DateTime, server_default=func.now())
    
    # Связи
    channel = relationship("Channel", back_populates="subscribers")
    user = relationship("User")

class Message(Base):
    __tablename__ = "messages"
    
    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(Integer, ForeignKey('chats.id'), nullable=False)
    from_user_id = Column(Integer, ForeignKey('users.id'))
    content = Column(Text)
    message_type = Column(String(20), default="text")
    file_url = Column(String(500))
    created_at = Column(DateTime, server_default=func.now())
    
    # Связи
    chat = relationship("Chat")
    sender = relationship("User", foreign_keys=[from_user_id], back_populates="messages_sent")

class File(Base):
    __tablename__ = "files"
    
    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(255), nullable=False)
    original_filename = Column(String(255))
    file_type = Column(String(50))
    file_size = Column(Integer)
    uploaded_by = Column(Integer, ForeignKey('users.id'))
    url = Column(String(500), nullable=False)
    created_at = Column(DateTime, server_default=func.now())
