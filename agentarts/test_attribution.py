# -*- coding: utf-8 -*-
"""test_attribution.py —— 本地验证「模型归因 + 白名单校验」这一层。

不依赖 AgentArts SDK，也不依赖云端：直接跑 dispatch.handle_invocation。
    python test_attribution.py
"""
from __future__ import annotations

import json
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

os.environ.setdefault("RENDER_MODE", "auto")

import dispatch  # noqa: E402

PAYLOAD = {
    "window": {"windowStart": "07:30", "windowEnd": "09:20"},
    "tasks": [
        {"taskId": "A", "serialNo": 18, "team": "萍乡新场线路工区",
         "unitCodes": ["列602区"], "start": "07:30", "end": "09:20"},
        {"taskId": "B", "serialNo": 49, "team": "萍乡检查工区",
         "unitCodes": ["萍乡新场列602区"], "start": "07:30", "end": "09:20"},
        {"taskId": "C", "serialNo": 33, "team": "萍乡检查工区",
         "unitCodes": ["列4区"], "start": "08:10", "end": "09:00"},
        {"taskId": "D", "serialNo": 40, "team": "萍乡线路工区",
         "unitCodes": ["列4区"], "start": "08:20", "end": "09:10"},
    ],
}


def main() -> int:
    t0 = time.time()
    out = dispatch.handle_invocation(PAYLOAD)
    dt = time.time() - t0

    print(f"status={out.get('status')}  conflictCount={out.get('conflictCount')}")
    print(f"clauseSource={out.get('clauseSource')}  （model=模型归因生效）")
    print(f"clauseRefs={out.get('clauseRefs')}")
    notes = out.get("attributionNotes") or []
    print(f"attributionNotes={len(notes)} 条")
    for n in notes:
        print("   ·", n)
    print(f"耗时 {dt:.1f}s")
    print("\n—— 正文 ——")
    print(out.get("response", ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
