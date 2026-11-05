#!/usr/bin/env python3
"""逐项驱动 macOS 验收：每项录一段 webm、一张结果截图、一份 run.log 与 draft-run.json。

用法：python3 acc_run.py [feature-id ...]   （缺省跑全部规格；界面操作严格串行）
"""

from __future__ import annotations

import json
import sys
import time

import acc_core as a
from acc_dsl import R
from acc_specs import SPECS

CATALOG = a.REPO / "成都修茈科技有限公司/data/capabilities/catalog.json"


def names() -> dict:
    c = json.loads(CATALOG.read_text(encoding="utf-8"))
    return {f["id"]: f["name"] for d in c["domains"] for m in d["modules"] for f in m["features"]}


def main(ids: list[str]):
    ident, nm = a.identity(), names()
    p = a.Page()
    p.hook_net()
    summary = {}
    for fid in ids or list(SPECS):
        p.ensure_front()
        p.go("/", wait=1.5)
        F = a.Feature(p, fid, nm.get(fid, fid))
        F.log(f"开始验收 {fid} {F.name}；被测 {ident}")
        F.rec_start()
        try:
            SPECS[fid](R(p, F))
        except Exception as exc:  # noqa: BLE001
            F.log(f"规格执行异常 {type(exc).__name__}: {exc}")
        time.sleep(1.0)
        F.shot("result")
        F.rec_stop("operation")
        d = F.finish(ident)
        summary[fid] = f"{d['status']} {d['passed']}/{d['passed'] + d['failed']}"
        print(f"== {fid}: {summary[fid]}", flush=True)
    p.close()
    print(json.dumps(summary, ensure_ascii=False, indent=0))


if __name__ == "__main__":
    main(sys.argv[1:])
