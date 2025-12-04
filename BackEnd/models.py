from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    display_name = Column(String(100))
    password_hash = Column(String(255), nullable=False)
    is_online = Column(Boolean, default=False)
    is_guest = Column(Boolean, default=False)  # Новое поле: является ли пользователь гостем
    last_login = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())
    
    # Связи с сообщениями
    messages_sent = relationship("Message", foreign_keys="Message.from_user_id", back_populates="sender")
    messages_received = relationship("Message", foreign_keys="Message.to_user_id", back_populates="receiver")

class Message(Base):
    __tablename__ = "messages"
    
    id = Column(Integer, primary_key=True, index=True)
    from_user_id = Column(Integer, ForeignKey("users.id"))
    to_user_id = Column(Integer, ForeignKey("users.id"))
    content = Column(Text)
    message_type = Column(String(20), default="text")  # text, image, file
    file_url = Column(String(500))  # URL для изображений/файлов
    created_at = Column(DateTime, server_default=func.now())
    
    # Связи с пользователями
    sender = relationship("User", foreign_keys=[from_user_id], back_populates="messages_sent")
    receiver = relationship("User", foreign_keys=[to_user_id], back_populates="messages_received")

class Group(Base):
    __tablename__ = "groups"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, server_default=func.now())

class GroupMember(Base):
    __tablename__ = "group_members"
    
    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    joined_at = Column(DateTime, server_default=func.now())

class File(Base):
    __tablename__ = "files"
    
    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(255), nullable=False)
    original_filename = Column(String(255))
    file_type = Column(String(50))  # image, document, video, audio
    file_size = Column(Integer)
    uploaded_by = Column(Integer, ForeignKey("users.id"))
    url = Column(String(500), nullable=False)
    created_at = Column(DateTime, server_default=func.now())
