"""Typed build state and retry checkpoints for one owned employee delivery."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

Payload = dict[str, Any]
EMPLOYEE_STEPS = (
    "spec",
    "employee_plan",
    "generate",
    "validate",
    "script_workflow",
    "embed_script",
    "workflow",
    "register_pack",
    "workflow_sandbox",
    "mod_sandbox",
    "standalone_smoke",
    "host_check",
    "six_dim_gate",
    "complete",
)


@dataclass
class EmployeeBuildState:
    session_id: str
    user_id: int
    payload: Payload
    brief: str
    provider: str | None
    model: str | None
    replace: bool
    target: str
    embed_script_workflow: bool
    workflow_name: str | None
    fhd_base: str | None
    employee_files: list[Payload]
    routing_brief: str
    pipeline_label: str
    needs_llm_reasoning: bool
    uploaded_docx: bool
    use_assets: bool
    use_word_extract: bool
    current_step: str = "employee_plan"
    resume_from: str | None = None
    employee_plan: Payload = field(default_factory=dict)
    employee_brief: str = ""
    script_brief: str = ""
    script_hint: str = ""
    workflow_brief: str = ""
    planned_script_name: str | None = None
    planned_workflow_name: str | None = None
    result: Payload = field(default_factory=dict)
    package_path: Path | None = None
    script_result: Payload = field(default_factory=dict)
    script_workflow: Payload | None = None
    script_attachment: Payload = field(default_factory=dict)
    workflow_attachment: Payload = field(default_factory=dict)
    saved_package: Payload = field(default_factory=dict)
    published_to_catalog: bool = False
    workflow_id: int | None = None
    workflow_sandbox: Payload = field(default_factory=dict)
    package_sandbox: Payload = field(default_factory=dict)
    host_probe: Payload = field(default_factory=lambda: {"skipped": True})
    workflow_business_ok: bool | None = None
    standalone_smoke_ok: bool = True
    registration_missing: bool = False
    six_dimension_report: Payload = field(default_factory=dict)
    quality_items: list[Payload] = field(default_factory=list)
    runnable: bool = False
    critical_failed: bool = False
    failed_critical: list[str] = field(default_factory=list)

    @property
    def pack_dir(self) -> Path:
        if self.package_path is None:
            raise ValueError("员工生成结果缺少包目录")
        return self.package_path

    @pack_dir.setter
    def pack_dir(self, value: Path) -> None:
        self.package_path = value

    def should_skip(self, step_id: str) -> bool:
        return bool(
            self.resume_from in EMPLOYEE_STEPS
            and step_id in EMPLOYEE_STEPS
            and (EMPLOYEE_STEPS.index(step_id) < EMPLOYEE_STEPS.index(self.resume_from))
        )

    def restore(self, checkpoint: Payload) -> None:
        """Reuse package construction; rerun registration and all execution evidence."""
        result, path = (checkpoint.get("res"), checkpoint.get("pack_dir"))
        if not isinstance(result, dict) or not result or (not path):
            return
        self.result = result
        self.package_path = Path(str(path))
        self.employee_plan = checkpoint.get("employee_plan") or {}
        self.script_workflow = checkpoint.get("script_wf")
        self.script_attachment = checkpoint.get("script_attachment") or {}
        self.workflow_attachment = checkpoint.get("wf_attach") or {}
        self.saved_package = checkpoint.get("saved_package") or {}
        self.published_to_catalog = bool(checkpoint.get("published_to_catalog", False))
        self.target = checkpoint.get("employee_target") or self.target
        self.embed_script_workflow = bool(
            checkpoint.get("embed_script_workflow", self.embed_script_workflow)
        )
        self.workflow_name = checkpoint.get("wf_name") or self.workflow_name
        self.fhd_base = checkpoint.get("fhd_base") or self.fhd_base
        self.resume_from = checkpoint.get("failed_step") or "embed_script"
        if self.resume_from in EMPLOYEE_STEPS and EMPLOYEE_STEPS.index(
            self.resume_from
        ) > EMPLOYEE_STEPS.index("register_pack"):
            self.resume_from = "register_pack"

    def checkpoint(self) -> Payload:
        return {
            "failed_step": self.current_step,
            "res": self.result if self.result.get("ok") else None,
            "pack_dir": str(self.package_path) if self.package_path else None,
            "employee_plan": self.employee_plan,
            "script_wf": self.script_workflow,
            "script_attachment": self.script_attachment,
            "wf_attach": self.workflow_attachment,
            "saved_package": self.saved_package,
            "published_to_catalog": self.published_to_catalog,
            "employee_target": self.target,
            "embed_script_workflow": self.embed_script_workflow,
            "wf_name": self.workflow_name,
            "fhd_base": self.fhd_base,
        }
