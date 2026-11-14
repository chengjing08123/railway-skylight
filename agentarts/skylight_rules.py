# -*- coding: utf-8 -*-
"""skylight_rules.py —— 天窗冲突判定（Python 版，与 Java AgentCheckService 同判据）

为什么要有这一份：AgentArts 的智能体运行时跑在华为云上，访问不到你本机的
127.0.0.1:8081，所以判定逻辑必须能在运行时里直接跑。Java 版保留在仓库里给
现有系统用，这份是给平台的。

判据（与 9/23 窗口 gold 校准过，10 对全中）：
  1. 只在【不同工区】之间判单元冲突 —— 同工区自有作业可自行避让；
  2. 两两成对输出，一条冲突只涉及两条作业；
  3. 时段必须重叠（半开区间，端点相接不算）；
  4. 单元级一致 → 严重；仅区域级一致但有里程或道岔佐证 → 严重；否则 → 一般；
  5. 时长冲突默认关闭（作业时段抄了天窗时段，判据失去区分力）。

对应 Java：skylight-server/src/main/java/com/skylight/agent/AgentCheckService.java
两份必须同时改，否则会分叉 —— verify_rules.py 是防分叉的哨兵。
"""
from __future__ import annotations

import re
import unicodedata
from datetime import time

FIXED_OVERHEAD_MIN = 15

STATION_PREFIX = re.compile(r"^(萍乡新场|萍乡|新场)")
UNIT_LEVEL = re.compile(r"^列(\d{3})区$")
LEADING_SEP = re.compile(r"^[-—_·、,，]+")


# ---------------------------------------------------------------- 归一化
def normalize_units(raw: list[str] | None) -> list[str]:
    """NFKC → 去空白 → 去站名前缀 → 去残留分隔符。

    真实数据里是「萍乡新场-列602区」这种写法，少任何一步都会把同一个单元
    当成两个，直接漏冲突。
    """
    if not raw:
        return []
    out: list[str] = []
    for one in raw:
        if not one:
            continue
        s = unicodedata.normalize("NFKC", str(one))
        s = re.sub(r"\s+", "", s)
        s = STATION_PREFIX.sub("", s)
        s = LEADING_SEP.sub("", s)
        if s and s not in out:
            out.append(s)
    return out


def is_unit_level(unit: str) -> bool:
    return bool(UNIT_LEVEL.match(unit))


def parse_time(v) -> time | None:
    if v is None:
        return None
    s = str(v).strip()
    if len(s) < 5:
        return None
    try:
        hh, mm = int(s[0:2]), int(s[3:5])
        return time(hh, mm)
    except (ValueError, IndexError):
        return None


def minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def hhmm(t: time) -> str:
    return f"{t.hour:02d}:{t.minute:02d}"


# ---------------------------------------------------------------- 判定
def _prepare(tasks: list[dict]) -> list[dict]:
    out = []
    for t in tasks:
        s, e = parse_time(t.get("start")), parse_time(t.get("end"))
        if s is None or e is None or not s < e:
            continue          # 时刻非法就跳过这一条，不让整批失败
        out.append({
            "task": t,
            "start": s,
            "end": e,
            "units": normalize_units(t.get("unitCodes")),
        })
    return out


def _id_of(t: dict) -> str:
    tid = (t.get("taskId") or "").strip()
    if tid:
        return tid
    return str(t.get("serialNo") or "unknown")


def _team(t: dict) -> str:
    return (t.get("team") or "").strip()


def _mile_overlap(a: dict, b: dict) -> int:
    t1, t2 = a["task"], b["task"]
    f1, t1v = t1.get("mileFrom"), t1.get("mileTo")
    f2, t2v = t2.get("mileFrom"), t2.get("mileTo")
    if None in (f1, t1v, f2, t2v):
        return 0
    return max(0, min(t1v, t2v) - max(f1, f2))


def _switch_overlap(a: dict, b: dict) -> list[str]:
    s1 = set(a["task"].get("switches") or [])
    s2 = set(b["task"].get("switches") or [])
    return sorted(s1 & s2)


def _unit_conflicts(prepared: list[dict]) -> list[dict]:
    conflicts = []
    n = len(prepared)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = prepared[i], prepared[j]

            # ① 跨工区
            if _team(a["task"]) == _team(b["task"]):
                continue
            # ② 时段重叠
            if not (a["start"] < b["end"] and b["start"] < a["end"]):
                continue
            # ③ 共享单元
            shared = [u for u in a["units"] if u in b["units"]]
            if not shared:
                continue

            unit_level = any(is_unit_level(u) for u in shared)
            mile = _mile_overlap(a, b)
            sw = _switch_overlap(a, b)
            severe = unit_level or mile > 0 or len(sw) >= 2

            ids = [_id_of(a["task"]), _id_of(b["task"])]
            serials = sorted(
                x for x in (a["task"].get("serialNo"), b["task"].get("serialNo"))
                if x is not None
            )
            unit_text = "、".join(shared)
            desc = (f"作业单元【{unit_text}】被「{_team(a['task'])}」与「{_team(b['task'])}」"
                    f"在 {hhmm(a['start'])}—{hhmm(a['end'])} 同时占用")
            basis = (f"共享单元={unit_text}；级别={'单元级' if unit_level else '区域级'}；"
                     f"里程重叠={mile}m；道岔重叠={len(sw)}组"
                     + (f"({','.join(sw)})" if sw else ""))

            conflicts.append({
                "id": "作业单元冲突|" + "|".join(ids),
                "type": "作业单元冲突",
                "involved": ids,
                "serialNos": serials,
                "ruleRef": "2.2.10 第 1 款",
                "severity": "严重" if severe else "一般",
                "description": desc,
                "suggestion": ("按 2.2.10 第 1 款由车务段指定主体单位并划分分界点；"
                               "或将其中一条作业移出该单元") if severe
                              else "作业区域重叠，需确认分界点与防护措施",
                "basis": basis,
            })
    return conflicts


def _duration_conflicts(prepared: list[dict], ws: str, we: str) -> list[dict]:
    w_start, w_end = parse_time(ws), parse_time(we)
    if w_start is None or w_end is None or not w_start < w_end:
        return []
    window_min = minutes(w_end) - minutes(w_start)
    usable = window_min - FIXED_OVERHEAD_MIN

    by_unit: dict[str, list[dict]] = {}
    for p in prepared:
        for u in p["units"]:
            by_unit.setdefault(u, []).append(p)

    out = []
    for unit, group in sorted(by_unit.items()):
        if len(group) < 2:
            continue                      # 单条作业占满天窗是填表习惯，不是超窗
        iv = sorted((minutes(p["start"]), minutes(p["end"])) for p in group)
        total, s, e = 0, iv[0][0], iv[0][1]
        for x0, x1 in iv[1:]:
            if x0 <= e:
                e = max(e, x1)
            else:
                total, s, e = total + e - s, x0, x1
        used = total + e - s

        if used <= usable:
            continue
        out.append({
            "id": f"时长冲突|{unit}",
            "type": "时长冲突",
            "involved": [_id_of(p["task"]) for p in group],
            "serialNos": sorted(p["task"].get("serialNo") for p in group
                                if p["task"].get("serialNo") is not None),
            "ruleRef": "2.2.1",
            "severity": "一般",
            "description": (f"作业单元【{unit}】占用 {used} 分钟，有效可用仅 {usable} 分钟"
                            f"（天窗 {window_min} 分钟，已扣 {FIXED_OVERHEAD_MIN} 分钟固定开销）"),
            "suggestion": "压缩作业量，或将部分作业移出该天窗",
            "basis": f"并集占用={used}min；可用={usable}min；单元作业数={len(group)}",
        })
    return out


def check_window(tasks: list[dict], window: dict | None = None,
                 detect_duration: bool = False) -> dict:
    """判定一个天窗内的冲突。

    :param tasks: 作业列表，每条含 taskId/serialNo/team/unitCodes/start/end/...
    :param window: {"windowStart": "07:30", "windowEnd": "09:20"}
    :param detect_duration: 是否判时长冲突，默认 False（原因见模块 docstring）
    """
    window = window or {}
    prepared = _prepare(tasks or [])

    conflicts = _unit_conflicts(prepared)
    if detect_duration:
        conflicts += _duration_conflicts(
            prepared, window.get("windowStart"), window.get("windowEnd"))

    return {
        "taskCount": len(tasks or []),
        "conflictCount": len(conflicts),
        "conflicts": conflicts,
    }
