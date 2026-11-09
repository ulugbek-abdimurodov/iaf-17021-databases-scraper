package com.certifind.repository;

import com.certifind.domain.AccreditedScope;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.util.List;

/**
 * Every query here returns only valid issuing rights: the scope and its accreditation
 * are ACTIVE and the accreditation has not expired, and the certification body also holds
 * an active ISO/IEC 17021-1 accreditation (same rule as the v_issuing_rights view).
 */
@Repository
public interface AccreditedScopeRepository extends JpaRepository<AccreditedScope, Integer> {

    String VALID_ACCREDITATION_CONDITION = """
        s.status = 'ACTIVE' AND a.status = 'ACTIVE'
          AND (a.expiryDate IS NULL OR a.expiryDate >= CURRENT_DATE)
          AND (a.accreditationStandard = 'ISO/IEC 17021-1'
               OR EXISTS (SELECT base FROM Accreditation base
                          WHERE base.certificationBody.id = a.certificationBody.id
                            AND base.accreditationStandard = 'ISO/IEC 17021-1'
                            AND base.status = 'ACTIVE'
                            AND (base.expiryDate IS NULL OR base.expiryDate >= CURRENT_DATE)))""";

    @Query("SELECT DISTINCT s.certificationStandard FROM AccreditedScope s JOIN s.accreditation a " +
           "WHERE " + VALID_ACCREDITATION_CONDITION + " " +
           "ORDER BY s.certificationStandard")
    List<String> findDistinctCertificationStandards();

    /** Each row is {certificationStandard, eaCode}; non-EA scopes are left out. */
    @Query("SELECT DISTINCT s.certificationStandard, s.eaCode FROM AccreditedScope s JOIN s.accreditation a " +
           "WHERE s.eaCode IS NOT NULL AND " + VALID_ACCREDITATION_CONDITION + " " +
           "ORDER BY s.certificationStandard, s.eaCode")
    List<Object[]> findDistinctStandardEaCodes();

    @Query("SELECT s FROM AccreditedScope s " +
           "JOIN FETCH s.accreditation a " +
           "JOIN FETCH a.certificationBody cb " +
           "JOIN FETCH a.accreditationBody ab " +
           "WHERE s.certificationStandard = :standard AND " + VALID_ACCREDITATION_CONDITION + " " +
           "ORDER BY cb.name ASC, s.eaCode ASC")
    List<AccreditedScope> findValidScopesByStandard(@Param("standard") String standard);

    @Query("SELECT s FROM AccreditedScope s " +
           "JOIN FETCH s.accreditation a " +
           "JOIN FETCH a.certificationBody cb " +
           "JOIN FETCH a.accreditationBody ab " +
           "WHERE " + VALID_ACCREDITATION_CONDITION + " " +
           "ORDER BY cb.id ASC, s.certificationStandard ASC, s.eaCode ASC")
    List<AccreditedScope> findAllValidScopes();
}
