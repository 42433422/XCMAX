"""Public package imports stay usable in fresh workers and dependency overrides."""

import subprocess
import sys
import textwrap
from pathlib import Path


def _assert_shared_orchestration_records_do_not_require_document_or_spreadsheet_runtimes_0(
    _shared_literal_0,
):
    _fresh_process(_shared_literal_0)


def _fresh_process(source):
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(source)],
        cwd=Path(__file__).parents[2],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_orchestration_records_do_not_require_document_or_spreadsheet_runtimes():
    return _assert_shared_orchestration_records_do_not_require_document_or_spreadsheet_runtimes_0(
        "\n        import importlib.abc\n        import sys\n\n        class UnavailableOptionalRuntime(importlib.abc.MetaPathFinder):\n            def find_spec(self, fullname, path=None, target=None):\n                if fullname.split('.')[0] in {'pandas', 'numpy', 'torch', 'docx'}:\n                    raise AssertionError(f'unrelated runtime imported: {fullname}')\n\n        sys.meta_path.insert(0, UnavailableOptionalRuntime())\n        from app.application.agent_orchestrator import AgentStep\n\n        step = AgentStep(node_id='read-only', tool_id='dataset_rag', action='status')\n        payload = step.to_dict()\n        assert payload['node_id'] == 'read-only'\n        assert payload['tool_id'] == 'dataset_rag'\n        assert payload['action'] == 'status'\n        "
    )


def test_cold_public_exports_follow_and_restore_dependency_overrides():
    return _assert_shared_orchestration_records_do_not_require_document_or_spreadsheet_runtimes_0(
        "\n        from unittest.mock import patch, sentinel\n        import pytest\n        import app.application as application\n        from app.application import user_app_service\n\n        original = user_app_service.get_user_app_service\n        # The first package-level lookup happens inside a child-module override.\n        with patch.object(user_app_service, 'get_user_app_service', return_value=sentinel.child):\n            assert application.get_user_app_service() is sentinel.child\n        assert application.get_user_app_service is original\n\n        with patch.object(application, 'get_user_app_service', return_value=sentinel.root):\n            from app.application import get_user_app_service\n            assert get_user_app_service() is sentinel.root\n        assert application.get_user_app_service is original\n\n        with pytest.MonkeyPatch.context() as override:\n            override.setattr('app.application.session_account_meta.load_session_account_meta', lambda *_: {'test': True})\n            assert application.session_account_meta.load_session_account_meta('isolated') == {'test': True}\n\n        assert 'get_user_app_service' in dir(application)\n        assert 'AIChatApplicationService' in application.__all__\n        "
    )
