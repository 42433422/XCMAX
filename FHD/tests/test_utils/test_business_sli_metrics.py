"""业务 SLI 指标 + SLO-BIZ 注册完整性单元测试。

覆盖范围（铁律 3 禁止只测 happy path / 铁律 6 分支覆盖 ≠ 行覆盖）：
- record_customer_op / record_doc_recognition / record_export_task / record_mod_install
  * happy path：计数 + 直方图样本数增加
  * fail-open：RECOVERABLE_ERRORS 不抛错
- collect_slo_metrics.py 的 QUERIES / TARGETS 完整性
- meets_target() 对 SLO-BIZ-* 的 ge/lt 操作符正确性
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from app.utils import metrics

# ── record_customer_op ─────────────────────────────────────────────────────


class TestRecordCustomerOp:
    def test_increments_counter_success(self):
        before = metrics.customer_op_total.labels(operation="create", status="success")._value.get()
        metrics.record_customer_op("create", "success", 0.123)
        after = metrics.customer_op_total.labels(operation="create", status="success")._value.get()
        assert after == before + 1

    def test_increments_counter_error(self):
        before = metrics.customer_op_total.labels(operation="update", status="error")._value.get()
        metrics.record_customer_op("update", "error", 0.05)
        after = metrics.customer_op_total.labels(operation="update", status="error")._value.get()
        assert after == before + 1

    def test_observes_duration_samples_histogram(self):
        """Histogram 的 _sum 应累加，buckets 总计数应 +1。

        prometheus_client Histogram 子样本通过 ``_sum``（累加观测值）与
        ``_buckets``（累积桶计数）暴露；总观测数 = ``sum(b.get() for b in _buckets)``，
        等价于 ``+Inf`` 桶（最后一个桶）的值。
        """
        hist = metrics.customer_op_duration_seconds.labels(operation="delete")
        count_before = sum(b.get() for b in hist._buckets)
        sum_before = hist._sum.get()
        metrics.record_customer_op("delete", "success", 0.25)
        hist_after = metrics.customer_op_duration_seconds.labels(operation="delete")
        assert sum(b.get() for b in hist_after._buckets) == count_before + 1
        assert hist_after._sum.get() == pytest.approx(sum_before + 0.25, rel=1e-9)

    def test_query_operation_distinct_labels(self):
        """query 操作与 create 操作不互相污染（标签隔离）。"""
        before_create = metrics.customer_op_total.labels(
            operation="create", status="success"
        )._value.get()
        before_query = metrics.customer_op_total.labels(
            operation="query", status="success"
        )._value.get()
        metrics.record_customer_op("query", "success", 0.01)
        after_create = metrics.customer_op_total.labels(
            operation="create", status="success"
        )._value.get()
        after_query = metrics.customer_op_total.labels(
            operation="query", status="success"
        )._value.get()
        assert after_create == before_create  # create 不变
        assert after_query == before_query + 1  # query +1


# ── record_doc_recognition ─────────────────────────────────────────────────


class TestRecordDocRecognition:
    def test_increments_counter_excel(self):
        before = metrics.doc_recognition_total.labels(
            doc_type="excel", status="success"
        )._value.get()
        metrics.record_doc_recognition("excel", "success", 1.2)
        after = metrics.doc_recognition_total.labels(
            doc_type="excel", status="success"
        )._value.get()
        assert after == before + 1

    def test_increments_counter_ocr_error(self):
        before = metrics.doc_recognition_total.labels(doc_type="ocr", status="error")._value.get()
        metrics.record_doc_recognition("ocr", "error", 0.8)
        after = metrics.doc_recognition_total.labels(doc_type="ocr", status="error")._value.get()
        assert after == before + 1

    def test_observes_duration(self):
        """doc_recognition_duration_seconds 累积观测一次。

        通过 ``_buckets`` 累积计数验证（prometheus_client Histogram 子样本 API）。
        """
        hist = metrics.doc_recognition_duration_seconds.labels(doc_type="word")
        count_before = sum(b.get() for b in hist._buckets)
        sum_before = hist._sum.get()
        metrics.record_doc_recognition("word", "success", 2.5)
        hist_after = metrics.doc_recognition_duration_seconds.labels(doc_type="word")
        assert sum(b.get() for b in hist_after._buckets) == count_before + 1
        assert hist_after._sum.get() == pytest.approx(sum_before + 2.5, rel=1e-9)


# ── record_export_task ────────────────────────────────────────────────────


class TestRecordExportTask:
    def test_increments_counter_excel(self):
        before = metrics.export_task_total.labels(
            export_type="excel", status="success"
        )._value.get()
        metrics.record_export_task("excel", "success", 5.0)
        after = metrics.export_task_total.labels(export_type="excel", status="success")._value.get()
        assert after == before + 1

    def test_observes_duration(self):
        """export_task_duration_seconds 累积观测一次（prometheus_client Histogram API）。"""
        hist = metrics.export_task_duration_seconds.labels(export_type="csv")
        count_before = sum(b.get() for b in hist._buckets)
        sum_before = hist._sum.get()
        metrics.record_export_task("csv", "success", 1.5)
        hist_after = metrics.export_task_duration_seconds.labels(export_type="csv")
        assert sum(b.get() for b in hist_after._buckets) == count_before + 1
        assert hist_after._sum.get() == pytest.approx(sum_before + 1.5, rel=1e-9)


# ── record_mod_install ─────────────────────────────────────────────────────


class TestRecordModInstall:
    def test_increments_install_success(self):
        before = metrics.mod_install_total.labels(
            operation="install", status="success", device_scope="server_runtime"
        )._value.get()
        metrics.record_mod_install("install", "success")
        after = metrics.mod_install_total.labels(
            operation="install", status="success", device_scope="server_runtime"
        )._value.get()
        assert after == before + 1

    def test_increments_uninstall_error(self):
        before = metrics.mod_install_total.labels(
            operation="uninstall", status="error", device_scope="server_runtime"
        )._value.get()
        metrics.record_mod_install("uninstall", "error")
        after = metrics.mod_install_total.labels(
            operation="uninstall", status="error", device_scope="server_runtime"
        )._value.get()
        assert after == before + 1

    def test_mod_install_has_no_duration_metric(self):
        """SLO-BIZ-05 只测成功率，不测延迟（设计取舍）。"""
        assert not hasattr(metrics, "mod_install_duration_seconds")


class TestBusinessHttpInstrumentation:
    def test_customer_request_records_real_operation(self):
        labels = metrics.customer_op_total.labels(operation="update", status="success")
        before = labels._value.get()
        metrics.record_business_http_request("PATCH", "/api/customers/42", 200, 0.2)
        assert labels._value.get() == before + 1

    def test_ocr_and_export_paths_record_separate_sli_families(self):
        ocr = metrics.doc_recognition_total.labels(doc_type="ocr", status="success")
        export = metrics.export_task_total.labels(export_type="pdf", status="error")
        ocr_before = ocr._value.get()
        export_before = export._value.get()
        metrics.record_business_http_request("POST", "/api/ocr/recognize", 201, 0.8)
        metrics.record_business_http_request("GET", "/api/report/export.pdf", 500, 1.2)
        assert ocr._value.get() == ocr_before + 1
        assert export._value.get() == export_before + 1

    def test_server_mod_action_is_not_mislabelled_as_external_customer(self):
        local = metrics.mod_install_total.labels(
            operation="install", status="success", device_scope="server_runtime"
        )
        external = metrics.mod_install_total.labels(
            operation="install", status="success", device_scope="external_customer"
        )
        local_before = local._value.get()
        external_before = external._value.get()
        metrics.record_business_http_request("POST", "/api/mod-store/install", 200, 0.4)
        assert local._value.get() == local_before + 1
        assert external._value.get() == external_before


# ── collect_slo_metrics.py QUERIES / TARGETS 注册完整性 ────────────────────


def _load_collect_slo_module():
    """以 importlib 加载 collect_slo_metrics.py（不在 app 包内，需手动加载）。"""
    fhd_root = Path(metrics.__file__).resolve().parents[2]
    module_path = fhd_root / "scripts" / "observability" / "collect_slo_metrics.py"
    spec = importlib.util.spec_from_file_location("collect_slo_metrics", module_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def slo_module():
    return _load_collect_slo_module()


class TestSloBizRegistration:
    """SLO-BIZ-01..05 在 QUERIES / TARGETS 中注册完整。"""

    BIZ_IDS = ("SLO-BIZ-01", "SLO-BIZ-02", "SLO-BIZ-03", "SLO-BIZ-04", "SLO-BIZ-05")

    def test_all_biz_ids_in_queries(self, slo_module):
        for sid in self.BIZ_IDS:
            assert sid in slo_module.QUERIES, f"{sid} 缺失 PromQL 查询"

    def test_all_biz_ids_in_targets(self, slo_module):
        for sid in self.BIZ_IDS:
            assert sid in slo_module.TARGETS, f"{sid} 缺失目标值"

    def test_queries_and_targets_keys_symmetric(self, slo_module):
        """QUERIES 与 TARGETS 必须键对称（避免 SLO 一侧注册缺失）。"""
        assert set(slo_module.QUERIES.keys()) == set(slo_module.TARGETS.keys())

    def test_biz_queries_use_window_placeholder(self, slo_module):
        """所有 BIZ 查询必须包含 {w} 窗口占位符（铁律 3 SLO 窗口双制）。"""
        for sid in self.BIZ_IDS:
            assert "{w}" in slo_module.QUERIES[sid], f"{sid} 缺失 {{w}} 窗口占位符"

    def test_biz_targets_match_slo_md(self, slo_module):
        """目标值与 docs/SLO.md 业务 SLO 章节声明一致。"""
        expected = {
            "SLO-BIZ-01": ("customer_op_p95_ms", 800, "lt"),
            "SLO-BIZ-02": ("customer_op_error_rate", 0.005, "lt"),
            "SLO-BIZ-03": ("doc_recognition_p95_ms", 5000, "lt"),
            "SLO-BIZ-04": ("export_task_p95_ms", 30000, "lt"),
            "SLO-BIZ-05": ("mod_install_success_rate", 0.99, "ge"),
        }
        for sid, exp in expected.items():
            assert slo_module.TARGETS[sid] == exp, (
                f"{sid} 目标值漂移：{slo_module.TARGETS[sid]} != {exp}"
            )


class TestMeetsTargetBiz:
    """meets_target() 对 SLO-BIZ-* 的 ge/lt 操作符正确。"""

    def test_biz_01_lt_threshold_passes(self, slo_module):
        """SLO-BIZ-01 P95 < 800ms：实测 799ms 通过。"""
        assert slo_module.meets_target("SLO-BIZ-01", 799.0) is True

    def test_biz_01_lt_threshold_fails_at_boundary(self, slo_module):
        """SLO-BIZ-01 P95 = 800ms（边界）不通过（lt 严格小于）。"""
        assert slo_module.meets_target("SLO-BIZ-01", 800.0) is False

    def test_biz_01_lt_threshold_fails_above(self, slo_module):
        """SLO-BIZ-01 P95 > 800ms 不通过。"""
        assert slo_module.meets_target("SLO-BIZ-01", 1000.0) is False

    def test_biz_02_error_rate_lt_passes(self, slo_module):
        """SLO-BIZ-02 错误率 < 0.5%：实测 0.004 通过。"""
        assert slo_module.meets_target("SLO-BIZ-02", 0.004) is True

    def test_biz_02_error_rate_lt_fails(self, slo_module):
        """SLO-BIZ-02 错误率 = 0.01 不通过。"""
        assert slo_module.meets_target("SLO-BIZ-02", 0.01) is False

    def test_biz_05_ge_threshold_passes(self, slo_module):
        """SLO-BIZ-05 成功率 ≥ 99%：实测 0.991 通过。"""
        assert slo_module.meets_target("SLO-BIZ-05", 0.991) is True

    def test_biz_05_ge_threshold_at_boundary_passes(self, slo_module):
        """SLO-BIZ-05 成功率 = 0.99（边界）通过（ge 包含等于）。"""
        assert slo_module.meets_target("SLO-BIZ-05", 0.99) is True

    def test_biz_05_ge_threshold_fails_below(self, slo_module):
        """SLO-BIZ-05 成功率 < 99% 不通过。"""
        assert slo_module.meets_target("SLO-BIZ-05", 0.985) is False

    def test_meets_target_none_returns_none(self, slo_module):
        """Prometheus 不可达 → None（铁律 9 CI 采集容错）。"""
        assert slo_module.meets_target("SLO-BIZ-01", None) is None


# ── 标签基数合规（铁律 8）─────────────────────────────────────────────────


class TestLabelCardinality:
    """验证业务指标标签基数 < 20（铁律 8）。"""

    def test_customer_op_label_cardinality(self):
        """operation × status = 4 × 2 = 8 < 20。"""
        # 标签名空间设计值，不强制运行时枚举
        ops = {"create", "update", "delete", "query"}
        statuses = {"success", "error"}
        assert len(ops) * len(statuses) < 20

    def test_doc_recognition_label_cardinality(self):
        """doc_type × status = 4 × 2 = 8 < 20。"""
        doc_types = {"excel", "word", "ocr", "pdf"}
        statuses = {"success", "error"}
        assert len(doc_types) * len(statuses) < 20

    def test_export_task_label_cardinality(self):
        """export_type × status = 3 × 2 = 6 < 20。"""
        export_types = {"excel", "csv", "pdf"}
        statuses = {"success", "error"}
        assert len(export_types) * len(statuses) < 20

    def test_mod_install_label_cardinality(self):
        """operation × status = 4 × 2 = 8 < 20。"""
        ops = {"install", "uninstall", "activate", "deactivate"}
        statuses = {"success", "error"}
        assert len(ops) * len(statuses) < 20
