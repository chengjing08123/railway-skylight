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
    """把「全员占满整个天窗」拆成两套价值取向不同的候选方案。

    **不写死任何工区名和数字** —— 换一个天窗、换一批作业，照样能用：

      A 顺延：把「退让方」的作业移出本天窗，另排
        —— 冲突下降，代价是这些作业延期
      B 分界：全部保留，冲突转为「需人工划分界点」
        —— 作业量不损失，代价是重叠仍需逐条协调

    退让方怎么选：
      1. 优先工区名里带「检查」的（检查作业可延后，不影响线路维修主体）；
      2. 没有检查工区，就取「作业条数最少」的工区（影响面最小）；
      3. 只有一个工区，就明确标「无可退让」，不硬凑方案。

    代价里的「冲突」一栏由核查者回填（见 fill_cost）—— 编排者提方案，核查者给数，
    这也是角色分离的一部分：编排者不给自己打分。
    """
    team_of = lambda t: (t.get("team") or "").strip()  # noqa: E731
    by_team: dict[str, list[dict]] = {}
    for t in tasks:
        by_team.setdefault(team_of(t), []).append(t)

    defer_team = ""
    if any("检查" in name for name in by_team):
        defer_team = next(name for name in by_team if "检查" in name)
    elif len(by_team) >= 2:
        defer_team = min(by_team, key=lambda k: (len(by_team[k]), k))

    moved = by_team.get(defer_team, []) if defer_team else []
    moved_ids = {id(t) for t in moved}
    kept = [t for t in tasks if id(t) not in moved_ids]
    is_inspection = "检查" in defer_team

    if defer_team and moved:
        name_a = "检查工区顺延" if is_inspection else f"{defer_team}顺延"
        risk_a = (f"{len(moved)} 条检查作业需另排天窗，可能延后 1 天" if is_inspection
                  else f"{len(moved)} 条 {defer_team} 作业需另排天窗，可能延后 1 天")
        rationale_a = (f"安全优先：宁可变更检查计划，也不留下跨工区重叠。"
                       if is_inspection else
                       f"安全优先：把「{defer_team}」{len(moved)} 条作业移出本天窗，优先消除重叠。")
    else:
        name_a = "无可退让（本窗只有一个工区）"
        risk_a = "本天窗内只有一个工区，无法靠顺延消除冲突"
        rationale_a = "本窗无跨工区作业，顺延方案不适用。"

    plan_a = {
        "planId": "A",
        "name": name_a,
        "tasks": kept,                          # 移出退让方，冲突应下降
        "movedTasks": [t.get("serialNo") for t in moved],
        "cost": {
            "affectedTeam": defer_team or "—",
            "movedCount": len(moved),
            "workloadRisk": risk_a,
            "safetyGain": "重叠减少，天窗内跨工区交叉作业减少" if moved
                          else "无法改善（无可退让作业）",
            "quantified": {"冲突": "待核查", "延期作业": len(moved),
                           "延期天数": 1 if moved else 0},
        },
        "rationale": rationale_a,
    }

    all_teams = " + ".join(sorted(by_team)) or "—"
    plan_b = {
        "planId": "B",
        "name": "保留全部 · 分区分界",
        "tasks": tasks,                         # 全保留，靠人工划分界点化解
        "movedTasks": [],
        "cost": {
            "affectedTeam": all_teams,
            "movedCount": 0,
            "workloadRisk": "作业量不损失，但重叠需车务段逐条指定主体单位并划分界点",
            "safetyGain": "无 —— 重叠仍在，只靠协调与防护措施控制",
            "quantified": {"冲突": "待核查", "延期作业": 0, "延期天数": 0},
        },
        "rationale": "作业量优先：不动计划，用协调与防护消化重叠。",
    }
    return [plan_a, plan_b]


def fill_cost(plans: list[dict], results: list[dict]) -> None:
    """把核查结果回填到方案的代价里（就地修改）。

    编排者只说「我要移出谁」，到底能消除多少冲突，由核查者算完写回来。
    """
    by_id = {r.get("planId"): r for r in results}
    for p in plans:
        r = by_id.get(p.get("planId"))
        if not r:
            continue
        n = int(r.get("conflictCount") or 0)
        p["cost"]["quantified"]["冲突"] = "归零" if n == 0 else f"维持 {n} 条"
        if p.get("planId") == "B" and n == 0:
            p["cost"]["safetyGain"] = "无重叠，无需处置"

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

    fill_cost(plans, checked)        # 核查者给数，回填进方案的代价

    verdict = arbitrate(checked, plans)
    tr.msg(ROLE_CHK, ROLE_ARB, "checked", verdict["options"])
    tr.decide(ROLE_ARB, verdict["recommended"], verdict["reason"])

    return {
        "plans": plans,
        "checks": checked,
        "verdict": verdict,
        "trace": tr.as_dict(),
    }


