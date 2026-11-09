package com.certifind.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.util.Objects;

@Entity
@Table(name = "sector_keywords")
public class SectorKeyword {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Integer id;

    @Column(name = "keyword", nullable = false, length = 255)
    private String keyword;

    @Column(name = "language", nullable = false, length = 2)
    private String language;

    @Column(name = "ea_code", nullable = false)
    private Integer eaCode;

    public Integer getId() {
        return id;
    }

    public String getKeyword() {
        return keyword;
    }

    public String getLanguage() {
        return language;
    }

    public Integer getEaCode() {
        return eaCode;
    }

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof SectorKeyword that)) return false;
        return Objects.equals(id, that.id);
    }

    @Override
    public int hashCode() {
        return Objects.hashCode(id);
    }

    @Override
    public String toString() {
        return "SectorKeyword{" +
                "id=" + id +
                ", keyword='" + keyword + '\'' +
                ", language='" + language + '\'' +
                ", eaCode=" + eaCode +
                '}';
    }
}
