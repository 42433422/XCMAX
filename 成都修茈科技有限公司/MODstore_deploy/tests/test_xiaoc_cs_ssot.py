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
        assert "权限契约" in text

    def test_corp_prompt_is_xiaoc_not_legacy_name(self):
        from modstore_server.xiaoc_cs_ssot import xiaoc_system_prompt

        text = xiaoc_system_prompt(mode="corp")
        assert "小C" in text
        assert "小茈" not in text
        assert "官网" in text
        assert "禁止" in text
        assert "联合发布的独立产品品牌" in text
        assert "已经自动打通" in text

    def test_permission_policy_external_no_tools(self):
        from modstore_server.xiaoc_cs_ssot import permission_policy

        p = permission_policy(mode="external")
        assert p["auth"] == "none"
        assert p["tools"]["navigate"] is False
        assert p["tools"]["enhance_current_page"] is False
        assert p["knowledge"]["read_persy"] is True
        assert p["knowledge"]["write_persy"] is False

    def test_permission_policy_admin_has_tools(self):
        from modstore_server.xiaoc_cs_ssot import (
            INTERNAL_DATASET_ID,
            PUBLIC_DATASET_ID,
            permission_policy,
        )

        p = permission_policy(mode="admin")
        assert p["tools"]["navigate"] is True
        assert p["tools"]["enhance_current_page"] is True
        assert p["tools"]["wallet_pay"] is False
        assert p["tools"]["get_my_account_snapshot"] is True
        assert p["tools"]["get_ops_update_brief"] is True
        names = p["limits"]["tool_names"]
        assert "get_my_tickets" in names
        assert "get_ops_update_brief" in names
        assert "查询他人账户/订单/工单" in p["denied"]
        kn = p["knowledge"]["datasets"]
        assert PUBLIC_DATASET_ID in kn["read"]
        assert INTERNAL_DATASET_ID in kn["read"]
        assert PUBLIC_DATASET_ID in kn["write"]
        assert INTERNAL_DATASET_ID in kn["write"]

    def test_kb_isolation_corp_public_only(self):
        from unittest.mock import patch

        from modstore_server.xiaoc_cs_ssot import (
            INTERNAL_DATASET_ID,
            PUBLIC_DATASET_ID,
            dataset_allowed_for_mode,
            knowledge_block_for_query,
            permission_policy,
            retrieve_knowledge_for_mode,
        )

        ext = permission_policy(mode="corp")
        assert ext["knowledge"]["datasets"]["read"] == [PUBLIC_DATASET_ID]
        assert INTERNAL_DATASET_ID not in ext["knowledge"]["datasets"]["read"]
        assert dataset_allowed_for_mode(INTERNAL_DATASET_ID, mode="corp") is False
        assert dataset_allowed_for_mode("user_acme", mode="admin") is False

        corp_calls: list[str] = []
        admin_calls: list[str] = []

        def _corp_retrieve(query, *, dataset_id, top_k=5):
            corp_calls.append(dataset_id)
            return [
                {
                    "text": "public-hit",
                    "source": "faq.md",
                    "metadata": {
                        "audience": "public",
                        "publication_status": "published",
                        "knowledge_owner": "chengdu-xiuci-technology",
                    },
                }
            ]

        def _admin_retrieve(query, *, dataset_id, top_k=5):
            admin_calls.append(dataset_id)
            metadata = (
                {
                    "audience": "public",
                    "publication_status": "published",
                    "knowledge_owner": "chengdu-xiuci-technology",
                }
                if dataset_id == PUBLIC_DATASET_ID
                else {}
            )
            return [{"text": f"hit-{dataset_id}", "source": "t.md", "metadata": metadata}]

        with patch(
            "modstore_server.xiaoc_cs_ssot.retrieve_dataset_knowledge",
            side_effect=_corp_retrieve,
        ):
            corp_chunks = retrieve_knowledge_for_mode("报价", mode="external", top_k=4)
        with patch(
            "modstore_server.xiaoc_cs_ssot.retrieve_dataset_knowledge",
            side_effect=_corp_retrieve,
        ):
            block = knowledge_block_for_query("报价", mode="corp", top_k=4)

        with patch(
            "modstore_server.xiaoc_cs_ssot.retrieve_dataset_knowledge",
            side_effect=_admin_retrieve,
        ):
            admin_chunks = retrieve_knowledge_for_mode("报价", mode="admin", top_k=4)

        assert set(corp_calls) == {PUBLIC_DATASET_ID}
        assert INTERNAL_DATASET_ID not in corp_calls
        assert all(c.get("dataset_id") == PUBLIC_DATASET_ID for c in corp_chunks)
        assert admin_calls == [PUBLIC_DATASET_ID, INTERNAL_DATASET_ID]
        assert {c.get("dataset_id") for c in admin_chunks} == {
            PUBLIC_DATASET_ID,
            INTERNAL_DATASET_ID,
        }
        assert "公开库" in block
        assert "内部库" not in block

    def test_external_retrieval_rejects_unpublished_public_chunks(self):
        from modstore_server.xiaoc_cs_ssot import retrieve_knowledge_for_mode

        dirty = {
            "text": "Generated contract",
            "source": "contract.docx",
            "metadata": {"tenant_id": "eval-user"},
        }
        with patch(
            "modstore_server.xiaoc_cs_ssot.retrieve_dataset_knowledge",
            return_value=[dirty],
        ):
            assert retrieve_knowledge_for_mode("公司产品", mode="external") == []

    def test_local_public_retrieval_queries_public_published_scope(self, monkeypatch, tmp_path):
        import sys
        import types

        from modstore_server.xiaoc_cs_ssot import PUBLIC_DATASET_ID, _local_retrieve

        fhd_root = tmp_path / "FHD"
        (fhd_root / "app").mkdir(parents=True)
        monkeypatch.setenv("XCAGI_FHD_ROOT", str(fhd_root))

        calls = []

        class _Access:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        class _Service:
            def query(self, **kwargs):
                calls.append(kwargs)
                return {"chunks": [{"text": "public hit", "metadata": {}}]}

        app_pkg = types.ModuleType("app")
        app_pkg.__path__ = []
        application_pkg = types.ModuleType("app.application")
        application_pkg.__path__ = []
        rag_module = types.ModuleType("app.application.dataset_rag_app_service")
        rag_module.DATASET_ADMIN_PERMISSION = "dataset.admin"
        rag_module.DATASET_READ_PERMISSION = "dataset.read"
        rag_module.DatasetAccessContext = _Access
        rag_module.get_dataset_rag_app_service = lambda: _Service()
        monkeypatch.setitem(sys.modules, "app", app_pkg)
        monkeypatch.setitem(sys.modules, "app.application", application_pkg)
        monkeypatch.setitem(
            sys.modules,
            "app.application.dataset_rag_app_service",
            rag_module,
        )

        out = _local_retrieve("报价", top_k=3, dataset_id=PUBLIC_DATASET_ID)

        assert out == [{"text": "public hit", "metadata": {}}]
        assert calls
        assert calls[0]["tenant_id"] == "public"
        assert calls[0]["metadata_filter"] == {
            "audience": "public",
            "publication_status": "published",
            "knowledge_owner": "chengdu-xiuci-technology",
        }


class TestKnowledgeFormat:
    def test_format_knowledge_block(self):
        from modstore_server.xiaoc_cs_ssot import format_knowledge_block

        block = format_knowledge_block([{"text": "会员可按年付费", "source": "faq.md"}])
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


class TestVisitorIdentity:
    def test_guest_and_format(self):
        from modstore_server.xiaoc_cs_ssot import (
            format_visitor_block,
            identity_from_guest,
            sanitize_visitor_id,
        )

        assert sanitize_visitor_id("bad") == ""
        assert sanitize_visitor_id("v_abcdefgh") == "v_abcdefgh"
        ident = identity_from_guest(visitor_id="v_abcdefgh", visitor_label="小张")
        block = format_visitor_block(ident)
        assert "当前对话对象" in block
        assert "kind=guest" in block
        assert "小张" in block
        assert "v_abcdefgh" in block

    def test_user_masks_email(self):
        from types import SimpleNamespace

        from modstore_server.xiaoc_cs_ssot import (
            format_visitor_block,
            identity_from_user,
            mask_email,
        )

        assert mask_email("ab@x.com") == "a*@x.com"
        assert mask_email("alice@example.com").startswith("a***e@")
        user = SimpleNamespace(id=42, username="alice", email="alice@example.com")
        ident = identity_from_user(user, source="butler", membership_tier="VIP+")
        block = format_visitor_block(ident)
        assert "kind=user" in block
        assert "user_id=42" in block
        assert "alice" in block
        assert "会员=VIP+" in block
        assert "alice@example.com" not in block

    def test_admin_enterprise_and_plan_from_db(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        from modstore_server.xiaoc_cs_ssot import format_visitor_block, resolve_user_identity

        user = SimpleNamespace(
            id=9,
            username="boss",
            email="boss@x.com",
            is_admin=True,
            is_enterprise=True,
        )
        plan_row = SimpleNamespace(plan_id="plan_enterprise", id=1)
        q = MagicMock()
        q.filter.return_value.order_by.return_value.first.return_value = plan_row
        db = MagicMock()
        db.query.return_value = q
        ident = resolve_user_identity(user, db=db, source="butler")
        block = format_visitor_block(ident)
        assert ident.account_role == "admin"
        assert ident.membership == "svip"
        assert "角色=管理员" in block
        assert "会员=svip" in block
        assert "套餐=plan_enterprise" in block

    def test_free_user_is_ordinary(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        from modstore_server.xiaoc_cs_ssot import format_visitor_block, resolve_user_identity

        user = SimpleNamespace(
            id=3, username="newbie", email="", is_admin=False, is_enterprise=False
        )
        q = MagicMock()
        q.filter.return_value.order_by.return_value.first.return_value = None
        db = MagicMock()
        db.query.return_value = q
        nested = MagicMock()
        db.begin_nested.return_value = nested
        ident = resolve_user_identity(user, db=db, source="market_cs")
        block = format_visitor_block(ident)
        assert ident.membership == "普通用户"
        assert "会员=普通用户" in block
        assert "角色=" not in block
        nested.commit.assert_called_once()

    def test_active_plan_query_failure_uses_savepoint(self):
        """套餐查询失败时回滚 SAVEPOINT，返回空串，不向外抛。"""
        from unittest.mock import MagicMock

        from modstore_server.xiaoc_cs_ssot import active_plan_id_for_user

        db = MagicMock()
        nested = MagicMock()
        db.begin_nested.return_value = nested
        db.query.side_effect = RuntimeError("column user_plans.auto_renew does not exist")
        assert active_plan_id_for_user(db, 61) == ""
        nested.rollback.assert_called_once()
        nested.commit.assert_not_called()


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
                    visitor_id="v_testguest01",
                    visitor_label="小李",
                )
            )
        assert msgs[0]["role"] == "system"
        assert "小C" in msgs[0]["content"]
        assert "persy-knowledge" in msgs[0]["content"]
        assert "当前对话对象" in msgs[0]["content"]
        assert "小李" in msgs[0]["content"]
        assert "v_testguest01" in msgs[0]["content"]

    def test_build_messages_injects_logged_in_user(self):
        from types import SimpleNamespace

        from modstore_server.agent_butler_api import (
            ButlerChatDTO,
            ButlerMessageDTO,
            _build_messages,
        )

        user = SimpleNamespace(id=7, username="bob", email="bob@x.com")
        with patch(
            "modstore_server.xiaoc_cs_ssot.knowledge_block_for_query",
            return_value="",
        ):
            msgs = _build_messages(
                ButlerChatDTO(
                    messages=[ButlerMessageDTO(role="user", content="你好")],
                    page_context="当前页面: 首页",
                ),
                "当前页面: 首页",
                user=user,
            )
        assert "当前对话对象" in msgs[0]["content"]
        assert "kind=user" in msgs[0]["content"]
        assert "bob" in msgs[0]["content"]
        assert "user_id=7" in msgs[0]["content"]
