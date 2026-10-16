package com.skylight.entity;

/**
 * 作业任务 —— 对应真实表「作业任务」实体（冲突检测主战场）。
 * 时间统一用「当日分钟数」(0-1440) 表示，方便做区间重叠计算。
 */
public class WorkTask {
    public long id;
    public long skylightId;       // 所属天窗ID
    public int serialNo;          // 序号（对应真实表「序号」）
    public String workshop = "";  // 车间
    public String workArea = "";  // 工区（冲突检测的“主体”）
    public String profession = "工务"; // 专业：工务/电务/供电/…
    public String workUnitCode = "";   // 作业单元编码：列X区、局Ⅰ/Ⅱ
    public int startMin;          // 作业开始（当日分钟）
    public int endMin;            // 作业结束（当日分钟）
    public String workType = "点内";   // 点内/点外
    public String workCategory = "正常"; // 正常/临时
    public boolean needsPower;    // 是否带电作业（电务）
    public String powerScope = "";// 停电范围/供电臂

    public int duration() {
        return endMin - startMin;
    }
}
