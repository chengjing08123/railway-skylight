package com.skylight.agent;

import java.util.List;

/**
 * AI 核查说明接口的 DTO。
 *
 * <p>与 {@link AgentCheckDtos} 的区别：那边是「判成什么」（结构化冲突），
 * 这边是「怎么跟人解释」（一段话 + 引用的条文号）。两者刻意分开 ——
 * 判定结果是确定性的，解释文本是生成的，接口不混在一起才不会让人误以为
 * 判定也过了模型。
 */
public final class AgentExplainDtos {

    private AgentExplainDtos() {
    }

    /**
     * 请 AI 解释某次天窗核查。
     *
     * @param windowId 天窗 ID；为空时由 involved 里的序号反查
     * @param involved 涉及作业的序号，逗号串（前端直接传「18, 49」）
     * @param type     冲突类型；仅回显与日志用，判定与归因都不靠它
     */
    public record ExplainRequest(Long windowId, String involved, String type) {
    }

    /**
     * 一次 AI 解释的结果。
     *
     * @param status      ok / error
     * @param source      cloud（走 AgentArts）/ local（云端不可用，同镜像降级）
     * @param text        给调度员看的核查说明（**可能含模型生成内容**）
     * @param clauseRefs  这段说明引用的条文号，全部经过白名单校验
     * @param clauseSource 条文归因来源：model / mixed / rules
     * @param taskCount   参与核查的作业条数
     * @param elapsedMs   端到端耗时，演示时可以直接念
     * @param note        降级说明等提示，正常时为空
     */
    public record ExplainResponse(
            String status,
            String source,
            String text,
            List<String> clauseRefs,
            String clauseSource,
            Integer taskCount,
            long elapsedMs,
            String note) {

        public static ExplainResponse error(String msg, long elapsedMs) {
            return new ExplainResponse("error", "none", msg, List.of(), "rules",
                    0, elapsedMs, msg);
        }
    }
}
