# 最小多智能体设计（PLAN_AND_NEGOTIATE）

> 承接：《项目方案 v1.2》4.5 节「多智能体：为什么必须是『多』」
> 状态：代码已实现并跑通（`multi_agent.py` + `test_negotiate.py`）；
> **路线 2（一个运行时 /invocations 按 mode 分派）已上云**，路线 1 待做
> 日期：2026-11-15

---

## 一、为什么是三个角色，不是六个

方案原文：「七个功能模块不是七个智能体……得到 6 个执行角色和 1 个编排者」。

**6+1 是设计语言，3 是工程语言。** 本轮只实现方案里最硬的环节 `PLAN_AND_NEGOTIATE`，
其余四个 mode（REVIEW_AND_SIGN / BRIEF / POSTMORTEM / 执行态观测）留到二期。

| 方案角色（6+1） | 本轮 | 说明 |
|---|---|---|
| 编排者 | ✅ ORCHESTRATOR | 生成 A/B 候选方案 + 代价 |
| 合规核查 | ✅ CHECKER | 确定性判定，不经模型 |
| 仲裁 | ✅ ARBITER | 对比、给建议、**不拍板** |
| 方案编制 | ⏳ 二期 | 从申请单文本生成作业项 |
| 签署/留痕 | ⏳ 部分（留痕已有） | 人签，智能体只摆空格 |
| 简报/复盘 | ⏳ 二期 | — |

> **答辩口径建议**：说「我们实现了 6+1 里的核心三环（编排/核查/仲裁），其余按 mode 逐步接入」，
> 不要既说「必须多智能体」又说「其实是一个编排器的五个 mode」—— 这两句放一起会被追问。

---

## 二、三个角色的契约

### 2.1 ORCHESTRATOR（编排者）

| | |
|---|---|
| 入参 | `tasks[]`（作业列表）、`window{}`（天窗时段） |
| 出参 | `plans[]`：每个含 `planId` / `name` / `tasks[]` / `cost{}` / `rationale` |
| 禁止 | 不得输出没有 `cost` 的方案；不得替人选择 |
| 依据 | 「没有代价的方案不是方案，是口号」 |

**代价字段是必填**，结构：

```json
{
  "affectedTeam": "萍乡检查工区",
  "movedCount": 6,
  "workloadRisk": "6 条检查作业需另排天窗，可能延后 1 天",
  "safetyGain": "重叠减少，天窗内跨工区交叉作业减少",
  "quantified": {"冲突": "归零", "延期作业": 6, "延期天数": 1}
}
```

**退让方怎么选（不写死工区）**：

1. 工区名里带「检查」的优先 —— 检查作业可延后，不影响线路维修主体；
2. 没有检查工区，取**作业条数最少**的工区（影响面最小）；
3. 只有一个工区，明确标「无可退让」，不硬凑方案。

**「冲突」那一栏不归编排者写。** 编排者只说「移出谁」，核查者算完通过
`fill_cost()` 回填 —— 编排者不给自己打分，这是角色分离的又一处落点。

### 2.2 CHECKER（核查者）

| | |
|---|---|
| 入参 | 一个 `plan` |
| 出参 | `{planId, conflictCount, severe, normal, conflicts[]}` |
| 禁止 | **不得调用大模型**；判定只走 `skylight_rules.check_window` |

这一点是「确定性内核」的落点：核查结果可复现、可重放、与模型无关。

### 2.3 ARBITER（仲裁者）

| | |
|---|---|
| 入参 | 两个方案的核查结果 + 代价 |
| 出参 | `{recommended, reason, fallback, requiresHumanChoice: true, options[]}` |
| 禁止 | **不得输出「已决定」**；必须给退路条件 |

判据是确定性的（严重冲突数 → 总冲突数 → 变动量），模型只负责把理由说顺。

---

## 三、协商时序（每一次箭头传的都是结构化产物）

```
用户/调度员
   │  tasks[] + window{}
   ▼
ORCHESTRATOR ──plans[A,B]（含 cost）──► CHECKER
                                            │ 每个方案跑一次确定性判定
                                            ▼
                                     checked[{planId, conflictCount, severe}]
                                            │
                                            ▼
                                        ARBITER
                                            │ verdict{recommended, reason, fallback}
                                            ▼
                                        人工确认（确认台选 A / B）
```

**没有一条箭头传自由文本** —— 这正是方案里说的「与 AutoGen / LangGraph 的区别不在编排框架，
在于把协作负载约束成了契约」。

---

## 四、留痕三表

代码里的 `Trace` 已经产出事件流，落库时拆成三张表：

| 表 | 字段 | 对应事件 |
|---|---|---|
| `agent_session` | session_id、窗口、参与角色、开始/结束 | 一次 `negotiate()` |
| `agent_message` | session_id、轮次、speaker、to、kind、payload(JSON) | `{"type":"message"}` |
| `agent_decision` | session_id、by、choice、reason、人工是否采纳 | `{"type":"decision"}` |

当前实现每次协商产出 **5 条事件**（4 message + 1 decision）。

---

## 五、与真实数据的验证结果

9/23 窗口（12 条作业、110 分钟）跑出的协商：

| 方案 | 冲突 | 延期 | 安全 |
|---|---|---|---|
| **A 检查工区顺延** | **0 条** | 6 条作业、1 天 | 重叠消除 |
| B 保留全部·分区分界 | 10 条（严重 6） | 0 | 靠协调与防护 |

仲裁建议 A，理由「严重冲突 0 vs 6，安全优先」，**同时给出退路**：
「若检查计划不可延期，则应改取 B，并按 2.2.10 第 1 款逐条指定主体单位、划分界点」。

> 这不是两个技术方案，是两个价值取向：**安全优先 vs 作业量优先**。
> 能把这个权衡摆到台面上，比给一个「最优解」更像真实调度场景。

---

## 六、怎么落到 AgentArts

### 6.0 路线 2 已落地：一个入口，五个 mode

`/invocations` 的入参多一个 `mode` 字段，同一个运行时按它分派到不同角色。
**省略 `mode` 时按 `CHECK` 处理**，所以旧的调用方（前端、后端、演示脚本）一个字都不用改。

| mode | 谁在干活 | 产出 | 是否调模型 |
|---|---|---|---|
| `CHECK`（默认） | 四节点流水线 | 冲突清单 + 带引用的核查说明 | 是（失败回退模板） |
| `ORCHESTRATE` | 编排者 | 两套方案 + 代价 | 否 |
| `CHECK_PLAN` | 核查者 | 单个方案的冲突数 / 严重度 | **否**（确定性） |
| `ARBITRATE` | 仲裁者 | 建议 + 理由 + 退路 | 可选 |
| `NEGOTIATE` | 三者串联 | 上面全部 + 留痕 5 条事件 | 可选 |

调用示例（全链路协商）：

```json
{
  "mode": "NEGOTIATE",
  "window": {"windowStart": "07:30", "windowEnd": "09:20"},
  "tasks": [{"taskId": "...", "serialNo": 18, "team": "...",
             "unitCodes": ["列602区"], "start": "07:30", "end": "09:20"}]
}
```

返回（节选）：

```json
{
  "mode": "NEGOTIATE", "status": "ok", "sessionId": "S-01b938ba3de8",
  "conflictCount": 0,
  "verdict": {"recommended": "A", "requiresHumanChoice": true, "fallback": "…2.2.10 第 1 款…"},
  "trace": {"sessionId": "S-…", "events": [{"type": "message", "speaker": "ORCHESTRATOR", …},
                                            {"type": "decision", "by": "ARBITER", …}]},
  "response": "天窗 07:30—09:20，12 条作业，给出两套候选方案：…"
}
```

三条工程约定：

1. **会话号幂等** —— 不给 `sessionId` 时按 `(mode, 作业ID集合)` 的 SHA-1 前 12 位派生，
   同一批作业同一个 mode 连点两次拿到同一个会话号，不会重复烧模型；
2. **回包剥 `tasks`** —— 方案里只回 `planId / name / cost / movedTasks`，
   不然 12 条作业 × 2 套方案会把响应撑到几十 KB；
3. **分派逻辑与 SDK 分离** —— `dispatch.py`（可本地测）+ `app.py`（只挂 entrypoint），
   所以 `python test_modes.py` 能在不部署的情况下把五个 mode 全跑一遍。

#### taskMode：对外的业务叫法（方案 v1.3 表 4）

请求里带 `taskMode` 就不看 `mode`，一层名字映射，不新增实现：

| taskMode | 状态 | 内部实现 | 产出 |
|---|---|---|---|
| `PRE_REVIEW` 编制预审 | ✅ 一期 | `NEGOTIATE` + 冲突清单 | 仲裁建议 + 每条冲突的分界点要求 + 5 条留痕 |
| `SIGN_REVIEW` 会签审查 | ⏳ 二期 | — | `status: not_implemented` + `available: ["PRE_REVIEW"]` |
| `BRIEF` 点前交底 | ⏳ 二期 | — | 同上 |

**没做的就回 `not_implemented`**，不拿模板话术假装实现 —— 答辩时这一点比多做半档更有说服力。

### 路线 1（已落地）：三个独立运行时，客户端编排

同一个镜像部署 **三次**，靠 `AGENT_DEFAULT_MODE` 区分默认角色 —— 不传 `mode` 就是该角色：

| Agent 名 | 默认角色 | Runtime ID（2026-11-15 重建） |
|---|---|---|
| `skylight-orchestrator` | ORCHESTRATE | 同上 |
| `skylight-check` | CHECK | `5248b6ad-381f-493e-90f8-37cd2dde6254` |
| `skylight-arbiter` | ARBITRATE | 同上 |

串联放在**客户端**（`negotiate_cloud.py`），而不是运行时之间互调：

```
negotiate_cloud.py
  ├─ invoke skylight-orchestrator  → plans[]（含 cost）
  ├─ invoke skylight-check ×2      → checks[]（确定性判定）
  └─ invoke skylight-arbiter       → verdict{recommended, reason, fallback}
       ↓
  本地拼 trace（5 条事件）→ negotiate_cloud.json
```

为什么不做运行时互调：华为云的运行时之间调另一个运行时，要给它配**委托代理
（execution agency）+ IAM 签名**，这一步在公测期权限链最深、最容易卡住；
而「谁按什么顺序调用」本来就是编排者的职责，放在客户端只是把编排者的位置
从云端挪到了调用方 —— **角色仍是三个独立实例，契约也没变**。

- 优点：控制台里能看到 3 个智能体；每个角色能单独调、单独演示、单独扩缩
- 代价：3 次部署；冷启动各一次（脚本已自动重试）；客户端要串四次调用
- 工期：实际 40 分钟（镜像复用 + `--skip-build` 部署）

**踩到的一个坑**：仲裁者收到的 `checks` 是链路中间产物，只带计数、不带
`conflicts` 明细；`_mode_arbitrate` 里若直接 `c["conflicts"]` 就 KeyError。
契约要写清「哪个字段是必须的、哪个是可选的」—— 跨运行时之后，
每个角色的入参都不再由自己控制。

### 路线 2（已落地）：一个运行时，三个角色

现有 `skylight-check` 运行时内，`/invocations` 按 `mode` 字段分派到三个角色函数。

- 优点：零新增部署，今天就能上；留痕与契约完全一样
- 代价：平台侧只显示一个智能体，评审可能认为「不是多智能体」
- 工期：0.5 天

### 两个都落地之后的组合（答辩口径）

| 形态 | 怎么讲 |
|---|---|
| 部署形态 | **三个独立运行时**：编排 / 核查 / 仲裁各一个，控制台里能看到三个智能体 |
| 调用形态 | 前端与后端只调一个入口（`skylight-check`，默认 CHECK）——既有集成一行没改 |
| 演示形态 | `negotiate_cloud.py` 串三个运行时，一次跑出 A/B 两套方案 + 裁决 + 5 条留痕 |
| 判据 | 职责是否分离、协作负载是否契约化 —— **不是进程数** |

三种用法按场景取：要演示「多智能体」用三运行时；要演示「一条链路跑完」用
`NEGOTIATE`；现场只是查一条天窗，用 `CHECK`。

---

## 七、下一步（按优先级）

| # | 事项 | 工期 | 谁 | 状态 |
|---|---|---|---|---|
| 1 | 路线 2：`/invocations` 按 mode 分派三角色 | 0.5 天 | 我 | ✅ 2026-11-15 |
| 2 | 前端确认台接 A/B 选择（替换现有「已处理/忽略」） | 1 天 | 成员二 | 待做 |
| 3 | 留痕三表落库 + 导出 | 1 天 | 成员一 | 待做 |
| 4 | 路线 1：拆编排者/仲裁者两个运行时 | 2 天 | 我 | ✅ 2026-11-15（40 分钟） |
| 5 | 方案 4.5 与全流程设计的口径统一 | 0.5 天 | 文档主笔 | ✅ 2026-11-14 |
