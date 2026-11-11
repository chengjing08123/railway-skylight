package com.skylight.core;

/**
 * 冲突 —— 冲突检测引擎的产出结果（一条冲突记录）。
 * 字段与前端冻结契约一致：type/description/suggestion/involved/severity/ruleRef。
 */
public class Conflict {
    public String type;        // 冲突类型（六类之一）
    public String description; // 冲突描述
    public String suggestion;  // 处理建议
    public String involved;    // 涉及的任务（序号）
    public String severity;    // 严重度：high / mid / low
    public String ruleRef;     // 条文索引，如 "2.2.10"

    public Conflict(String type, String description, String suggestion, String involved,
                    String severity, String ruleRef) {
        this.type = type;
        this.description = description;
        this.suggestion = suggestion;
        this.involved = involved;
        this.severity = severity;
        this.ruleRef = ruleRef;
    }

    @Override
    public String toString() {
        return "【" + type + "】" + description
                + "\n    建议：" + suggestion
                + "\n    涉及：序" + involved
                + "\n    级别：" + severity + " · 条文：" + ruleRef;
    }
}
