package com.skylight.mapper;

import com.skylight.entity.TaskDependency;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface TaskDependencyMapper {
    @Select("SELECT * FROM task_dependency")
    List<TaskDependency> findAll();
}
