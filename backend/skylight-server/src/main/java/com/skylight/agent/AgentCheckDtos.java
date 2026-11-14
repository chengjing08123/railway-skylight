package com.skylight.agent;

import java.util.List;

/**
 * Agent 核查接口的 DTO。
 *
 * 设计原则：只描述「一次核查的输入」与「核查结果」，不依赖数据库实体，
 * 这样 AgentArts 侧传来的 JSON 可以直接反序列化，不需要先落库。
 */
public final class AgentCheckDtos {

    private AgentCheckDtos() {
    }

    // ------------------------------------------------------------------ 请求

    /**
     * 一次天窗核查请求。
     *
     * @param windowId    天窗 ID（可空，仅回显用）
     * @param windowStart 天窗开始时刻，HH:mm
     * @param windowEnd   天窗结束时刻，HH:mm
     * @param tasks       该天窗内的作业列表
     */
    public record CheckRequest(
            Long windowId,
            String line,
            String direction,
            String windowStart,
            String windowEnd,
            List<Task> tasks,
            Boolean detectDuration) {

        /** 时长冲突默认不开，原因见 AgentCheckService 的说明。 */
        public boolean durationOn() {
            return Boolean.TRUE.equals(detectDuration);
        }
    }

    /**
     * 一条作业。
     *
     * @param taskId    业务主键，如 PSXC-20260923-018；可空，空则用 serialNo 代替
     * @param serialNo  序号，人机对照用
     * @param team      工区；跨工区才判单元冲突，这是判据的前提
     * @param unitCodes 作业单元，**必须是数组**；一条作业可对应多个单元（如 列4区、列602区）
     * @param start     作业开始时刻 HH:mm
     * @param end       作业结束时刻 HH:mm
     * @param mileFrom  里程起点（米），可空
     * @param mileTo    里程终点（米），可空
     * @param switches  道岔编号，可空
     */
    public record Task(
            String taskId,
            Integer serialNo,
            String team,
            List<String> unitCodes,
            String start,
            String end,
            Long mileFrom,
            Long mileTo,
            List<String> switches) {
    }

    // ------------------------------------------------------------------ 响应

    public record CheckResponse(
            Long windowId,
            int taskCount,
            int conflictCount,
            List<ConflictItem> conflicts) {
    }

    /**
     * 一条冲突。字段对齐契约 2.1 节，前端可直接渲染。
     *
     * @param id        稳定主键，type + 涉及的 taskId 拼成
     * @param type      作业单元冲突 / 时长冲突 / 配合缺失
     * @param involved  涉及的 taskId 数组（**数组，不是逗号串**）
     * @param serialNos 涉及的序号，演示时念出来用
     * @param ruleRef   条文号，如「2.2.10 第 1 款」；可追溯率认这个字段
     * @param severity  严重 / 一般
     * @param basis     判定依据的事实（给大模型写解释用，不要直接展示给用户）
     */
    public record ConflictItem(
            String id,
            String type,
            List<String> involved,
            List<Integer> serialNos,
            String ruleRef,
            String severity,
            String description,
            String suggestion,
            String basis) {
    }
}
