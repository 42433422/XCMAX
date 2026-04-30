# -*- coding: utf-8 -*-
"""
审批流数据库模型

包含审批流程定义、审批请求、审批节点、审批记录等核心实体
"""

from datetime import datetime
from typing import Optional, List
from enum import Enum

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Float,
    UniqueConstraint,
    Index,
    func,
)
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.sql import func as sql_func

from app.db.base import Base
from app.domain.approval.safe_dsl import should_trigger_condition


class ApprovalStatus(str, Enum):
    """审批状态枚举"""
    PENDING = "pending"  # 待审批
    IN_PROGRESS = "in_progress"  # 审批中
    APPROVED = "approved"  # 已通过
    REJECTED = "rejected"  # 已拒绝
    CANCELLED = "cancelled"  # 已取消
    WITHDRAWN = "withdrawn"  # 已撤回


class ApprovalNodeType(str, Enum):
    """审批节点类型"""
    SERIAL = "serial"  # 串行审批 (按顺序)
    PARALLEL = "parallel"  # 并行审批 (同时)
    COUNTERSIGN = "countersign"  # 会签 (所有人同意)
    OR_SIGN = "or_sign"  # 或签 (一人同意即可)


class ApprovalAction(str, Enum):
    """审批操作类型"""
    APPROVE = "approve"  # 同意
    REJECT = "reject"  # 拒绝
    TRANSFER = "transfer"  # 转交
    DELEGATE = "delegate"  # 委托
    WITHDRAW = "withdraw"  # 撤回
    CANCEL = "cancel"  # 取消


class ApprovalFlow(Base):
    """
    审批流程定义表
    
    定义一个完整的审批流程模板，例如:
    - 价格审批流程
    - 订单折扣审批流程
    - 采购付款审批流程
    - 员工请假审批流程
    """
    __tablename__ = "approval_flows"

    id = Column(Integer, primary_key=True, autoincrement=True)
    flow_key = Column(String(64), unique=True, nullable=False, index=True)  # 流程标识符
    flow_name = Column(String(128), nullable=False)  # 流程名称
    description = Column(Text)  # 流程描述
    industry = Column(String(64), default="通用")  # 适用行业
    business_type = Column(String(64), default="general", index=True)  # 业务类型：shipment/purchase/expense/contract/general
    
    # 流程配置
    node_type = Column(String(32), default=ApprovalNodeType.SERIAL.value)  # 节点类型
    allow_transfer = Column(Boolean, default=True)  # 是否允许转交
    allow_delegate = Column(Boolean, default=False)  # 是否允许委托
    allow_withdraw = Column(Boolean, default=True)  # 是否允许撤回
    timeout_hours = Column(Integer, default=48)  # 审批超时时间 (小时)
    
    # 状态
    is_active = Column(Boolean, default=True, index=True)  # 是否启用
    is_deleted = Column(Boolean, default=False)  # 软删除标记
    
    # 审计字段
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime(timezone=True), server_default=sql_func.now())
    updated_at = Column(DateTime(timezone=True), server_default=sql_func.now(), onupdate=sql_func.now())
    
    # 关联关系
    nodes = relationship("ApprovalFlowNode", back_populates="flow", cascade="all, delete-orphan")
    requests = relationship("ApprovalRequest", back_populates="flow")
    creator = relationship("User", foreign_keys=[created_by])
    
    __table_args__ = (
        Index("idx_flow_key_active", "flow_key", "is_active"),
    )
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.id,
            "flow_key": self.flow_key,
            "flow_name": self.flow_name,
            "description": self.description,
            "industry": self.industry,
            "business_type": self.business_type or "general",
            "node_type": self.node_type,
            "allow_transfer": self.allow_transfer,
            "allow_delegate": self.allow_delegate,
            "allow_withdraw": self.allow_withdraw,
            "timeout_hours": self.timeout_hours,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "nodes": [node.to_dict() for node in self.nodes]
        }


class ApprovalFlowNode(Base):
    """
    审批流程节点表
    
    定义审批流程中的每个节点，例如:
    - 节点 1: 部门经理审批
    - 节点 2: 财务经理审批
    - 节点 3: 总经理审批
    """
    __tablename__ = "approval_flow_nodes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    flow_id = Column(Integer, ForeignKey("approval_flows.id", ondelete="CASCADE"), nullable=False, index=True)
    node_name = Column(String(128), nullable=False)  # 节点名称
    node_order = Column(Integer, nullable=False)  # 节点顺序 (从 1 开始)
    
    # 节点类型 (可覆盖流程默认设置)
    node_type = Column(String(32), default=ApprovalNodeType.SERIAL.value)
    
    # 审批人配置
    approver_type = Column(String(32), nullable=False)  # 审批人类型：user/role/position/dynamic
    approver_ids = Column(Text)  # 审批人 ID 列表 (JSON 数组)
    min_approvals = Column(Integer, default=1)  # 最少通过人数 (用于会签/或签)
    
    # 审批条件
    condition_expression = Column(Text)  # 条件表达式 (Python 语法)
    condition_description = Column(String(256))  # 条件描述
    
    # 超时配置
    timeout_hours = Column(Integer)  # 节点超时时间 (覆盖流程默认值)
    timeout_action = Column(String(32), default="notify")  # 超时动作：notify/auto_approve/auto_reject
    
    # 状态
    is_active = Column(Boolean, default=True)
    
    # 审计字段
    created_at = Column(DateTime(timezone=True), server_default=sql_func.now())
    updated_at = Column(DateTime(timezone=True), server_default=sql_func.now(), onupdate=sql_func.now())
    
    # 关联关系
    flow = relationship("ApprovalFlow", back_populates="nodes")
    
    def to_dict(self) -> dict:
        """转换为字典"""
        import json
        return {
            "id": self.id,
            "flow_id": self.flow_id,
            "node_name": self.node_name,
            "node_order": self.node_order,
            "node_type": self.node_type,
            "approver_type": self.approver_type,
            "approver_ids": json.loads(self.approver_ids) if self.approver_ids else [],
            "min_approvals": self.min_approvals,
            "condition_expression": self.condition_expression,
            "condition_description": self.condition_description,
            "timeout_hours": self.timeout_hours,
            "timeout_action": self.timeout_action,
            "is_active": self.is_active
        }

    def should_trigger(self, context: dict) -> bool:
        """Safely evaluate if this node should trigger based on condition_expression.
        
        Uses the secure DSL evaluator to prevent code injection attacks.
        Returns True if no condition is set or if condition evaluates to true.
        """
        return should_trigger_condition(self, context)


class ApprovalRequest(Base):
    """
    审批请求表
    
    记录每次审批请求的完整信息
    """
    __tablename__ = "approval_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    request_no = Column(String(64), unique=True, nullable=False, index=True)  # 审批单号
    
    # 关联信息
    flow_id = Column(Integer, ForeignKey("approval_flows.id"), nullable=False, index=True)
    business_type = Column(String(64), nullable=False)  # 业务类型：price/order/payment/leave...
    business_id = Column(Integer)  # 业务 ID (关联具体业务表)
    business_data = Column(Text)  # 业务数据快照 (JSON)
    
    # 申请人信息
    applicant_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    applicant_name = Column(String(64))  # 申请人姓名 (冗余字段)
    applicant_department = Column(String(64))  # 申请人部门
    
    # 审批信息
    title = Column(String(256), nullable=False)  # 审批标题
    description = Column(Text)  # 审批描述
    current_node_id = Column(Integer, ForeignKey("approval_flow_nodes.id"))  # 当前节点
    current_node_order = Column(Integer, default=1)  # 当前节点顺序
    
    # 状态
    status = Column(String(32), default=ApprovalStatus.PENDING.value, index=True)
    priority = Column(String(16), default="normal")  # 优先级：low/normal/high/urgent
    
    # 时间信息
    submitted_at = Column(DateTime(timezone=True), server_default=sql_func.now())
    approved_at = Column(DateTime(timezone=True))  # 最终通过时间
    rejected_at = Column(DateTime(timezone=True))  # 最终拒绝时间
    expired_at = Column(DateTime(timezone=True))  # 过期时间
    
    # 审批结果
    approved_by = Column(Integer, ForeignKey("users.id"))  # 最终审批人
    approved_by_name = Column(String(64))  # 最终审批人姓名
    rejection_reason = Column(String(512))  # 拒绝原因
    
    # 审计字段
    created_at = Column(DateTime(timezone=True), server_default=sql_func.now())
    updated_at = Column(DateTime(timezone=True), server_default=sql_func.now(), onupdate=sql_func.now())
    
    # 关联关系
    flow = relationship("ApprovalFlow", back_populates="requests")
    applicant = relationship("User", foreign_keys=[applicant_id])
    current_node = relationship("ApprovalFlowNode", foreign_keys=[current_node_id])
    records = relationship("ApprovalRecord", back_populates="request", cascade="all, delete-orphan")
    approver = relationship("User", foreign_keys=[approved_by])
    
    def to_dict(self) -> dict:
        """转换为字典"""
        import json
        return {
            "id": self.id,
            "request_no": self.request_no,
            "flow_id": self.flow_id,
            "flow_name": self.flow.flow_name if self.flow else None,
            "business_type": self.business_type,
            "business_id": self.business_id,
            "business_data": json.loads(self.business_data) if self.business_data else {},
            "applicant_id": self.applicant_id,
            "applicant_name": self.applicant_name,
            "applicant_department": self.applicant_department,
            "title": self.title,
            "description": self.description,
            "current_node_id": self.current_node_id,
            "current_node_order": self.current_node_order,
            "current_node_name": self.current_node.node_name if self.current_node else None,
            "current_approvers": (
                json.loads(self.current_node.approver_ids)
                if self.current_node and self.current_node.approver_ids
                else []
            ),
            "status": self.status,
            "priority": self.priority,
            "submitted_at": self.submitted_at.isoformat() if self.submitted_at else None,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "rejected_at": self.rejected_at.isoformat() if self.rejected_at else None,
            "approved_by": self.approved_by,
            "approved_by_name": self.approved_by_name,
            "rejection_reason": self.rejection_reason,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ApprovalRecord(Base):
    """
    审批记录表
    
    记录每个节点的审批操作历史
    """
    __tablename__ = "approval_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    request_id = Column(Integer, ForeignKey("approval_requests.id", ondelete="CASCADE"), nullable=False, index=True)
    node_id = Column(Integer, ForeignKey("approval_flow_nodes.id"), nullable=False)  # 审批节点
    node_name = Column(String(128))  # 节点名称 (冗余)
    node_order = Column(Integer)  # 节点顺序 (冗余)
    
    # 审批人信息
    approver_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    approver_name = Column(String(64))  # 审批人姓名
    
    # 审批操作
    action = Column(String(32), nullable=False)  # approve/reject/transfer/delegate/withdraw
    opinion = Column(Text)  # 审批意见
    reject_reason = Column(String(512))  # 拒绝原因
    
    # 转交/委托信息
    transferred_from = Column(Integer, ForeignKey("users.id"))  # 转交来源
    transferred_to = Column(Integer, ForeignKey("users.id"))  # 转交目标
    delegate_user = Column(Integer, ForeignKey("users.id"))  # 被委托人
    
    # 状态
    is_passed = Column(Boolean, default=False)  # 是否通过
    
    # 时间信息
    action_time = Column(DateTime(timezone=True), server_default=sql_func.now())
    deadline = Column(DateTime(timezone=True))  # 审批截止时间
    
    # 审计字段
    created_at = Column(DateTime(timezone=True), server_default=sql_func.now())
    
    # 关联关系
    request = relationship("ApprovalRequest", back_populates="records")
    approver = relationship("User", foreign_keys=[approver_id])
    
    __table_args__ = (
        Index("idx_request_node", "request_id", "node_order"),
    )
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.id,
            "request_id": self.request_id,
            "node_id": self.node_id,
            "node_name": self.node_name,
            "node_order": self.node_order,
            "approver_id": self.approver_id,
            "approver_name": self.approver_name,
            "action": self.action,
            "opinion": self.opinion,
            "reject_reason": self.reject_reason,
            "is_passed": self.is_passed,
            "action_time": self.action_time.isoformat() if self.action_time else None,
            "deadline": self.deadline.isoformat() if self.deadline else None,
        }


class ApprovalDelegation(Base):
    """
    审批委托表
    
    用户可以将自己的审批权限临时委托给他人
    """
    __tablename__ = "approval_delegations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    delegator_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)  # 委托人
    delegate_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)  # 被委托人
    
    # 委托配置
    flow_ids = Column(Text)  # 适用的审批流程 ID 列表 (JSON 数组), 空表示全部
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=False)
    
    # 委托说明
    reason = Column(String(512))
    
    # 状态
    is_active = Column(Boolean, default=True, index=True)
    
    # 审计字段
    created_at = Column(DateTime(timezone=True), server_default=sql_func.now())
    created_by = Column(Integer, ForeignKey("users.id"))
    
    # 关联关系
    delegator = relationship("User", foreign_keys=[delegator_id])
    delegate = relationship("User", foreign_keys=[delegate_id])
    
    def to_dict(self) -> dict:
        """转换为字典"""
        import json
        return {
            "id": self.id,
            "delegator_id": self.delegator_id,
            "delegator_name": self.delegator.name if self.delegator else None,
            "delegate_id": self.delegate_id,
            "delegate_name": self.delegate.name if self.delegate else None,
            "flow_ids": json.loads(self.flow_ids) if self.flow_ids else [],
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "reason": self.reason,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
