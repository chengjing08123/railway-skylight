package com.skylight.dto;

/**
 * 天窗接口响应体（对应前端甘特 normalizeWindow 的字段）。
 */
public record WindowDto(
        long id,
        String date,
        String line,
        String direction,
        String station,
        String start,
        String end,
        int overheadMinutes
) {}
