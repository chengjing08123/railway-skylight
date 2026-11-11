package com.skylight.entity;

/**
 * 配合关系 —— 作业需要的配合单位（配合缺失冲突的数据来源）。
 */
public class Coordination {
    public long id;
    public long taskId;            // 所属作业任务ID
    public String unitName = "";   // 配合单位名称
    public String unitType = "";   // 单位类型：工务/电务/供电/…
    public boolean confirmed;      // 是否确认到场
}
