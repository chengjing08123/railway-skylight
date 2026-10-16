# 铁路维修天窗多专业协同智能体

面向普速铁路维修天窗，在既有天窗计划系统之上，做「智能编排 + 合规核查」层——自动检测多工区/多专业作业在同一作业单元、同一时段内的冲突。

## 技术栈

- Java 25 · Spring Boot 4.0.6 · Maven 多模块
- MySQL 8.0 · MyBatis · PageHelper
- 核心算法为纯 Java（无框架依赖，可独立编译单测）

## 模块结构

```
railway-skylight/               父工程（pom）
├── skylight-common/            纯 Java：实体 + 冲突检测算法
│   └── src/main/java/com/skylight/
│       ├── entity/             实体（WorkTask / Skylight / Coordination / TaskDependency）
│       └── core/               冲突检测引擎 ConflictDetector + 结果类 Conflict
└── skylight-server/            Spring Boot 主服务
    └── src/main/
        ├── java/com/skylight/  SkylightApplication 启动类
        └── resources/          application.yml + db/schema.sql
```

## 快速开始

1. **配数据库**：改 `skylight-server/src/main/resources/application.yml` 里的 `password` 为你的 MySQL 密码；
2. **建库建表**：执行 `skylight-server/src/main/resources/db/schema.sql`；
3. **启动**：IDEA 里运行 `SkylightApplication`。

## 核心：六类冲突检测（全部确定性算法）

| 冲突 | 判定 |
|---|---|
| 作业单元冲突 | 同一作业单元被 ≥2 个工区占用 |
| 时长冲突 | 同单元作业时长之和 > 天窗时长 |
| 电气冲突 | 停电范围 ∩ 带电需求矛盾 |
| 依赖冲突 | 依赖关系成环（Kahn 拓扑排序）|
| 配合缺失 | 配合单位未确认到场 |
| 主次违反 | 主体与"设备归属专业"规则不符 |

算法入口 `ConflictDetector`，演示 `core/Demo`（真实萍乡数据样例，检出 7 条冲突）。

## 当前进度

- ✅ 六类冲突算法已实现并跑通验证
- ⏳ 待做：seed 数据导入 → MyBatis Mapper → Service → Controller → 前端看板
