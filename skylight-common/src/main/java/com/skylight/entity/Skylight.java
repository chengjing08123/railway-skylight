package com.skylight.entity;

/**
 * 天窗 —— 一个维修/施工天窗时间窗口。
 * 时间用「当日分钟数」表示。
 */
public class Skylight {
    public long id;
    public String lineName = "";   // 线名
    public String direction = "";  // 行别
    public int startMin;           // 天窗开始（当日分钟）
    public int endMin;             // 天窗结束
    public String mainUnit = "";   // 主体单位

    public int duration() {
        return endMin - startMin;
    }
}
