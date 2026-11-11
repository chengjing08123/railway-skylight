package com.skylight.mapper;

import com.skylight.entity.Coordination;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface CoordinationMapper {
    @Select("SELECT * FROM coordination")
    List<Coordination> findAll();
}
