# -*- coding: utf-8 -*-
"""dispatch.py —— mode 分派（不依赖 AgentArts SDK，本地可直接测试）

一个运行时，五个 mode（入口同一，产出不同）：

    CHECK        四节点核查（默认，向后兼容旧调用）
    ORCHESTRATE  只编排：出两套候选方案，每套带「代价」
    CHECK_PLAN   只核查：对给定方案跑确定性判定（不经模型）
    ARBITRATE    只仲裁：对比两套方案，给建议 + 退路（不拍板）
    NEGOTIATE    全链路：编排 → 核查 → 仲裁，带留痕

三条设计约束（照方案 4.5 / 4.6）：
    1. 判定不经过模型 —— 一律走 skylight_rules.check_window；
    2. 角色之间只传结构化契约 —— 每个角色收发 dict，不传自由文本；
    3. 每一步留痕 —— NEGOTIATE 返回 trace（session / message / decision）。

为什么和 app.py 分开：SDK 只在云端有。分派逻辑单独成模块，本地
`python test_modes.py` 就能把五个 mode 全跑一遍，不用先部署。
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict

from dotenv import load_dotenv

import agent_core
import multi_agent
from skylight_rules import check_window

load_dotenv()

KB = agent_core.load_kb()

MODE_CHECK = "CHECK"
MODE_ORCH = "ORCHESTRATE"
MODE_CHK_PLAN = "CHECK_PLAN"
MODE_ARB = "ARBITRATE"
MODE_NEGOTIATE = "NEGOTIATE"
MODES = (MODE_CHECK, MODE_ORCH, MODE_CHK_PLAN, MODE_ARB, MODE_NEGOTIATE)
DEFAULT_MODE = MODE_CHECK

CONTRACT = (
    "入参：{\"mode\":\"CHECK|ORCHESTRATE|CHECK_PLAN|ARBITRATE|NEGOTIATE\", "
    "\"window\":{\"windowStart\":\"07:30\",\"windowEnd\":\"09:20\"}, "
    "\"tasks\":[{\"taskId\":\"...\",\"serialNo\":18,\"team\":\"...\","
    "\"unitCodes\":[\"列602区\"],\"start\":\"07:30\",\"end\":\"09:20\"}], "
    "\"plans\":[...],   // 仅 ARBITRATE / CHECK_PLAN 需要\n"
    "省略 mode 时按 CHECK 处理。"
)


# ---------------------------------------------------------------- 小工具
def _norm_request(request: Any) -> Dict[str, Any]:
    """容错：平台有时把 body 当字符串传进来。"""
    if isinstance(request, dict):
        return request
    if isinstance(request, str):
        text = request.strip()
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                obj = json.loads(text[start:end + 1])
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                pass
    return {}


def _session_id(request: Dict[str, Any], tasks: list[dict], mode: str) -> str:
    """没给 sessionId 就按内容派生 —— 同一批作业同一个 mode 拿同一个会话号，幂等。"""
    sid = str(request.get("sessionId") or "").strip()
    if sid:
        return sid
    seed = json.dumps(
        {"mode": mode, "tasks": sorted(str(t.get("taskId")) for t in tasks)},
        ensure_ascii=False, sort_keys=True)
    return "S-" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]


def _kb_refs(clauses: dict[str, dict] | None = None) -> set[str]:
    """可引用的条号集合：整个条目库 ∪ 本次检索到的。"""
    refs = {c.get("rule_ref", "") for c in KB if c.get("rule_ref")}
    for c in (clauses or {}).values():
        if c.get("rule_ref"):
            refs.add(c["rule_ref"])
    return refs


def _render_plan_result(plan: dict, chk: dict, window: dict,
                        clauses: dict[str, dict]) -> str:
    fake = {"taskCount": len(plan.get("tasks") or []),
            "conflictCount": chk["conflictCount"],
            "conflicts": chk["conflicts"]}
    return agent_core.render_template(fake, clauses, window)


def _render_negotiation(neg: dict, clauses: dict[str, dict], window: dict,
                        want_llm: bool) -> str:
    text = agent_core.render_negotiation_template(neg, clauses, window)
    if not want_llm or not os.getenv("MODEL_API_KEY", "").strip():
        return text
    try:
        text = agent_core.render_negotiation_llm(neg, clauses, window)
    except Exception as exc:                       # 模型不可用不能拖垮协商
        return text + (f"\n\n（注：模型改写失败，已用确定性模板。原因："
                       f"{type(exc).__name__}）")
    bad = agent_core.validate_citations(text, clauses, extra_refs=_kb_refs(clauses))
    if bad:                                        # 不可追溯的措辞不交给用户
        return (agent_core.render_negotiation_template(neg, clauses, window)
                + f"\n\n（注：模型输出含无法核实的条号 {bad}，已改用可追溯版本。）")
    return text


# ---------------------------------------------------------------- mode 实现
def _mode_check(request: Dict[str, Any], tasks: list[dict], window: dict) -> Dict[str, Any]:
    """四节点核查 —— 与部署 v1 完全一致，保证旧调用方不受影响。"""
    result = check_window(tasks, window,
                          detect_duration=bool(request.get("detectDuration")))

    render_mode = os.getenv("RENDER_MODE", "auto").strip().lower()
    want_model = render_mode != "template" and bool(os.getenv("MODEL_API_KEY", "").strip())

    # ③ 条文检索：让模型参与归因，但用白名单逐字校验兜底。
    # 判错不会传导到判定结果 —— 最坏情况是退回规则表，条文照样可追溯。
    clauses, clause_source, attr_notes = agent_core.attribute_clauses(
        result["conflicts"], KB, window, allow_model=want_model)

    if not want_model:
        answer = agent_core.render_template(result, clauses, window)
    else:
        try:
            answer = agent_core.render_llm(result, clauses, window)
        except Exception as exc:                   # 模型不可用不能拖垮整条链路
            answer = (agent_core.render_template(result, clauses, window)
                      + f"\n\n（注：模型调用失败，已回退到确定性模板。原因："
                        f"{type(exc).__name__}）")

    if agent_core.validate_citations(answer, clauses):
        answer = agent_core.render_template(result, clauses, window)

    out = {
        "mode": MODE_CHECK,
        "response": answer,
        "status": "ok",
        "conflictCount": result["conflictCount"],
        "clauseRefs": sorted({c["rule_ref"] for c in clauses.values()}),
        "clauseSource": clause_source,
    }
    if attr_notes:
        out["attributionNotes"] = attr_notes[:8]
    return out


def _mode_orchestrate(request: Dict[str, Any], tasks: list[dict],
                      window: dict) -> Dict[str, Any]:
    plans = multi_agent.orchestrate(tasks, window)
    tr = multi_agent.Trace(_session_id(request, tasks, MODE_ORCH))
    tr.msg(multi_agent.ROLE_ORCH, multi_agent.ROLE_CHK, "plans",
           [{"planId": p["planId"], "name": p["name"], "cost": p["cost"]}
            for p in plans])
    body = "\n".join(
        [f"方案 {p['planId']}｜{p['name']}：冲突 {p['cost']['quantified']['冲突']}，"
         f"延期 {p['cost']['quantified']['延期作业']} 条；{p['rationale']}"
         for p in plans])
    return {
        "mode": MODE_ORCH,
        "status": "ok",
        "response": f"已生成 {len(plans)} 套候选方案（每套均带代价）：\n{body}",
        "plans": [{k: v for k, v in p.items() if k != "tasks"} for p in plans],
        "trace": tr.as_dict(),
    }


def _mode_check_plan(request: Dict[str, Any], tasks: list[dict],
                     window: dict) -> Dict[str, Any]:
    plan = request.get("plan")
    if not isinstance(plan, dict):
        plans = request.get("plans")
        plan = plans[0] if isinstance(plans, list) and plans else None
    if not isinstance(plan, dict):
        return {"mode": MODE_CHK_PLAN, "status": "error", "conflictCount": 0,
                "response": "CHECK_PLAN 需要 plan（或 plans[0]）："
                            "{\"plan\":{\"planId\":\"A\",\"tasks\":[...]}}\n" + CONTRACT}

    plan = {**plan, "tasks": plan.get("tasks") or tasks}
    chk = multi_agent.check_plan(plan, window)
    clauses = agent_core.retrieve(chk["conflicts"], KB)
    return {
        "mode": MODE_CHK_PLAN,
        "status": "ok",
        "planId": chk["planId"],
        "conflictCount": chk["conflictCount"],
        "severe": chk["severe"],
        "normal": chk["normal"],
        "conflicts": chk["conflicts"],
        "response": _render_plan_result(plan, chk, window, clauses),
    }


def _mode_arbitrate(request: Dict[str, Any], tasks: list[dict],
                    window: dict) -> Dict[str, Any]:
    plans = request.get("plans")
    if not isinstance(plans, list) or len(plans) < 2:
        if not tasks:
            return {"mode": MODE_ARB, "status": "error",
                    "response": "ARBITRATE 需要 plans（两套）或 tasks（由本机编排）。\n" + CONTRACT}
        plans = multi_agent.orchestrate(tasks, window)   # 没给方案就自己编两套

    checks = request.get("checks")
    if not isinstance(checks, list) or len(checks) != len(plans):
        if not any(p.get("tasks") for p in plans) and not tasks and not checks:
            return {"mode": MODE_ARB, "status": "error",
                    "response": "ARBITRATE 需要 plans[].tasks（或 checks，或 tasks 让本机自编）。\n"
                                + CONTRACT}
        checks = [multi_agent.check_plan(
            {**p, "tasks": p.get("tasks") or tasks}, window) for p in plans]

    verdict = multi_agent.arbitrate(checks, plans)
    neg = {"plans": plans, "checks": checks, "verdict": verdict}
    clauses: dict[str, dict] = {}
    for c in checks:
        # 跨运行时调用时，checks 可能只带摘要（无 conflicts 明细）—— 不能硬取
        clauses.update(agent_core.retrieve(c.get("conflicts") or [], KB))
    want_llm = str(request.get("render") or "").strip().lower() == "llm"
    return {
        "mode": MODE_ARB,
        "status": "ok",
        "response": _render_negotiation(neg, clauses, window, want_llm),
        "verdict": verdict,
        "options": verdict["options"],
        "checks": [{"planId": c["planId"], "conflictCount": c["conflictCount"],
                    "severe": c["severe"], "normal": c["normal"]} for c in checks],
    }


def _mode_negotiate(request: Dict[str, Any], tasks: list[dict],
                    window: dict) -> Dict[str, Any]:
    sid = _session_id(request, tasks, MODE_NEGOTIATE)
    neg = multi_agent.negotiate(tasks, window, session_id=sid)

    clauses: dict[str, dict] = {}
    for c in neg["checks"]:
        clauses.update(agent_core.retrieve(c["conflicts"], KB))

    want_llm = str(request.get("render") or "").strip().lower() == "llm"
    resp = _render_negotiation(neg, clauses, window, want_llm)

    rec = neg["verdict"]["recommended"]
    rec_check = next(c for c in neg["checks"] if c["planId"] == rec)
    return {
        "mode": MODE_NEGOTIATE,
        "status": "ok",
        "response": resp,
        "sessionId": sid,
        "conflictCount": rec_check["conflictCount"],
        "plans": [{k: v for k, v in p.items() if k != "tasks"} for p in neg["plans"]],
        "checks": [{"planId": c["planId"], "conflictCount": c["conflictCount"],
                    "severe": c["severe"], "normal": c["normal"]}
                   for c in neg["checks"]],
        "verdict": neg["verdict"],
        "trace": neg["trace"],
    }


HANDLERS = {
    MODE_CHECK: _mode_check,
    MODE_ORCH: _mode_orchestrate,
    MODE_CHK_PLAN: _mode_check_plan,
    MODE_ARB: _mode_arbitrate,
    MODE_NEGOTIATE: _mode_negotiate,
}


# ---------------------------------------------------------------- 入口
def handle_invocation(request: Any) -> Dict[str, Any]:
    """一个入口，按 mode 分派到不同角色。默认 CHECK（兼容旧调用）。"""
    req = _norm_request(request)
    raw_mode = str(req.get("mode") or os.getenv("AGENT_DEFAULT_MODE") or DEFAULT_MODE)
    # 容错：前端可能传小写或带空格
    mode = raw_mode.strip().upper().replace("-", "_")

    tasks, window = agent_core.parse_payload(req)

    if mode not in MODES:
        return {
            "mode": mode, "status": "error", "conflictCount": 0,
            "response": f"未知 mode「{raw_mode}」。可用：{' / '.join(MODES)}",
        }

    if not tasks and mode not in (MODE_ARB, MODE_CHK_PLAN):
        return {
            "mode": mode, "status": "error", "conflictCount": 0,
            "response": ("没有收到作业列表。\n" + CONTRACT),
        }

    if mode == MODE_ARB:
        return _mode_arbitrate(req, tasks, window)

    return HANDLERS[mode](req, tasks, window)
