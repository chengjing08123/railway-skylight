# -*- coding: utf-8 -*-
"""eval_full.py —— 全量 55 条的检出率 / 误报率，产出方案与初赛材料里那三个数

跑法（不联网、不装依赖，只用标准库）：
    python eval_full.py

它算的就是对外报的三个数：
    标注 14 对 / 检出 13 对 / 误报 0 对   →  检出率 92.9%、误报率 0%

口径（写材料时照抄，别再出现「92.9% 但不说分母」）：
    作业单元冲突 = 按天窗分组后两两成对；一对算一条正例
    宽口径 = gold 里全部单元冲突对（A+B）        → 对外报这个
    严口径 = 只算 tier=A 的对                   → 只用来算检出率，不用来算误报率

数据从哪来：**评测集不入库**（tasks_55.csv 含真实姓名与电话）。把这两个 CSV 放在
本机任意目录，用环境变量 `EVAL_DATA_DIR` 指过去即可：

    $env:EVAL_DATA_DIR = "D:/your/path/to/data"
    python eval_full.py

为什么要有这个文件：方案 7.4 与初赛信息表都写着「92.9%，eval_full.py 可复现」。
以前那个「可复现」依赖绝对路径，换台机器就失效；现在只要把评测集放好、
指一下 EVAL_DATA_DIR，clone 下来就能跑。
"""
from __future__ import annotations

import csv
import os
import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from skylight_rules import check_window  # noqa: E402


def data_dir() -> Path:
    env = os.getenv("EVAL_DATA_DIR", "").strip()
    if env:
        return Path(env)
    local = HERE / "eval"
    if (local / "tasks_55.csv").exists():
        return local
    raise SystemExit(
        f"找不到评测集。评测集不入库（含真实姓名与电话），请自备后指路：\n"
        f"  $env:EVAL_DATA_DIR = \"<含 tasks_55.csv 与 gold_55.csv 的目录>\"\n"
        f"  python eval_full.py"
    )


def load_tasks(path: Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            r = {(k or "").strip(): (v or "").strip() for k, v in r.items()}
            units = [u.strip() for u in (r.get("unit_ids") or "").split(";") if u.strip()]
            sw = [s.strip() for s in (r.get("switches") or "").split("|") if s.strip()]
            mf, mt = r.get("mile_from", ""), r.get("mile_to", "")
            rows.append({
                "taskId": r["task_id"],
                "serialNo": int(r["no"]),
                "team": r["team"],
                "unitCodes": units,
                "start": r["t_start"],
                "end": r["t_end"],
                "mileFrom": int(mf) if mf.lstrip("-").isdigit() else None,
                "mileTo": int(mt) if mt.lstrip("-").isdigit() else None,
                "switches": sw,
                "winStart": r.get("window_start", ""),
                "winEnd": r.get("window_end", ""),
            })
    return rows


def load_gold(path: Path) -> tuple[set, set]:
    wide, strict = set(), set()
    with open(path, encoding="utf-8-sig") as f:
        for g in csv.DictReader(f):
            g = {(k or "").strip(): (v or "").strip() for k, v in g.items()}
            if g.get("is_conflict") != "1" or g.get("conflict_type") != "作业单元冲突":
                continue
            peer = g.get("peer_task_id", "")
            if not peer:
                continue
            pair = frozenset((g["task_id"], peer))
            wide.add(pair)
            if g.get("tier") == "A":
                strict.add(pair)
    return wide, strict


def predict(tasks: list[dict]) -> set:
    """按天窗分组跑判定。不同天窗的作业不可能撞，混在一起算会出假冲突。"""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for t in tasks:
        if t["winStart"]:
            groups[(t["winStart"], t["winEnd"])].append(t)
    got = set()
    for (ws, we), group in groups.items():
        if len(group) < 2:
            continue
        for c in check_window(group, {"windowStart": ws, "windowEnd": we})["conflicts"]:
            if c["type"] == "作业单元冲突":
                got.add(frozenset(c["involved"]))
    return got


def rate(gold: set, got: set) -> tuple[int, int, int]:
    return len(gold & got), len(gold - got), len(got - gold)


def main() -> int:
    d = data_dir()
    tasks = load_tasks(d / "tasks_55.csv")
    wide, strict = load_gold(d / "gold_55.csv")
    got = predict(tasks)
    in_win = [t for t in tasks if t["winStart"]]
    windows = len({(t["winStart"], t["winEnd"]) for t in in_win})

    h, m, e = rate(wide, got)
    rec = h / len(wide) if wide else 0.0
    fp = e / len(got) if got else 0.0

    print(f"评测集：{d}")
    print(f"tasks={len(tasks)}  有窗={len(in_win)}  天窗组={windows}")
    print(f"预测对={len(got)}   gold 宽口径={len(wide)}   gold 严口径={len(strict)}")
    print()
    print(f"宽口径（A+B）：命中 {h} / 漏 {m} / 多报 {e}  →  检出率 {rec:.1%}  误报率 {fp:.1%}")
    hs, ms, es = rate(strict, got)
    print(f"严口径（仅 A）：命中 {hs} / 漏 {ms} / 多报 {es}  →  检出率 {hs / len(strict):.1%}"
          if strict else "严口径：无 A 类正例")
    print("    注：严口径只算检出率。用同一份预测算误报率，被排除的 B 类全会变成「误报」，"
          "得出的数没有意义，不要采用。")
    if m:
        print("\n漏报明细：")
        for pair in sorted(wide - got, key=lambda s: sorted(s)):
            print("  ", " × ".join(sorted(pair)))
    if e:
        print("\n多报明细：")
        for pair in sorted(got - wide, key=lambda s: sorted(s)):
            print("  ", " × ".join(sorted(pair)))

    print()
    print("对外一句话："
          f"55 条日计划（{len(in_win)} 条点内、{windows} 个天窗）检出 {len(got)} 对作业单元冲突，"
          f"人工标注 {len(wide)} 对，检出率 {rec:.1%}、误报率 {fp:.1%}。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
