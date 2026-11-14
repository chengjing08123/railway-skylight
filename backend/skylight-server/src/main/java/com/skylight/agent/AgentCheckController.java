package com.skylight.agent;

import com.skylight.agent.AgentExplainDtos.ExplainRequest;
import com.skylight.agent.AgentExplainDtos.ExplainResponse;
import com.skylight.agent.AgentCheckDtos.CheckRequest;
import com.skylight.agent.AgentCheckDtos.CheckResponse;
import java.util.Map;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Agent 核查接口。
 *
 * <p>三个端点，分别对应「判定」「解释」「活着」：
 * <ul>
 *   <li>{@code POST /api/agent/check} —— 按一次天窗的作业列表做确定性判定，
 *       不经过模型，出参带 {@code ruleRef} 与判定依据；</li>
 *   <li>{@code POST /api/agent/explain} —— 查库组装该天窗的作业，交给 AgentArts
 *       上的智能体写成核查说明（**这是产品里唯一调用大模型的地方**）；</li>
 *   <li>{@code GET /api/agent/ping} —— 联调时确认后端活着、路由通了。</li>
 * </ul>
 *
 * <p>与 {@code ConflictController} 的关系：那边 {@code GET /api/conflicts} 扫全库、
 * 供列表页展示；这边按天窗粒度给智能体用，入参由调用方组装。
 *
 * <p>放在 {@code com.skylight.agent} 包里，不碰现有的 controller / service / core。
 */
@RestController
@RequestMapping("/api/agent")
public class AgentCheckController {

    /**
     * 直接持有判定服务，不走 Spring 注入。
     *
     * <p>原因：{@link AgentCheckService} 刻意不加 {@code @Service}，
     * 保持纯 JDK 依赖，这样它能脱离 Spring 单独编译和单测
     * （{@code javac AgentCheckDtos.java AgentCheckService.java} 即可）。
     * 本类无状态，直接 new 一个实例不会有问题。
     */
    private final AgentCheckService service = new AgentCheckService();

    /** 解释服务要查库、要起子进程，走正常注入。 */
    private final AgentExplainService explainService;

    public AgentCheckController(AgentExplainService explainService) {
        this.explainService = explainService;
    }

    /**
     * 核查一个天窗内的作业冲突。
     *
     * @param req 天窗信息 + 作业列表
     * @return 冲突列表；作业列表为空时返回空数组而不是报错
     */
    @PostMapping(value = "/check", consumes = MediaType.APPLICATION_JSON_VALUE,
            produces = MediaType.APPLICATION_JSON_VALUE)
    public CheckResponse check(@RequestBody CheckRequest req) {
        return service.check(req);
    }

    /**
     * 请 AI 写一段核查说明。
     *
     * <p>入参只需要「哪次天窗」或「涉及哪几个序号」——作业清单由后端自己查库组装，
     * 前端不必知道表结构。这正是「数据库 → 后端 → 智能体」这条链路的入口。
     *
     * @param req windowId 与 involved 二选一
     * @return 说明文本 + 引用条文号；云端不可用时 {@code source=local} 并附 note
     */
    @PostMapping(value = "/explain", consumes = MediaType.APPLICATION_JSON_VALUE,
            produces = MediaType.APPLICATION_JSON_VALUE)
    public ExplainResponse explain(@RequestBody ExplainRequest req) {
        return explainService.explain(req);
    }

    /**
     * 健康检查。AgentArts 运行时有自己的 /ping，
     * 这个接口用来在联调时确认「后端活着、路由通了」。
     */
    @GetMapping(value = "/ping", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> ping() {
        return Map.of("status", "ok", "service", "agent-check");
    }
}
