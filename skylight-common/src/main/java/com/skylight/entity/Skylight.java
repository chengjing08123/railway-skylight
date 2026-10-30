package com.skylight.entity;

import java.time.Duration;
import java.time.LocalTime;

/**
 * 天窗 —— 一个维修/施工天窗时间窗口。
 * 时间用 LocalTime（对应数据库 TIME 列），duration() 返回分钟数。
 */
public class Skylight {
    public long id;
    public String lineName = "";   // 线名
    public String direction = "";  // 行别
    public LocalTime startTime;    // 天窗开始时刻
    public LocalTime endTime;      // 天窗结束时刻
    public String mainUnit = "";   // 主体单位

    public int duration() {
        return (int) Duration.between(startTime, endTime).toMinutes();
    }
}
