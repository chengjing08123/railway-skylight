package com.skylight.entity;

/**
 * 作业依赖 —— 作业之间的先后依赖（依赖冲突的数据来源）。
 */
public class TaskDependency {
    public long id;
    public long taskId;        // 作业任务ID
    public long dependsOnId;   // 依赖的前置任务ID
}
