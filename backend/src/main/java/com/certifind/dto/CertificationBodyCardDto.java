package com.certifind.dto;

import java.time.LocalDate;
import java.util.List;

public record CertificationBodyCardDto(
    Integer id,
    String name,
    String country,
    String accreditationBodyCode,
    String phone,
    String email,
    String website,
    String address,
    String sourceUrl,
    LocalDate verifiedAt,
    String proofUrl,
    int eaCode,
    String eaDescription,
    String scopeSection,
    List<AccreditationScopeDto> scopes,
    LocalDate expiryDate
) {}
