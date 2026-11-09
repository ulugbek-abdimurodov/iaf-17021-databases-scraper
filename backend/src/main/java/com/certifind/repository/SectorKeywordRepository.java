package com.certifind.repository;

import java.util.Optional;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import com.certifind.domain.SectorKeyword;

@Repository
public interface SectorKeywordRepository extends JpaRepository<SectorKeyword, Integer> {

    /**
     * Best keyword for free sector text: an exact match, else the shortest keyword
     * containing the text ("metall" -> "metallo"), else the longest keyword
     * contained in the text ("carpenteria metallica Brescia" -> "carpenteria metallica").
     */
    @Query(value = """
        SELECT * FROM sector_keywords k
        WHERE lower(k.keyword) LIKE '%' || lower(:text) || '%'
           OR lower(:text) LIKE '%' || lower(k.keyword) || '%'
        ORDER BY
            CASE
                WHEN lower(k.keyword) = lower(:text) THEN 0
                WHEN lower(k.keyword) LIKE '%' || lower(:text) || '%' THEN 1
                ELSE 2
            END,
            CASE WHEN lower(k.keyword) LIKE '%' || lower(:text) || '%'
                 THEN length(k.keyword) ELSE -length(k.keyword) END,
            k.id
        LIMIT 1
        """, nativeQuery = true)
    Optional<SectorKeyword> findBestMatch(@Param("text") String text);
}
