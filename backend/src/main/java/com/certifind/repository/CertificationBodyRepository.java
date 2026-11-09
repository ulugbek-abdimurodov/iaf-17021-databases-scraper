package com.certifind.repository;

import com.certifind.domain.CertificationBody;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface CertificationBodyRepository extends JpaRepository<CertificationBody, Integer> {
    List<CertificationBody> findAllByOrderByNameAsc();
}
