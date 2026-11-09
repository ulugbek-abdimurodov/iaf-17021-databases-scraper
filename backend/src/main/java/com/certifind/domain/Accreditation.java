package com.certifind.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.FetchType;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;
import java.time.LocalDate;
import java.util.Objects;

/** One accreditation certificate (e.g. ISO/IEC 17021-1 from ACCREDIA) held by a certification body. */
@Entity
@Table(name = "accreditations")
public class Accreditation {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Integer id;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "certification_body_id", nullable = false)
    private CertificationBody certificationBody;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "accreditation_body_id", nullable = false)
    private AccreditationBody accreditationBody;

    @Column(name = "accreditation_standard", nullable = false, length = 50)
    private String accreditationStandard;

    @Column(name = "certificate_number", nullable = false, length = 50)
    private String certificateNumber;

    @Column(name = "status", nullable = false, length = 20)
    private String status;

    @Column(name = "issue_date", nullable = false)
    private LocalDate issueDate;

    @Column(name = "expiry_date")
    private LocalDate expiryDate;

    @Column(name = "proof_url", columnDefinition = "TEXT")
    private String proofUrl;

    public Integer getId() {
        return id;
    }

    public CertificationBody getCertificationBody() {
        return certificationBody;
    }

    public AccreditationBody getAccreditationBody() {
        return accreditationBody;
    }

    public String getAccreditationStandard() {
        return accreditationStandard;
    }

    public String getCertificateNumber() {
        return certificateNumber;
    }

    public String getStatus() {
        return status;
    }

    public LocalDate getIssueDate() {
        return issueDate;
    }

    public LocalDate getExpiryDate() {
        return expiryDate;
    }

    public String getProofUrl() {
        return proofUrl;
    }

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof Accreditation that)) return false;
        return Objects.equals(id, that.id);
    }

    @Override
    public int hashCode() {
        return Objects.hashCode(id);
    }

    @Override
    public String toString() {
        return "Accreditation{" +
                "id=" + id +
                ", accreditationStandard='" + accreditationStandard + '\'' +
                ", certificateNumber='" + certificateNumber + '\'' +
                ", status='" + status + '\'' +
                ", expiryDate=" + expiryDate +
                '}';
    }
}
