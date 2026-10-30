package com.skylight.entity;

import java.time.Duration;
import java.time.LocalTime;

/**
 * 作业任务 —— 对应真实表「作业任务」实体（冲突检测主战场）。
 * 时间用 LocalTime（对应数据库 TIME 列），duration() 返回分钟数。
 */
public class WorkTask {
    public long id;
    public long skylightId;       // 所属天窗ID
    public int serialNo;          // 序号（对应真实表「序号」）
    public String workshop = "";  // 车间
    public String workArea = "";  // 工区（冲突检测的“主体”）
    public String profession = "工务"; // 专业：工务/电务/供电/…
    public String workUnitCode = "";   // 作业单元编码：列X区、局Ⅰ/Ⅱ
    public LocalTime startTime;   // 作业开始时刻
    public LocalTime endTime;     // 作业结束时刻
    public String workType = "点内";   // 点内/点外
    public String workCategory = "正常"; // 正常/临时
    public boolean needsPower;    // 是否带电作业（电务）
    public String powerScope = "";// 停电范围/供电臂

    public int duration() {
        return (int) Duration.between(startTime, endTime).toMinutes();
    }
}
