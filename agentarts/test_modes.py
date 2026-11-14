# -*- coding: utf-8 -*-
"""test_modes.py —— 本地把五个 mode 全跑一遍，不联网、不部署。

    python test_modes.py

不依赖 AgentArts SDK：直接测 dispatch.handle_invocation —— 平台入口 app.py
只是把它包一层，所以这里过了，云端行为就是一致的（除了模型措辞）。
"""
from __future__ import annotations

import json
import sys

sys.stdout.reconfigure(encoding="utf-8")

import dispatch  # noqa: E402
import local_test  # noqa: E402

WINDOW = {"windowStart": "07:30", "windowEnd": "09:20"}

_failed = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global _failed
    if not cond:
        _failed += 1
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))


def line(title: str) -> None:
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def main() -> int:
    tasks = local_test.load_tasks()
    print(f"数据：{len(tasks)} 条作业，天窗 07:30—09:20（110 分钟），条款库 {len(dispatch.KB)} 条")

    # ---------------------------------------------------------- 0 向后兼容
    line("0. 不传 mode —— 必须与部署 v1 行为一致（CHECK）")
    out = dispatch.handle_invocation({"window": WINDOW, "tasks": tasks})
    check("mode 回显 CHECK", out.get("mode") == "CHECK", str(out.get("mode")))
    check("冲突 10 条", out.get("conflictCount") == 10, str(out.get("conflictCount")))
    check("带 clauseRefs", bool(out.get("clauseRefs")), str(out.get("clauseRefs")))
    check("正文提到 10 条", "10 条" in out["response"])
    print("  --- 正文前 3 行 ---")
    for ln in out["response"].splitlines()[:3]:
        print("  " + ln)

    # ---------------------------------------------------------- 1 ORCHESTRATE
    line("1. ORCHESTRATE —— 只编排，出两套带代价的方案")
    out = dispatch.handle_invocation({"mode": "ORCHESTRATE", "window": WINDOW, "tasks": tasks})
    plans = out.get("plans") or []
    check("两套方案", len(plans) == 2, str([p.get("planId") for p in plans]))
    check("每套都有 cost.quantified", all("quantified" in (p.get("cost") or {}) for p in plans))
    check("回包里不带 tasks（省流量）", all("tasks" not in p for p in plans))
    check("有留痕 trace", "trace" in out and len(out["trace"]["events"]) >= 1)
    for p in plans:
        q = p["cost"]["quantified"]
        print(f"  方案 {p['planId']}｜{p['name']}：冲突 {q['冲突']}，"
              f"延期 {q['延期作业']} 条 / {q['延期天数']} 天")

    # ---------------------------------------------------------- 2 CHECK_PLAN
    line("2. CHECK_PLAN —— 只核查单个方案（不经模型）")
    plan_a = plans[0]
    plan_b = plans[1]
    # 只编排时回包剥了 tasks，单点核查要显式给回作业列表
    plan_a_full = {**plan_a, "tasks": [t for t in tasks if "检查" not in (t.get("team") or "")]}
    ra = dispatch.handle_invocation({"mode": "CHECK_PLAN", "window": WINDOW, "plan": plan_a_full})
    check("方案 A 冲突归零", ra.get("conflictCount") == 0, str(ra.get("conflictCount")))
    rb = dispatch.handle_invocation({"mode": "CHECK_PLAN", "window": WINDOW,
                                     "plan": {**plan_b, "tasks": tasks}})
    check("方案 B 冲突 10 条", rb.get("conflictCount") == 10, str(rb.get("conflictCount")))
    check("方案 B 严重 6 条", rb.get("severe") == 6, str(rb.get("severe")))
    check("核查正文可追溯", "2.2.10 第 1 款" in rb["response"])

    # ---------------------------------------------------------- 3 ARBITRATE
    line("3. ARBITRATE —— 只仲裁，给建议 + 退路（不拍板）")
    out = dispatch.handle_invocation({"mode": "ARBITRATE", "window": WINDOW, "tasks": tasks})
    v = out.get("verdict") or {}
    check("建议 A", v.get("recommended") == "A", str(v.get("recommended")))
    check("不替人决定", v.get("requiresHumanChoice") is True)
    check("给退路且引条文", "2.2.10 第 1 款" in (v.get("fallback") or ""))
    check("options 两套", len(v.get("options") or []) == 2)
    print("  理由：" + (v.get("reason") or "")[:160])

    # 跨运行时场景：仲裁者收到的是「精简版 checks」（只有计数，没有 conflicts 明细）
    slim = [{"planId": "A", "conflictCount": 0, "severe": 0, "normal": 0},
            {"planId": "B", "conflictCount": 10, "severe": 6, "normal": 4}]
    out = dispatch.handle_invocation({"mode": "ARBITRATE", "window": WINDOW,
                                      "tasks": tasks, "plans": plans, "checks": slim})
    check("精简 checks 也能仲裁",
          out.get("status") == "ok" and (out.get("verdict") or {}).get("recommended") == "A",
          f"status={out.get('status')}")

    # ---------------------------------------------------------- 4 NEGOTIATE
    line("4. NEGOTIATE —— 全链路：编排 → 核查 → 仲裁 + 留痕")
    out = dispatch.handle_invocation({"mode": "NEGOTIATE", "window": WINDOW, "tasks": tasks})
    check("建议 A", (out.get("verdict") or {}).get("recommended") == "A")
    ev = (out.get("trace") or {}).get("events") or []
    kinds: dict[str, int] = {}
    for e in ev:
        kinds[e["type"]] = kinds.get(e["type"], 0) + 1
    check("留痕 5 条事件（4 message + 1 decision）", len(ev) == 5, json.dumps(kinds, ensure_ascii=False))
    check("协商正文引 2.2.10 第 1 款", "2.2.10 第 1 款" in out["response"])
    check("正文含两套方案", "方案 A" in out["response"] and "方案 B" in out["response"])
    check("conflictCount = 建议方案的冲突数", out.get("conflictCount") == 0, str(out.get("conflictCount")))
    check("sessionId 非空", bool(out.get("sessionId")), str(out.get("sessionId")))

    # 幂等：同一批作业同一个 mode，两次调用同一个会话号
    out2 = dispatch.handle_invocation({"mode": "NEGOTIATE", "window": WINDOW, "tasks": tasks})
    check("会话号幂等", out2.get("sessionId") == out.get("sessionId"))

    # ---------------------------------------------------------- 5 容错
    line("5. 容错")
    out = dispatch.handle_invocation({"mode": "negotiate", "window": WINDOW, "tasks": tasks})
    check("小写 mode 也认", out.get("mode") == "NEGOTIATE", str(out.get("mode")))
    out = dispatch.handle_invocation({"mode": "check-plan", "window": WINDOW, "tasks": tasks})
    check("中划线写成 check-plan 也认", out.get("mode") == "CHECK_PLAN", str(out.get("mode")))
    out = dispatch.handle_invocation({"mode": "FOO", "window": WINDOW, "tasks": tasks})
    check("未知 mode 报错且列出可用值", out.get("status") == "error" and "NEGOTIATE" in out["response"])
    out = dispatch.handle_invocation({"mode": "CHECK", "tasks": []})
    check("空作业列表给契约提示", out.get("status") == "error" and "tasks" in out["response"])
    out = dispatch.handle_invocation(json.dumps({"mode": "CHECK", "window": WINDOW,
                                                 "tasks": tasks[:2]}))
    check("入参是字符串也能解析", out.get("status") == "ok", str(out.get("status")))

    # ---------------------------------------------------------- 6 taskMode（业务模式）
    line("6. taskMode —— 业务模式分派（方案 v1.3 表 4）")
    out = dispatch.handle_invocation({"taskMode": "PRE_REVIEW", "window": WINDOW, "tasks": tasks})
    check("PRE_REVIEW 走通", out.get("status") == "ok", str(out.get("status")))
    check("回显 taskMode", out.get("taskMode") == "PRE_REVIEW")
    check("标注实际 mode", out.get("taskModeImpl") == "NEGOTIATE", str(out.get("taskModeImpl")))
    check("给仲裁建议", (out.get("verdict") or {}).get("recommended") == "A")
    check("给冲突清单（含分界点要求）",
          len(out.get("conflicts") or []) == 10
          and "分界点" in (out["conflicts"][0].get("suggestion") or ""),
          f"{len(out.get('conflicts') or [])} 条")
    for tm in ("SIGN_REVIEW", "BRIEF"):
        out = dispatch.handle_invocation({"taskMode": tm, "window": WINDOW, "tasks": tasks})
        check(f"{tm} 明确回 not_implemented",
              out.get("status") == "not_implemented" and "PRE_REVIEW" in out["response"],
              str(out.get("status")))
    out = dispatch.handle_invocation({"taskMode": "pre-review", "window": WINDOW, "tasks": tasks})
    check("小写+中划线的 taskMode 也认", out.get("taskMode") == "PRE_REVIEW")
    out = dispatch.handle_invocation({"taskMode": "FOO", "window": WINDOW, "tasks": tasks})
    check("未知 taskMode 报错", out.get("status") == "error")

    # ---------------------------------------------------------- 样例输出
    line("样例：NEGOTIATE 正文（云端返回的就是这一段）")
    print(dispatch.handle_invocation(
        {"mode": "NEGOTIATE", "window": WINDOW, "tasks": tasks})["response"])

    print("\n" + ("全部通过" if _failed == 0 else f"有 {_failed} 项失败"))
    return 0 if _failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
