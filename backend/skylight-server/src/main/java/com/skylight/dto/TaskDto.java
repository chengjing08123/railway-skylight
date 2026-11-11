package com.skylight.dto;

/**
 * 作业任务接口响应体（对应前端甘特 normalizeTask 的字段）。
 */
public record TaskDto(
        long id,
        long windowId,
        int serial,
        String team,
        String unit,
        String item,
        String start,
        String end
) {}
