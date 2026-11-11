package com.skylight.mapper;

import com.skylight.entity.Skylight;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface SkylightMapper {
    @Select("SELECT * FROM skylight")
    List<Skylight> findAll();
}
