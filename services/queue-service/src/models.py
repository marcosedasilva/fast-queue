from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    DateTime,
    Enum,
    ForeignKey,
    Boolean,
)
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from .database import Base
import enum


class QueueStatus(str, enum.Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    DELETED = "DELETED"


class QueueEntryStatus(str, enum.Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    WAITING = "WAITING"
    CALLED = "CALLED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    DELETED = "DELETED"


class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    display_name = Column(String, nullable=True)
    wallet_balance = Column(Float, default=0.0)
    is_streamer = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    queues = relationship("Queue", back_populates="streamer")


class Queue(Base):
    __tablename__ = "queues"
    id = Column(Integer, primary_key=True, index=True)
    streamer_id = Column(String, ForeignKey("users.id"), nullable=False)
    title = Column(String, index=True, nullable=False)
    max_slots = Column(Integer, default=10)
    entry_fee = Column(Integer, nullable=False)
    status = Column(Enum(QueueStatus, native_enum=False), default=QueueStatus.OPEN)
    streamer_name = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    streamer = relationship("User", back_populates="queues")
    entries = relationship("QueueEntry", back_populates="queue")


class QueueEntry(Base):
    __tablename__ = "queue_entries"
    id = Column(Integer, primary_key=True, index=True)
    queue_id = Column(Integer, ForeignKey("queues.id"), nullable=False)
    viewer_id = Column(String, ForeignKey("users.id"), nullable=False)
    position = Column(Integer, nullable=False)
    status = Column(
        Enum(QueueEntryStatus, native_enum=False),
        default=QueueEntryStatus.PENDING_PAYMENT,
    )
    game_nick = Column(String, nullable=False)
    social_handle = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    queue = relationship("Queue", back_populates="entries")
    viewer = relationship("User")

    @property
    def display_name(self):
        return self.viewer.display_name if self.viewer else None
