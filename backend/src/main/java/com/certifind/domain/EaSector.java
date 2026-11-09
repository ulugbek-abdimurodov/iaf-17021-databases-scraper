package com.certifind.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

@Entity
@Table(name = "ea_sectors")
public class EaSector {

    @Id
    private Integer code;

    @Column(name = "name_en", nullable = false, length = 200)
    private String nameEn;

    @Column(name = "name_it", nullable = false, length = 200)
    private String nameIt;

    public Integer getCode() {
        return code;
    }

    public String getNameEn() {
        return nameEn;
    }

    public String getNameIt() {
        return nameIt;
    }
}
