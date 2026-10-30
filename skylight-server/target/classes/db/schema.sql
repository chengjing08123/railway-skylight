-- ============================================================
-- 铁路维修天窗多专业协同智能体 — 数据库建表脚本（T1）
-- 数据库：MySQL 8.0   字符集：utf8mb4
-- 说明：T1 核心 6 表，字段名对齐真实「工务段作业计划表」
-- ============================================================

CREATE DATABASE IF NOT EXISTS railway_skylight
  DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
USE railway_skylight;

-- 1. 天窗表：一个维修/施工天窗时间窗口
CREATE TABLE IF NOT EXISTS skylight (
    id               BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '天窗ID',
    plan_date        DATE         COMMENT '作业日期',
    line_name        VARCHAR(32)  COMMENT '天窗线名（沪昆等）',
    direction        VARCHAR(16)  COMMENT '天窗行别（上/下/站内/单）',
    register_station VARCHAR(32)  COMMENT '登记站',
    level            VARCHAR(8)   COMMENT '天窗等级（Ⅰ/Ⅱ/Ⅲ）',
    start_time       TIME         COMMENT '天窗开始时刻',
    end_time         TIME         COMMENT '天窗结束时刻',
    main_unit        VARCHAR(64)  COMMENT '天窗主体单位',
    leader           VARCHAR(32)  COMMENT '天窗负责人',
    project          VARCHAR(255) COMMENT '天窗项目',
    location         VARCHAR(255) COMMENT '天窗地点',
    KEY idx_date (plan_date),
    KEY idx_line (line_name, direction)
) COMMENT='天窗（维修/施工时间窗口）';

-- 2. 作业任务表：某工区/专业在天窗内的一项作业（冲突检测主战场）
CREATE TABLE IF NOT EXISTS work_task (
    id              BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '作业任务ID',
    skylight_id     BIGINT       COMMENT '所属天窗ID',
    serial_no       INT          COMMENT '序号',
    workshop        VARCHAR(64)  COMMENT '车间',
    work_area       VARCHAR(64)  COMMENT '工区（冲突检测主体）',
    profession      VARCHAR(16)  COMMENT '专业（工务/电务/供电/…）',
    work_unit_code  VARCHAR(32)  COMMENT '作业单元编码（列X区/局ⅠⅡ）',
    start_time      TIME         COMMENT '作业开始时刻',
    end_time        TIME         COMMENT '作业结束时刻',
    work_type       VARCHAR(16)  COMMENT '作业类型（点内/点外）',
    work_category   VARCHAR(16)  COMMENT '作业类别（正常/临时）',
    needs_power     TINYINT(1)   DEFAULT 0 COMMENT '是否带电作业（电务）',
    power_scope     VARCHAR(64)  COMMENT '停电范围/供电臂',
    KEY idx_skylight (skylight_id),
    KEY idx_unit (work_unit_code),
    KEY idx_area (work_area)
) COMMENT='作业任务';

-- 3. 作业单元表：作业单元字典（列X区、局Ⅰ/Ⅱ 等）
CREATE TABLE IF NOT EXISTS work_unit (
    id          BIGINT PRIMARY KEY AUTO_INCREMENT,
    code        VARCHAR(32) COMMENT '单元编码',
    line_name   VARCHAR(32),
    direction   VARCHAR(16),
    station     VARCHAR(32),
    mileage     VARCHAR(64),
    KEY idx_code (code)
) COMMENT='作业单元字典';

-- 4. 配合表：作业需要的配合单位（配合缺失冲突的数据来源）
CREATE TABLE IF NOT EXISTS coordination (
    id          BIGINT PRIMARY KEY AUTO_INCREMENT,
    task_id     BIGINT COMMENT '所属作业任务ID',
    unit_name   VARCHAR(64) COMMENT '配合单位名称',
    unit_type   VARCHAR(16) COMMENT '单位类型（工务/电务/供电/…）',
    confirmed   TINYINT(1) DEFAULT 0 COMMENT '是否确认到场（0未/1已）',
    KEY idx_task (task_id)
) COMMENT='配合关系';

-- 5. 依赖表：作业之间的先后依赖（依赖冲突的数据来源）
CREATE TABLE IF NOT EXISTS task_dependency (
    id            BIGINT PRIMARY KEY AUTO_INCREMENT,
    task_id       BIGINT COMMENT '作业任务ID',
    depends_on_id BIGINT COMMENT '依赖的前置任务ID',
    KEY idx_task (task_id)
) COMMENT='作业依赖关系';

-- 6. 人员防护表：作业的负责人/防护配置（卡控核查的数据来源）
CREATE TABLE IF NOT EXISTS personnel (
    id               BIGINT PRIMARY KEY AUTO_INCREMENT,
    task_id          BIGINT COMMENT '所属作业任务ID',
    leader           VARCHAR(32) COMMENT '负责人',
    shift_leader     VARCHAR(32) COMMENT '带班人',
    station_liaison  VARCHAR(32) COMMENT '驻站联络员',
    site_protector   VARCHAR(32) COMMENT '现场防护员',
    remote_protector VARCHAR(32) COMMENT '远方防护员',
    register_station VARCHAR(32) COMMENT '登记站',
    worker_count     INT COMMENT '职工数',
    KEY idx_task (task_id)
) COMMENT='人员与防护';
