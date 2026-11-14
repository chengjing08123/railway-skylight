# -*- coding: utf-8 -*-
"""agent_core.py —— 智能体的四节点核心逻辑（不依赖 AgentArts SDK）

拆出来的原因：这样本地就能跑通、能测，不用先部署。app.py 只是把它包一层。

四节点：
    ① 解析      parse_payload    —— 从请求里取出作业列表
    ② 判定      check_window     —— skylight_rules（确定性，不经模型）
    ③ 条文检索  retrieve         —— 按 conflict_type 过滤条目库
    ④ 生成+校验 render_answer    —— 模板或大模型；强制引用校验
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from skylight_rules import check_window

HERE = Path(__file__).resolve().parent
KB_PATH = HERE / "clauses.json"

CITE_RE = re.compile(r"(\d+\.\d+\.\d+(?:\s*第\s*\d+\s*款)?|\d+\.\d+\.\d+(?:\s*第\s*\d+\s*类)?)")


# ---------------------------------------------------------------- ① 解析
def parse_payload(payload: dict) -> tuple[list[dict], dict]:
    """取出作业列表与天窗信息。

    支持两种入参写法：
      A. {"window": {...}, "tasks": [...]}       —— 结构化，推荐
      B. {"message": "<json 字符串>"}            —— 从对话里带过来的 JSON
    """
    if not isinstance(payload, dict):
        return [], {}
    tasks = payload.get("tasks")
    window = payload.get("window") or {}

    if tasks is None:
        msg = payload.get("message")
        if isinstance(msg, str):
            text = msg.strip()
            start, end = text.find("{"), text.rfind("}")
            if start >= 0 and end > start:
                try:
                    obj = json.loads(text[start:end + 1])
                    tasks = obj.get("tasks")
                    window = window or obj.get("window") or {}
                except json.JSONDecodeError:
                    tasks = None

    return (tasks or []), window


# ---------------------------------------------------------------- ③ 检索
def load_kb(path: Path = KB_PATH) -> list[dict]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    return data.get("clauses", [])


def retrieve(conflicts: list[dict], kb: list[dict]) -> dict[str, dict]:
    """按冲突类型取条文。先按 conflict_type 精确过滤，再退回 rule_ref 前缀匹配。

    这一步用元数据过滤，不用向量检索 —— 条目只有几条，精确匹配比相似度更可靠，
    也避免「列602区被占用」召回成「配合」条文这类串台。
    """
    index: dict[str, dict] = {}
    for c in conflicts:
        ctype = c.get("type", "")
        hit = next((k for k in kb if k.get("conflict_type") == ctype), None)
        if hit is None and c.get("ruleRef"):
            head = c["ruleRef"].split()[0]
            hit = next((k for k in kb if k.get("rule_ref", "").startswith(head)), None)
        if hit:
            index[c["id"]] = hit
    return index


ATTRIBUTION_PROMPT = """你是铁路天窗作业的规章条文归因助手。

给你若干条**已经由确定性内核判定出来**的冲突，以及一份条文白名单。
你的任务只有一件：为每条冲突指出最适用的条文号。

硬性规则：
1. 条文号只能从白名单里挑，必须原样复制白名单里的字符串，一个字都不能改。
2. 选法按这个顺序，不要跳步：
   第一步 —— 冲突清单里每条都写了「类型」，白名单里每条都写了 conflict_type。
   两者**逐字相同**的，直接选它，不要再考虑其他条文。
   第二步 —— 只有类型完全对不上时，才按语义挑最接近的一条。
3. 一条冲突只给一个条文号，no 填冲突清单里的序号。
4. 白名单里确实没有合适的，这条的 rule_ref 填 "NONE"。
4. 只输出 JSON，不要解释、不要代码块、不要多余文字。

输出格式：
{"items":[{"no":1,"rule_ref":"<条文号>"}]}"""


def attribute_clauses(conflicts: list[dict], kb: list[dict],
                      window: dict | None = None,
                      allow_model: bool = True) -> tuple[dict[str, dict], str, list[str]]:
    """让模型做条文归因，并用白名单校验；校验不过就退回元数据检索。

    这是模型在整条链路里唯一「参与判断」的位置，所以边界划得很硬：

      * 输入的冲突列表是确定性内核判出来的，模型**不能增删**；
      * 模型的输出被压缩成「冲突 id → 条文号」一张映射表，
        输出短、可整体丢弃，判错的代价是回退，不是错判；
      * 条文号必须**逐字命中**白名单，否则这一条作废、按规则表补；
      * 模型拒绝作答（NONE / 空 / 超时 / 没有 key）时静默退回规则表。

    :return: (clauses, source, notes)
        clauses —— 与 retrieve() 同形，可直接喂给渲染层
        source  —— "model"（全走模型）/ "rules"（全走规则表）/ "mixed"
        notes   —— 被拒的模型输出，写进返回值便于现场解释「为什么回退」
    """
    base, base_source = retrieve(conflicts, kb), "rules"
    if not conflicts or not kb:
        return base, base_source, []

    notes: list[str] = []
    if not allow_model:
        return base, base_source, ["未启用模型归因（RENDER_MODE=template 或无 API Key）"]

    api_key = os.getenv("MODEL_API_KEY", "").strip()
    if not api_key:
        return base, base_source, ["缺少 MODEL_API_KEY"]

    # 一个条文号可能对应多条条目 —— clauses.json 里「2.2.10 第 1 款」就有两条
    # （UNIT-01 作业单元冲突 / LEAD-01 天窗负责人缺失）。按 rule_ref 建单值字典
    # 会让后一条覆盖前一条，校验时拿错对象、把对的提案判成错的。
    by_ref: dict[str, list[dict]] = {}
    for c in kb:
        ref = c.get("rule_ref", "")
        if ref:
            by_ref.setdefault(ref, []).append(c)
    if not by_ref:
        return base, base_source, ["条文库为空"]

    # 冲突清单给紧凑文本：给 JSON 模型会整段复述（这个坑在渲染层踩过一次）
    # 用「序号」而不是冲突 id —— id 形如「作业单元冲突|A|B」，带竖线，模型对着它
    # 输出会整条丢掉（实测 items 返回空数组）。序号短、无歧义。
    fact_lines = []
    for i, c in enumerate(conflicts, 1):
        seq = "×".join(f"序{n}" for n in c.get("serialNos") or [])
        fact_lines.append(
            f"{i}. 类型 {c.get('type', '')}；严重度 {c.get('severity', '')}；"
            f"涉及 {seq}；{c.get('description', '')}")
    wl_lines = []
    for i, (ref, group) in enumerate(by_ref.items(), 1):
        types = "、".join(sorted({g.get("conflict_type", "") for g in group}))
        wl_lines.append(f"{i}. {ref} —— 适用于：{types}")
        for g in group:
            wl_lines.append(f"     · {g.get('conflict_type', '')}：{g.get('summary', '')}")

    user = ("【冲突清单】\n" + "\n".join(fact_lines)
            + "\n\n【条文白名单】\n" + "\n".join(wl_lines)
            + "\n\n请按格式输出归因结果。no 填冲突清单里的序号，"
              "rule_ref 原样复制白名单里的条文号。")

    try:
        import httpx
    except ImportError:
        return base, base_source, notes + ["缺少 httpx"]

    model = os.getenv("MODEL_NAME", "deepseek-v4.1-flash")
    url = os.getenv("MODEL_URL", "https://api.modelarts-maas.com/openai/v1").rstrip("/")
    try:
        with httpx.Client(timeout=60) as cli:
            resp = cli.post(
                f"{url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}",
                         "Content-Type": "application/json"},
                json={"model": model,
                      "messages": [{"role": "system", "content": ATTRIBUTION_PROMPT},
                                   {"role": "user", "content": user}],
                      "temperature": 0.0, "max_tokens": 3000},
            )
            resp.raise_for_status()
            raw = (resp.json()["choices"][0]["message"].get("content") or "").strip()
    except Exception as exc:
        return base, base_source, notes + [f"模型归因调用失败：{type(exc).__name__}"]

    if not raw:
        return base, base_source, notes + ["模型归因返回空正文（reasoning 吃掉配额）"]

    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return base, base_source, notes + ["模型归因输出里没有 JSON"]
    try:
        items = json.loads(raw[start:end + 1]).get("items")
    except (json.JSONDecodeError, AttributeError):
        return base, base_source, notes + ["模型归因输出不是合法 JSON"]
    if not isinstance(items, list):
        return base, base_source, notes + ["模型归因输出缺少 items 数组"]

    by_no = {i: c for i, c in enumerate(conflicts, 1)}
    picked: dict[str, dict] = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        try:
            no = int(it.get("no"))
        except (TypeError, ValueError):
            notes.append(f"丢弃：缺少序号「{it}」")
            continue
        target = by_no.get(no)
        if target is None:
            notes.append(f"丢弃：序号 {no} 不存在")
            continue
        ref = str(it.get("rule_ref") or "").strip()

        # 第一道闸：必须逐字命中白名单 —— 防「编条文」。
        group = by_ref.get(ref)
        if group is None:
            if ref and ref.upper() != "NONE":
                notes.append(f"拒绝：序号 {no} →「{ref}」不在白名单")
            continue

        target_type = str(target.get("type", "")).strip()
        covered = any(str(g.get("conflict_type", "")).strip() == target_type
                      for g in kb if g.get("rule_ref"))

        # 第二道闸：类型必须对得上。
        # 实测踩到过：模型把「作业单元冲突」归到「2.2.8 配合缺失」，
        # 那是个真条文、白名单也认，但类型不符 —— 单靠白名单拦不住。
        # 同一款对应多条条目时，按冲突类型挑对的那一条。
        match = next((g for g in group
                      if str(g.get("conflict_type", "")).strip() == target_type), None)
        if match is not None:
            picked[target["id"]] = match
        elif covered:
            declared = "、".join(sorted({g.get("conflict_type", "") for g in group}))
            notes.append(f"拒绝：序号 {no} 冲突类型「{target_type}」"
                         f"与条文「{ref}」的类型「{declared}」不符")
        else:
            # 条文库里压根没有这个冲突类型 —— 此时才允许模型的语义兜底，
            # 也仍然只限定在这一款的实际条目内。
            picked[target["id"]] = group[0]

    if not picked:
        return base, base_source, notes + ["模型未给出可用归因，整体回退规则表"]

    merged = dict(base)
    merged.update(picked)
    source = "model" if len(picked) >= len(conflicts) else "mixed"
    return merged, source, notes


def clause_line(clause: dict) -> str:
    """把一条条文渲染成一句可引用的话。有原文用原文，没有就标明是摘要。"""
    ref = clause.get("rule_ref", "")
    if clause.get("text"):
        return f"（依据 {ref}）{clause['text']}"
    return f"（依据 {ref}）{clause.get('summary', '')}（条文摘要，原文待补）"


# ---------------------------------------------------------------- ④ 生成
def validate_citations(text: str, used: dict[str, dict],
                       extra_refs: set[str] | None = None) -> list[str]:
    """校验输出里出现的条号是否都在检索结果（或给定条目库）里。

    :param used: 本次检索到的条文 {conflict_id: clause}
    :param extra_refs: 额外承认的条号（协商场景下取整个条目库）
    :return: 「找不到依据的条号」列表；为空表示全部可追溯。
    """
    known = {c.get("rule_ref", "") for c in used.values()}
    known |= {c.get("rule_ref", "").split()[0] for c in used.values()}
    for r in (extra_refs or ()):
        if r:
            known.add(r)
            known.add(r.split()[0])
    bad = []
    for m in CITE_RE.finditer(text):
        cite = m.group(1).strip()
        if cite not in known and cite.split()[0] not in known:
            bad.append(cite)
    return bad


def render_template(result: dict, clauses: dict[str, dict],
                    window: dict | None = None) -> str:
    """不用模型的版本：结构固定，引用 100% 可控。断网/没 key 时用它。

    条文只在末尾统一列一次 —— 10 条冲突都依据同一款时，重复贴 10 遍纯属噪音。
    """
    ws = (window or {}).get("windowStart") or "07:30"
    we = (window or {}).get("windowEnd") or "09:20"
    conflicts = result.get("conflicts", [])
    if not conflicts:
        return ("该天窗内未发现作业单元范围重叠。\n"
                "说明：本结论基于确定性判定，未调用生成模型。")

    severe = [c for c in conflicts if c["severity"] == "严重"]
    normal = [c for c in conflicts if c["severity"] != "严重"]

    lines = [f"本天窗共 {result['taskCount']} 条作业，检出 {len(conflicts)} 条需处理项："
             f"严重 {len(severe)} 条、提示 {len(normal)} 条。", ""]

    def one(c: dict, no: int) -> str:
        seq = "×".join(f"序{n}" for n in c["serialNos"])
        unit = c["description"].split("【")[1].split("】")[0] if "【" in c["description"] else ""
        return (f"{no}. {unit}　{seq}　{ws}—{we} 同时占用"
                f"（依据 {c['ruleRef']}）")

    if severe:
        lines.append(f"一、需立即处理（{len(severe)} 条）")
        for i, c in enumerate(severe, 1):
            lines.append(one(c, i))
        lines.append("")

    if normal:
        lines.append(f"二、待确认 · 区域级重叠，未必构成冲突（{len(normal)} 条）")
        for i, c in enumerate(normal, 1):
            lines.append(one(c, i))
        lines.append("")

    lines.append("三、条文依据")
    seen: set[str] = set()
    for c in conflicts:
        clause = clauses.get(c["id"])
        if not clause or clause["rule_ref"] in seen:
            continue
        seen.add(clause["rule_ref"])
        lines.append(f"· {clause_line(clause)}")
    lines.append("")

    lines.append("处置建议：需立即处理项按条文由车务段指定主体单位并划分分界点，"
                 "或将其一作业移出该单元。")
    lines.append("判定说明：仅在不同工区之间判定单元冲突；单元级一致、或里程/道岔可佐证时判"
                 "「严重」，仅作业区域一致判「提示」。以上均为待确认项，不构成违规认定。")
    return "\n".join(lines)


SYSTEM_PROMPT = """你是铁路天窗作业计划的合规核查助手，面向车站调度员写核查说明。

硬性规则：
1. 只依据给出的判定结果作答，不得引入外部知识，不得自行新增条号。
2. 每条结论后必须附条文号，格式：（依据 2.2.10 第 1 款）。
3. 没有匹配到条文的，写「未匹配到条文」，不要编造。
4. 不判断谁对谁错，只陈述「存在重叠，需确认分界点」。
5. 分「需立即处理」与「待确认」两类，每条一行，不用表格、不用代码块、不用 JSON。
6. 不要复述输入清单，不要罗列原始字段，直接给结论。
"""


def render_llm(result: dict, clauses: dict[str, dict],
               window: dict | None = None) -> str:
    """调 MaaS 生成解释性文本。引用校验不过就退回模板版本。"""
    try:
        import httpx
    except ImportError as e:
        raise RuntimeError("缺少 httpx，请 pip install httpx") from e

    api_key = os.getenv("MODEL_API_KEY", "").strip()
    model = os.getenv("MODEL_NAME", "deepseek-v4.1-flash")
    base = os.getenv("MODEL_URL", "https://api.modelarts-maas.com/openai/v1").rstrip("/")
    if not api_key:
        return render_template(result, clauses, window)

    # 事实用紧凑的文本清单给，不给 JSON —— 给 JSON 模型会整段复述
    lines = [f"天窗：{result.get('taskCount')} 条作业，检出 {len(result.get('conflicts', []))} 条需处理项。", ""]
    for code, c in zip("①②③④⑤⑥⑦⑧⑨⑩", result.get("conflicts", [])):
        seq = "×".join(f"序{n}" for n in c["serialNos"])
        ref = clauses.get(c["id"], {}).get("rule_ref", "未匹配")
        lines.append(f"{code} {c['description']}（涉及 {seq}；严重度 {c['severity']}；依据 {ref}）")
    body = "\n".join(lines)

    user = (
        "以下是系统确定性判定的结果。请据此写一段给车站调度员的核查说明，直接输出正文，不要输出 JSON。\n\n"
        f"{body}\n\n"
        "要求：先一句话说总体情况，再按「需立即处理」和「待确认」两类分条列出（每条一行，"
        "保留单元名、序号、条文号），最后一句给处置建议。不要重复上面的事实清单的括号内容，"
        "不要输出代码块或表格。"
    )

    with httpx.Client(timeout=60) as cli:
        resp = cli.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"},
            json={"model": model,
                  "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                               {"role": "user", "content": user}],
                  "temperature": 0.2, "max_tokens": 8000},
        )
        resp.raise_for_status()
        text = (resp.json()["choices"][0]["message"].get("content") or "").strip()

    if not text:
        # 推理模型可能把 token 全花在 reasoning 上，正文为空 —— 当作失败，交给上层回退
        raise ValueError("模型返回空正文（reasoning 吃掉了 token 配额）")

    bad = validate_citations(text, clauses)
    if bad:
        # 引用校验不过 —— 不把不可追溯的文本交给用户
        fallback = render_template(result, clauses, window)
        return fallback + f"\n\n（注：模型输出含无法核实的条号 {bad}，已改用可追溯版本。）"
    return text


# ---------------------------------------------------------------- ④' 协商陈述
def render_negotiation_template(neg: dict, clauses: dict[str, dict],
                                window: dict | None = None) -> str:
    """把一次协商（编排 + 核查 + 仲裁）渲染成人能读的说明。

    刻意不用模型：协商结论的价值在于「两套方案的账摆得清」，模板比模型稳，
    也保证数字与条号一个不差。要模型改写措辞，走 render_negotiation_llm。
    """
    ws = (window or {}).get("windowStart") or "07:30"
    we = (window or {}).get("windowEnd") or "09:20"
    plans = neg.get("plans") or []
    checks = {c["planId"]: c for c in (neg.get("checks") or [])}
    verdict = neg.get("verdict") or {}

    n = max((len(p.get("tasks") or []) for p in plans), default=0)
    head = f"天窗 {ws}—{we}" + (f"，{n} 条作业" if n else "")
    lines = [f"{head}，给出两套候选方案：", ""]

    for p in plans:
        pid = p.get("planId")
        c = checks.get(pid) or {}
        cost = p.get("cost") or {}
        q = cost.get("quantified") or {}
        lines.append(f"方案 {pid}｜{p.get('name', '')}")
        if p.get("rationale"):
            lines.append(f"  做法：{p['rationale']}")
        if c:
            lines.append(f"  核查：冲突 {c['conflictCount']} 条"
                         f"（严重 {c['severe']} / 提示 {c['normal']}）")
        if cost:
            lines.append(f"  代价：{cost.get('affectedTeam', '—')}，"
                         f"{cost.get('workloadRisk', '—')}")
            lines.append(f"  安全：{cost.get('safetyGain', '—')}")
        if q:
            lines.append(f"  量化：冲突 {q.get('冲突')}，"
                         f"延期作业 {q.get('延期作业')} 条 / {q.get('延期天数')} 天")
        lines.append("")

    if verdict:
        lines.append(f"仲裁建议：方案 {verdict.get('recommended')}"
                     f"（{verdict.get('recommendedName', '')}）")
        if verdict.get("reason"):
            lines.append(f"  理由：{verdict['reason']}")
        if verdict.get("fallback"):
            lines.append(f"  退路：{verdict['fallback']}")
        lines.append("")

    lines.append("说明：本建议不替人决定 —— 最终由调度员在确认台选定其中一套，"
                 "选择结果与理由一并写入留痕。")
    return "\n".join(lines)


def render_negotiation_llm(neg: dict, clauses: dict[str, dict],
                           window: dict | None = None) -> str:
    """让模型把协商结果改写成一段话。条号与数字必须原样保留，否则上层回退模板。"""
    try:
        import httpx
    except ImportError as e:
        raise RuntimeError("缺少 httpx，请 pip install httpx") from e

    api_key = os.getenv("MODEL_API_KEY", "").strip()
    model = os.getenv("MODEL_NAME", "deepseek-v4.1-flash")
    base = os.getenv("MODEL_URL", "https://api.modelarts-maas.com/openai/v1").rstrip("/")
    if not api_key:
        return render_negotiation_template(neg, clauses, window)

    ws = (window or {}).get("windowStart") or "07:30"
    we = (window or {}).get("windowEnd") or "09:20"
    plans = neg.get("plans") or []
    checks = {c["planId"]: c for c in (neg.get("checks") or [])}
    verdict = neg.get("verdict") or {}

    facts = [f"天窗 {ws}—{we}，两套候选方案："]
    for p in plans:
        c = checks.get(p.get("planId")) or {}
        cost = p.get("cost") or {}
        facts.append(
            f"- 方案 {p.get('planId')}「{p.get('name')}」：冲突 {c.get('conflictCount')} 条"
            f"（严重 {c.get('severe')}），代价 {cost.get('workloadRisk')}，"
            f"安全 {cost.get('safetyGain')}，做法 {p.get('rationale')}")
    facts.append(f"- 仲裁建议：{verdict.get('recommended')}（{verdict.get('recommendedName')}）")
    facts.append(f"- 理由：{verdict.get('reason')}")
    facts.append(f"- 退路：{verdict.get('fallback')}")

    user = (
        "以下是系统确定性判定与仲裁的结构化结果。请据此写一段给车站调度员的建议说明，"
        "直接输出正文，不要输出 JSON、代码块或表格。\n\n"
        + "\n".join(facts) + "\n\n"
        "要求：先说两套方案各是什么、代价是什么，再说建议哪一套、为什么，最后给退路条件；"
        "所有方案编号、冲突条数、条号必须原样保留，不得新增或改动。"
    )

    with httpx.Client(timeout=60) as cli:
        resp = cli.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"},
            json={"model": model,
                  "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                               {"role": "user", "content": user}],
                  "temperature": 0.2, "max_tokens": 8000},
        )
        resp.raise_for_status()
        text = (resp.json()["choices"][0]["message"].get("content") or "").strip()

    if not text:
        raise ValueError("模型返回空正文（reasoning 吃掉了 token 配额）")
    return text


# ---------------------------------------------------------------- 串起来
def run(payload: dict, kb: list[dict] | None = None) -> dict:
    """同步版本：解析 → 判定 → 检索 → 模板生成。本地测试与降级都用它。"""
    tasks, window = parse_payload(payload)
    result = check_window(tasks, window, detect_duration=bool(payload.get("detectDuration")))
    kb = kb if kb is not None else load_kb()
    clauses = retrieve(result["conflicts"], kb)
    answer = render_template(result, clauses)
    bad = validate_citations(answer, clauses)
    return {
        "answer": answer,
        "result": result,
        "clauseRefs": sorted({c["rule_ref"] for c in clauses.values()}),
        "uncited": bad,
    }
