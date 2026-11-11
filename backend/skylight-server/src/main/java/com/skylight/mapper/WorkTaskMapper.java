package com.skylight.mapper;

import com.skylight.entity.WorkTask;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface WorkTaskMapper {
    @Select("SELECT * FROM work_task")
    List<WorkTask> findAll();
}
