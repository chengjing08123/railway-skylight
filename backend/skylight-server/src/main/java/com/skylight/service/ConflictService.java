package com.skylight.service;

import com.skylight.core.Conflict;
import com.skylight.core.ConflictDetector;
import com.skylight.dto.TaskDto;
import com.skylight.dto.WindowDto;
import com.skylight.entity.Coordination;
import com.skylight.entity.Skylight;
import com.skylight.entity.TaskDependency;
import com.skylight.entity.WorkTask;
import com.skylight.mapper.CoordinationMapper;
import com.skylight.mapper.SkylightMapper;
import com.skylight.mapper.TaskDependencyMapper;
import com.skylight.mapper.WorkTaskMapper;
import org.springframework.stereotype.Service;

import java.time.LocalTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 冲突检测业务层：查库 → 组装 → 喂给 ConflictDetector → 返回结果。
 * 同时提供甘特所需的作业任务与天窗数据。
 */
@Service
public class ConflictService {

    private static final DateTimeFormatter HHMM = DateTimeFormatter.ofPattern("HH:mm");
    private static final int OVERHEAD_MINUTES = 15; // 请点、防护、开通等固定开销

    private final WorkTaskMapper workTaskMapper;
    private final SkylightMapper skylightMapper;
    private final CoordinationMapper coordinationMapper;
    private final TaskDependencyMapper taskDependencyMapper;

    public ConflictService(WorkTaskMapper workTaskMapper,
                           SkylightMapper skylightMapper,
                           CoordinationMapper coordinationMapper,
                           TaskDependencyMapper taskDependencyMapper) {
        this.workTaskMapper = workTaskMapper;
        this.skylightMapper = skylightMapper;
        this.coordinationMapper = coordinationMapper;
        this.taskDependencyMapper = taskDependencyMapper;
    }

    /** 跑全部六类冲突检测 */
    public List<Conflict> detectAll() {
        List<WorkTask> tasks = workTaskMapper.findAll();
        List<Skylight> skylights = skylightMapper.findAll();
        List<Coordination> coords = coordinationMapper.findAll();
        List<TaskDependency> deps = taskDependencyMapper.findAll();

        Map<Long, Skylight> skyMap = new HashMap<>();
        for (Skylight s : skylights) {
            skyMap.put(s.id, s);
        }

        List<Conflict> all = new ArrayList<>();
        all.addAll(ConflictDetector.detectUnitContention(tasks));
        all.addAll(ConflictDetector.detectDurationConflict(tasks, skyMap));
        all.addAll(ConflictDetector.detectElectricalConflict(tasks));
        all.addAll(ConflictDetector.detectDependencyConflict(tasks, deps));
        all.addAll(ConflictDetector.detectCoordinationMissing(coords));
        all.addAll(ConflictDetector.detectLeaderMissing(tasks, skyMap));
        return all;
    }

    /** 甘特页：全部作业任务 */
    public List<TaskDto> getTasks() {
        return workTaskMapper.findAll().stream()
                .map(t -> new TaskDto(
                        t.id,
                        t.skylightId,
                        t.serialNo,
                        t.workArea,
                        t.workUnitCode,
                        t.workType,
                        fmt(t.startTime),
                        fmt(t.endTime)))
                .toList();
    }

    /** 甘特页：全部天窗 */
    public List<WindowDto> getWindows() {
        return skylightMapper.findAll().stream()
                .map(s -> new WindowDto(
                        s.id,
                        s.planDate == null ? "" : s.planDate.toString(),
                        s.lineName,
                        s.direction,
                        s.registerStation,
                        fmt(s.startTime),
                        fmt(s.endTime),
                        OVERHEAD_MINUTES))
                .toList();
    }

    private static String fmt(LocalTime t) {
        return t == null ? "" : t.format(HHMM);
    }
}
