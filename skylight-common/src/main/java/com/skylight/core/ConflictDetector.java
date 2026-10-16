package com.skylight.core;

import com.skylight.entity.Coordination;
import com.skylight.entity.Skylight;
import com.skylight.entity.TaskDependency;
import com.skylight.entity.WorkTask;

import java.util.*;

/**
 * 冲突检测引擎 —— 六类冲突，全部确定性算法（T1 核心，纯 Java 无框架依赖）。
 * 说明：时间统一用「当日分钟数」int 表示，区间/求和都是基础数据结构。
 */
public class ConflictDetector {

    /**
     * ① 作业单元冲突：同一作业单元被两个及以上工区/专业同时占用。
     */
    public static List<Conflict> detectUnitContention(List<WorkTask> tasks) {
        Map<String, Set<String>> unitAreas = new LinkedHashMap<>();
        Map<String, List<WorkTask>> unitTasks = new LinkedHashMap<>();
        for (WorkTask t : tasks) {
            if (t.workUnitCode == null || t.workUnitCode.isEmpty()) continue;
            String key = t.skylightId + "#" + t.workUnitCode;
            unitAreas.computeIfAbsent(key, k -> new LinkedHashSet<>()).add(t.workArea);
            unitTasks.computeIfAbsent(key, k -> new ArrayList<>()).add(t);
        }
        List<Conflict> out = new ArrayList<>();
        for (Map.Entry<String, Set<String>> e : unitAreas.entrySet()) {
            if (e.getValue().size() >= 2) {
                String unit = e.getKey().split("#", 2)[1];
                out.add(new Conflict(
                        "作业单元冲突",
                        "作业单元【" + unit + "】被 " + e.getValue().size()
                                + " 个工区同时占用：" + e.getValue(),
                        "按专业主次排序，或协商更换作业单元",
                        serials(unitTasks.get(e.getKey()))));
            }
        }
        return out;
    }

    /**
     * ② 时长冲突：同一作业单元内各作业时长之和超过天窗时长。
     */
    public static List<Conflict> detectDurationConflict(List<WorkTask> tasks, Map<Long, Skylight> skylights) {
        Map<String, List<WorkTask>> byUnit = new LinkedHashMap<>();
        for (WorkTask t : tasks) {
            if (t.workUnitCode == null || t.workUnitCode.isEmpty()) continue;
            byUnit.computeIfAbsent(t.skylightId + "#" + t.workUnitCode, k -> new ArrayList<>()).add(t);
        }
        List<Conflict> out = new ArrayList<>();
        for (Map.Entry<String, List<WorkTask>> e : byUnit.entrySet()) {
            long skyId = Long.parseLong(e.getKey().split("#")[0]);
            String unit = e.getKey().split("#", 2)[1];
            Skylight sky = skylights.get(skyId);
            if (sky == null) continue;
            int sum = 0;
            for (WorkTask t : e.getValue()) sum += t.duration();
            if (sum > sky.duration()) {
                out.add(new Conflict(
                        "时长冲突",
                        "作业单元【" + unit + "】作业时长之和 " + sum + " 分钟，超过天窗时长 "
                                + sky.duration() + " 分钟",
                        "压缩作业量，或将部分作业移出该天窗",
                        serials(e.getValue())));
            }
        }
        return out;
    }

    /**
     * ③ 电气冲突：同一作业单元内，供电停电范围与电务带电需求矛盾。
     * 逻辑已就绪，待补齐电务/供电数据后生效。
     */
    public static List<Conflict> detectElectricalConflict(List<WorkTask> tasks) {
        Map<String, List<WorkTask>> byUnit = new LinkedHashMap<>();
        for (WorkTask t : tasks) {
            if (t.workUnitCode == null || t.workUnitCode.isEmpty()) continue;
            byUnit.computeIfAbsent(t.skylightId + "#" + t.workUnitCode, k -> new ArrayList<>()).add(t);
        }
        List<Conflict> out = new ArrayList<>();
        for (Map.Entry<String, List<WorkTask>> e : byUnit.entrySet()) {
            List<WorkTask> list = e.getValue();
            boolean hasOutage = list.stream().anyMatch(t -> t.powerScope != null && !t.powerScope.isEmpty());
            boolean hasLive = list.stream().anyMatch(t -> t.needsPower);
            if (hasOutage && hasLive) {
                out.add(new Conflict(
                        "电气冲突",
                        "作业单元【" + e.getKey().split("#", 2)[1] + "】同时存在停电范围与带电作业需求",
                        "调整作业顺序，或改用带电作业替代方案",
                        serials(list)));
            }
        }
        return out;
    }

    /**
     * ④ 依赖冲突：作业依赖关系成环（Kahn 拓扑排序检测）。
     */
    public static List<Conflict> detectDependencyConflict(List<WorkTask> tasks, List<TaskDependency> deps) {
        Set<Long> ids = new HashSet<>();
        for (WorkTask t : tasks) ids.add(t.id);
        Map<Long, List<Long>> graph = new HashMap<>();   // 前置 -> 依赖它的任务
        Map<Long, Integer> indeg = new HashMap<>();
        for (TaskDependency d : deps) {
            graph.computeIfAbsent(d.dependsOnId, k -> new ArrayList<>()).add(d.taskId);
            indeg.merge(d.taskId, 1, Integer::sum);
            indeg.putIfAbsent(d.dependsOnId, 0);
        }
        Queue<Long> q = new ArrayDeque<>();
        for (long id : ids) if (indeg.getOrDefault(id, 0) == 0) q.add(id);
        int visited = 0;
        while (!q.isEmpty()) {
            long u = q.poll();
            visited++;
            for (long v : graph.getOrDefault(u, Collections.emptyList())) {
                if (indeg.merge(v, -1, Integer::sum) == 0) q.add(v);
            }
        }
        List<Conflict> out = new ArrayList<>();
        if (visited < ids.size()) {
            out.add(new Conflict(
                    "依赖冲突",
                    "作业依赖关系存在环（无法拓扑排序），" + (ids.size() - visited) + " 项作业陷入循环依赖",
                    "检查并断开循环依赖，明确先后顺序",
                    "见 task_dependency 表"));
        }
        return out;
    }

    /**
     * ⑤ 配合缺失：有配合单位但未确认到场。
     */
    public static List<Conflict> detectCoordinationMissing(List<Coordination> coords) {
        List<Conflict> out = new ArrayList<>();
        for (Coordination c : coords) {
            if (c.unitName != null && !c.unitName.isEmpty() && !c.confirmed) {
                out.add(new Conflict(
                        "配合缺失",
                        "作业需「" + c.unitName + "」配合，但未确认到场",
                        "自动补齐配合通知清单，列入待确认项",
                        "任务#" + c.taskId));
            }
        }
        return out;
    }

    /**
     * ⑥ 主次违反：作业主体与「设备归属专业决定主体」规则不符。
     * 规则已核实：线路专业(车间)为默认主体，设备属哪专业管就谁为主体。
     * 待接入「设备归属→专业」规则表后完全生效。
     */
    public static List<Conflict> detectSubjectViolation(List<WorkTask> tasks) {
        // TODO: 接入「设备归属→专业」规则表后实现
        return new ArrayList<>();
    }

    private static String serials(List<WorkTask> tasks) {
        List<Integer> ss = new ArrayList<>();
        for (WorkTask t : tasks) ss.add(t.serialNo);
        Collections.sort(ss);
        return ss.toString().replace("[", "").replace("]", "");
    }
}
