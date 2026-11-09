package com.certifind.dto;

import java.time.LocalDate;

public record AccreditationScopeDto(
        Integer eaCode,
        String eaDescription,
        String scopeSection,
        String proofUrl,
        String isoStandard,
        String accreditationStandard,
        String accreditationBodyCode,
        String certificateNumber,
        LocalDate expiryDate
) {}
