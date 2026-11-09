package com.certifind.repository;

import com.certifind.domain.Accreditation;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface AccreditationRepository extends JpaRepository<Accreditation, Integer> {
    @Query("""
        SELECT a FROM Accreditation a
        JOIN FETCH a.accreditationBody
        ORDER BY a.certificationBody.id ASC, a.id ASC
    """)
    List<Accreditation> findAllWithAccreditationBody();
}
