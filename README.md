# 铁路维修天窗多专业协同智能体

面向普速铁路维修天窗，在既有天窗计划系统之上，做「智能编排 + 合规核查」层——自动检测多工区/多专业作业在同一作业单元、同一时段内的冲突。

## 项目结构

```
├── backend/     Spring Boot 后端（Maven 多模块：skylight-common + skylight-server）
├── frontend/    前端（单文件 index.html + nginx 配置）
└── .gitignore
```

- 后端构建 / 运行：见 [backend/README.md](backend/README.md)
- 前端部署：见 [frontend/README.md](frontend/README.md)

## 技术栈

- 后端：Java 25 · Spring Boot 4.0.6 · MySQL 8.0 · MyBatis · PageHelper
- 前端：原生 HTML/CSS/JS 单页 + Nginx 反代
- 核心算法：纯 Java（无框架依赖，可独立编译单测）

## 完整方案

完整需求、规则与开发方案见仓库外《铁路综合维修天窗多专业协同智能体-合并版方案.md》。
