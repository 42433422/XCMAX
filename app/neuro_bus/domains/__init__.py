"""
神经域（NeuroDomain）体系

提供领域隔离的事件通道
"""

from app.neuro_bus.domains.base import NeuroDomain, DomainHandler, DomainChannel

__all__ = ["NeuroDomain", "DomainHandler", "DomainChannel"]
