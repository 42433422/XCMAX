"""Versioned, server-owned course catalog for real business practice."""

from __future__ import annotations

from typing import Any

COURSE_VERSION = 2


def _step(
    step_id: str,
    title: str,
    *,
    goal: str,
    instruction: str,
    success: str,
    why: str,
    hint: str,
    route_name: str,
    target_selector: str,
    verifier: str,
) -> dict[str, Any]:
    return {
        "id": step_id,
        "title": title,
        "goal": goal,
        "instruction": instruction,
        "success_criteria": success,
        "why": why,
        "hint": hint,
        "route_name": route_name,
        "target_selector": target_selector,
        "verifier": verifier,
        "required": True,
    }


COURSES: tuple[dict[str, Any], ...] = (
    {
        "id": "task-workspace",
        "title": "智能对话与任务工作区",
        "summary": "亲手执行只读查询，并在独立任务工作区核验状态与证据。",
        "estimated_minutes": 8,
        "prerequisite_ids": [],
        "version": COURSE_VERSION,
        "steps": [
            _step(
                "submit-readonly-query",
                "提交只读业务查询",
                goal="让小C产生一项真实、可追踪的只读任务。",
                instruction="在智能对话中查询 A 产品的库存，不要创建或修改业务数据。",
                success="教学空间内出现属于你的已完成只读任务。",
                why="任务工作区展示的是后端持久任务，不是临时聊天动画。",
                hint="可以输入：查询 A 产品当前库存。",
                route_name="chat",
                target_selector="#chatInput, textarea[data-testid='chat-input']",
                verifier="completed_readonly_task",
            ),
            _step(
                "inspect-task-evidence",
                "查看任务结果证据",
                goal="认识任务状态、进度、运行次数、未读与结果证据。",
                instruction="打开刚才的任务工作区并查看结果证据，然后返回验证。",
                success="提交的任务 ID 属于你、已完成且存在执行记录。",
                why="业务结果必须可以从任务追到执行证据。",
                hint="点击顶部任务入口，打开刚完成的任务。",
                route_name="chat",
                target_selector="[data-testid='global-task-center'], .global-task-center",
                verifier="task_evidence_viewed",
            ),
        ],
    },
    {
        "id": "master-data",
        "title": "客户与产品建档",
        "summary": "亲手建立销售闭环所需的精确客户和产品主数据。",
        "estimated_minutes": 10,
        "prerequisite_ids": [],
        "version": COURSE_VERSION,
        "steps": [
            _step(
                "create-customer",
                "创建客户B",
                goal="在教学空间建立唯一客户。",
                instruction="进入客户管理，新建名称精确为“客户B”的客户。",
                success="客户B 恰好一条。",
                why="精确且唯一的客户主数据是后续自动执行可判定的前提。",
                hint="不要添加空格，也不要写成客户 B。",
                route_name="customers",
                target_selector="[data-tutorial-id='customer-create'], button",
                verifier="exact_customer",
            ),
            _step(
                "create-product",
                "创建 A 产品",
                goal="建立可销售、可扣减库存的产品。",
                instruction="进入产品管理，创建名称“A 产品”、价格 100、库存 100 的产品。",
                success="A 产品恰好一条，价格为 100，库存为 100。",
                why="销售闭环会以这些精确字段做后端核验。",
                hint="产品名中的空格必须保留。",
                route_name="products",
                target_selector="[data-tutorial-id='product-create'], button",
                verifier="exact_product",
            ),
        ],
    },
    {
        "id": "sales-to-cash",
        "title": "销售到收款完整闭环",
        "summary": "从自然语言销售指令走到审批、订单、库存、开票、收款和凭证。",
        "estimated_minutes": 15,
        "prerequisite_ids": ["master-data"],
        "version": COURSE_VERSION,
        "steps": [
            _step(
                "submit-sales-sentence",
                "提交并确认销售任务",
                goal="生成一项真实待审批的销售闭环任务。",
                instruction="发送精确句子：把 A 产品卖给客户B，10 个，单价 100，开票收款；随后确认任务。",
                success="教学空间中出现与该句子关联的待审批申请，且尚未产生销售业务行。",
                why="高风险写操作必须先停在审批边界。",
                hint="不要改写产品名、客户名、数量或单价。",
                route_name="chat",
                target_selector="#chatInput, textarea[data-testid='chat-input']",
                verifier="sales_waiting_approval",
            ),
            _step(
                "approve-sales-request",
                "批准并核验销售闭环",
                goal="在审批工作台批准真实申请并验证完整业务结果。",
                instruction="打开审批工作台和审批详情，批准刚才的申请。",
                success="一单一明细；库存 100→90；订单已开票且已收款；收款核销存在；凭证借贷平衡。",
                why="只有持久业务副作用全部一致，销售任务才算完成。",
                hint="如果列表中有多条申请，请按任务句子和申请单号核对。",
                route_name="approval-workspace",
                target_selector="[data-testid='approval-workspace'], .approval-workspace",
                verifier="sales_closed_loop",
            ),
        ],
    },
    {
        "id": "data-import",
        "title": "业务文件导入",
        "summary": "使用内置教学 Excel 完成映射、预览、确认写入和结果核验。",
        "estimated_minutes": 12,
        "prerequisite_ids": [],
        "version": COURSE_VERSION,
        "steps": [
            _step(
                "import-preview",
                "上传并核对预览",
                goal="理解上传、目标选择、字段映射和预览边界。",
                instruction="在数据对接中心选择内置教学 Excel，完成目标和字段映射并生成预览。",
                success="存在属于你的 preview_ready 教学导入任务和逐行预览。",
                why="预览先于写入，可在错误进入业务库前发现问题。",
                hint="先检查成功行、错误行和实体匹配结果，再确认。",
                route_name="business-docking",
                target_selector="[data-testid='etl-upload'], input[type='file']",
                verifier="etl_preview",
            ),
            _step(
                "import-execute",
                "确认写入并查看结果",
                goal="执行经过核对的导入草稿。",
                instruction="确认写入，并打开导入记录查看成功行和错误行结果。",
                success="导入任务完成、成功行大于零、逐行结果和实体引用均已持久化。",
                why="导入任务、逐行证据和业务实体必须可以相互追踪。",
                hint="验证失败时先查看错误行，不要重复上传同一文件。",
                route_name="business-docking",
                target_selector="[data-testid='etl-confirm'], button",
                verifier="etl_completed",
            ),
        ],
    },
    {
        "id": "evidence-trace",
        "title": "结果核验与业务追踪",
        "summary": "沿任务、审批和财务业务对象追踪同一教学闭环。",
        "estimated_minutes": 12,
        "prerequisite_ids": ["task-workspace", "sales-to-cash", "data-import"],
        "version": COURSE_VERSION,
        "steps": [
            _step(
                "trace-task",
                "查看任务证据",
                goal="从任务定位执行结果。",
                instruction="打开销售任务的结果证据。",
                success="任务证据与教学空间的销售闭环关联。",
                why="任务是跨业务对象的入口。",
                hint="记录任务 ID 后验证。",
                route_name="chat",
                target_selector="[data-testid='global-task-center'], .global-task-center",
                verifier="trace_task",
            ),
            _step(
                "trace-approval",
                "查看审批详情",
                goal="从任务追到审批申请。",
                instruction="打开已批准的销售审批详情。",
                success="审批申请属于同一教学租户并已批准。",
                why="审批证据解释了写操作为何获准。",
                hint="按申请单号核对。",
                route_name="approval-workspace",
                target_selector="[data-testid='approval-detail'], .approval-detail",
                verifier="trace_approval",
            ),
            _step(
                "trace-order",
                "查看订单与库存",
                goal="核对销售订单、明细和库存扣减。",
                instruction="依次打开订单详情和库存中的 A 产品。",
                success="订单与 A 产品一致，数量 10，库存为 90。",
                why="订单与库存是同一履约事实的两个视角。",
                hint="核对客户B、A 产品和数量 10。",
                route_name="inventory",
                target_selector="[data-testid='inventory-table'], table",
                verifier="trace_order_inventory",
            ),
            _step(
                "trace-finance",
                "查看发票、收款和凭证",
                goal="核对销售闭环的财务证据。",
                instruction="打开发票、收款核销和记账凭证。",
                success="订单已收款、核销金额 1000，相关凭证全部借贷平衡。",
                why="财务结果必须与订单金额交叉一致。",
                hint="核对金额 1000 和订单引用。",
                route_name="kitten-finance",
                target_selector="[data-testid='finance-ledger'], .finance-ledger",
                verifier="trace_finance",
            ),
            _step(
                "trace-import",
                "查看导入记录",
                goal="核对文件、逐行结果和业务实体关联。",
                instruction="返回数据对接中心并打开已完成的导入记录。",
                success="导入记录属于同一教学代次，且包含成功行和可审计结果。",
                why="文件导入也必须拥有与在线操作同等级的结果证据。",
                hint="打开最近一次 completed 记录。",
                route_name="business-docking",
                target_selector="[data-testid='etl-history'], .etl-history",
                verifier="trace_import",
            ),
        ],
    },
)

COURSE_BY_ID = {str(course["id"]): course for course in COURSES}


def public_course(course: dict[str, Any]) -> dict[str, Any]:
    """Strip server-only verifier keys before returning the public DTO."""
    result = {key: value for key, value in course.items() if key != "steps"}
    result["steps"] = [
        {key: value for key, value in step.items() if key != "verifier"} for step in course["steps"]
    ]
    return result


__all__ = ["COURSE_BY_ID", "COURSES", "COURSE_VERSION", "public_course"]
