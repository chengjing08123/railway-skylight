# -*- coding: utf-8 -*-
"""export_kb.py —— 把 clauses.json 导出成可上传知识库的 Markdown。

AgentArts 知识库一般按标题切块，所以一条条文一个二级标题，正文里带上
条号、类型、适用场景 —— 这样检索时元数据也在文本里，召回更稳。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
KB = HERE / "clauses.json"
OUT = HERE / "规章条目库.md"


def main() -> int:
    data = json.loads(KB.read_text(encoding="utf-8-sig"))
    clauses = data.get("clauses", [])

    L = ["# 普速铁路工务安全规则 · 天窗合规核查条目库", ""]
    L.append(f"> 版本 {data.get('version', '1.0')}　｜　共 {len(clauses)} 条")
    L.append("> 用途：天窗作业计划合规核查，供智能体检索条文依据。")
    L.append("")

    for i, c in enumerate(clauses, 1):
        L.append(f"## {i}. {c['conflict_type']}（{c['rule_ref']}）")
        L.append("")
        L.append(f"- **规则编号**：{c.get('rule_code', '')}")
        L.append(f"- **冲突类型**：{c.get('conflict_type', '')}")
        L.append(f"- **适用场景**：{'、'.join(c.get('applies_to', []))}")
        L.append("")
        if c.get("text"):
            L.append(f"**条文原文**：{c['text']}")
        else:
            L.append(f"**条文摘要**：{c.get('summary', '')}")
            L.append("")
            L.append("> 注：本条原文尚未核对录入，当前为摘要。用于引用时须标注「条文摘要」。")
        L.append("")

    L.append("---")
    L.append("")
    L.append("## 使用约定")
    L.append("")
    L.append("1. 判定「是否冲突」用确定性算法，条文只用于**解释与追溯**，不用来解释倒推判定。")
    L.append("2. 每条结论必须能回指到具体的「条号 + 款号」，回指不到的不输出。")
    L.append("3. 标为「条文摘要」的条目，生成时须带「条文摘要」字样，不得表述为原文。")

    OUT.write_text("\n".join(L), encoding="utf-8")
    print(f"ok → {OUT}")
    print(f"条目 {len(clauses)} 条，原文 {sum(1 for c in clauses if c.get('text'))} 条，"
          f"摘要 {sum(1 for c in clauses if not c.get('text'))} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
