package com.certifind.dto;

import java.util.List;

public record SearchResponse(
    int resolvedEaCode,
    String resolvedEaDescription,
    List<CertificationBodyCardDto> results,
    boolean directory
) {}
