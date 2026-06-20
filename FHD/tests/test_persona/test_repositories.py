"""PersonaProfileRepository 接口测试。"""

from __future__ import annotations

import pytest

from app.application.ports.persona_repository import PersonaProfileRepository


class TestPersonaProfileRepository:
    """仓储接口测试。"""

    def test_cannot_instantiate_abstract_class(self):
        with pytest.raises(TypeError):
            PersonaProfileRepository()  # type: ignore[abstract]

    def test_has_find_by_user_id_method(self):
        assert hasattr(PersonaProfileRepository, "find_by_user_id")

    def test_has_save_method(self):
        assert hasattr(PersonaProfileRepository, "save")

    def test_has_delete_method(self):
        assert hasattr(PersonaProfileRepository, "delete")
