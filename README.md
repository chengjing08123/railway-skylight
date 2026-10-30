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
        ├── java/com/skylight/
        │   ├── SkylightApplication.java    启动类
        │   ├── mapper/                     MyBatis Mapper（查库）
        │   ├── service/                    ConflictService（查库 → 算法）
        │   └── controller/                 ConflictController（REST）
        └── resources/
            ├── application.yml             公共配置（无敏感信息）
            ├── application-dev.yml         本地数据库配置（已 gitignore）
            ├── application-dev.yml.example 配置模板（复制改密码）
            └── db/
                ├── schema.sql              建表脚本
                └── seed.sql                测试数据（工务段真实作业）
```

## 快速开始

1. **配数据库**：复制 `application-dev.yml.example` 为 `application-dev.yml`，填入你的 MySQL 密码；
2. **建库建表**：执行 `db/schema.sql`；
3. **导入测试数据**：执行 `db/seed.sql`（21 个天窗 + 42 条真实作业 + 4 条配合）；
4. **启动**：运行 `SkylightApplication`；
5. **验证**：浏览器访问 `http://localhost:8080/api/conflicts`，应返回冲突 JSON。

## 核心：六类冲突检测（全部确定性算法）

| 冲突 | 判定 | 状态 |
|---|---|---|
| 作业单元冲突 | 同一作业单元被 ≥2 个工区占用 | ✅ 已实现 |
| 时长冲突 | 同单元作业时长之和 > 天窗时长 | ✅ 已实现 |
| 电气冲突 | 停电范围 ∩ 带电需求矛盾 | 🔸 逻辑就绪，待电务/供电数据 |
| 依赖冲突 | 依赖关系成环（Kahn 拓扑排序）| ✅ 已实现 |
| 配合缺失 | 配合单位未确认到场 | ✅ 已实现 |
| 主次违反 | 主体与"设备归属专业"规则不符 | 🔸 待规则表 |

## REST API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/conflicts` | 返回全部冲突检测结果（JSON，字段 type/description/suggestion/involved）|

## 当前进度

- ✅ 后端链路：实体 → Mapper → Service → Controller → REST API，真实数据端到端跑通
- ⏳ 待做：前端看板（任务看板 + 冲突提示 + 甘特图）

详细方案见 `../铁路综合维修天窗多专业协同智能体-合并版方案.md`。
