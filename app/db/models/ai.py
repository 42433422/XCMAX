import json
import logging
from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.db.base import Base

logger = logging.getLogger(__name__)


class AIToolCategory(Base):
    __tablename__ = "ai_tool_categories"
    __table_args__ = {"sqlite_autoincrement": True}

    id = Column(Integer, primary_key=True, autoincrement=True)
    category_name = Column(String, nullable=False)
    category_key = Column(String, unique=True, nullable=False)
    description = Column(String)
    icon = Column(String)
    sort_order = Column(Integer, default=0)
    is_active = Column(Integer, default=1)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
    
    # Relationship mappings
    tools = relationship("AITool", back_populates="category")


class AITool(Base):
    __tablename__ = "ai_tools"
    __table_args__ = {"sqlite_autoincrement": True}

    id = Column(Integer, primary_key=True, autoincrement=True)
    tool_key = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    category_id = Column(Integer, ForeignKey('ai_tool_categories.id', ondelete='SET NULL'))
    description = Column(String)
    parameters = Column(String)
    is_active = Column(Integer, default=1)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
    
    # Relationship mappings
    category = relationship("AIToolCategory", back_populates="tools")


class AIConversation(Base):
    __tablename__ = "ai_conversations"
    __table_args__ = {"sqlite_autoincrement": True}

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, ForeignKey('ai_conversation_sessions.session_id', ondelete='CASCADE'), nullable=False)
    user_id = Column(String)
    role = Column(String, nullable=False)
    content = Column(String, nullable=False)
    intent = Column(String)
    conversation_metadata = Column(String)
    created_at = Column(DateTime)
    
    # Relationship mappings
    session = relationship("AIConversationSession", back_populates="conversations")


class AIConversationSession(Base):
    __tablename__ = "ai_conversation_sessions"
    __table_args__ = {"sqlite_autoincrement": True}

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, unique=True, nullable=False)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'))
    title = Column(String)
    summary = Column(String)
    message_count = Column(Integer, default=0)
    last_message_at = Column(DateTime)
    created_at = Column(DateTime)
    
    # Relationship mappings
    user = relationship("User", back_populates="ai_conversation_sessions")
    conversations = relationship("AIConversation", back_populates="session", cascade="all, delete-orphan")


class UserPreference(Base):
    __tablename__ = "user_preferences"
    __table_args__ = {"sqlite_autoincrement": True}

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, nullable=False)
    preference_key = Column(String, nullable=False)
    preference_value = Column(String)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)


class UserMemory(Base):
    __tablename__ = "user_memories"
    __table_args__ = {"sqlite_autoincrement": True}

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, nullable=False, index=True)
    preferences = Column(Text)
    frequent_actions = Column(Text)
    historical_contexts = Column(Text)
    feedback_history = Column(Text)
    updated_at = Column(DateTime)
    
    # Data governance fields to prevent unbounded growth (addresses architecture issue #6)
    ttl_days = Column(Integer, default=90)  # Records older than this will be eligible for archive/cleanup
    max_preferences = Column(Integer, default=50)
    max_actions = Column(Integer, default=30)
    max_contexts = Column(Integer, default=100)
    max_feedback = Column(Integer, default=50)

    @property
    def preferences_dict(self) -> Dict[str, Any]:
        if self.preferences:
            return json.loads(self.preferences)
        return {}

    @property
    def frequent_actions_list(self) -> List[Dict[str, Any]]:
        if self.frequent_actions:
            return json.loads(self.frequent_actions)
        return []

    @property
    def historical_contexts_list(self) -> List[Dict[str, Any]]:
        if self.historical_contexts:
            return json.loads(self.historical_contexts)
        return []

    @property
    def feedback_history_list(self) -> List[Dict[str, Any]]:
        if self.feedback_history:
            return json.loads(self.feedback_history)
        return []

    def update_from_dict(self, data: Dict[str, Any]) -> None:
        """Update with automatic pruning to prevent unbounded growth of JSON fields."""
        if "preferences" in data:
            prefs = data["preferences"]
            if isinstance(prefs, dict) and len(prefs) > (self.max_preferences or 50):
                # Prune to most recent/relevant (simple heuristic)
                prefs = dict(list(prefs.items())[:self.max_preferences or 50])
            self.preferences = json.dumps(prefs, ensure_ascii=False)
        
        if "frequent_actions" in data:
            actions = data["frequent_actions"]
            if isinstance(actions, list):
                # Keep top N by frequency
                actions = sorted(actions, key=lambda x: x.get('count', 0) if isinstance(x, dict) else 0, reverse=True)
                actions = actions[:self.max_actions or 30]
            self.frequent_actions = json.dumps(actions, ensure_ascii=False)
        
        if "historical_contexts" in data:
            contexts = data["historical_contexts"]
            if isinstance(contexts, list):
                contexts = contexts[:self.max_contexts or 100]
            self.historical_contexts = json.dumps(contexts, ensure_ascii=False)
        
        if "feedback_history" in data:
            feedback = data["feedback_history"]
            if isinstance(feedback, list):
                feedback = feedback[:self.max_feedback or 50]
            self.feedback_history = json.dumps(feedback, ensure_ascii=False)
        
        self.updated_at = datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "preferences": self.preferences_dict,
            "frequent_actions": self.frequent_actions_list,
            "historical_contexts": self.historical_contexts_list,
            "feedback_history": self.feedback_history_list,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "ttl_days": self.ttl_days,
        }

    @classmethod
    def cleanup_old_records(cls, db_session, days: int = 90) -> int:
        """Clean up old UserMemory records to prevent unbounded growth.
        
        Moves old records to an archive table or deletes them based on business rules.
        Should be called by a scheduled background job (e.g. APScheduler).
        """
        from datetime import timedelta
        from sqlalchemy import text
        
        cutoff = datetime.now() - timedelta(days=days)
        # For production, this would use proper archiving. For now, delete old records.
        # In PostgreSQL this could be a partitioned table or separate archive schema.
        
        result = db_session.query(cls).filter(
            cls.updated_at < cutoff
        ).delete()
        
        db_session.commit()
        logger.info(f"Cleaned up {result} old UserMemory records older than {days} days")
        return result
