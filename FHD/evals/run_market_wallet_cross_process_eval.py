from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
FHD_ROOT = REPO_ROOT / "FHD"
MARKET_ROOT = REPO_ROOT / "成都修茈科技有限公司" / "MODstore_deploy"
XIUCI_COMMON_ROOT = REPO_ROOT / "成都修茈科技有限公司" / "packages" / "xcagi_common"

if str(FHD_ROOT) not in sys.path:
    sys.path.insert(0, str(FHD_ROOT))


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _market_env(db_path: Path, jwt_secret: str) -> dict[str, str]:
    pythonpath = os.pathsep.join(
        [
            str(MARKET_ROOT),
            str(XIUCI_COMMON_ROOT),
            os.environ.get("PYTHONPATH", ""),
        ]
    )
    env = dict(os.environ)
    env.update(
        {
            "PYTHONPATH": pythonpath,
            "MODSTORE_DB_PATH": str(db_path),
            "MODSTORE_JWT_SECRET": jwt_secret,
            "MODSTORE_DISABLE_CSRF": "1",
            "MODSTORE_RUN_BACKGROUND_JOBS": "0",
            "MODSTORE_PYTEST_USE_SQLITE": "1",
            "MODSTORE_TEST_ENV_QUIET": "1",
            "PAYMENT_BACKEND": "python",
        }
    )
    env.pop("DATABASE_URL", None)
    return env


def _run_market_setup(env: dict[str, str]) -> dict[str, Any]:
    code = r"""
import json
from decimal import Decimal

from modstore_server.auth_service import create_access_token, register_user
from modstore_server.models import Wallet, get_session_factory, init_db

init_db()
user = register_user(
    "cross_process_ai_wallet_user",
    "pytest-pass-12",
    "cross-process-ai-wallet@pytest.local",
)
sf = get_session_factory()
with sf() as session:
    wallet = session.query(Wallet).filter(Wallet.user_id == user.id).first()
    if wallet is None:
        wallet = Wallet(user_id=user.id, balance=Decimal("0.00"))
        session.add(wallet)
        session.flush()
    wallet.balance = Decimal("10.00")
    session.commit()

token = create_access_token(user.id, user.username)
print(json.dumps({"user_id": user.id, "username": user.username, "token": token}))
"""
    python = shutil.which("python3") or sys.executable
    proc = subprocess.run(
        [python, "-c", code],
        cwd=str(MARKET_ROOT),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"market setup failed\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _start_market_server(env: dict[str, str], port: int) -> subprocess.Popen[str]:
    python = shutil.which("python3") or sys.executable
    return subprocess.Popen(
        [
            python,
            "-m",
            "uvicorn",
            "modstore_server.api.app_factory:create_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=str(MARKET_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _wait_for_market(base_url: str, proc: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 20
    last_error = ""
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            output = proc.stdout.read() if proc.stdout else ""
            raise RuntimeError(f"market server exited early code={proc.returncode}\n{output}")
        try:
            response = httpx.get(f"{base_url}/openapi.json", timeout=1.0)
            if response.status_code == 200:
                return
            last_error = f"HTTP {response.status_code}"
        except httpx.HTTPError as exc:
            last_error = str(exc)
        time.sleep(0.2)
    output = proc.stdout.read() if proc.stdout else ""
    raise RuntimeError(f"market server did not become ready: {last_error}\n{output}")


def _terminate(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def _event_types(run: Any) -> list[str]:
    return [str(event.event_type) for event in run.events]


def run_cross_process_eval() -> dict[str, Any]:
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
    from app.application.workflow.types import PlanGraph, WorkflowNode

    with tempfile.TemporaryDirectory(prefix="xcmax_market_wallet_cross_process_") as tmp:
        tmp_path = Path(tmp)
        db_path = tmp_path / "market.sqlite"
        ledger_path = tmp_path / "fhd_model_usage.json"
        jwt_secret = "cross-process-market-wallet-secret-32"
        market_env = _market_env(db_path, jwt_secret)
        user = _run_market_setup(market_env)
        port = _free_port()
        base_url = f"http://127.0.0.1:{port}"
        proc = _start_market_server(market_env, port)
        try:
            _wait_for_market(base_url, proc)
            plan = PlanGraph(
                plan_id="cross-process-market-wallet-refund",
                intent="business_db_read",
                nodes=[
                    WorkflowNode(
                        node_id="read_products",
                        tool_id="business_db",
                        action="read",
                        params={"entity": "products", "keyword": "5003"},
                        risk="low",
                        idempotent=True,
                    )
                ],
            )
            env_patch = {
                "MODEL_USAGE_LEDGER_PATH": str(ledger_path),
                "MODEL_USAGE_WALLET_BACKEND": "market",
                "MODEL_USAGE_MARKET_BASE_URL": base_url,
                "MODEL_USAGE_MARKET_AUTH_TOKEN": str(user["token"]),
                "MODEL_USAGE_MARKET_YUAN_PER_COST_UNIT": "0.02",
                "MODEL_USAGE_MARKET_MIN_CHARGE": "0.02",
            }
            with ExitStack() as stack:
                stack.enter_context(patch.dict(os.environ, env_patch, clear=False))
                stack.enter_context(
                    patch(
                        "app.application.facades.tools_facade.execute_registered_workflow_tool",
                        return_value={"success": False, "message": "temporary database error"},
                    )
                )
                run = AgentOrchestrator(repository=InMemoryAgentRunRepository()).start_run_from_plan(
                    user_id=str(user["user_id"]),
                    message="cross process market wallet refund",
                    plan=plan,
                    runtime_context={"source": "cross_process_market_wallet_eval"},
                )

            headers = {"Authorization": f"Bearer {user['token']}"}
            transactions_response = httpx.get(
                f"{base_url}/api/wallet/transactions",
                headers=headers,
                timeout=5.0,
            )
            overview_response = httpx.get(
                f"{base_url}/api/wallet/overview",
                headers=headers,
                timeout=5.0,
            )
            transactions_response.raise_for_status()
            overview_response.raise_for_status()
            transactions = transactions_response.json().get("transactions") or []
            overview = overview_response.json()
            txn_types = [str(item.get("type") or "") for item in transactions]
            wallet_refund = run.tool_calls[0].metadata.get("wallet_refund", {})
            checks = {
                "run_failed_after_tool_error": run.status == "failed"
                and run.error == "temporary database error",
                "billing_debited_event": "billing.debited" in _event_types(run),
                "billing_refunded_event": "billing.refunded" in _event_types(run),
                "market_refund_status": wallet_refund.get("status") == "refunded",
                "market_refund_amount": wallet_refund.get("amount_yuan") == "0.02",
                "market_balance_restored": run.metadata.get("model_wallet_balance_yuan") == "10.00",
                "market_transactions": all(
                    txn_type in txn_types
                    for txn_type in ("ai_preauth", "ai_settle", "ai_refund")
                ),
                "wallet_overview_balance": str(
                    (overview.get("wallet") or {}).get("balance") or overview.get("balance") or ""
                )
                in {"10.0", "10.00", "10"},
            }
            return {
                "suite": "market_wallet_cross_process",
                "passed": all(checks.values()),
                "base_url": base_url,
                "user_id": user["user_id"],
                "run_id": run.run_id,
                "run_status": run.status,
                "checks": checks,
                "events": _event_types(run),
                "wallet_refund": wallet_refund,
                "market_transaction_types": txn_types,
                "wallet_overview": overview.get("wallet") or overview,
            }
        finally:
            _terminate(proc)


def main() -> int:
    result = run_cross_process_eval()
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
