package com.skylight.agent;

import com.skylight.entity.Skylight;
import com.skylight.entity.WorkTask;
import com.skylight.mapper.SkylightMapper;
import com.skylight.mapper.WorkTaskMapper;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Service;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.json.JsonMapper;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.time.LocalTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;

import static com.skylight.agent.AgentExplainDtos.ExplainRequest;
import static com.skylight.agent.AgentExplainDtos.ExplainResponse;

/**
 * AI 核查说明服务 —— 把「一次天窗的核查结果」交给 AgentArts 上的智能体写成说明。
 *
 * <p><b>这一步是整个产品里唯一会调用大模型的地方</b>，边界刻意划得很清楚：
 * <ol>
 *   <li>判定不经过模型 —— 冲突是 {@link AgentCheckService} 确定性判出来的，
 *       模型拿到的只是判定结果，改不动它；</li>
 *   <li>条文号必须可追溯 —— 模型给的条号要过白名单与类型两道校验，
 *       过不了就退回规则表；</li>
 *   <li>云端不可用不影响演示 —— 桥接脚本会降级到同一份本地逻辑，
 *       输出结构与云端一致，只是措辞退回模板。</li>
 * </ol>
 *
 * <p><b>为什么不直接打网关</b>：AgentArts 网关认证是 IAM（AK/SK 签名），
 * 由 CLI 承担签名比在本服务里实现一遍 V4 签名可靠。所以这里起子进程调
 * {@code explain_bridge.py}，它是唯一知道凭证与网关细节的地方。
 */
@Service
public class AgentExplainService {

    private static final DateTimeFormatter HHMM = DateTimeFormatter.ofPattern("HH:mm");

    /** 子进程上限：推理模型的单次调用可能到 30s，加冷启动重试留足余量。 */
    private static final long TIMEOUT_SECONDS = 240;

    private final WorkTaskMapper workTaskMapper;
    private final SkylightMapper skylightMapper;

    /**
     * Spring Boot 4 用的是 Jackson 3（包名从 {@code com.fasterxml.jackson} 换成
     * {@code tools.jackson}），而且 3.x 的读写异常改成了非受检异常。
     * 这里自己建一个实例，不注入 Spring 的 —— 只用来拼 payload，不需要项目的定制配置。
     */
    private final ObjectMapper json = JsonMapper.builder().build();
    private final Environment env;

    public AgentExplainService(WorkTaskMapper workTaskMapper,
                               SkylightMapper skylightMapper,
                               Environment env) {
        this.workTaskMapper = workTaskMapper;
        this.skylightMapper = skylightMapper;
        this.env = env;
    }

    /** 解释一次天窗核查。任何异常都收敛成 status=error，不往上抛。 */
    public ExplainResponse explain(ExplainRequest req) {
        long t0 = System.currentTimeMillis();

        String python = env.getProperty("skylight.agent.python",
                "C:\\Users\\21264\\AppData\\Local\\Programs\\Python\\Python314\\python.exe");
        String script = env.getProperty("skylight.agent.bridge",
                "C:\\Users\\21264\\ds harness work\\work\\contest-entry\\agentarts\\explain_bridge.py");

        Long windowId = req == null ? null : req.windowId();
        List<Integer> focusSerials = parseSerials(req == null ? null : req.involved());

        List<WorkTask> all = workTaskMapper.findAll();
        if (windowId == null) {
            windowId = resolveWindow(all, focusSerials);
        }
        if (windowId == null) {
            return ExplainResponse.error(focusSerials.isEmpty()
                    ? "这条冲突没有关联作业序号（如「配合缺失」来自配合单），"
                      + "无法定位到天窗；请直接传 windowId"
                    : "按序号 " + focusSerials + " 找不到对应作业，无法定位天窗",
                    elapsed(t0));
        }

        final long wid = windowId;
        List<WorkTask> tasks = all.stream()
                .filter(t -> t.skylightId == wid)
                .toList();
        Skylight window = skylightMapper.findAll().stream()
                .filter(s -> s.id == wid)
                .findFirst().orElse(null);
        if (window == null || tasks.isEmpty()) {
            return ExplainResponse.error("天窗 " + wid + " 没有作业或不存在", elapsed(t0));
        }

        Map<String, Object> payload = buildPayload(window, tasks, all, focusSerials);

        String stdout;
        try {
            stdout = runBridge(python, script, payload);
        } catch (Exception exc) {
            return ExplainResponse.error("调用智能体失败：" + exc.getClass().getSimpleName()
                    + " " + exc.getMessage(), elapsed(t0));
        }

        return parse(stdout, tasks.size(), elapsed(t0));
    }

    // ------------------------------------------------------------------ 组装

    /**
     * 组装给智能体的 payload。
     *
     * <p>刻意给「整个天窗的全部作业」而不是只给冲突的两条：模型要知道天窗几点到几点、
     * 总共几条作业，才能写出带上下文的说明。只给两条它会把话说得很空。
     */
    private Map<String, Object> buildPayload(Skylight window, List<WorkTask> tasks,
                                             List<WorkTask> all, List<Integer> focusSerials) {
        Map<String, Object> body = new LinkedHashMap<>();
        Map<String, Object> win = new LinkedHashMap<>();
        win.put("windowStart", fmt(window.startTime));
        win.put("windowEnd", fmt(window.endTime));
        body.put("window", win);

        List<Map<String, Object>> list = new ArrayList<>();
        List<String> focusIds = new ArrayList<>();
        for (WorkTask t : all) {
            if (t.skylightId != window.id) {
                continue;
            }
            Map<String, Object> one = new LinkedHashMap<>();
            String taskId = taskId(t);
            one.put("taskId", taskId);
            one.put("serialNo", t.serialNo);
            one.put("team", blankToEmpty(t.workArea));
            one.put("unitCodes", unitCodes(t));
            one.put("start", fmt(t.startTime));
            one.put("end", fmt(t.endTime));
            list.add(one);
            if (focusSerials.isEmpty() || focusSerials.contains(t.serialNo)) {
                focusIds.add(taskId);
            }
        }
        body.put("tasks", list);
        if (!focusIds.isEmpty()) {
            // 桥接脚本据此裁剪 payload，避免撞 Windows 命令行长度上限
            body.put("focusTaskIds", focusIds);
        }
        return body;
    }

    /** 作业单元 → 数组。库里是「列4区、列602区」这种顿号串，拆开才能逐条比对。 */
    private static List<String> unitCodes(WorkTask t) {
        LinkedHashSet<String> out = new LinkedHashSet<>();
        String raw = blankToEmpty(t.workUnitCode);
        for (String one : raw.split("[、,，;；/]")) {
            String s = one.trim();
            if (!s.isEmpty()) {
                out.add(s);
            }
        }
        return new ArrayList<>(out);
    }

    /**
     * 由 involved 的序号反查天窗。
     *
     * <p>前端点的是冲突卡片，它只知道自己牵扯哪几个序号。**刻意不做「猜一个天窗」
     * 的兜底** —— 早期的实现取全表第一条，结果「配合缺失」这类不挂作业的冲突
     * 会落到某个不相关的天窗上，答出「0 条需处理项」，比报错更容易误导人。
     */
    private static Long resolveWindow(List<WorkTask> all, List<Integer> serials) {
        for (Integer no : serials) {
            for (WorkTask t : all) {
                if (t.serialNo == no) {
                    return t.skylightId;
                }
            }
        }
        return null;
    }

    private static List<Integer> parseSerials(String involved) {
        List<Integer> out = new ArrayList<>();
        if (involved == null || involved.isBlank()) {
            return out;
        }
        for (String piece : involved.split("[^0-9]+")) {
            if (piece.isEmpty()) {
                continue;
            }
            try {
                out.add(Integer.parseInt(piece));
            } catch (NumberFormatException ignored) {
                // 序号以外的字（「序」「作业」等）直接跳过
            }
        }
        return out;
    }

    private static String taskId(WorkTask t) {
        return "T" + t.id;
    }

    // ------------------------------------------------------------------ 子进程

    /** 起 explain_bridge.py：payload 走 stdin，结果走 stdout（UTF-8 单行 JSON）。 */
    private String runBridge(String python, String script, Map<String, Object> payload)
            throws IOException, InterruptedException {
        String body = json.writeValueAsString(payload);

        ProcessBuilder pb = new ProcessBuilder(python, script);
        pb.redirectErrorStream(false);
        // 桥接脚本按 UTF-8 读写；不显式声明，Windows 上中文会变成问号
        pb.environment().put("PYTHONIOENCODING", "utf-8");
        pb.environment().put("PYTHONUTF8", "1");

        Process proc = pb.start();
        try (OutputStream in = proc.getOutputStream()) {
            in.write(body.getBytes(StandardCharsets.UTF_8));
        }

        String out;
        String err;
        try (InputStream os = proc.getInputStream();
             InputStream es = proc.getErrorStream()) {
            out = new String(os.readAllBytes(), StandardCharsets.UTF_8);
            err = new String(es.readAllBytes(), StandardCharsets.UTF_8);
        }

        if (!proc.waitFor(TIMEOUT_SECONDS, TimeUnit.SECONDS)) {
            proc.destroyForcibly();
            throw new IOException("智能体调用超时（" + TIMEOUT_SECONDS + "s）");
        }
        if (out.isBlank()) {
            throw new IOException("桥接脚本无输出"
                    + (err.isBlank() ? "" : "：" + tail(err, 300)));
        }
        return out;
    }

    private ExplainResponse parse(String stdout, int taskCount, long elapsed) {
        Map<?, ?> obj;
        try {
            obj = json.readValue(stdout.trim(), Map.class);
        } catch (Exception exc) {
            return ExplainResponse.error("智能体返回的不是 JSON：" + tail(stdout, 200), elapsed);
        }
        String status = str(obj.get("status"), "error");
        if (!"ok".equals(status)) {
            return ExplainResponse.error(str(obj.get("error"), "智能体返回失败"), elapsed);
        }
        List<String> refs = new ArrayList<>();
        if (obj.get("clauseRefs") instanceof List<?> raw) {
            for (Object o : raw) {
                if (o != null) {
                    refs.add(String.valueOf(o));
                }
            }
        }
        return new ExplainResponse(
                "ok",
                str(obj.get("source"), "cloud"),
                str(obj.get("text"), ""),
                refs,
                str(obj.get("clauseSource"), "rules"),
                taskCount,
                elapsed,
                str(obj.get("note"), ""));
    }

    // ------------------------------------------------------------------ 工具

    private static long elapsed(long t0) {
        return System.currentTimeMillis() - t0;
    }

    private static String fmt(LocalTime t) {
        return t == null ? "" : t.format(HHMM);
    }

    private static String blankToEmpty(String s) {
        return s == null ? "" : s;
    }

    private static String str(Object o, String dft) {
        if (o == null) {
            return dft;
        }
        String s = String.valueOf(o);
        return s.isBlank() ? dft : s;
    }

    private static String tail(String s, int n) {
        String t = s == null ? "" : s.trim();
        return t.length() <= n ? t : t.substring(t.length() - n);
    }
}
