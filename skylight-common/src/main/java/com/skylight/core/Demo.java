package com.skylight.core;

import com.skylight.entity.Coordination;
import com.skylight.entity.Skylight;
import com.skylight.entity.TaskDependency;
import com.skylight.entity.WorkTask;

import java.time.LocalTime;
import java.util.*;

/**
 * 演示入口：用「工务段 2026-09-23 计划」的真实冲突样例 + 少量构造样例，
 * 跑一遍六类冲突检测，验证核心算法。
 *
 * 在 IDEA 里直接右键 Run 即可，或在命令行：
 *   javac -encoding UTF-8 -d out $(find src -name "*.java")
 *   java -cp out com.skylight.core.Demo
 */
public class Demo {

    /** "HH:MM" → LocalTime */
    static LocalTime t(String hhmm) {
        return LocalTime.parse(hhmm);
    }

    public static void main(String[] args) {
        // ===== 天窗（真实数据）=====
        Map<Long, Skylight> skies = new HashMap<>();
        skies.put(1L, sky(1, "沪昆", "站内下行", "11:05", "13:35", "萍乡工务段")); // 150 分钟
        skies.put(2L, sky(2, "沪昆", "站内上行", "07:30", "09:20", "萍乡工务段")); // 110 分钟（例外短天窗）
        skies.put(3L, sky(3, "沪昆", "站内",     "08:00", "10:00", "萍乡工务段")); // 120 分钟（构造，用于时长冲突）

        // ===== 作业任务（真实冲突样例 + 构造样例）=====
        List<WorkTask> tasks = new ArrayList<>();
        // 真实：天窗1 内，序16 与 序43 争用「列2区」
        tasks.add(task(1, 1, 16, "萍乡新场线路工区", "工务", "列2区", "11:05", "13:35"));
        tasks.add(task(2, 1, 43, "萍乡老场线路工区", "工务", "列2区", "11:05", "13:35"));
        // 真实：天窗2 内，序18 与 序49 争用「列602区」
        tasks.add(task(3, 2, 18, "萍乡新场线路工区", "工务", "列602区", "07:30", "09:20"));
        tasks.add(task(4, 2, 49, "萍乡检查工区",     "工务", "列602区", "07:30", "09:20"));
        // 对照：同天窗、同工区、不同单元（不应冲突）
        tasks.add(task(5, 2, 19, "萍乡新场线路工区", "工务", "列606区", "07:30", "09:20"));
        // 构造：天窗3 内，列1区 三个 60 分钟作业，时长之和 180 > 120（时长冲突）
        tasks.add(task(6, 3, 1, "萍乡新场线路工区", "工务", "列1区", "08:00", "09:00"));
        tasks.add(task(7, 3, 2, "萍乡新场线路工区", "工务", "列1区", "08:30", "09:30"));
        tasks.add(task(8, 3, 3, "萍乡新场线路工区", "工务", "列1区", "09:00", "10:00"));

        // ===== 配合关系：序16 需电务配合但未确认 =====
        Coordination coord = new Coordination();
        coord.taskId = 1; coord.unitName = "电务"; coord.unitType = "电务"; coord.confirmed = false;

        // ===== 依赖关系：构造 1→2→3→1 循环 =====
        List<TaskDependency> deps = Arrays.asList(dep(1, 2), dep(2, 3), dep(3, 1));

        // ===== 跑六类冲突检测 =====
        List<Conflict> all = new ArrayList<>();
        all.addAll(ConflictDetector.detectUnitContention(tasks));
        all.addAll(ConflictDetector.detectDurationConflict(tasks, skies));
        all.addAll(ConflictDetector.detectElectricalConflict(tasks));
        all.addAll(ConflictDetector.detectDependencyConflict(tasks, deps));
        all.addAll(ConflictDetector.detectCoordinationMissing(Collections.singletonList(coord)));
        all.addAll(ConflictDetector.detectSubjectViolation(tasks));

        // ===== 打印结果 =====
        System.out.println("========== 冲突检测结果（萍乡工务段真实样例） ==========");
        if (all.isEmpty()) {
            System.out.println("未发现冲突。");
        } else {
            int i = 1;
            for (Conflict c : all) {
                System.out.println(i++ + ". " + c);
                System.out.println();
            }
        }
        System.out.println("共检出 " + all.size() + " 条冲突。");
    }

    static Skylight sky(long id, String line, String dir, String s, String e, String unit) {
        Skylight sk = new Skylight();
        sk.id = id; sk.lineName = line; sk.direction = dir;
        sk.startTime = t(s); sk.endTime = t(e); sk.mainUnit = unit;
        return sk;
    }

    static WorkTask task(long id, long skyId, int serial, String area, String prof,
                         String unit, String s, String e) {
        WorkTask w = new WorkTask();
        w.id = id; w.skylightId = skyId; w.serialNo = serial;
        w.workArea = area; w.profession = prof; w.workUnitCode = unit;
        w.startTime = t(s); w.endTime = t(e);
        return w;
    }

    static TaskDependency dep(long taskId, long dependsOnId) {
        TaskDependency d = new TaskDependency();
        d.taskId = taskId; d.dependsOnId = dependsOnId;
        return d;
    }
}
