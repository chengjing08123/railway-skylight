package com.skylight.agent;

import java.text.Normalizer;
import java.time.LocalTime;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import static com.skylight.agent.AgentCheckDtos.CheckRequest;
import static com.skylight.agent.AgentCheckDtos.CheckResponse;
import static com.skylight.agent.AgentCheckDtos.ConflictItem;
import static com.skylight.agent.AgentCheckDtos.Task;

/**
 * Agent 核查服务 —— 把「一次天窗的作业列表」判成「冲突列表」。
 *
 * <p>与 {@code ConflictDetector} 的关系：判据同源，但这里是**独立实现**，
 * 原因是现有检测器把 {@code workUnitCode} 当单值、且按单元聚合成一条，
 * 无法表达「一条作业属于多个单元」与「冲突按两两成对输出」。
 * 等后端 D2 改完，本类可以退化成对 {@code ConflictDetector} 的委托。
 *
 * <p>判据（与 9/23 窗口的 gold 校准过，10 对全中）：
 * <ol>
 *   <li>只在 <b>不同工区</b> 之间判单元冲突 —— 同工区自有作业可自行避让；</li>
 *   <li>两两成对输出，一条冲突只涉及两条作业，可直接对应到分界点协商；</li>
 *   <li>时段必须重叠；</li>
 *   <li>单元级一致 → 严重；仅区域级一致但有里程或道岔佐证 → 严重；否则 → 一般（提示级）。</li>
 * </ol>
 */
public class AgentCheckService {

    /** 登记请点、防护、开通吃掉的固定开销（分钟）。 */
    private static final int FIXED_OVERHEAD_MIN = 15;

    /** 单元级：列 + 三位数字 + 区，如 列602区（与股道号一一对应）。 */
    private static final Pattern UNIT_LEVEL = Pattern.compile("^列(\\d{3})区$");

    /** 站名前缀，比对前必须去掉，否则同一单元会被当成两个。 */
    private static final Pattern STATION_PREFIX =
            Pattern.compile("^(萍乡新场|萍乡|新场)");

    // ------------------------------------------------------------------ 入口

    public CheckResponse check(CheckRequest req) {
        List<Task> tasks = req.tasks() == null ? List.of() : req.tasks();
        if (tasks.isEmpty()) {
            return new CheckResponse(req.windowId(), 0, 0, List.of());
        }

        // 预解析：时刻、规范化单元。非法行直接跳过，不让整批失败。
        List<Parsed> parsed = new ArrayList<>();
        for (Task t : tasks) {
            LocalTime s = parseTime(t.start());
            LocalTime e = parseTime(t.end());
            if (s == null || e == null || !s.isBefore(e)) {
                continue;
            }
            parsed.add(new Parsed(t, s, e, normalizeUnits(t.unitCodes())));
        }

        List<ConflictItem> out = new ArrayList<>();
        out.addAll(detectUnitPairs(parsed));
        // 时长冲突默认不开：本批 55 条数据里「作业时段 = 天窗时段」是填表习惯，
        // 并集恒等于天窗全长，判据失去区分力（见 qna Q2 / gold 标注记录 §3）。
        // 真实现场填了真实作业时段后再打开 detectDuration。
        if (req.durationOn()) {
            out.addAll(detectDuration(parsed, req.windowStart(), req.windowEnd()));
        }

        return new CheckResponse(req.windowId(), tasks.size(), out.size(), out);
    }

    // ------------------------------------------------------------------ ① 单元冲突（两两成对）

    private List<ConflictItem> detectUnitPairs(List<Parsed> parsed) {
        List<ConflictItem> out = new ArrayList<>();

        for (int i = 0; i < parsed.size(); i++) {
            for (int j = i + 1; j < parsed.size(); j++) {
                Parsed a = parsed.get(i);
                Parsed b = parsed.get(j);

                // 条件一：跨工区
                if (sameTeam(a, b)) {
                    continue;
                }
                // 条件二：时段重叠（半开区间，端点相接不算重叠）
                if (!a.start().isBefore(b.end()) || !b.start().isBefore(a.end())) {
                    continue;
                }
                // 条件三：至少共享一个单元
                List<String> shared = new ArrayList<>(a.units());
                shared.retainAll(b.units());
                if (shared.isEmpty()) {
                    continue;
                }

                boolean unitLevel = shared.stream().anyMatch(AgentCheckService::isUnitLevel);
                long mileOverlap = mileOverlap(a, b);
                List<String> switchOverlap = switchOverlap(a, b);
                boolean severe = unitLevel || mileOverlap > 0 || switchOverlap.size() >= 2;

                String unitText = String.join("、", shared);
                String description = "作业单元【" + unitText + "】被「" + safe(a.task().team())
                        + "」与「" + safe(b.task().team()) + "」在 " + hhmm(a.start()) + "—"
                        + hhmm(a.end()) + " 同时占用";

                String basis = "共享单元=" + unitText
                        + "；级别=" + (unitLevel ? "单元级" : "区域级")
                        + "；里程重叠=" + mileOverlap + "m"
                        + "；道岔重叠=" + switchOverlap.size() + "组"
                        + (switchOverlap.isEmpty() ? "" : "(" + String.join(",", switchOverlap) + ")");

                out.add(build(a, b, "作业单元冲突", "2.2.10 第 1 款",
                        severe ? "严重" : "一般",
                        description,
                        severe
                                ? "按 2.2.10 第 1 款由车务段指定主体单位并划分分界点；或将其中一条作业移出该单元"
                                : "作业区域重叠，需确认分界点与防护措施",
                        basis));
            }
        }
        return out;
    }

    // ------------------------------------------------------------------ ② 时长冲突（并集，不是累加）

    private List<ConflictItem> detectDuration(List<Parsed> parsed, String ws, String we) {
        LocalTime wStart = parseTime(ws);
        LocalTime wEnd = parseTime(we);
        if (wStart == null || wEnd == null || !wStart.isBefore(wEnd)) {
            return List.of();
        }
        int windowMin = minutes(wEnd) - minutes(wStart);
        int usable = windowMin - FIXED_OVERHEAD_MIN;

        // 按单元归组（一条作业进它所有的单元）
        Map<String, List<Parsed>> byUnit = new TreeMap<>();
        for (Parsed p : parsed) {
            for (String unit : p.units()) {
                byUnit.computeIfAbsent(unit, k -> new ArrayList<>()).add(p);
            }
        }

        List<ConflictItem> out = new ArrayList<>();
        for (Map.Entry<String, List<Parsed>> e : byUnit.entrySet()) {
            List<Parsed> list = e.getValue();
            // 单条作业占满整个天窗是填表习惯，不是超窗 —— 至少两条才判
            if (list.size() < 2) {
                continue;
            }
            int used = unionMinutes(list);
            if (used <= usable) {
                continue;
            }
            List<String> ids = new ArrayList<>();
            List<Integer> serials = new ArrayList<>();
            for (Parsed p : list) {
                ids.add(idOf(p.task()));
                if (p.task().serialNo() != null) {
                    serials.add(p.task().serialNo());
                }
            }
            out.add(new ConflictItem(
                    "时长冲突|" + e.getKey(),
                    "时长冲突",
                    ids,
                    serials,
                    "2.2.1",
                    "一般",
                    "作业单元【" + e.getKey() + "】占用 " + used + " 分钟，有效可用仅 " + usable
                            + " 分钟（天窗 " + windowMin + " 分钟，已扣 " + FIXED_OVERHEAD_MIN
                            + " 分钟固定开销）",
                    "压缩作业量，或将部分作业移出该天窗",
                    "并集占用=" + used + "min；可用=" + usable + "min；单元作业数=" + list.size()));
        }
        return out;
    }

    /** 区间并集长度（分钟）。 */
    private int unionMinutes(List<Parsed> list) {
        List<int[]> iv = new ArrayList<>();
        for (Parsed p : list) {
            iv.add(new int[]{minutes(p.start()), minutes(p.end())});
        }
        iv.sort(Comparator.comparingInt(x -> x[0]));
        int total = 0;
        int s = iv.get(0)[0];
        int e = iv.get(0)[1];
        for (int[] x : iv.subList(1, iv.size())) {
            if (x[0] <= e) {
                e = Math.max(e, x[1]);
            } else {
                total += e - s;
                s = x[0];
                e = x[1];
            }
        }
        return total + e - s;
    }

    // ------------------------------------------------------------------ 工具

    private ConflictItem build(Parsed a, Parsed b, String type, String ruleRef,
                               String severity, String description, String suggestion,
                               String basis) {
        List<String> ids = List.of(idOf(a.task()), idOf(b.task()));
        List<Integer> serials = new ArrayList<>();
        if (a.task().serialNo() != null) {
            serials.add(a.task().serialNo());
        }
        if (b.task().serialNo() != null) {
            serials.add(b.task().serialNo());
        }
        serials.sort(Comparator.naturalOrder());
        return new ConflictItem(type + "|" + String.join("|", ids), type, ids, serials,
                ruleRef, severity, description, suggestion, basis);
    }

    private static boolean sameTeam(Parsed a, Parsed b) {
        return safe(a.task().team()).equals(safe(b.task().team()));
    }

    private static long mileOverlap(Parsed a, Parsed b) {
        Long a1 = a.task().mileFrom();
        Long a2 = a.task().mileTo();
        Long b1 = b.task().mileFrom();
        Long b2 = b.task().mileTo();
        if (a1 == null || a2 == null || b1 == null || b2 == null) {
            return 0;
        }
        return Math.max(0, Math.min(a2, b2) - Math.max(a1, b1));
    }

    private static List<String> switchOverlap(Parsed a, Parsed b) {
        if (a.task().switches() == null || b.task().switches() == null) {
            return List.of();
        }
        List<String> x = new ArrayList<>(a.task().switches());
        x.retainAll(b.task().switches());
        x.sort(Comparator.naturalOrder());
        return x;
    }

    /**
     * 单元归一：NFKC（全角转半角）→ 去空白 → 去站名前缀。
     * <p>第 3 步是必须的：序 23 写「列4区」，序 49 写「萍乡新场列4区」，
     * 不去前缀会被当成两个单元，直接漏掉 6 对冲突。
     */
    static List<String> normalizeUnits(List<String> raw) {
        if (raw == null) {
            return List.of();
        }
        LinkedHashSet<String> out = new LinkedHashSet<>();
        for (String one : raw) {
            if (one == null) {
                continue;
            }
            String s = Normalizer.normalize(one, Normalizer.Form.NFKC);
            s = s.replaceAll("\\s+", "");
            s = STATION_PREFIX.matcher(s).replaceFirst("");
            // 原文是「萍乡新场-列602区」这种写法，去前缀后会残留分隔符
            s = s.replaceFirst("^[-—_·、,，]+", "");
            if (!s.isEmpty()) {
                out.add(s);
            }
        }
        return new ArrayList<>(out);
    }

    static boolean isUnitLevel(String unit) {
        Matcher m = UNIT_LEVEL.matcher(unit);
        return m.matches();
    }

    private static String idOf(Task t) {
        if (t.taskId() != null && !t.taskId().isBlank()) {
            return t.taskId();
        }
        return t.serialNo() == null ? "unknown" : String.valueOf(t.serialNo());
    }

    private static int minutes(LocalTime t) {
        return t.getHour() * 60 + t.getMinute();
    }

    private static String hhmm(LocalTime t) {
        return String.format("%02d:%02d", t.getHour(), t.getMinute());
    }

    private static String safe(String s) {
        return s == null ? "" : s;
    }

    static LocalTime parseTime(String s) {
        if (s == null || s.isBlank()) {
            return null;
        }
        try {
            return LocalTime.parse(s.length() == 5 ? s : s.substring(0, 5));
        } catch (Exception ex) {
            return null;
        }
    }

    /** 预解析后的一条作业。 */
    private record Parsed(Task task, LocalTime start, LocalTime end, List<String> units) {
    }
}
