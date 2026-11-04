"""Public package imports stay usable in fresh workers and dependency overrides."""

import subprocess
import sys
import textwrap
from pathlib import Path


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
    _fresh_process(
        """
        import importlib.abc
        import sys

        class UnavailableOptionalRuntime(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname.split('.')[0] in {'pandas', 'numpy', 'torch', 'docx'}:
                    raise AssertionError(f'unrelated runtime imported: {fullname}')

        sys.meta_path.insert(0, UnavailableOptionalRuntime())
        from app.application.agent_orchestrator import AgentStep

        step = AgentStep(node_id='read-only', tool_id='dataset_rag', action='status')
        payload = step.to_dict()
        assert payload['node_id'] == 'read-only'
        assert payload['tool_id'] == 'dataset_rag'
        assert payload['action'] == 'status'
        """
    )


def test_cold_public_exports_follow_and_restore_dependency_overrides():
    _fresh_process(
        """
        from unittest.mock import patch, sentinel
        import pytest
        import app.application as application
        from app.application import user_app_service

        original = user_app_service.get_user_app_service
        # The first package-level lookup happens inside a child-module override.
        with patch.object(user_app_service, 'get_user_app_service', return_value=sentinel.child):
            assert application.get_user_app_service() is sentinel.child
        assert application.get_user_app_service is original

        with patch.object(application, 'get_user_app_service', return_value=sentinel.root):
            from app.application import get_user_app_service
            assert get_user_app_service() is sentinel.root
        assert application.get_user_app_service is original

        with pytest.MonkeyPatch.context() as override:
            override.setattr('app.application.session_account_meta.load_session_account_meta', lambda *_: {'test': True})
            assert application.session_account_meta.load_session_account_meta('isolated') == {'test': True}

        assert 'get_user_app_service' in dir(application)
        assert 'AIChatApplicationService' in application.__all__
        """
    )
