"""
复式记账服务（Double-entry bookkeeping）

吸收 Odoo 18 account.move/account.move.line 能力：提供总账查询与记账凭证创建。
JD: 借方(debit)增加资产/费用，贷方(credit)增加负债/权益/收入；凭证必须借贷平衡。
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any, cast

from app.db.models import ChartOfAccount, JournalEntry, JournalEntryLine
from app.db.session import get_db
from app.services.accounting_values import (
    AGING_BUCKETS as _AGING_BUCKETS,
)
from app.services.accounting_values import (
    DEFAULT_CHART_OF_ACCOUNTS,
)
from app.services.accounting_values import (
    to_decimal as _to_decimal,
)
from app.services.accounting_values import (
    to_float as _to_float,
)

logger = logging.getLogger(__name__)


def query_financial_ledger(
    account_id: int | None = None,
    account_code: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    status: str | None = None,
    page: int = 1,
    per_page: int = 20,
) -> dict[str, Any]:
    """查询总账：聚合各科目借贷发生额与余额。

    - 有 account 过滤时返回该科目的逐笔分录；
    - 无 account 过滤时按科目 code 汇总借贷发生额。
    """
    with get_db() as db:
        q = db.query(JournalEntry)
        if status:
            q = q.filter(JournalEntry.status == status)
        if start_date:
            q = q.filter(JournalEntry.journal_date >= start_date)
        if end_date:
            q = q.filter(JournalEntry.journal_date <= end_date)
        q = q.order_by(JournalEntry.journal_date.desc(), JournalEntry.id.desc())
        total = q.count()
        entries = q.offset((page - 1) * per_page).limit(per_page).all()

        if account_id is not None or account_code:
            account = (
                db.query(ChartOfAccount)
                .filter(
                    ChartOfAccount.id == account_id
                    if account_id is not None
                    else ChartOfAccount.code == account_code
                )
                .first()
            )
            if account is None:
                return {"success": False, "message": "科目不存在", "data": []}
            lines = []
            for entry in entries:
                for line in entry.lines:
                    if account_id is not None and line.account_id != account_id:
                        continue
                    if account_code and line.account_code != account_code:
                        continue
                    lines.append(
                        {
                            "entry_id": entry.id,
                            "entry_no": entry.entry_no,
                            "journal_date": (
                                entry.journal_date.isoformat() if entry.journal_date else None
                            ),
                            "description": entry.description,
                            "account_code": line.account_code,
                            "account_name": line.account_name,
                            "debit": _to_float(line.debit),
                            "credit": _to_float(line.credit),
                            "partner_name": line.partner_name,
                            "reference": line.reference,
                        }
                    )
            return {
                "success": True,
                "data": lines,
                "total": len(lines),
                "page": page,
                "per_page": per_page,
                "account": account.to_dict(),
            }

        return {
            "success": True,
            "data": [e.to_dict() for e in entries],
            "total": total,
            "page": page,
            "per_page": per_page,
        }


def create_journal_entry(data: dict[str, Any], *, db: Any = None) -> dict[str, Any]:
    """创建复式记账凭证；借贷必须平衡，否则拒写。

    - ``db``：可选，调用方持有的 SQLAlchemy 会话。传入时在调用方事务内执笔，
      不提交（由调用方统一 commit/rollback）；缺省时自建会话并在退出时提交，
      保持旧调用方行为不变。
    - 金额内部一律用 ``Decimal``，不做 float 转换。
    """
    if db is None:
        with get_db() as session:
            return _create_journal_entry(data, session)
    return _create_journal_entry(data, db)


def _create_journal_entry(data: dict[str, Any], db: Any) -> dict[str, Any]:
    lines_data = data.get("lines") or []
    if not isinstance(lines_data, list) or not lines_data:
        return {"success": False, "message": "缺少 lines 分录行"}

    parsed_lines = []
    debit_total = Decimal("0")
    credit_total = Decimal("0")
    for item in lines_data:
        account_id = item.get("account_id")
        account = None
        if account_id:
            account = _find_account(db, account_id)
        elif item.get("account_code"):
            account = _find_account_by_code(db, item.get("account_code"))
        debit = _to_decimal(item.get("debit", 0))
        credit = _to_decimal(item.get("credit", 0))
        if debit == 0 and credit == 0:
            return {"success": False, "message": "分录行借贷不能同时为 0"}
        debit_total += debit
        credit_total += credit
        parsed_lines.append(
            {
                "account_id": account.id if account else None,
                "account_code": item.get("account_code") or (account.code if account else None),
                "account_name": item.get("account_name") or (account.name if account else None),
                "debit": debit,
                "credit": credit,
                "partner_id": item.get("partner_id"),
                "partner_name": item.get("partner_name"),
                "reference": item.get("reference"),
            }
        )

    if abs(debit_total - credit_total) > Decimal("0.01"):
        return {
            "success": False,
            "message": f"借贷不平衡: 借 {debit_total} vs 贷 {credit_total}",
        }

    entry_no = data.get("entry_no") or _generate_entry_no()
    entry = JournalEntry(
        entry_no=entry_no,
        journal_date=data.get("journal_date") or date.today(),
        status=data.get("status") or "posted",
        description=data.get("description"),
        reference_type=data.get("reference_type"),
        reference_id=data.get("reference_id"),
        debit_total=Decimal("0"),
        credit_total=Decimal("0"),
        reversed_of_id=data.get("reversed_of_id"),
        credit_note_of_id=data.get("credit_note_of_id"),
        is_credit_note=data.get("is_credit_note", 0),
        created_at=datetime.now(),
    )
    db.add(entry)
    for line in parsed_lines:
        entry.lines.append(
            JournalEntryLine(
                account_id=line["account_id"],
                account_code=line["account_code"],
                account_name=line["account_name"],
                debit=line["debit"],
                credit=line["credit"],
                partner_id=line["partner_id"],
                partner_name=line["partner_name"],
                reference=line["reference"],
                created_at=datetime.now(),
            )
        )
    db.flush()
    entry.refresh_totals()
    return {
        "success": True,
        "message": f"记账凭证已创建: {entry.entry_no}",
        "data": entry.to_dict(),
    }


def _find_account(db: Any, account_id: int) -> ChartOfAccount | None:
    return cast(
        "ChartOfAccount | None",
        db.query(ChartOfAccount).filter(ChartOfAccount.id == int(account_id)).first(),
    )


def _find_account_by_code(db: Any, code: str) -> ChartOfAccount | None:
    return cast(
        "ChartOfAccount | None",
        db.query(ChartOfAccount).filter(ChartOfAccount.code == str(code)).first(),
    )


def get_chart_of_accounts() -> dict[str, Any]:
    """返回启用中的科目表（供 Agent 选择借贷科目）。"""
    with get_db() as db:
        accounts = (
            db.query(ChartOfAccount)
            .filter(ChartOfAccount.is_active == 1)
            .order_by(ChartOfAccount.code)
            .all()
        )
        return {"success": True, "data": [a.to_dict() for a in accounts]}


def _generate_entry_no() -> str:
    # 含微秒前缀，避免同秒内多张凭证 entry_no 冲突（entry_no 唯一约束）
    return f"JE{datetime.now().strftime('%Y%m%d%H%M%S%f')}"


def seed_default_chart_of_accounts() -> dict[str, Any]:
    """幂等种入默认科目表；code 已存在则跳过。返回 success 与新增数量。"""
    created = 0
    with get_db() as db:
        for spec in DEFAULT_CHART_OF_ACCOUNTS:
            exists = db.query(ChartOfAccount).filter(ChartOfAccount.code == spec["code"]).first()
            if exists:
                continue
            db.add(ChartOfAccount(**spec))
            created += 1
        db.commit()
    return {
        "success": True,
        "message": f"默认科目已初始化，新增 {created} 个",
        "created": created,
    }


def journal_entry_reverse(entry_id: int, *, description: str | None = None) -> dict[str, Any]:
    """按指定凭证生成反向冲销分录。

    - 原凭证不存在 → 失败；已冲销（reversed_of_id 或 reversed_at 非空）→ 失败。
    - 新凭证借贷方向全部反转（借↔贷），金额不变，天然借贷平衡。
    - 原凭证标记 reversed_at=now 表示已冲销，新凭证 reversed_of_id=原凭证 id。
    """
    with get_db() as db:
        entry = db.query(JournalEntry).filter(JournalEntry.id == int(entry_id)).first()
        if entry is None:
            return {"success": False, "message": f"原凭证不存在: id={entry_id}"}
        if entry.reversed_of_id is not None or entry.reversed_at is not None:
            return {
                "success": False,
                "message": f"凭证 {entry.entry_no} 已冲销，不能重复冲销",
            }

        new_entry = JournalEntry(
            entry_no=_generate_entry_no(),
            journal_date=date.today(),
            status="posted",
            description=description or f"冲销: {entry.entry_no}",
            reference_type="reversal",
            reference_id=entry.id,
            reversed_of_id=entry.id,
            created_at=datetime.now(),
        )
        db.add(new_entry)
        db.flush()
        for line in entry.lines:
            db.add(
                JournalEntryLine(
                    entry_id=new_entry.id,
                    account_id=line.account_id,
                    account_code=line.account_code,
                    account_name=line.account_name,
                    debit=line.credit or 0,
                    credit=line.debit or 0,
                    partner_id=line.partner_id,
                    partner_name=line.partner_name,
                    reference=line.reference,
                    created_at=datetime.now(),
                )
            )
        new_entry.refresh_totals()
        entry.reversed_at = datetime.now()
        db.commit()
        db.refresh(new_entry)
        return {
            "success": True,
            "message": f"冲销凭证已生成: {new_entry.entry_no}",
            "data": new_entry.to_dict(),
        }


def aging_report(party_type: str, party_id: int, as_of_date: date | None = None) -> dict[str, Any]:
    """应收/应付账龄分析。

    - party_type: "receivable"(应收/客户) 或 "payable"(应付/供应商)。
    - 按该 partner 的分录行聚合未结余额到账期桶；账期 = as_of_date - journal_date。
    - receivable: 借↗应收、贷抵减；payable: 贷↗应付、借抵减。
    """
    if party_type not in ("receivable", "payable"):
        return {
            "success": False,
            "message": "party_type 必须为 receivable(应收) 或 payable(应付)",
        }
    as_of = as_of_date or date.today()
    bucket_amounts = {name: 0.0 for name, _, _ in _AGING_BUCKETS}
    with get_db() as db:
        rows = (
            db.query(JournalEntryLine)
            .join(JournalEntry, JournalEntryLine.entry_id == JournalEntry.id)
            .filter(JournalEntryLine.partner_id == int(party_id))
            .all()
        )
        for line in rows:
            entry = line.entry
            if entry is None or entry.journal_date is None:
                continue
            days = (as_of - entry.journal_date).days
            if days < 0:
                continue  # 未来账期忽略
            if party_type == "receivable":
                amount = _to_float(line.debit) - _to_float(line.credit)
            else:
                amount = _to_float(line.credit) - _to_float(line.debit)
            for name, lo, hi in _AGING_BUCKETS:
                if lo <= days <= hi:
                    bucket_amounts[name] += amount
                    break
    data = [
        {"bucket": name, "amount": round(bucket_amounts[name], 2)} for name, _, _ in _AGING_BUCKETS
    ]
    total = round(sum(bucket_amounts.values()), 2)
    return {
        "success": True,
        "party_type": party_type,
        "party_id": int(party_id),
        "as_of_date": as_of.isoformat(),
        "data": data,
        "total_outstanding": total,
    }


def create_sale_invoice_entry(
    order_id: int,
    *,
    partner_id: int | None = None,
    partner_name: str | None = None,
    amount: float | Decimal = 0.0,
    journal_date: date | None = None,
    description: str | None = None,
    db: Any = None,
) -> dict[str, Any]:
    """生成销售开票平衡凭证：借应收账款(1122, partner) / 贷主营业务收入(6001)。

    - ``reference_type='sale'``、``reference_id=order_id``。
    - 复用通用平衡记账 API ``create_journal_entry``，借贷平衡由该 API 强制。
    - ``db``：可选，调用方事务内执笔（同 ``create_journal_entry``）。
    """
    return create_journal_entry(
        {
            "journal_date": journal_date or date.today(),
            "status": "posted",
            "description": description or f"销售开票-订单{order_id}",
            "reference_type": "sale",
            "reference_id": order_id,
            "lines": [
                {
                    "account_code": "1122",
                    "partner_id": partner_id,
                    "partner_name": partner_name,
                    "debit": amount,
                    "credit": 0,
                },
                {
                    "account_code": "6001",
                    "debit": 0,
                    "credit": amount,
                },
            ],
        },
        db=db,
    )


def create_credit_note_entry(
    original_entry_id: int,
    *,
    order_id: int | None = None,
    journal_date: date | None = None,
    description: str | None = None,
    db: Any = None,
) -> dict[str, Any]:
    """按原销售凭证生成贷项通知单反向凭证，经 ``reversed_of_id`` 关联原凭证。

    - 借贷方向全部反转（借↔贷），金额不变，天然借贷平衡。
    - 复用通用平衡记账 API ``create_journal_entry``；原凭证不存在或已冲销则拒写。
    - 在**同一事务**内创建反向凭证并标记原凭证 ``reversed_at``：传入 ``db`` 时
      随调用方统一提交/回滚（原子）；缺省时自建会话并在退出时提交，保持旧行为。
    """
    if db is None:
        with get_db() as session:
            return _create_credit_note_entry(
                original_entry_id,
                session,
                order_id=order_id,
                journal_date=journal_date,
                description=description,
            )
    return _create_credit_note_entry(
        original_entry_id,
        db,
        order_id=order_id,
        journal_date=journal_date,
        description=description,
    )


def _create_credit_note_entry(
    original_entry_id: int,
    db: Any,
    *,
    order_id: int | None = None,
    journal_date: date | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    original = db.query(JournalEntry).filter(JournalEntry.id == int(original_entry_id)).first()
    if original is None:
        return {"success": False, "message": f"原销售凭证不存在: id={original_entry_id}"}
    if original.reversed_of_id is not None or original.reversed_at is not None:
        return {
            "success": False,
            "message": f"凭证 {original.entry_no} 已冲销，不能重复生成贷项通知单",
        }
    reversed_lines = []
    for line in original.lines:
        reversed_lines.append(
            {
                "account_id": line.account_id,
                "account_code": line.account_code,
                "account_name": line.account_name,
                "partner_id": line.partner_id,
                "partner_name": line.partner_name,
                "reference": line.reference,
                "debit": line.credit or Decimal("0"),
                "credit": line.debit or Decimal("0"),
            }
        )

    result = create_journal_entry(
        {
            "journal_date": journal_date or date.today(),
            "status": "posted",
            "description": description or f"贷项通知单-冲销{original.entry_no}",
            "reference_type": "credit-note",
            "reference_id": order_id if order_id is not None else original.reference_id,
            "reversed_of_id": original.id,
            "is_credit_note": 1,
            "lines": reversed_lines,
        },
        db=db,
    )
    if result["success"]:
        original.reversed_at = datetime.now()
    return result


__all__ = [
    "create_journal_entry",
    "get_chart_of_accounts",
    "query_financial_ledger",
    "seed_default_chart_of_accounts",
    "journal_entry_reverse",
    "aging_report",
    "create_sale_invoice_entry",
    "create_credit_note_entry",
]
