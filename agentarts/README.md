# 天窗协同 · AgentArts 智能体（赛题 2）

> 这是**跑在 AgentArts 平台上**的智能体实现，用于创新赛赛题 2。
> 仓库里那套 Java 服务继续给现有系统用；两边判据相同，靠 `verify_rules.py` 防分叉。

---

## 一、文件说明

| 文件 | 作用 | 本地可跑 |
|---|---|---|
| `skylight_rules.py` | 冲突判定（Python 版，与 Java `AgentCheckService` 同判据） | ✅ |
| `verify_rules.py` | 拿 9/23 的 12 条真实数据比对 gold，防两份实现分叉 | ✅ 纯标准库 |
| `agent_core.py` | 四节点：解析 → 判定 → 检索 → 生成 + 引用校验；协商陈述 | ✅ |
| `multi_agent.py` | 三角色：编排（出 A/B + 代价）/ 核查（确定性）/ 仲裁（给建议 + 退路） | ✅ |
| `dispatch.py` | **mode 分派**：CHECK / ORCHESTRATE / CHECK_PLAN / ARBITRATE / NEGOTIATE | ✅ 不依赖 SDK |
| `test_modes.py` | 五个 mode 全跑一遍（29 项检查） | ✅ |
| `negotiate_cloud.py` | 三个云端运行时串一次协商（方案三） | 需已部署 |
| `clauses.json` | 规章条目库（带 `conflict_type` 元数据做前置过滤） | ✅ |
| `local_test.py` | 本地把整条链路跑一遍，打印最终答复 | ✅ |
| `app.py` | AgentArts 运行时入口（`@app.entrypoint`，转给 `dispatch`） | 需 SDK |
| `requirements.txt` / `.env.example` | 依赖与配置模板 | — |

---

## 二、先在本地验证（不用装任何东西）

```powershell
cd "C:\Users\21264\ds harness work\work\contest-entry\agentarts"
python verify_rules.py     # 期望：PASS，10 对全中，严重 6 / 一般 4
python local_test.py       # 打印一份完整的核查说明
```

`verify_rules.py` 是**防分叉哨兵**：改了 Java 或改了 Python，都要跑一次，两边结果必须一致。

输出示例（节选）：

```
本天窗共 12 条作业，检出 10 条需处理项：严重 6 条、提示 4 条。

一、需立即处理（6 条）
1. 列602区　序18×序49　07:30—09:20 同时占用（依据 2.2.10 第 1 款）
...
三、条文依据
· （依据 2.2.10 第 1 款）两个及以上单位在同一区间或站内作业时，由车务段（直属站）指定主体单位并明确主体负责人。
```

---

## 三、部署到 AgentArts

### 前置（顺序不能乱）

1. 开通 AgentArts 服务
2. **管理中心 > 授权管理** → 完成依赖云服务授权 ← 不授权后面全失败，且报错不指向根因
3. 取模型地址：进「**西南-贵阳一**」[MaaS 控制台](https://console.huaweicloud.com/modelarts/#/model-studio/homepage) → 模型推理 > 在线推理 → 选模型 → API 调用 > 主推版本

> AgentArts 运行时**只支持 cn-southwest-2（贵阳一）**。资源开在别的区会起不来。

### 安装与配置

```powershell
pip install agentarts-sdk -i https://repo.huaweicloud.com/repository/pypi/simple --trusted-host repo.huaweicloud.com
pip install httpx python-dotenv

copy .env.example .env      # 然后填 MODEL_API_KEY
$env:JAVA_HOME 不用管，这条线是 Python

$env:HUAWEICLOUD_SDK_AK = "你的 AK"
$env:HUAWEICLOUD_SDK_SK = "你的 SK"
```

### 部署

```powershell
agentarts configure --entrypoint app:app
```

| 参数 | 填法 |
|---|---|
| Agent name | `skylight-check`（小写字母开头，可含数字和中划线） |
| Region | `cn-southwest-2` |
| Dependency file | `requirements.txt` |
| SWR Organization | 自定义一个（先在贵阳一 SWR 控制台建好） |
| SWR Repository | **留空**，让工具自动建 |

```powershell
agentarts launch          # 自动：构建镜像 → 推 SWR → 部署到运行时
agentarts invoke --agent skylight-check "{\"window\":{\"windowStart\":\"07:30\",\"windowEnd\":\"09:20\"},\"tasks\":[...]}"
```

---

## 四、三个会直接卡住的坑

| 现象 | 原因 | 处理 |
|---|---|---|
| `third-party agent returned status 401` | 默认 IAM 认证，调测需要 API Key | 改 `.agentarts_config.yaml`：`authorizer_type: API_KEY`，**然后删掉已托管的智能体重新 launch**，否则不生效 |
| `launch` 构建失败 / 镜像跑不起来 | 镜像是 **ARM64**，x86 构建的调用必失败 | 官方建议在 **Ubuntu 22.04 ARM64**（可用鲲鹏 ECS）上构建 |
| `invoke` 无响应 | `/ping` 没通或者端口不是 8080 | 先 `curl http://<地址>/ping` 看健康检查 |

Windows 上构建 ARM64 镜像可能不顺。**实在卡住就用一台鲲鹏 ECS 跑 `agentarts launch`**，本地 Windows 只负责写代码和本地测试。

---

## 五、四节点在工作流里的位置

```
① 解析      parse_payload     从请求里取作业列表（结构化 JSON 或 message 里的 JSON 串）
② 判定      check_window      确定性算法，不经模型 —— 这是「不把安全判定交给模型」的落点
③ 检索      retrieve          按 conflict_type 元数据精确过滤，不用向量相似度
④ 生成+校验 render_llm        调 MaaS 生成；输出后校验条号是否真实存在，不过就换模板版
```

**第 ④ 步的引用校验是本项目相对同类方案的差异点**：模型输出里的每一个 `2.x.x` 都会被回查，
查不到就整段替换成模板版本，绝不把编造的条文交给调度员。

---

## 六、初赛要交的截图（照这个清单截）

| # | 截什么 | 在哪 |
|---|---|---|
| 1 | 智能体运行时详情（含部署状态） | 托管与运行 > 智能体运行时 |
| 2 | 编排逻辑 / 运行代码 | 智能体详情 |
| 3 | 知识库列表 + 一条条文详情 | 知识库管理 |
| 4 | 工具或插件定义 | 工具管理 |
| 5 | 一次成功调用的返回（就是上面那段核查说明） | 调测 / invoke |
| 6 | 平台评估报告（用 55 条 gold 跑） | 观测与优化 > 评估 |

前 5 张证明「真的在平台上做了」，第 6 张证明「做得准」。

---

## 七、与 Java 版的关系（重要）

同一套判据现在有两份实现：

| 位置 | 用途 |
|---|---|
| `_repo/.../agent/AgentCheckService.java` | 现有系统的 HTTP 接口 `/api/agent/check` |
| 本目录 `skylight_rules.py` | AgentArts 运行时（云上访问不到本机，必须内嵌） |

**改判据必须两边同时改，然后各跑一次验证**：

```powershell
python verify_rules.py                      # Python 侧
python ..\agent-api\smoke_agent_api.py      # Java 侧（需先 start-8081.cmd）
```

两边都应输出 10 对、命中 10。任一边不到 10，说明改分叉了。

> 长期看应该只留一份（比如 Java 侧调 Python 服务，或平台侧保留 Java）。
> 初赛阶段先接受这个重复 —— 它换来的是一天内就能跑通平台。
