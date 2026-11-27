#!/usr/bin/env python3
"""Generate isolated promtool tests using the collector's actual expressions.

Synthetic fixtures are never submitted to production Prometheus or SLO evidence.
The JSON output is also valid YAML for `promtool test rules`.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from collect_slo_metrics import QUERIES, SCRAPE_QUERIES, SCRAPE_SERVICES, SCRAPE_TARGETS

RATIOS = ("SLO-API-01", "SLO-API-03", "SLO-BUS-01", "SLO-BIZ-02", "SLO-BIZ-05")


def agent_fixtures() -> list[dict]:
    dashboard = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "ops/monitoring/grafana/provisioning/dashboards/fhd.json"
        ).read_text(encoding="utf-8")
    )
    expressions = {
        panel["id"]: panel["targets"][0]["expr"].replace("$job", "fhd-api-stable")
        for panel in dashboard["panels"]
    }

    def series(metric: str, values: str, labels: str = "", job: str = "fhd-api-stable") -> dict:
        extra = f",{labels}" if labels else ""
        environment = "staging" if job == "fhd-api-staging" else "production"
        return {
            "series": f'{metric}{{job="{job}",environment="{environment}",service="fhd",instance="127.0.0.1:5100"{extra}}}',
            "values": values,
        }

    def ratio_case(
        name: str, inputs: list[dict], agent: float | None, http: float | None = None
    ) -> dict:
        return {
            "name": name,
            "interval": "1m",
            "input_series": inputs,
            "promql_expr_test": [
                {
                    "expr": expressions[id],
                    "eval_time": "15m",
                    "exp_samples": [] if value is None else [{"labels": "{}", "value": value}],
                }
                for id, value in ((9, agent), (3, http))
            ],
        }

    terminals = [
        series("xcagi_run_terminal_total", "0+1x15", f'status="{status}"')
        for status in ("completed", "failed", "cancelled", "rejected")
    ]
    sparse = terminals + [
        series(
            "xcagi_run_terminal_total", "0+1000x15", 'status="completed"', job="fhd-api-staging"
        ),
        series("xcagi_run_terminal_total", "0+1000x15", 'status="waiting_for_approval"'),
        series("xcagi_run_terminal_total", "0+1000x15", 'status="unknown"'),
        series("api_requests_total", "0+1x15", 'status="200"'),
        series("api_requests_total", "0+1x15", 'status="500"'),
        series("api_requests_total", "0+1000x15", 'status="200"', job="fhd-api-staging"),
    ]
    tests = [
        ratio_case(
            "agent sparse outcomes keep cancellations and rejections in denominator and isolate staging",
            sparse,
            0.25,
            0.5,
        ),
        ratio_case("only failed tasks cannot appear as no data or successful", terminals[1:2], 0),
        ratio_case("completed outcomes with no failures are observable success", terminals[:1], 1),
        ratio_case(
            "counter resets preserve the actual outcome ratio",
            [{**item, "values": "0 1 2 3 4 5 6 7 0 1 2 3 4 5 6 7"} for item in terminals[:2]],
            0.5,
        ),
        ratio_case(
            "zero terminal samples are unknown",
            [{**item, "values": "0+0x15"} for item in sparse],
            None,
        ),
        ratio_case("missing Agent telemetry is unknown", [], None),
    ]
    tests.append(
        {
            "name": "measured model stages and slow tools keep their dimensions",
            "interval": "1m",
            "input_series": [
                series(metric, "0+60x15", labels + f',le="{bound}"')
                for metric, labels in (
                    ("xcagi_tool_duration_ms_bucket", 'tool="inventory",status="failure"'),
                    (
                        "xcagi_model_phase_duration_ms_bucket",
                        'source="provider",phase="response_wait"',
                    ),
                )
                for bound in ("100", "+Inf")
            ],
            "promql_expr_test": [
                {
                    "expr": expressions[id],
                    "eval_time": "15m",
                    "exp_samples": [{"labels": labels, "value": 95}],
                }
                for id, labels in (
                    (12, '{tool="inventory",status="failure"}'),
                    (11, '{source="provider",phase="response_wait"}'),
                )
            ],
        }
    )
    timestamp = series("xcagi_agent_diagnostic_last_complete_scan_timestamp_seconds", "0+60x20")
    findings = series(
        "xcagi_agent_diagnostic_findings", "1+0x20", 'layer="runtime",kind="progress_stalled"'
    )
    fresh_alert = {
        "exp_labels": {"severity": "warning"},
        "exp_annotations": {
            "summary": "Agent 最近完整扫描发现进度、队列、租约或期限异常",
            "description": "仅消费5分钟内完成的诊断快照。合法审批、子任务和质检等待不计为卡死；查看原任务与修复候选证据，不重放未知写入。",
        },
    }
    for name, inputs, expected in (
        ("fresh complete diagnosis raises progress alert", [timestamp, findings], [fresh_alert]),
        (
            "stale diagnosis cannot claim a current stuck task",
            [{**timestamp, "values": "0+0x20"}, findings],
            [],
        ),
        ("missing complete scan cannot turn findings into current facts", [findings], []),
        (
            "legitimate approval waiting never raises progress alert",
            [
                timestamp,
                series(
                    "xcagi_agent_diagnostic_findings",
                    "10+0x20",
                    'layer="runtime",kind="waiting_for_approval"',
                ),
            ],
            [],
        ),
    ):
        tests.append(
            {
                "name": name,
                "interval": "1m",
                "input_series": inputs,
                "alert_rule_test": [
                    {
                        "eval_time": "15m",
                        "alertname": "XcmaxAgentProgressStalled",
                        "exp_alerts": expected,
                    }
                ],
            }
        )
    tests.append(
        {
            "name": "missing diagnostic telemetry explicitly alerts as an observation gap",
            "interval": "1m",
            "input_series": [],
            "alert_rule_test": [
                {
                    "eval_time": "15m",
                    "alertname": "XcmaxAgentDiagnosticScanStale",
                    "exp_alerts": [
                        {
                            "exp_labels": {
                                "severity": "warning",
                                "environment": "production",
                                "service": "fhd",
                            },
                            "exp_annotations": {
                                "summary": "Agent 完整诊断扫描缺失或已陈旧",
                                "description": "尚无完整扫描或距离上次完整扫描超过5分钟。此告警表示观测缺口，不宣称任务卡死；检查扫描健康及有界游标进度。",
                            },
                        }
                    ],
                }
            ],
        }
    )
    tests.append(
        {
            "name": "initial zero scan timestamp is unknown rather than a completed scan",
            "interval": "1m",
            "input_series": [{**timestamp, "values": "0+0x20"}],
            "promql_expr_test": [{"expr": expressions[15], "eval_time": "15m", "exp_samples": []}],
        }
    )
    tests.append(
        {
            "name": "every provisioned panel parses and keeps absent telemetry unknown",
            "interval": "1m",
            "input_series": [],
            "promql_expr_test": [
                {"expr": expression, "eval_time": "15m", "exp_samples": []}
                for expression in expressions.values()
            ],
        }
    )
    return tests


def fixture(rules_file: str) -> dict:
    def series(metric: str, values: str, labels: str = "") -> dict:
        extra = f",{labels}" if labels else ""
        return {"series": f'{metric}{{environment="production"{extra}}}', "values": values}

    def case(name: str, inputs: list[dict], expected: list[float] | None) -> dict:
        return {
            "name": name,
            "interval": "1m",
            "input_series": inputs,
            "promql_expr_test": [
                {
                    "expr": QUERIES[slo_id].format(w="10m"),
                    "eval_time": "10m",
                    "exp_samples": []
                    if expected is None
                    else [{"labels": "{}", "value": expected[index]}],
                }
                for index, slo_id in enumerate(RATIOS)
            ],
        }

    sparse = [
        series("api_requests_total", "0+1x10", 'status="200"'),
        series("api_requests_total", "0+1x10", 'status="500"'),
        series("neurobus_events_published_total", "0+10x10"),
        series("neurobus_events_dead_lettered_total", "0+1x10"),
        series("neurobus_events_lost_total", "0+1x10"),
        series("customer_op_total", "0+8x10", 'status="success"'),
        series("customer_op_total", "0+2x10", 'status="error"'),
        series("mod_install_total", "0+9x10", 'status="success",device_scope="external_customer"'),
        series("mod_install_total", "0+1x10", 'status="error",device_scope="external_customer"'),
        # Large staging/internal counters must not dilute customer production errors.
        {
            "series": 'api_requests_total{environment="staging",status="200"}',
            "values": "0+10000x10",
        },
        series("mod_install_total", "0+10000x10", 'status="success",device_scope="internal"'),
    ]
    successful = [
        series("api_requests_total", "0+1x10", 'status="200"'),
        series("neurobus_events_published_total", "0+1x10"),
        series("customer_op_total", "0+1x10", 'status="success"'),
        series("mod_install_total", "0+1x10", 'status="success",device_scope="external_customer"'),
    ]
    zero = [{**item, "values": "0+0x10"} for item in successful]
    resets = [dict(item) for item in sparse]
    for item in resets[:2]:
        item["values"] = "0 1 2 3 4 0 1 2 3 4 5"
    scrapes = [
        series(
            "up", "1+0x5760", f'job="{job}",instance="{instance}",service="{SCRAPE_SERVICES[job]}"'
        )
        for job, instance in SCRAPE_TARGETS.items()
    ]
    scrape_tests = [
        {
            "name": "successful scrape count includes the whole day",
            "interval": "15s",
            "input_series": scrapes,
            "promql_expr_test": [
                {"expr": expr, "eval_time": "1d", "exp_samples": [{"labels": "{}", "value": 5760}]}
                for expr in SCRAPE_QUERIES.values()
            ],
        },
        {
            "name": "missing target cannot disappear from scrape inventory",
            "interval": "15s",
            "input_series": scrapes[:1],
            "promql_expr_test": [
                {
                    "expr": SCRAPE_QUERIES["modstore-api-production"],
                    "eval_time": "1d",
                    "exp_samples": [],
                }
            ],
        },
        {
            "name": "complete scrape history resolves the coverage alert",
            "interval": "15s",
            "input_series": scrapes,
            "alert_rule_test": [
                {
                    "eval_time": "1d",
                    "alertname": "XcmaxProductionScrapeCoverageBelow99",
                    "exp_alerts": [],
                }
            ],
        },
        {
            "name": "missing samples still alert after scrape recovery",
            "interval": "15s",
            "input_series": [
                series(
                    "up",
                    "1+0x2879 _x2879 1+0x60",
                    'job="fhd-api-stable",instance="127.0.0.1:5100",service="fhd"',
                ),
            ],
            "alert_rule_test": [
                {
                    "eval_time": "24h15m",
                    "alertname": "XcmaxProductionScrapeCoverageBelow99",
                    "exp_alerts": [
                        {
                            "exp_labels": {
                                "job": "fhd-api-stable",
                                "instance": "127.0.0.1:5100",
                                "service": "fhd",
                                "environment": "production",
                                "severity": "warning",
                            },
                            "exp_annotations": {
                                "summary": "fhd 近 24h 抓取覆盖率 50% < 99%",
                                "description": "L4-18 门槛被击穿，SLO 证据将判定为不可采信。",
                            },
                        }
                    ],
                }
            ],
        },
    ]
    return {
        "evaluation_interval": "1m",
        "rule_files": [rules_file],
        "tests": [
            case("sparse traffic retains true failure ratio", sparse, [0.5, 0.5, 0.8, 0.2, 0.9]),
            case("counter reset does not erase failures", resets, [0.5, 0.5, 0.8, 0.2, 0.9]),
            case("observed success with no error series", successful, [1, 0, 1, 0, 1]),
            case("zero samples produce no result, not 100 percent", zero, None),
            case("missing telemetry produces no result", [], None),
        ]
        + scrape_tests
        + agent_fixtures(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--rules-file",
        default=str(Path(__file__).resolve().parents[2] / "ops/monitoring/production-alerts.yml"),
    )
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(fixture(args.rules_file), indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
