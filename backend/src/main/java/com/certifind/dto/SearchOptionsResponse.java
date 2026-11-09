package com.certifind.dto;

import java.util.List;
import java.util.Map;

public record SearchOptionsResponse(
    List<String> standards,
    Map<String, List<SectorOption>> sectorsByStandard
) {}
