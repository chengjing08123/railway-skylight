# -*- coding: utf-8 -*-
"""check_clauses.py —— 条文原文补录的自检工具（成员二每天跑一次）

    python check_clauses.py

检查项：
  1. P0 三条（作业单元 / 时长 / 配合）是否已有原文与来源
  2. 判定用条目（有 conflict_type）的 text 是否够长
  3. rule_ref 是否重复
  4. 是否有未确认的「第 X 类」写法（规则原文未必这样编号）
  5. 原文条目是否都记了来源

退出码：0 全绿；1 有未完成项。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
KB = HERE / "clauses.json"

P0_TYPES = ("作业单元冲突", "时长冲突", "配合缺失")
MIN_LEN = 15


def main() -> int:
    data = json.loads(KB.read_text(encoding="utf-8-sig"))
    clauses = data.get("clauses", [])
    pending = data.get("pending", [])

    print(f"条目库 v{data.get('version')}：{len(clauses)} 条判定用 + {len(pending)} 条待补\n")

    problems = 0

    print("一、P0 三条（对外口径靠它）")
    for c in clauses:
        if c.get("conflict_type") not in P0_TYPES:
            continue
        has = bool((c.get("text") or "").strip())
        src = bool((c.get("source") or "").strip())
        mark = "✅" if (has and src) else "❌"
        print(f"  {mark} {c['rule_ref']:>12}  {c['conflict_type']:<8} "
              f"原文{'有' if has else '无'} / 来源{'有' if src else '无'}")
        if not (has and src):
            problems += 1

    print("\n二、全部条目")
    refs: dict[str, int] = {}
    for c in clauses:
        refs[c["rule_ref"]] = refs.get(c["rule_ref"], 0) + 1
        t = (c.get("text") or "").strip()
        status = "原文" if t else "摘要"
        warn = ""
        if t and len(t) < MIN_LEN:
            warn += " ⚠ 原文过短"
            problems += 1
        if "第 1 类" in c["rule_ref"] or "第 2 类" in c["rule_ref"]:
            warn += " ⚠ 含「第 X 类」，需确认原文是否这样编号"
            problems += 1
        if t and not (c.get("source") or "").strip():
            warn += " ⚠ 有原文但没记来源"
            problems += 1
        print(f"  [{status}] {c['rule_ref']:>12}  {c.get('conflict_type') or '—':<8}{warn}")

    print("\n三、rule_ref 重复检查")
    dup = {k: v for k, v in refs.items() if v > 1}
    if dup:
        # 同一条文被两类冲突共用是正常的（2.2.10 就同时管单元与负责人）
        print("  提示（同一条文被多条规则引用，通常正常）：", dup)
    else:
        print("  无重复")

    if pending:
        print(f"\n四、待补清单（P1，不影响 P0 验收）：{len(pending)} 条")
        print("  " + "、".join(p["rule_ref"] for p in pending))

    done = sum(1 for c in clauses if (c.get("text") or "").strip())
    print(f"\n小计：原文 {done}/{len(clauses)} 条" + (f"，待补 {len(pending)} 条" if pending else ""))

    if problems:
        print(f"\n❌ 还有 {problems} 处未完成。补完再跑一次。")
        return 1
    print("\n✅ 全绿：P0 有原文有来源，无格式风险项。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
