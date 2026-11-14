# -*- coding: utf-8 -*-
"""verify_cloud.py —— 调云端已部署的智能体，与 gold 逐对比对。

    python verify_cloud.py            # 12 条真实作业，对比 gold
    python verify_cloud.py --raw      # 只打印原始输出，不比对

与 invoke_agent.py 的区别：这个会解析 confl生成文本里的「序NN×序MM」配对，
和 gold_0923.csv 做集合比对，给出 命中/漏/多报。
"""
from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
CLI = Path(os.environ["LOCALAPPDATA"]) / "Programs/Python/Python314/Scripts/agentarts.exe"
DATA = Path(r"C:\Users\21264\ds harness work\work\tools\data")
TASKS_CSV = DATA / "tasks_0923.csv"
GOLD_CSV = DATA / "gold_0923.csv"
CRED = Path(r"D:\下载\credentials.csv")
AGENT = "skylight-check"

PAIR_RE = re.compile(r"序(\d+)\s*×\s*序(\d+)")


def set_credentials() -> None:
    if not CRED.exists():
        return
    rows = list(csv.DictReader(open(CRED, encoding="utf-8-sig")))
    if rows:
        os.environ["HUAWEICLOUD_SDK_AK"] = rows[0]["Access Key Id"].strip()
        os.environ["HUAWEICLOUD_SDK_SK"] = rows[0]["Secret Access Key"].strip()


def build_payload() -> dict:
    tasks = []
    with open(TASKS_CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            r = {(k or "").strip(): (v or "").strip() for k, v in r.items()}
            units = [u.strip() for u in (r.get("unit_ids") or "").split(";") if u.strip()]
            sw = [s.strip() for s in (r.get("switches") or "").split("|") if s.strip()]
            mf, mt = r.get("mile_from", ""), r.get("mile_to", "")
            tasks.append({
                "taskId": r["task_id"], "serialNo": int(r["no"]), "team": r["team"],
                "unitCodes": units, "start": r["t_start"], "end": r["t_end"],
                "mileFrom": int(mf) if mf.isdigit() else None,
                "mileTo": int(mt) if mt.isdigit() else None,
                "switches": sw,
            })
    return {"window": {"windowStart": "07:30", "windowEnd": "09:20"}, "tasks": tasks}


def serial_map() -> dict[str, int]:
    m = {}
    with open(TASKS_CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            r = {(k or "").strip(): (v or "").strip() for k, v in r.items()}
            m[r["task_id"]] = int(r["no"])
    return m


def gold_pairs() -> set[frozenset[int]]:
    s = serial_map()
    pairs: set[frozenset[int]] = set()
    with open(GOLD_CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            r = {(k or "").strip(): (v or "").strip() for k, v in r.items()}
            if r.get("is_conflict") != "1":
                continue
            peer = r.get("peer_task_id") or ""
            if not peer:
                continue
            a, b = s.get(r["task_id"]), s.get(peer)
            if a and b:
                pairs.add(frozenset((a, b)))
    return pairs


def extract_text(stdout: str) -> str:
    """从 agentarts invoke 的输出里拼出答复正文。"""
    chunks = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        raw = line[5:].strip()
        if not raw or raw == "[DONE]":
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and obj.get("response"):
            chunks.append(obj["response"])
    if chunks:
        return "".join(chunks)
    # 兜底：整段输出里找 response 字段
    for m in re.finditer(r'"response"\s*:\s*"((?:[^"\\]|\\.)*)"', stdout):
        try:
            chunks.append(json.loads(f'"{m.group(1)}"'))
        except json.JSONDecodeError:
            pass
    return "".join(chunks)


def section_pairs(text: str) -> tuple[set[frozenset[int]], set[frozenset[int]]]:
    """切出「需立即处理（严重）」与「待确认」两段，各自提取配对。"""
    serious: set[frozenset[int]] = set()
    minor: set[frozenset[int]] = set()

    i1 = text.find("需立即处理")
    i2 = text.find("待确认")
    i3 = text.find("条文依据")

    if i1 >= 0 and i2 > i1:
        for a, b in PAIR_RE.findall(text[i1:i2]):
            serious.add(frozenset((int(a), int(b))))
    if i2 >= 0:
        end = i3 if i3 > i2 else len(text)
        for a, b in PAIR_RE.findall(text[i2:end]):
            minor.add(frozenset((int(a), int(b))))
    return serious, minor


def fmt(pairs: set[frozenset[int]]) -> str:
    return "、".join("×".join(str(x) for x in sorted(p)) for p in sorted(pairs, key=lambda s: sorted(s))) or "无"


def main() -> int:
    set_credentials()
    payload = build_payload()
    js = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    print(f"invoke → {AGENT}（{len(payload['tasks'])} 条作业）...")
    r = subprocess.run([str(CLI), "invoke", "--agent", AGENT, js],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=900)
    out = (r.stdout or "")
    text = extract_text(out)

    if "--raw" in sys.argv or not text:
        print(out.strip()[:4000])
        if r.stderr:
            print("[stderr]", (r.stderr.strip())[:2000])
        if not text:
            print(f"\n✗ 没有解析到答复正文，退出码 {r.returncode}")
            return 1

    serious, minor = section_pairs(text)
    got = serious | minor
    gold = gold_pairs()

    hit = got & gold
    miss = gold - got
    extra = got - gold

    print("\n" + "=" * 62)
    print(text.strip())
    print("=" * 62)
    print(f"云端 严重 {len(serious)} / 提示 {len(minor)} / 合计 {len(got)}")
    print(f"gold {len(gold)} 对 / 云端 {len(got)} 对 / 命中 {len(hit)}")
    print(f"漏   {fmt(miss)}")
    print(f"多报 {fmt(extra)}")

    ok = not miss and not extra and len(got) == len(gold)
    print("\n结论： " + ("PASS 云端结果与 gold 完全一致" if ok else "FAIL 与 gold 不一致"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
