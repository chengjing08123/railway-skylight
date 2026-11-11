package com.skylight.controller;

import com.skylight.core.Conflict;
import com.skylight.dto.TaskDto;
import com.skylight.dto.WindowDto;
import com.skylight.service.ConflictService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * 冲突检测 REST 接口。
 */
@RestController
@RequestMapping("/api")
public class ConflictController {

    private final ConflictService conflictService;

    public ConflictController(ConflictService conflictService) {
        this.conflictService = conflictService;
    }

    /** GET /api/conflicts —— 返回全部冲突检测结果 */
    @GetMapping("/conflicts")
    public List<Conflict> getConflicts() {
        return conflictService.detectAll();
    }

    /** GET /api/tasks —— 返回作业任务（供甘特页） */
    @GetMapping("/tasks")
    public List<TaskDto> getTasks() {
        return conflictService.getTasks();
    }

    /** GET /api/windows —— 返回天窗（供甘特页） */
    @GetMapping("/windows")
    public List<WindowDto> getWindows() {
        return conflictService.getWindows();
    }
}
