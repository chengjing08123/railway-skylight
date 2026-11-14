# -*- coding: utf-8 -*-
"""local_test.py —— 不部署、不联网，本地跑一遍四节点，看输出长什么样。

    python local_test.py            # 模板模式（不调模型）
    python local_test.py --llm      # 调 MaaS（需要 .env 里有 MODEL_API_KEY）
"""
from __future__ import annotations

import asyncio
import csv
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

import agent_core  # noqa: E402

DATA = Path(r"C:\Users\21264\ds harness work\work\tools\data")


def load_tasks() -> list[dict]:
    rows = []
    with open(DATA / "tasks_0923.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            r = {(k or "").strip(): (v or "").strip() for k, v in r.items()}
            units = [u.strip() for u in (r.get("unit_ids") or "").split(";") if u.strip()]
            sw = [s.strip() for s in (r.get("switches") or "").split("|") if s.strip()]
            mf, mt = r.get("mile_from", ""), r.get("mile_to", "")
            rows.append({
                "taskId": r["task_id"], "serialNo": int(r["no"]), "team": r["team"],
                "unitCodes": units, "start": r["t_start"], "end": r["t_end"],
                "mileFrom": int(mf) if mf.isdigit() else None,
                "mileTo": int(mt) if mt.isdigit() else None,
                "switches": sw,
            })
    return rows


def main() -> int:
    payload = {
        "window": {"windowId": 9, "windowStart": "07:30", "windowEnd": "09:20"},
        "tasks": load_tasks(),
        "detectDuration": False,
    }

    out = agent_core.run(payload)
    print("=" * 64)
    print(out["answer"])
    print("=" * 64)
    print(f"冲突 {out['result']['conflictCount']} 条 / 引用条文 {out['clauseRefs']} / "
          f"无依据条号 {out['uncited'] or '无'}")

    if "--llm" in sys.argv:
        print("\n\n—— 大模型版本 ——\n")
        tasks, window = agent_core.parse_payload(payload)
        from skylight_rules import check_window
        result = check_window(tasks, window)
        clauses = agent_core.retrieve(result["conflicts"], agent_core.load_kb())
        text = agent_core.render_llm(result, clauses, window)
        print(text)
        print(f"\n引用校验：{agent_core.validate_citations(text, clauses) or '全部可追溯'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
