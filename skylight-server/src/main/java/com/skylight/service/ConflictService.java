package com.skylight.service;

import com.skylight.core.Conflict;
import com.skylight.core.ConflictDetector;
import com.skylight.entity.Coordination;
import com.skylight.entity.Skylight;
import com.skylight.entity.TaskDependency;
import com.skylight.entity.WorkTask;
import com.skylight.mapper.CoordinationMapper;
import com.skylight.mapper.SkylightMapper;
import com.skylight.mapper.TaskDependencyMapper;
import com.skylight.mapper.WorkTaskMapper;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 冲突检测业务层：查库 → 组装 → 喂给 ConflictDetector → 返回全部冲突。
 */
@Service
public class ConflictService {

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
        all.addAll(ConflictDetector.detectSubjectViolation(tasks));
        return all;
    }
}
