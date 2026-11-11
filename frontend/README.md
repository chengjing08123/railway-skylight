# 前端

单文件前端（`index.html`，内含 CSS/JS），三个页面（hash 路由）：冲突清单 `#list`、时长甘特 `#gantt`、人工确认 `#confirm`。

## 文件

- `index.html` —— 前端源码（单文件）
- `nginx.skylight.conf` —— nginx 站点配置

## 部署（配合便携版 nginx）

1. 把 `index.html` 放到 nginx 的 `html/skylight/` 目录；
2. 把 `nginx.skylight.conf` 放到 nginx 的 `conf/` 目录；
3. 启动：`nginx.exe -c conf/nginx.skylight.conf`；
4. 访问 `http://localhost:8088/`。

> nginx 配置监听 8088，`/api/` 反代到后端 `127.0.0.1:8080`；后端不可达时，前端自动回退到内置演示数据（右上角数据源圆点变橙色）。

## 数据接口（来自后端 8080）

| 接口 | 用途 |
|---|---|
| `/api/conflicts` | 冲突列表（默认页面）|
| `/api/tasks` | 作业任务（甘特）|
| `/api/windows` | 天窗（甘特）|
