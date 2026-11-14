# -*- coding: utf-8 -*-
"""_add_agents.py —— 复制 skylight-check 的配置，生成另两个运行时（一次性工具）。

方案三：三个独立运行时，同一个镜像，靠 AGENT_DEFAULT_MODE 区分默认角色。

    python _add_agents.py            # 写入 .agentarts_config.yaml（幂等）
    python _add_agents.py --dry-run  # 只看会写什么
"""
from __future__ import annotations

import copy
import shutil
import sys
from pathlib import Path

import yaml

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
CFG = HERE / ".agentarts_config.yaml"

NEW_AGENTS = [
    ("skylight-orchestrator", "ORCHESTRATE"),
    ("skylight-arbiter", "ARBITRATE"),
]


def main() -> int:
    dry = "--dry-run" in sys.argv
    data = yaml.safe_load(CFG.read_text(encoding="utf-8"))
    agents = data["agents"]
    base = agents["skylight-check"]

    added = []
    for name, mode in NEW_AGENTS:
        if name in agents:
            print(f"= {name} 已存在，跳过")
            continue
        blk = copy.deepcopy(base)
        blk["base"]["name"] = name
        blk["swr_config"]["repository"] = base["swr_config"]["repository"]

        rt = blk["runtime"]
        rt["agent_id"] = None                       # 新运行时，不复用旧 ID
        rt["artifact_source"]["url"] = base["runtime"]["artifact_source"]["url"]
        envs = [e for e in (rt.get("environment_variables") or [])
                if e.get("key") != "AGENT_DEFAULT_MODE"]
        envs.append({"key": "AGENT_DEFAULT_MODE", "value": mode})
        rt["environment_variables"] = envs
        agents[name] = blk
        added.append((name, mode))
        print(f"+ {name}（默认 mode={mode}）")

    if not added:
        print("没有新增，配置未改。")
        return 0
    if dry:
        print("[dry-run] 未写盘")
        return 0

    shutil.copy2(CFG, HERE / "备份-.agentarts_config.yaml")
    CFG.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                   encoding="utf-8")
    print(f"已写入 {CFG.name}（备份 备份-.agentarts_config.yaml）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
