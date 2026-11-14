# -*- coding: utf-8 -*-
"""test_negotiate.py —— 用 9/23 真实窗口跑一次完整协商，打印 A/B 两套方案与裁决。

    python test_negotiate.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

import local_test
import multi_agent

WINDOW = {"windowStart": "07:30", "windowEnd": "09:20"}


def main() -> int:
    tasks = local_test.load_tasks()
    out = multi_agent.negotiate(tasks, WINDOW, session_id="S-0923-01")

    print("=" * 72)
    print(f"参与协商：{len(tasks)} 条作业，天窗 07:30—09:20（110 分钟）")
    print("=" * 72)

    for plan, chk in zip(out["plans"], out["checks"]):
        cost = plan["cost"]
        q = cost["quantified"]
        print(f"\n【方案 {plan['planId']}｜{plan['name']}】")
        print(f"  做法：{plan['rationale']}")
        print(f"  影响：{cost['affectedTeam']}")
        print(f"  工作量：{cost['workloadRisk']}")
        print(f"  安全：{cost['safetyGain']}")
        print(f"  量化：冲突 {q['冲突']}，延期作业 {q['延期作业']} 条，延期 {q['延期天数']} 天")
        print(f"  核查：冲突 {chk['conflictCount']} 条（严重 {chk['severe']} / 提示 {chk['normal']}）")

    v = out["verdict"]
    print("\n" + "-" * 72)
    print(f"仲裁建议：方案 {v['recommended']}（{v['recommendedName']}）")
    print(f"  理由：{v['reason']}")
    print(f"  退路：{v['fallback']}")
    print(f"  最终决定权：{'人（智能体只摆选项，不代签）' if v['requiresHumanChoice'] else '智能体'}")

    ev = out["trace"]["events"]
    kinds: dict[str, int] = {}
    for e in ev:
        kinds[e["type"]] = kinds.get(e["type"], 0) + 1
    print(f"\n留痕：{len(ev)} 条事件 {kinds}")

    Path("negotiate_sample.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("完整结果 → negotiate_sample.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
