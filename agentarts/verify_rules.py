# -*- coding: utf-8 -*-
"""verify_rules.py —— 证明 Python 版判定与 Java 版、与 gold 完全一致。

跑法（无需任何依赖，纯标准库）：
    python verify_rules.py
期望：
    gold 10 对 / Python 10 对 / 命中 10 / 漏 0 / 多报 0
    其中 严重 6 条、一般 4 条
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from skylight_rules import check_window  # noqa: E402

DATA = Path(r"C:\Users\21264\ds harness work\work\tools\data")


def load_tasks() -> list[dict]:
    rows = []
    with open(DATA / "tasks_0923.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            r = {(k or "").strip(): (v or "").strip() for k, v in r.items()}
            units = [u.strip() for u in (r.get("unit_ids") or "").split(";") if u.strip()]
            sw = [s.strip() for s in (r.get("switches") or "").split("|") if s.strip()]
            mf = r.get("mile_from", "")
            mt = r.get("mile_to", "")
            rows.append({
                "taskId": r["task_id"],
                "serialNo": int(r["no"]),
                "team": r["team"],
                "unitCodes": units,
                "start": r["t_start"],
                "end": r["t_end"],
                "mileFrom": int(mf) if mf.isdigit() else None,
                "mileTo": int(mt) if mt.isdigit() else None,
                "switches": sw,
            })
    return rows


def load_gold() -> set[frozenset]:
    gold = set()
    with open(DATA / "gold_0923.csv", encoding="utf-8") as f:
        for g in csv.DictReader(f):
            g = {k.strip(): (v or "").strip() for k, v in g.items()}
            if g.get("is_conflict") != "1" or g.get("conflict_type") != "作业单元冲突":
                continue
            a = int(re.search(r"-(\d+)$", g["task_id"]).group(1))
            b = int(re.search(r"-(\d+)$", g["peer_task_id"]).group(1))
            gold.add(frozenset((a, b)))
    return gold


def main() -> int:
    tasks = load_tasks()
    resp = check_window(tasks, {"windowStart": "07:30", "windowEnd": "09:20"})

    got = {frozenset(c["serialNos"]) for c in resp["conflicts"]}
    gold = load_gold()
    hit, missed, extra = gold & got, gold - got, got - gold
    severe = sum(1 for c in resp["conflicts"] if c["severity"] == "严重")
    normal = sum(1 for c in resp["conflicts"] if c["severity"] == "一般")

    print(f"tasks={resp['taskCount']} conflicts={resp['conflictCount']}")
    print(f"gold {len(gold)} 对 / Python {len(got)} 对 / 命中 {len(hit)}")
    print(f"漏 {sorted(map(tuple, map(sorted, missed)))}")
    print(f"多报 {sorted(map(tuple, map(sorted, extra)))}")
    print(f"严重 {severe} / 一般 {normal}")

    ok = (len(got) == len(gold) == len(hit) == 10 and not missed and not extra
          and severe == 6 and normal == 4)
    print("结论：", "PASS 与 Java 版、与 gold 完全一致" if ok else "FAIL 与预期不符")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
