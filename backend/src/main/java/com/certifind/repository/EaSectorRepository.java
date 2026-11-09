package com.certifind.repository;

import com.certifind.domain.EaSector;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

@Repository
public interface EaSectorRepository extends JpaRepository<EaSector, Integer> {
}
