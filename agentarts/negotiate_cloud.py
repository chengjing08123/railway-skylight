# -*- coding: utf-8 -*-
"""negotiate_cloud.py —— 三个云端运行时串一次协商（方案三）

    python negotiate_cloud.py

    skylight-orchestrator  → 编排者：出两套方案 + 代价
    skylight-check         → 核查者：每个方案跑一次确定性判定
    skylight-arbiter       → 仲裁者：对比、给建议 + 退路

三个都是**独立的 AgentArts 运行时**，同一个镜像，靠 AGENT_DEFAULT_MODE 区分默认角色。
串联放在客户端做：这样不用解决运行时互调的 IAM 授权，每个角色仍是独立实例 ——
答辩时可以说「三个智能体都部署在 AgentArts 上，各自有独立运行时，靠契约协作」。
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from invoke_agent import CLI, full_payload, set_credentials  # noqa: E402

HERE = Path(__file__).resolve().parent
WINDOW = {"windowStart": "07:30", "windowEnd": "09:20"}
AGENT_ORCH = "skylight-orchestrator"
AGENT_CHECK = "skylight-check"
AGENT_ARB = "skylight-arbiter"


def call(agent: str, payload: dict, retries: int = 3) -> dict:
    """调一个云端运行时，返回解析后的 JSON。

    冷启动会报 `callback_addresses is empty` —— 重试即可（部署手册坑 5）。
    """
    js = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    child = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    for attempt in range(1, retries + 1):
        r = subprocess.run([str(CLI), "invoke", "--agent", agent, js],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=900, env=child)
        out = (r.stdout or "") + "\n" + (r.stderr or "")
        if r.returncode == 0:
            idx = out.rfind("Response:")
            body = out[idx + len("Response:"):].strip() if idx >= 0 else out
            end = body.rfind("}")
            return json.loads(body[:end + 1] if end >= 0 else body)
        if "callback_addresses is empty" in out and attempt < retries:
            print(f"    （{agent} 冷启动，{attempt} 次失败，5 秒后重试）")
            time.sleep(5)
            continue
        raise RuntimeError(f"{agent} 调用失败：{out[-800:]}")
    raise RuntimeError(f"{agent} 调用失败：重试 {retries} 次仍未成功")


def main() -> int:
    set_credentials()
    tasks = full_payload()["tasks"]
    seed = json.dumps(sorted(t["taskId"] for t in tasks), sort_keys=True)
    sid = "S-CLOUD-" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:8]

    print(f"方案三：三个独立运行时协同，{len(tasks)} 条作业，天窗 07:30—09:20\n")

    # ① 编排者：不传 mode，用它的默认角色
    print(f"[1/3] {AGENT_ORCH}（编排者）…")
    orch = call(AGENT_ORCH, {"window": WINDOW, "tasks": tasks})
    plans = orch["plans"]
    for p in plans:
        print(f"      方案 {p['planId']}｜{p['name']}：冲突 {p['cost']['quantified']['冲突']}")

    # ② 核查者：每个方案跑一次（回包剥了 tasks，这里补回去）
    print(f"[2/3] {AGENT_CHECK}（核查者，跑两遍）…")
    team_of = {t["taskId"]: (t.get("team") or "") for t in tasks}
    checks = []
    for p in plans:
        moved = set(p.get("movedTasks") or [])
        plan_tasks = [t for t in tasks
                      if t["taskId"] not in moved and "检查" not in team_of[t["taskId"]]] \
            if p["planId"] == "A" else tasks
        chk = call(AGENT_CHECK, {"mode": "CHECK_PLAN", "window": WINDOW,
                                 "plan": {**p, "tasks": plan_tasks}})
        checks.append({"planId": chk["planId"], "conflictCount": chk["conflictCount"],
                       "severe": chk["severe"], "normal": chk["normal"]})
        print(f"      方案 {chk['planId']}：冲突 {chk['conflictCount']} 条"
              f"（严重 {chk['severe']}）")

    # ③ 仲裁者：把两套方案 + 核查结果（契约）交给它
    print(f"[3/3] {AGENT_ARB}（仲裁者）…")
    arb_plans = [{k: v for k, v in p.items() if k != "tasks"} for p in plans]
    arb = call(AGENT_ARB, {"window": WINDOW, "tasks": tasks,
                           "plans": arb_plans, "checks": checks})
    v = arb["verdict"]
    print(f"      建议：方案 {v['recommended']}（{v['recommendedName']}）")

    trace = {
        "sessionId": sid,
        "events": [
            {"type": "message", "speaker": "ORCHESTRATOR", "to": "CHECKER",
             "kind": "plans",
             "payload": [{"planId": p["planId"], "name": p["name"], "cost": p["cost"]}
                         for p in plans]},
            *[{"type": "message", "speaker": "CHECKER", "to": "ORCHESTRATOR",
               "kind": "check_result",
               "payload": {"planId": c["planId"], "conflictCount": c["conflictCount"],
                           "severe": c["severe"]}} for c in checks],
            {"type": "message", "speaker": "CHECKER", "to": "ARBITER",
             "kind": "checked", "payload": v["options"]},
            {"type": "decision", "by": "ARBITER", "choice": v["recommended"],
             "reason": v["reason"]},
        ],
    }

    out = {
        "mode": "NEGOTIATE_CLOUD",
        "sessionId": sid,
        "agents": {"orchestrator": AGENT_ORCH, "checker": AGENT_CHECK,
                   "arbiter": AGENT_ARB},
        "plans": arb_plans,
        "checks": checks,
        "verdict": v,
        "trace": trace,
        "response": arb["response"],
    }
    (HERE / "negotiate_cloud.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 70)
    print(arb["response"])
    print("=" * 70)
    print(f"留痕：{len(trace['events'])} 条事件，会话 {sid} → negotiate_cloud.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
