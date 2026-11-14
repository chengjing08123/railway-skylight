# -*- coding: utf-8 -*-
"""app.py —— AgentArts 高代码运行时入口

只做三件事：建 app、挂 entrypoint、转给 dispatch.handle_invocation。
分派逻辑在 dispatch.py 里 —— SDK 只有云端有，本地跑不了，所以把能测的部分
单独成模块，`python test_modes.py` 就能把五个 mode 全跑一遍。

为什么用同步函数：平台的 @app.entrypoint 异步生成器会被当作「流式输出」，
流式调用要求运行时配回调地址，否则创建沙箱时报 `callback_addresses is empty`。
同步返回字典走标准请求-响应链路，不依赖回调。
"""
from __future__ import annotations

import os
from typing import Any, Dict

from dotenv import load_dotenv

from dispatch import handle_invocation

load_dotenv()

try:
    from agentarts.sdk import AgentArtsRuntimeApp
except ImportError:  # 本地只做语法检查时允许缺包
    raise SystemExit(
        "缺少 agentarts-sdk。部署前执行：\n"
        "  pip install agentarts-sdk -i https://repo.huaweicloud.com/repository/pypi/simple "
        "--trusted-host repo.huaweicloud.com\n"
        "本地测试不需要它：python test_modes.py 直接测 dispatch.py"
    )

app = AgentArtsRuntimeApp()


@app.entrypoint
def invoke(request: Dict[str, Any]) -> Dict[str, Any]:
    """平台入口：一个运行时，按 mode 分派。默认 CHECK（兼容旧调用）。"""
    return handle_invocation(request)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("AGENT_RUN_PORT", "8080")))
