package com.skylight.core;

/**
 * 冲突 —— 冲突检测引擎的产出结果（一条冲突记录）。
 */
public class Conflict {
    public String type;        // 冲突类型（六类之一）
    public String description; // 冲突描述
    public String suggestion;  // 处理建议
    public String involved;    // 涉及的任务（序号）

    public Conflict(String type, String description, String suggestion, String involved) {
        this.type = type;
        this.description = description;
        this.suggestion = suggestion;
        this.involved = involved;
    }

    @Override
    public String toString() {
        return "【" + type + "】" + description
                + "\n    建议：" + suggestion
                + "\n    涉及：序" + involved;
    }
}
