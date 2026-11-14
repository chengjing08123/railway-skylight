# -*- coding: utf-8 -*-
"""explain_bridge.py —— 后端（Java）调云端智能体的桥。

为什么需要桥，而不是让 Java 直接打网关：
    AgentArts 网关的认证方式是 IAM（AK/SK 签名）。Java 侧要么引入华为云 SDK
    只为签名，要么自己实现 V4 签名，都属于给演示加故障点。CLI 这条路已经
    在实测里跑通了（含冷启动重试、UTF-8 编码修正），桥一层最省事。

调用方式（由 Java 的 ProcessBuilder 拉起）：
    echo '<payload-json>' | python explain_bridge.py

输入：stdin，UTF-8 JSON，与 /invocations 的 payload 同形
输出：stdout，单行 JSON
    {
      "status":     "ok" | "error",
      "source":     "cloud" | "local",        # 这一发实际走了哪条路
      "text":       "<给调度员看的核查说明>",
      "clauseRefs": ["2.2.10 第 1 款", ...],
      "conflictCount": 10,
      "note":       "云端冷启动失败，已用同镜像本地逻辑降级" （可选）
    }

退出码：0 成功；2 失败（此时 stdout 仍是 JSON，status=error）

设计约束（与方案 4.5 一致）：判定一律走确定性内核，模型只负责条文归因与措辞；
模型输出的条号若不在白名单内，整体回退，绝不把编造的条文交给调度员。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
CLI = Path(os.getenv("AGENTARTS_CLI")
           or (Path(os.environ.get("LOCALAPPDATA", ""))
               / "Programs/Python/Python314/Scripts/agentarts.exe"))
AGENT = os.getenv("AGENTARTS_AGENT", "skylight-check")
CRED = Path(os.getenv("HUAWEICLOUD_CRED_FILE", r"D:\下载\credentials.csv"))

WARMUP_HINT = "callback_addresses is empty"
MAX_ATTEMPTS = 3

# Windows 命令行 8191 字符上限。payload 超过这个数就只留涉及的作业，
# 否则 CLI 会静默失败（这个坑在 .cmd 上踩过一次，这里是同一个根因）。
ARGV_SAFE_CHARS = 7000


def _fail(msg: str) -> dict:
    return {"status": "error", "source": "none", "text": "", "clauseRefs": [],
            "error": msg}


def _set_credentials() -> None:
    """CLI 需要 AK/SK。已 export 就尊重环境变量，否则从 csv 读。"""
    if os.getenv("HUAWEICLOUD_SDK_AK") and os.getenv("HUAWEICLOUD_SDK_SK"):
        return
    if not CRED.exists():
        return
    try:
        import csv
        rows = list(csv.DictReader(open(CRED, encoding="utf-8-sig")))
    except Exception:
        return
    if not rows:
        return
    os.environ["HUAWEICLOUD_SDK_AK"] = rows[0].get("Access Key Id", "").strip()
    os.environ["HUAWEICLOUD_SDK_SK"] = rows[0].get("Secret Access Key", "").strip()


def _shape(payload: dict) -> dict:
    """裁剪 payload，保证命令行长度安全。

    优先保留：window、mode、render、以及涉及冲突的那几条作业。
    正常演示一个天窗 10~12 条作业不会触发裁剪；55 条全量会。
    """
    js = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(js) <= ARGV_SAFE_CHARS:
        return payload

    tasks = payload.get("tasks") or []
    keep_ids = {str(x) for x in (payload.get("focusTaskIds") or [])}
    if keep_ids:
        small = [t for t in tasks if str(t.get("taskId")) in keep_ids]
    else:
        small = tasks[:4]
    trimmed = {k: v for k, v in payload.items() if k != "focusTaskIds"}
    trimmed["tasks"] = small
    return trimmed


def _parse_cli_output(out: str) -> dict | None:
    """CLI 会打一个方框再打 Response: <json>，取最后一个 Response: 之后的内容。"""
    idx = out.rfind("Response:")
    if idx < 0:
        return None
    body = out[idx + len("Response:"):].strip()
    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(body[start:end + 1])
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _call_cloud(payload: dict) -> tuple[dict | None, str]:
    """调云端智能体。返回 (结果, 错误说明)。"""
    if not CLI.exists():
        return None, f"找不到 CLI：{CLI}"

    _set_credentials()
    if not os.getenv("HUAWEICLOUD_SDK_AK"):
        return None, "缺少 AK/SK（环境变量与 csv 都没读到）"

    js = json.dumps(_shape(payload), ensure_ascii=False, separators=(",", ":"))
    child_env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}

    last = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        r = subprocess.run([str(CLI), "invoke", "--agent", AGENT, js],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=180, env=child_env)
        out = (r.stdout or "").strip()
        err = (r.stderr or "").strip()
        combined = out + "\n" + err

        if r.returncode == 0:
            obj = _parse_cli_output(out)
            if obj is not None:
                return obj, ""
            return None, "云端返回里解析不出 JSON"

        last = (err or out)[:800]
        # 运行时空闲被回收后的第一次调用必失败，紧接着重打就正常 —— 不是真故障。
        if WARMUP_HINT in combined and attempt < MAX_ATTEMPTS:
            time.sleep(5)
            continue
        break
    return None, last or "云端调用失败"


def _call_local(payload: dict) -> dict | None:
    """降级路径：跑同一份 dispatch.py（不进 SDK，所以本机能跑）。

    演示时云端突然抽风，页面也不能白屏 —— 输出结构与云端一致，
    只是模型那一层退回模板，条文照样可追溯。
    """
    try:
        import dispatch
    except Exception:
        return None
    try:
        return dispatch.handle_invocation(payload)
    except Exception:
        return None


def main() -> int:
    raw = sys.stdin.buffer.read().decode("utf-8", errors="replace").strip()
    if not raw:
        print(json.dumps(_fail("stdin 为空，没收到 payload"), ensure_ascii=False))
        return 2

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(json.dumps(_fail(f"payload 不是合法 JSON：{exc}"), ensure_ascii=False))
        return 2
    if not isinstance(payload, dict):
        print(json.dumps(_fail("payload 必须是对象"), ensure_ascii=False))
        return 2

    obj, err = _call_cloud(payload)
    source, note = "cloud", ""

    if obj is None:
        obj = _call_local(payload)
        if obj is None:
            print(json.dumps(_fail(err or "云端与本地都失败"), ensure_ascii=False))
            return 2
        source = "local"
        note = f"云端不可用（{err}），已降级为同镜像本地逻辑"

    text = str(obj.get("response") or "").strip()
    if not text:
        print(json.dumps(_fail("智能体返回了空正文"), ensure_ascii=False))
        return 2

    result = {
        "status": "ok",
        "source": source,
        "text": text,
        "clauseRefs": obj.get("clauseRefs") or [],
        "conflictCount": obj.get("conflictCount"),
        "mode": obj.get("mode"),
    }
    if obj.get("clauseSource"):
        result["clauseSource"] = obj["clauseSource"]
    if note:
        result["note"] = note
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
