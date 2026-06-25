# -*- coding: utf-8 -*-
"""contract_lifecycle 纯函数 + webhook/到期通知行为契约测试。

覆盖此前未测的：transition_contract / start_esign_flow / handle_esign_webhook /
notify_contract_expiry_items / run_contract_expiry_scan。均为真实分支断言（成功/
失败/降级），非行覆盖填充。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services import contract_lifecycle as cl


class TestGetContractBlock:
    def test_returns_copy_when_present(self):
        inner = {"status": "signed", "esign_task": {"a": 1}}
        doc = {"contract_lifecycle": inner}
        block = cl.get_contract_block(doc)
        assert block["status"] == "signed"
        # 必须是副本，改返回值不应回写原 doc
        block["status"] = "draft"
        assert doc["contract_lifecycle"]["status"] == "signed"

    def test_default_when_missing(self):
        assert cl.get_contract_block({}) == {"status": "draft", "esign_task": {}}

    def test_default_when_none(self):
        assert cl.get_contract_block(None)["status"] == "draft"

    def test_default_when_not_dict(self):
        assert cl.get_contract_block({"contract_lifecycle": "nope"})["status"] == "draft"


class TestTransitionContract:
    def test_sets_status_source_note(self):
        out = cl.transition_contract({}, "signed", source="webhook", note="ok")
        block = out["contract_lifecycle"]
        assert block["status"] == "signed"
        assert block["source"] == "webhook"
        assert block["note"] == "ok"

    def test_empty_status_keeps_existing(self):
        doc = {"contract_lifecycle": {"status": "esign_pending", "esign_task": {}}}
        out = cl.transition_contract(doc, "   ")
        assert out["contract_lifecycle"]["status"] == "esign_pending"

    def test_does_not_mutate_input(self):
        doc = {"x": 1}
        out = cl.transition_contract(doc, "signed")
        assert "contract_lifecycle" not in doc
        assert out["x"] == 1

    def test_no_source_no_note_omits_keys(self):
        out = cl.transition_contract({}, "draft")
        block = out["contract_lifecycle"]
        assert "source" not in block
        assert "note" not in block


class TestApplyContractToCrmMeta:
    def test_returns_copy(self):
        doc = {"a": 1}
        out = cl.apply_contract_to_crm_meta(doc)
        assert out == {"a": 1}
        assert out is not doc

    def test_none_input(self):
        assert cl.apply_contract_to_crm_meta(None) == {}


class TestStartEsignFlow:
    def test_populates_esign_task(self):
        out = cl.start_esign_flow({}, party_a="甲", party_b="乙", amount_cents=10000)
        block = out["contract_lifecycle"]
        assert block["esign_task"]["party_a"] == "甲"
        assert block["esign_task"]["party_b"] == "乙"
        assert block["esign_task"]["amount_cents"] == 10000
        assert block["esign_task"]["status"] == "pending"
        # get_contract_block 给空 doc 注入 status="draft"，故 `or "esign_pending"` 不触发
        assert block["status"] == "draft"

    def test_blank_status_falls_back_to_esign_pending(self):
        doc = {"contract_lifecycle": {"status": "", "esign_task": {}}}
        out = cl.start_esign_flow(doc, party_a="a", party_b="b", amount_cents=1)
        assert out["contract_lifecycle"]["status"] == "esign_pending"

    def test_keeps_existing_status(self):
        doc = {"contract_lifecycle": {"status": "negotiating", "esign_task": {}}}
        out = cl.start_esign_flow(doc, party_a="a", party_b="b", amount_cents=None)
        assert out["contract_lifecycle"]["status"] == "negotiating"


class TestHandleEsignWebhook:
    def test_unsigned_rejected(self):
        res = cl.handle_esign_webhook({"signed": False})
        assert res == {"success": False, "error": "unsigned"}

    def test_missing_market_user_id(self):
        res = cl.handle_esign_webhook({"signed": True})
        assert res["success"] is False
        assert res["error"] == "missing market_user_id"

    def test_success_persists_signed_state(self):
        saved = {}

        def fake_save(doc):
            saved.update(doc)

        with (
            patch("app.services.user_cs_pipeline.load_pipeline", return_value={}),
            patch("app.services.user_cs_pipeline.save_pipeline", side_effect=fake_save),
        ):
            res = cl.handle_esign_webhook({"signed": True, "market_user_id": "42", "task_id": "T1"})
        assert res["success"] is True
        assert res["data"]["market_user_id"] == "42"
        block = saved["contract_lifecycle"]
        assert block["status"] == "signed"
        assert block["esign_task"]["status"] == "signed"
        assert block["esign_task"]["task_id"] == "T1"

    def test_recoverable_error_returns_failure(self):
        with patch(
            "app.services.user_cs_pipeline.load_pipeline",
            side_effect=ValueError("boom"),
        ):
            res = cl.handle_esign_webhook({"signed": True, "market_user_id": 7})
        assert res["success"] is False
        assert "boom" in res["error"]


class TestNotifyContractExpiryItems:
    def test_empty_items(self):
        assert cl.notify_contract_expiry_items(None) == {
            "notified": 0,
            "pushed": 0,
            "failed": 0,
        }

    def test_skips_non_dict_and_incomplete(self):
        repo = MagicMock()
        with patch(
            "app.infrastructure.persistence.contract_expiry_notification_repository.get_contract_expiry_notification_repository",
            return_value=repo,
        ):
            res = cl.notify_contract_expiry_items(["bad", {"market_user_id": 0}, {"end_date": ""}])
        assert res == {"notified": 0, "pushed": 0, "failed": 0}

    def test_dry_run_counts_notified_only(self):
        repo = MagicMock()
        with patch(
            "app.infrastructure.persistence.contract_expiry_notification_repository.get_contract_expiry_notification_repository",
            return_value=repo,
        ):
            res = cl.notify_contract_expiry_items(
                [{"market_user_id": 1, "end_date": "2026-07-01"}], dry_run=True
            )
        assert res["notified"] == 1
        assert res["pushed"] == 0
        repo.insert_notification.assert_not_called()

    def test_push_success(self):
        repo = MagicMock()
        repo.was_recently_notified.return_value = False
        svc = MagicMock()
        svc.send_wechat_message.return_value = {"success": True, "message_sent": True}
        with (
            patch(
                "app.infrastructure.persistence.contract_expiry_notification_repository.get_contract_expiry_notification_repository",
                return_value=repo,
            ),
            patch("app.services.user_cs_pipeline.load_pipeline", return_value={}),
            patch(
                "app.services.user_cs_intake_notice._primary_contact_name",
                return_value="张三",
            ),
            patch(
                "app.desktop_automation.service.get_desktop_automation_service",
                return_value=svc,
            ),
        ):
            res = cl.notify_contract_expiry_items(
                [{"market_user_id": 1, "end_date": "2026-07-01", "username": "u"}],
                push=True,
            )
        assert res["pushed"] == 1
        assert res["failed"] == 0
        repo.insert_notification.assert_called_once()
        assert repo.insert_notification.call_args.kwargs["push_status"] == "success"

    def test_push_no_contact_marks_failed(self):
        repo = MagicMock()
        repo.was_recently_notified.return_value = False
        with (
            patch(
                "app.infrastructure.persistence.contract_expiry_notification_repository.get_contract_expiry_notification_repository",
                return_value=repo,
            ),
            patch("app.services.user_cs_pipeline.load_pipeline", return_value={}),
            patch("app.services.user_cs_intake_notice._primary_contact_name", return_value=""),
        ):
            res = cl.notify_contract_expiry_items(
                [{"market_user_id": 1, "end_date": "2026-07-01"}], push=True
            )
        assert res["failed"] == 1
        assert repo.insert_notification.call_args.kwargs["error_message"] == "no contact"

    def test_push_skips_recently_notified(self):
        repo = MagicMock()
        repo.was_recently_notified.return_value = True
        with patch(
            "app.infrastructure.persistence.contract_expiry_notification_repository.get_contract_expiry_notification_repository",
            return_value=repo,
        ):
            res = cl.notify_contract_expiry_items(
                [{"market_user_id": 1, "end_date": "2026-07-01"}], push=True
            )
        assert res["notified"] == 1
        assert res["pushed"] == 0
        repo.insert_notification.assert_not_called()

    def test_push_failure_from_service(self):
        repo = MagicMock()
        repo.was_recently_notified.return_value = False
        svc = MagicMock()
        svc.send_wechat_message.return_value = {"success": False, "error": "offline"}
        with (
            patch(
                "app.infrastructure.persistence.contract_expiry_notification_repository.get_contract_expiry_notification_repository",
                return_value=repo,
            ),
            patch("app.services.user_cs_pipeline.load_pipeline", return_value={}),
            patch(
                "app.services.user_cs_intake_notice._primary_contact_name",
                return_value="李四",
            ),
            patch(
                "app.desktop_automation.service.get_desktop_automation_service",
                return_value=svc,
            ),
        ):
            res = cl.notify_contract_expiry_items(
                [{"market_user_id": 1, "end_date": "2026-07-01"}], push=True
            )
        assert res["failed"] == 1
        assert repo.insert_notification.call_args.kwargs["error_message"] == "offline"

    def test_push_service_raises_recoverable(self):
        repo = MagicMock()
        repo.was_recently_notified.return_value = False
        svc = MagicMock()
        svc.send_wechat_message.side_effect = ValueError("crash")
        with (
            patch(
                "app.infrastructure.persistence.contract_expiry_notification_repository.get_contract_expiry_notification_repository",
                return_value=repo,
            ),
            patch("app.services.user_cs_pipeline.load_pipeline", return_value={}),
            patch(
                "app.services.user_cs_intake_notice._primary_contact_name",
                return_value="王五",
            ),
            patch(
                "app.desktop_automation.service.get_desktop_automation_service",
                return_value=svc,
            ),
        ):
            res = cl.notify_contract_expiry_items(
                [{"market_user_id": 1, "end_date": "2026-07-01"}], push=True
            )
        assert res["failed"] == 1
        assert "crash" in repo.insert_notification.call_args.kwargs["error_message"]


class TestRunContractExpiryScan:
    def test_returns_summary_shape(self):
        res = cl.run_contract_expiry_scan(days_ahead=15, dry_run=False)
        assert res["days_ahead"] == 15
        assert res["dry_run"] is False
        assert set(res) == {"scanned", "expiring", "notified", "days_ahead", "dry_run"}
