package com.certifind.domain;

import java.util.Objects;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.FetchType;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;

/** One issuing right: a certification standard in one EA sector, granted by an accreditation. */
@Entity
@Table(name = "accredited_scopes")
public class AccreditedScope {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Integer id;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "accreditation_id", nullable = false)
    private Accreditation accreditation;

    @Column(name = "certification_standard", nullable = false, length = 50)
    private String certificationStandard;

    @Column(name = "ea_code", nullable = false)
    private Integer eaCode;

    @Column(name = "status", nullable = false, length = 20)
    private String status;

    @Column(name = "scope_note", columnDefinition = "TEXT")
    private String scopeNote;

    public Integer getId() {
        return id;
    }

    public Accreditation getAccreditation() {
        return accreditation;
    }

    public CertificationBody getCertificationBody() {
        return accreditation.getCertificationBody();
    }

    public String getCertificationStandard() {
        return certificationStandard;
    }

    public Integer getEaCode() {
        return eaCode;
    }

    public String getStatus() {
        return status;
    }

    public String getScopeNote() {
        return scopeNote;
    }

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof AccreditedScope that)) return false;
        return Objects.equals(id, that.id);
    }

    @Override
    public int hashCode() {
        return Objects.hashCode(id);
    }

    @Override
    public String toString() {
        return "AccreditedScope{" +
                "id=" + id +
                ", certificationStandard='" + certificationStandard + '\'' +
                ", eaCode=" + eaCode +
                ", status='" + status + '\'' +
                ", scopeNote='" + scopeNote + '\'' +
                '}';
    }
}
