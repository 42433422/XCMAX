"""小C 客服 SSOT：人设与管理端 persy 知识库检索。"""

from __future__ import annotations

from unittest.mock import patch


class TestXiaocPersona:
    def test_admin_prompt_is_xiaoc(self):
        from modstore_server.xiaoc_cs_ssot import xiaoc_system_prompt

        text = xiaoc_system_prompt(mode="admin")
        assert "小C" in text
        assert "数字管家" in text
        assert "导航" in text

    def test_corp_prompt_is_xiaoc_not_legacy_name(self):
        from modstore_server.xiaoc_cs_ssot import xiaoc_system_prompt

        text = xiaoc_system_prompt(mode="corp")
        assert "小C" in text
        assert "小茈" not in text
        assert "官网" in text


class TestKnowledgeFormat:
    def test_format_knowledge_block(self):
        from modstore_server.xiaoc_cs_ssot import format_knowledge_block

        block = format_knowledge_block(
            [{"text": "会员可按年付费", "source": "faq.md"}]
        )
        assert "persy-knowledge" in block
        assert "会员可按年付费" in block
        assert "faq.md" in block

    def test_format_empty(self):
        from modstore_server.xiaoc_cs_ssot import format_knowledge_block

        assert format_knowledge_block([]) == ""


class TestRetrieve:
    def test_retrieve_prefers_http(self):
        from modstore_server.xiaoc_cs_ssot import retrieve_persy_knowledge

        fake = [{"text": "报价需定制", "source": "pricing"}]
        with patch(
            "modstore_server.xiaoc_cs_ssot._http_retrieve",
            return_value=fake,
        ) as http_m:
            with patch(
                "modstore_server.xiaoc_cs_ssot._local_retrieve",
                return_value=[{"text": "local"}],
            ) as local_m:
                out = retrieve_persy_knowledge("报价多少")
        assert out == fake
        http_m.assert_called_once()
        local_m.assert_not_called()

    def test_retrieve_falls_back_local(self):
        from modstore_server.xiaoc_cs_ssot import retrieve_persy_knowledge

        with patch(
            "modstore_server.xiaoc_cs_ssot._http_retrieve",
            return_value=[],
        ):
            with patch(
                "modstore_server.xiaoc_cs_ssot._local_retrieve",
                return_value=[{"text": "local-hit"}],
            ):
                out = retrieve_persy_knowledge("怎么上手")
        assert out == [{"text": "local-hit"}]

    def test_last_user_text(self):
        from modstore_server.xiaoc_cs_ssot import last_user_text

        assert (
            last_user_text(
                [
                    {"role": "system", "content": "sys"},
                    {"role": "user", "content": "第一问"},
                    {"role": "assistant", "content": "答"},
                    {"role": "user", "content": "第二问"},
                ]
            )
            == "第二问"
        )


class TestButlerUsesSsot:
    def test_build_corp_messages_uses_xiaoc(self):
        from modstore_server.agent_butler_api import (
            ButlerMessageDTO,
            CorpChatDTO,
            _build_corp_messages,
        )

        with patch(
            "modstore_server.xiaoc_cs_ssot.knowledge_block_for_query",
            return_value="【管理端知识库·persy-knowledge】\n1. 测试摘录",
        ):
            msgs = _build_corp_messages(
                CorpChatDTO(
                    messages=[ButlerMessageDTO(role="user", content="你们做什么")],
                    page_id="index",
                )
            )
        assert msgs[0]["role"] == "system"
        assert "小C" in msgs[0]["content"]
        assert "persy-knowledge" in msgs[0]["content"]
