# -*- coding: utf-8 -*-
"""
审批流功能使用示例

演示如何使用审批流系统
"""

import json
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models.approval import ApprovalFlow, ApprovalFlowNode, ApprovalRequest
from app.services.approval_service import get_approval_service
from app.db.session import get_db


def example_create_approval_flow():
    """示例 1: 创建审批流程"""
    print("=" * 60)
    print("示例 1: 创建价格审批流程")
    print("=" * 60)
    
    # 使用数据库会话
    with get_db() as db:
        service = get_approval_service(db)
        
        # 定义流程基本信息
        flow_data = {
            "flow_key": "price_approval",
            "flow_name": "价格审批流程",
            "description": "用于产品价格调整和折扣审批",
            "industry": "通用",
            "node_type": "serial",  # 串行审批
            "allow_transfer": True,
            "allow_delegate": False,
            "allow_withdraw": True,
            "timeout_hours": 48,
            "created_by": 1  # 管理员 ID
        }
        
        # 定义审批节点
        nodes = [
            {
                "node_name": "部门经理审批",
                "node_order": 1,
                "node_type": "serial",
                "approver_type": "user",
                "approver_ids": [2, 3],  # 部门经理 ID 列表
                "min_approvals": 1,
                "condition_description": "折扣率 < 20%",
                "timeout_hours": 24,
                "timeout_action": "notify"
            },
            {
                "node_name": "财务经理审批",
                "node_order": 2,
                "node_type": "serial",
                "approver_type": "user",
                "approver_ids": [4],  # 财务经理 ID
                "min_approvals": 1,
                "condition_description": "折扣率 >= 20%",
                "timeout_hours": 24,
                "timeout_action": "notify"
            },
            {
                "node_name": "总经理审批",
                "node_order": 3,
                "node_type": "serial",
                "approver_type": "user",
                "approver_ids": [1],  # 总经理 ID
                "min_approvals": 1,
                "condition_description": "折扣率 >= 50%",
                "timeout_hours": 48,
                "timeout_action": "notify"
            }
        ]
        
        # 创建流程
        flow = service.create_flow(flow_data, nodes)
        
        print(f"✅ 流程创建成功!")
        print(f"   流程 ID: {flow.id}")
        print(f"   流程标识：{flow.flow_key}")
        print(f"   流程名称：{flow.flow_name}")
        print(f"   节点数量：{len(flow.nodes)}")
        
        # 打印节点信息
        for node in flow.nodes:
            print(f"   - 节点 {node.node_order}: {node.node_name}")
        
        return flow.id


def example_create_approval_request(flow_id: int):
    """示例 2: 创建审批请求"""
    print("\n" + "=" * 60)
    print("示例 2: 创建价格调整审批请求")
    print("=" * 60)
    
    with get_db() as db:
        service = get_approval_service(db)
        
        # 获取流程
        flow = db.query(ApprovalFlow).filter(ApprovalFlow.id == flow_id).first()
        
        # 业务数据 (价格调整)
        business_data = {
            "product_id": 1001,
            "product_name": "产品 A",
            "original_price": 100.00,
            "new_price": 85.00,
            "discount_rate": 15,  # 85 折
            "reason": "促销活动",
            "effective_date": "2026-04-15",
            "end_date": "2026-05-15"
        }
        
        # 创建审批请求
        request = service.create_request(
            flow_key=flow.flow_key,
            business_type="price",
            business_id=business_data["product_id"],
            business_data=business_data,
            applicant_id=100,  # 申请人 ID
            title="产品 A 价格调整申请 - 85 折促销",
            description="因五一促销活动，申请产品 A 价格调整为 85 折",
            priority="normal"
        )
        
        print(f"✅ 审批请求创建成功!")
        print(f"   审批单号：{request.request_no}")
        print(f"   当前节点：{request.current_node_order}")
        print(f"   状态：{request.status}")
        print(f"   申请人：{request.applicant_name}")
        
        return request.id


def example_approve_request(request_id: int):
    """示例 3: 审批通过"""
    print("\n" + "=" * 60)
    print("示例 3: 部门经理审批通过")
    print("=" * 60)
    
    with get_db() as db:
        service = get_approval_service(db)
        
        # 部门经理审批通过
        request = service.approve(
            request_id=request_id,
            approver_id=2,  # 部门经理 ID
            opinion="同意，请财务部审核",
            transfer_to=None
        )
        
        print(f"✅ 审批通过!")
        print(f"   审批单号：{request.request_no}")
        print(f"   当前节点：{request.current_node_order}")
        print(f"   状态：{request.status}")
        
        if request.status == "approved":
            print(f"   🎉 审批已完成!")
        else:
            print(f"   ⏳ 等待下一节点审批...")
        
        return request


def example_reject_request(request_id: int):
    """示例 4: 审批拒绝"""
    print("\n" + "=" * 60)
    print("示例 4: 财务经理审批拒绝")
    print("=" * 60)
    
    with get_db() as db:
        service = get_approval_service(db)
        
        # 财务经理拒绝
        request = service.reject(
            request_id=request_id,
            approver_id=4,  # 财务经理 ID
            reason="折扣率过低，建议调整为 9 折"
        )
        
        print(f"❌ 审批拒绝!")
        print(f"   审批单号：{request.request_no}")
        print(f"   状态：{request.status}")
        print(f"   拒绝原因：{request.rejection_reason}")


def example_withdraw_request(request_id: int):
    """示例 5: 撤回审批请求"""
    print("\n" + "=" * 60)
    print("示例 5: 申请人撤回审批")
    print("=" * 60)
    
    with get_db() as db:
        service = get_approval_service(db)
        
        # 申请人撤回
        request = service.withdraw(
            request_id=request_id,
            applicant_id=100  # 申请人 ID
        )
        
        print(f"↩️ 审批已撤回!")
        print(f"   审批单号：{request.request_no}")
        print(f"   状态：{request.status}")


def example_create_delegation():
    """示例 6: 创建审批委托"""
    print("\n" + "=" * 60)
    print("示例 6: 创建审批委托 (经理出差委托)")
    print("=" * 60)
    
    with get_db() as db:
        service = get_approval_service(db)
        
        # 创建委托 (经理委托给副经理)
        delegation = service.create_delegation(
            delegator_id=2,  # 经理 ID
            delegate_id=5,   # 副经理 ID
            flow_ids=[1],    # 委托的流程 ID 列表
            start_time=datetime.now(),
            end_time=datetime.now() + timedelta(days=7),  # 委托 7 天
            reason="经理出差，委托副经理代为审批"
        )
        
        print(f"✅ 审批委托创建成功!")
        print(f"   委托 ID: {delegation.id}")
        print(f"   委托人：用户 {delegation.delegator_id}")
        print(f"   被委托人：用户 {delegation.delegate_id}")
        print(f"   委托时间：{delegation.start_time} 至 {delegation.end_time}")
        print(f"   委托原因：{delegation.reason}")


def example_list_requests():
    """示例 7: 查询审批请求列表"""
    print("\n" + "=" * 60)
    print("示例 7: 查询我的审批请求")
    print("=" * 60)
    
    with get_db() as db:
        service = get_approval_service(db)
        
        # 查询我的申请
        requests, total = service.list_requests(
            applicant_id=100,
            page=1,
            page_size=10
        )
        
        print(f"我的申请 (共 {total} 条):")
        for req in requests:
            status_icon = {
                "pending": "⏳",
                "in_progress": "🔄",
                "approved": "✅",
                "rejected": "❌",
                "withdrawn": "↩️"
            }.get(req.status, "📄")
            
            print(f"   {status_icon} {req.request_no} - {req.title} ({req.status})")
        
        # 查询待我审批
        pending_requests, pending_total = service.list_requests(
            approver_id=2,
            status="pending",
            page=1,
            page_size=10
        )
        
        print(f"\n待我审批 (共 {pending_total} 条):")
        for req in pending_requests:
            print(f"   ⏰ {req.request_no} - {req.title}")


def run_all_examples():
    """运行所有示例"""
    print("\n" + "=" * 60)
    print("🚀 XCAGI 审批流功能示例")
    print("=" * 60 + "\n")
    
    try:
        # 示例 1: 创建审批流程
        flow_id = example_create_approval_flow()
        
        # 示例 2: 创建审批请求
        request_id = example_create_approval_request(flow_id)
        
        # 示例 3: 审批通过
        example_approve_request(request_id)
        
        # 示例 7: 查询列表
        example_list_requests()
        
        # 示例 6: 创建委托
        example_create_delegation()
        
        print("\n" + "=" * 60)
        print("✅ 所有示例运行完成!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ 示例运行失败：{e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    run_all_examples()
