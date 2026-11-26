"""Safe chat-visible setup failures shared by legacy and Xiaox runtime migrations."""

from __future__ import annotations

from typing import Any


def public_runtime_failure(error: Exception) -> dict[str, Any]:
    """Publish a stable error code, not a private model/token/host exception."""
    from app.application.agent_runtime import configuration

    # No unknown exception is exposed by this helper.
    if not isinstance(error, configuration.RuntimePolicyError):
        raise TypeError("runtime policy error required")
    messages = {
        **configuration._QUALIFICATION_ERRORS,
        "runtime_not_qualified": "运行配置尚未通过核验，请检查模型设置或联系部署管理员。",
        "runtime_configuration_required": "请核对模型设置",
        "runtime_login_required": "当前账号登录已失效，请重新登录后继续原任务。",
        "runtime_account_model_required": "请在模型设置中选择当前账号可用的平台模型或自带密钥模型。",
        "runtime_storage_invalid": "运行验收状态无法读取，请检查本机数据目录权限。",
        "runtime_qualification_in_progress": "当前模型正在完成运行验收，请稍后继续。",
        "runtime_changed": "原任务的模型配置已变化，请恢复原路由后继续；任务和回执已保留。",
        "runtime_platform_unavailable": "平台模型配置暂时无法读取，请检查网络后重试。",
        "runtime_host_unverified": "本机版本身份无法核验，请检查安装包或部署版本记录。",
    }
    error_code = getattr(error, "code", None)
    code = (
        error_code if isinstance(error_code, str) and error_code in messages else "runtime_not_qualified"
    )
    checks = getattr(error, "checks", {})
    return {
        "error_code": code,
        "message": messages[code],
        "checks": {
            name: checks[name]
            for name in configuration.QUALIFICATION_CHECKS
            if isinstance(checks, dict) and checks.get(name) in ("PASS", "FAIL")
        },
    }
