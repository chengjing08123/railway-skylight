# -*- coding: utf-8 -*-
"""multi_agent.py —— 最小多智能体：编排 / 核查 / 仲裁

对应《项目方案 v1.2》4.5 节的 PLAN_AND_NEGOTIATE 环节，砍到三个角色：

    编排者  ORCHESTRATOR  把一次冲突拆成 A / B 两套候选方案，各自带「代价」
    核查者  CHECKER       对每个方案跑确定性判定，返回冲突数（不参与生成）
    仲裁者  ARBITER       对比冲突数与代价，给出建议 + 理由（引条文）

三条设计约束（照方案原文）：
    1. 协作负载是**结构化契约**，不是自由文本 —— 每个角色只收发 dict；
    2. 判定不经过模型 —— 核查者调用 skylight_rules，模型只负责措辞；
    3. 每一步留痕 —— 产出 session / message / decision 三类事件。

与 AgentArts 的映射有两套，见 DESIGN-多智能体.md。
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field, asdict
from typing import Any

from skylight_rules import check_window

sys.stdout.reconfigure(encoding="utf-8")

ROLE_ORCH = "ORCHESTRATOR"
ROLE_CHK = "CHECKER"
ROLE_ARB = "ARBITER"


# ---------------------------------------------------------------- 留痕
@dataclass
class Trace:
    """一次编排的留痕。对应方案里的 agent_session / agent_message / agent_decision。"""
    session_id: str
    events: list[dict] = field(default_factory=list)

    def msg(self, speaker: str, to: str, kind: str, payload: Any) -> None:
        self.events.append({
            "type": "message", "speaker": speaker, "to": to,
            "kind": kind, "payload": payload,
        })

    def decide(self, by: str, choice: str, reason: str) -> None:
        self.events.append({
            "type": "decision", "by": by, "choice": choice, "reason": reason,
        })

    def as_dict(self) -> dict:
        return {"sessionId": self.session_id, "events": self.events}


# ---------------------------------------------------------------- ① 编排
def orchestrate(tasks: list[dict], window: dict) -> list[dict]:
    """把「全员占满整个天窗」拆成两套真正不同的候选方案。

    真实数据里 12 条作业的时段都填成 07:30—09:20（整窗），所以**任何时段压缩都
    消不掉重叠** —— 压缩后仍然落满窗作业的区间里。能消除重叠的只有两条路：

      A 顺延：「检查工区」6 条作业移出本天窗，另排
        —— 冲突归零，代价是这 6 条作业延期，检查计划被打断
      B 分界：全部保留，冲突全部转为「需人工划分界点」
        —— 作业量不损失，代价是 10 条重叠仍需车务段逐条协调，安全风险未消除

    这不是两个技术方案，是两个价值取向：**安全优先 vs 作业量优先**。
    方案文档里「代价是必填字段，不是描述性文字」，指的就是这一栏。
    """
    inspection = [t for t in tasks if "检查" in (t.get("team") or "")]
    others = [t for t in tasks if "检查" not in (t.get("team") or "")]

    plan_a = {
        "planId": "A",
        "name": "检查工区顺延",
        "tasks": others,                       # 只留线路工区，冲突应归零
        "movedTasks": [t["serialNo"] for t in inspection],
        "cost": {
            "affectedTeam": "萍乡检查工区",
            "movedCount": len(inspection),
            "workloadRisk": f"{len(inspection)} 条检查作业需另排天窗，可能延后 1 天",
            "safetyGain": "重叠消除，天窗内无跨工区交叉作业",
            "quantified": {"冲突": "归零", "延期作业": len(inspection), "延期天数": "1"},
        },
        "rationale": "安全优先：宁可变更检查计划，也不留下 6 条严重重叠。",
    }

    plan_b = {
        "planId": "B",
        "name": "保留全部 · 分区分界",
        "tasks": tasks,                        # 全保留，靠人工划分界点化解
        "movedTasks": [],
        "cost": {
            "affectedTeam": "萍乡新场线路工区 + 萍乡检查工区",
            "movedCount": 0,
            "workloadRisk": "作业量不损失，但 6 条严重重叠需车务段逐条指定主体单位并划分界点",
            "safetyGain": "无 —— 重叠仍在，只靠协调与防护措施控制",
            "quantified": {"冲突": "维持 10 条", "延期作业": 0, "延期天数": 0},
        },
        "rationale": "作业量优先：不动计划，用协调与防护消化重叠。",
    }
    return [plan_a, plan_b]

# ---------------------------------------------------------------- ② 核查
def check_plan(plan: dict, window: dict) -> dict:
    """对单个方案跑确定性判定 —— 这一步不经过模型。"""
    res = check_window(plan["tasks"], window, detect_duration=False)
    severe = sum(1 for c in res["conflicts"] if c["severity"] == "严重")
    normal = sum(1 for c in res["conflicts"] if c["severity"] != "严重")
    return {
        "planId": plan["planId"],
        "conflictCount": res["conflictCount"],
        "severe": severe,
        "normal": normal,
        "conflicts": res["conflicts"],
    }


# ---------------------------------------------------------------- ③ 仲裁
def _moved(plan: dict) -> int:
    """方案的变动量。外部传入的方案可能没有 cost，按 0 处理。"""
    cost = plan.get("cost") or {}
    val = cost.get("movedCount", 0)
    try:
        return int(val or 0)
    except (TypeError, ValueError):
        return 0


def _quant(plan: dict) -> dict:
    return (plan.get("cost") or {}).get("quantified") or {}


def arbitrate(checked: list[dict], plans: list[dict]) -> dict:
    """对比两套方案，给出建议 —— 但**不替人做决定**。

    方案原文：「智能体不签、不代签、不催签。它只负责把空格摆出来，让空格看得见。」
    所以这里输出的是「建议 + 明确的取舍条件」，而不是一个拍板的答案。

    判据（确定性）：
      1. 先看严重冲突数：谁少谁优；
      2. 差距为 0 时，比「延期作业数」；
      3. 再相同，比「延期天数」。
    """
    by_id = {c["planId"]: c for c in checked}
    plans = [p for p in plans if p.get("planId") in by_id]
    if len(plans) < 2:
        return {
            "recommended": None,
            "recommendedName": "",
            "reason": "可比较的方案不足两套，无法给出建议。",
            "requiresHumanChoice": True,
            "fallback": "请提供两套方案，或省略 plans 由本机先编排两套。",
            "options": [],
        }

    pa, pb = plans[0], plans[1]
    ca, cb = by_id[pa["planId"]], by_id[pb["planId"]]

    def severe(c: dict) -> int:
        return int(c.get("severe") or 0)

    def count(c: dict) -> int:
        return int(c.get("conflictCount") or 0)

    # 安全优先：严重冲突少者胜；平了再比总冲突；再平比变动量
    if severe(ca) != severe(cb):
        win = pa if severe(ca) < severe(cb) else pb
        lose = pb if win is pa else pa
        reason = (f"方案 {win['planId']} 严重冲突 {severe(by_id[win['planId']])} 条，"
                  f"方案 {lose['planId']} 为 {severe(by_id[lose['planId']])} 条；"
                  f"安全优先取 {win['planId']}。")
    elif count(ca) != count(cb):
        win = pa if count(ca) < count(cb) else pb
        lose = pb if win is pa else pa
        reason = (f"两方案严重冲突相同，方案 {win['planId']} 总冲突更少"
                  f"（{count(by_id[win['planId']])} vs {count(by_id[lose['planId']])}）。")
    else:
        win = pa if _moved(pa) <= _moved(pb) else pb
        reason = "两方案冲突数相同，取变动更小的那套。"

    other = pb if win is pa else pa
    qa, qb = _quant(pa), _quant(pb)

    reason_full = (
        f"{reason}"
        f"方案 A：冲突 {qa.get('冲突', '—')}，延期作业 {qa.get('延期作业', '—')} 条；"
        f"方案 B：冲突 {qb.get('冲突', '—')}，延期作业 {qb.get('延期作业', '—')} 条。"
        f"建议取 {win['planId']}（{win.get('name', '')}）——{win.get('rationale', '')}"
    )

    return {
        "recommended": win["planId"],
        "recommendedName": win.get("name", ""),
        "reason": reason_full,
        "requiresHumanChoice": True,
        "fallback": (f"若方案 {win['planId']} 的代价不可接受 → 改取方案 {other['planId']}"
                     f"（{other.get('name', '')}），并按 2.2.10 第 1 款由车务段逐条"
                     f"指定主体单位、划分界点"),
        "options": [
            {"planId": p["planId"], "name": p.get("name", ""),
             "conflictCount": count(by_id[p["planId"]]),
             "severe": severe(by_id[p["planId"]]),
             "moved": _moved(p),
             "quantified": _quant(p)}
            for p in plans
        ],
    }

# ---------------------------------------------------------------- 串起来
def negotiate(tasks: list[dict], window: dict, session_id: str = "S-1") -> dict:
    """一次完整协商：编排 → 核查 → 仲裁，全程留痕。"""
    tr = Trace(session_id)

    plans = orchestrate(tasks, window)
    tr.msg(ROLE_ORCH, ROLE_CHK, "plans", [
        {"planId": p["planId"], "name": p["name"], "cost": p["cost"]} for p in plans])

    checked = []
    for p in plans:
        c = check_plan(p, window)
        checked.append(c)
        tr.msg(ROLE_CHK, ROLE_ORCH, "check_result", {
            "planId": c["planId"], "conflictCount": c["conflictCount"],
            "severe": c["severe"]})

    verdict = arbitrate(checked, plans)
    tr.msg(ROLE_CHK, ROLE_ARB, "checked", verdict["options"])
    tr.decide(ROLE_ARB, verdict["recommended"], verdict["reason"])

    return {
        "plans": plans,
        "checks": checked,
        "verdict": verdict,
        "trace": tr.as_dict(),
    }
