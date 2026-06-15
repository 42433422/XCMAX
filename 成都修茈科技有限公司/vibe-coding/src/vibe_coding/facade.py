"""VibeCoder for the standalone (code-layer only) build.

Differences from the upstream ``eskill.vibe_coding.facade.VibeCoder``:

- Drops the config-layer (``ESkill`` / ``ESkillRuntime`` / ``JsonSkillStore``)
  pieces because the standalone tree does not vendor those modules.
- ``code()`` / ``run()`` / ``execute()`` / ``history()`` / ``rollback()`` /
  ``report()`` work identically.
- ``config_skill()`` raises ``NotImplementedError``; install the upstream
  ``eskill`` package if you need it, or extend this facade.
- ``index_project()`` / ``edit_project()`` / ``apply_patch()`` /
  ``heal_project()`` are added in P0 of the agent upgrade and lazy-load the
  :mod:`vibe_coding.agent` subpackage so legacy imports stay free of the
  agent code.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from ._internals import CodeSkill, CodeSkillRun
from .audit import PatchLedger, PatchRecord
from .code_factory import GenerationMode, NLCodeSkillFactory
from .nl.llm import LLMClient
from .runtime import (
    CodeSkillRuntime,
    JsonCodeSkillStore,
    OpenAICodePatchGenerator,
    RuleBasedCodePatchGenerator,
)
from .workflow_engine import VibeWorkflowEngine, WorkflowRunResult
from .workflow_factory import NLWorkflowFactory, WorkflowGenerationReport
from .workflow_models import VibeWorkflowGraph

if TYPE_CHECKING:
    from .agent.context import AgentContext
    from .agent.patch import ApplyResult, ProjectPatch
    from .agent.repo_index import RepoIndex
    from .agent.coder import HealResult, ProjectVibeCoder


class VibeCoder:
    """High-level facade for the standalone code-layer flow."""

    def __init__(
        self,
        *,
        llm: LLMClient,
        store_dir: str | Path = "./vibe_coding_data",
        llm_for_repair: bool = True,
        code_runtime: CodeSkillRuntime | None = None,
    ):
        self.llm = llm
        self.store_dir = Path(store_dir)
        self.store_dir.mkdir(parents=True, exist_ok=True)

        self.code_store = JsonCodeSkillStore(self.store_dir / "code_skill_store.json")
        self.code_factory = NLCodeSkillFactory(llm, self.code_store)
        self.workflow_factory = NLWorkflowFactory(llm, self.code_factory)

        self.code_runtime = code_runtime or CodeSkillRuntime(
            self.code_store,
            llm_generator=_build_code_patch_generator(llm) if llm_for_repair else None,
        )
        self.engine = VibeWorkflowEngine(code_runtime=self.code_runtime)
        self.ledger = PatchLedger(code_store=self.code_store)

    # ------------------------------------------------------------------ generation

    def code(
        self,
        brief: str,
        *,
        mode: GenerationMode = "brief_first",
        skill_id: str | None = None,
        dependencies: list[str] | None = None,
        project_root: str | Path | None = None,
    ) -> CodeSkill:
        return self.code_factory.generate(
            brief,
            mode=mode,
            skill_id=skill_id,
            dependencies=dependencies,
            project_root=project_root,
        )

    def config_skill(self, brief: str, *, skill_id: str | None = None) -> Any:
        raise NotImplementedError(
            "Standalone vibe_coding is code-layer only. Use the upstream eskill.vibe_coding "
            "package for config-layer (template_transform / employee_task / pipeline) skills."
        )

    def workflow(
        self,
        brief: str,
        *,
        project_root: str | Path | None = None,
    ) -> VibeWorkflowGraph:
        return self.workflow_factory.generate(brief, project_root=project_root)

    def workflow_with_report(
        self,
        brief: str,
        *,
        project_root: str | Path | None = None,
    ) -> WorkflowGenerationReport:
        return self.workflow_factory.generate_with_report(
            brief, project_root=project_root
        )

    # ------------------------------------------------------------------ execution

    def run(self, skill_id: str, input_data: dict[str, Any]) -> CodeSkillRun:
        return self.code_runtime.run(skill_id, input_data)

    def execute(self, graph: VibeWorkflowGraph, input_data: dict[str, Any]) -> WorkflowRunResult:
        return self.engine.run(graph, input_data)

    # ------------------------------------------------------------------ audit

    def history(self, skill_id: str) -> list[PatchRecord]:
        return self.ledger.history(skill_id)

    def evolution_chain(self, skill_id: str) -> list[dict[str, Any]]:
        return self.ledger.evolution_chain(skill_id)

    def rollback(self, skill_id: str, target_version: int) -> CodeSkill:
        return self.ledger.rollback(skill_id, target_version)

    def report(self, skill_id: str | None = None) -> dict[str, Any]:
        return self.ledger.report(skill_id)

    # ------------------------------------------------------------------ list

    def list_code_skills(self) -> list[CodeSkill]:
        return self.code_store.list_code_skills()

    # ------------------------------------------------------------------ agent

    def project_coder(self, root: str | Path) -> "ProjectVibeCoder":
        """Construct (or reuse) a :class:`ProjectVibeCoder` for ``root``.

        Lazy-imports :mod:`vibe_coding.agent.coder` so legacy users never pay
        the import cost. The same coder is cached per-root for the lifetime
        of this :class:`VibeCoder` instance.
        """
        from .agent.coder import ProjectVibeCoder

        cache: dict[str, ProjectVibeCoder] = self.__dict__.setdefault(
            "_project_coders", {}
        )
        key = str(Path(root).resolve())
        coder = cache.get(key)
        if coder is None:
            coder = ProjectVibeCoder(
                llm=self.llm,
                root=root,
                store_dir=self.store_dir / "agent",
            )
            cache[key] = coder
        return coder

    def index_project(self, root: str | Path, *, refresh: bool = False) -> "RepoIndex":
        """Build (or refresh) the :class:`RepoIndex` for ``root``."""
        return self.project_coder(root).index_project(refresh=refresh)

    def edit_project(
        self,
        brief: str,
        *,
        root: str | Path,
        context: "AgentContext | None" = None,
        focus_paths: list[str] | None = None,
    ) -> "ProjectPatch":
        return self.project_coder(root).edit_project(
            brief, context=context, focus_paths=focus_paths
        )

    def apply_patch(
        self,
        patch: "ProjectPatch",
        *,
        root: str | Path,
        dry_run: bool = False,
    ) -> "ApplyResult":
        return self.project_coder(root).apply_patch(patch, dry_run=dry_run)

    def rollback_patch(self, patch_id: str, *, root: str | Path) -> bool:
        return self.project_coder(root).rollback_patch(patch_id)

    def heal_project(
        self,
        brief: str,
        *,
        root: str | Path,
        context: "AgentContext | None" = None,
        max_rounds: int = 3,
        tool_runner: Any | None = None,
    ) -> "HealResult":
        return self.project_coder(root).heal_project(
            brief,
            context=context,
            max_rounds=max_rounds,
            tool_runner=tool_runner,
        )

    # ------------------------------------------------------------------ marketplace

    def publish_skill(
        self,
        skill_id: str,
        *,
        base_url: str,
        admin_token: str,
        version: str = "",
        name: str = "",
        description: str = "",
        price: float = 0.0,
        artifact: str = "mod",
        industry: str = "通用",
        verify_ssl: bool = True,
        dry_run: bool = False,
    ) -> Any:
        """Package the given skill and publish it to a MODstore deployment.

        The publisher is lazy-loaded so users that never publish never
        pay the import cost. A ``dry_run=True`` invocation still produces
        the ``.xcmod`` zip on disk (handy to inspect / hand to ``modman``)
        without contacting the network.
        """
        from .agent.marketplace import (
            PublishOptions,
            SkillPublisher,
        )

        try:
            skill = self.code_store.get_code_skill(skill_id)
        except KeyError as exc:
            raise ValueError(f"unknown skill_id: {skill_id!r}") from exc
        publisher = SkillPublisher.from_token(
            base_url=base_url,
            admin_token=admin_token,
            verify_ssl=verify_ssl,
        )
        opts = PublishOptions(
            version=version,
            name=name or skill.skill_id,
            description=description,
            price=price,
            artifact=artifact,
            industry=industry,
        )
        return publisher.publish_skill(skill, options=opts, dry_run=dry_run)


def _build_code_patch_generator(llm: LLMClient):
    try:
        from .nl.llm import OpenAILLM

        if isinstance(llm, OpenAILLM):
            return OpenAICodePatchGenerator(api_key=llm.api_key, model=llm.model, base_url=llm.base_url)
    except Exception:  # noqa: BLE001
        pass
    return RuleBasedCodePatchGenerator()
