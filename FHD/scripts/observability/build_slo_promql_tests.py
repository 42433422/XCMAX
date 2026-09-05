#!/usr/bin/env python3
"""Generate isolated promtool tests using the collector's actual expressions.

Synthetic fixtures are never submitted to production Prometheus or SLO evidence.
The JSON output is also valid YAML for `promtool test rules`.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from collect_slo_metrics import QUERIES, SCRAPE_QUERIES, SCRAPE_TARGETS

RATIOS = ("SLO-API-01", "SLO-API-03", "SLO-BUS-01", "SLO-BIZ-02", "SLO-BIZ-05")


def fixture() -> dict:
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
        series("up", "1+0x5760", f'job="{job}",instance="{instance}"')
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
    ]
    return {
        "evaluation_interval": "1m",
        "tests": [
            case("sparse traffic retains true failure ratio", sparse, [0.5, 0.5, 0.8, 0.2, 0.9]),
            case("counter reset does not erase failures", resets, [0.5, 0.5, 0.8, 0.2, 0.9]),
            case("observed success with no error series", successful, [1, 0, 1, 0, 1]),
            case("zero samples produce no result, not 100 percent", zero, None),
            case("missing telemetry produces no result", [], None),
        ]
        + scrape_tests,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(fixture(), indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
