package com.certifind;

import java.util.List;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import com.certifind.domain.SectorKeyword;
import com.certifind.dto.CertificationBodyCardDto;
import com.certifind.dto.SearchRequest;
import com.certifind.dto.SearchResponse;
import com.certifind.repository.SectorKeywordRepository;
import com.certifind.service.SearchService;

@SpringBootTest
class CertifindApplicationTests {

    @Autowired
    private SectorKeywordRepository sectorKeywordRepository;

    @Autowired
    private SearchService searchService;

    private void assertSearchResults(String iso, String sector, int expectedEaCode) {
        SearchResponse response = searchService.search(new SearchRequest(iso, sector));
        List<CertificationBodyCardDto> results = response.results();
        List<String> names = results.stream().map(CertificationBodyCardDto::name).toList();

        assertEquals(expectedEaCode, response.resolvedEaCode());
        assertEquals(names.size(), names.stream().distinct().count());
        assertTrue(results.stream().allMatch(card -> card.scopes().stream()
                .anyMatch(scope -> scope.eaCode() == expectedEaCode
                        && iso.equals(scope.isoStandard()))));
    }

    @Test
    @DisplayName("Context loads successfully and validates JPA schema against PostgreSQL")
    void contextLoads() {
        assertNotNull(sectorKeywordRepository);
        assertNotNull(searchService);
    }

    @Test
    @DisplayName("Sector text resolves to EA codes")
    void testSectorResolution() {
        assertEquals(37, sectorKeywordRepository.findBestMatch("asilo").map(SectorKeyword::getEaCode).orElseThrow());
        assertEquals(17, sectorKeywordRepository.findBestMatch("Metall").map(SectorKeyword::getEaCode).orElseThrow());
        assertEquals(17, sectorKeywordRepository.findBestMatch("carpenteria metallica a Brescia")
                .map(SectorKeyword::getEaCode).orElseThrow());
        Optional<SectorKeyword> none = sectorKeywordRepository.findBestMatch("xyzxyz");
        assertTrue(none.isEmpty());
    }

    @Test
    @DisplayName("ISO 9001 in metal (EA 17) returns matching certification bodies")
    void testIso9001Metal() {
        assertSearchResults("ISO 9001", "metallo", 17);
    }

    @Test
    @DisplayName("ISO/IEC 27001 searches resolve requested EA sectors")
    void testIso27001AllSectors() {
        assertSearchResults("ISO/IEC 27001", "EA 17", 17);
        assertSearchResults("ISO/IEC 27001", "EA 39", 39);
    }
}
