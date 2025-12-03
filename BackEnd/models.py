from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base
import enum

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
    
    messages_sent = relationship("Message", foreign_keys="Message.from_user_id", back_populates="sender")
    messages_received = relationship("Message", foreign_keys="Message.to_user_id", back_populates="receiver")
    group_memberships = relationship("GroupMember", back_populates="user")
    channel_subscriptions = relationship("ChannelSubscriber", back_populates="user")

class Group(Base):
    __tablename__ = "groups"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    created_by = Column(Integer, ForeignKey("users.id"))
    is_public = Column(Boolean, default=True)
    invite_link = Column(String(50), unique=True)
    created_at = Column(DateTime, server_default=func.now())
    
    messages = relationship("Message", back_populates="group")
    members = relationship("GroupMember", back_populates="group")
    creator = relationship("User", foreign_keys=[created_by])

class GroupMember(Base):
    __tablename__ = "group_members"
    
    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    role = Column(String(20), default="member")  # admin, moderator, member
    joined_at = Column(DateTime, server_default=func.now())
    
    group = relationship("Group", back_populates="members")
    user = relationship("User", back_populates="group_memberships")

class Channel(Base):
    __tablename__ = "channels"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    created_by = Column(Integer, ForeignKey("users.id"))
    is_public = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    
    messages = relationship("Message", back_populates="channel")
    subscribers = relationship("ChannelSubscriber", back_populates="channel")
    creator = relationship("User", foreign_keys=[created_by])

class ChannelSubscriber(Base):
    __tablename__ = "channel_subscribers"
    
    id = Column(Integer, primary_key=True, index=True)
    channel_id = Column(Integer, ForeignKey("channels.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    role = Column(String(20), default="subscriber")  # admin, moderator, subscriber
    subscribed_at = Column(DateTime, server_default=func.now())
    
    channel = relationship("Channel", back_populates="subscribers")
    user = relationship("User", back_populates="channel_subscriptions")

class Message(Base):
    __tablename__ = "messages"
    
    id = Column(Integer, primary_key=True, index=True)
    from_user_id = Column(Integer, ForeignKey("users.id"))
    to_user_id = Column(Integer, ForeignKey("users.id"))
    group_id = Column(Integer, ForeignKey("groups.id"))
    channel_id = Column(Integer, ForeignKey("channels.id"))
    content = Column(Text)
    message_type = Column(String(20), default="text")  # text, image, sticker, file
    sticker_id = Column(Integer, ForeignKey("stickers.id"))
    file_url = Column(String(500))
    read_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())
    
    sender = relationship("User", foreign_keys=[from_user_id], back_populates="messages_sent")
    receiver = relationship("User", foreign_keys=[to_user_id], back_populates="messages_received")
    group = relationship("Group", back_populates="messages")
    channel = relationship("Channel", back_populates="messages")
    sticker = relationship("Sticker", back_populates="messages")

class StickerPack(Base):
    __tablename__ = "sticker_packs"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    publisher = Column(String(100))
    cover_url = Column(String(500))
    is_animated = Column(Boolean, default=False)
    is_free = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    
    stickers = relationship("Sticker", back_populates="pack")

class Sticker(Base):
    __tablename__ = "stickers"
    
    id = Column(Integer, primary_key=True, index=True)
    pack_id = Column(Integer, ForeignKey("sticker_packs.id"), nullable=False)
    emoji = Column(String(10))
    url = Column(String(500), nullable=False)
    width = Column(Integer, default=512)
    height = Column(Integer, default=512)
    created_at = Column(DateTime, server_default=func.now())
    
    pack = relationship("StickerPack", back_populates="stickers")
    messages = relationship("Message", back_populates="sticker")

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
