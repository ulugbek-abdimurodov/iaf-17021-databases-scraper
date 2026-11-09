package com.certifind.controller;

import com.certifind.dto.SearchRequest;
import com.certifind.dto.SearchResponse;
import com.certifind.dto.SearchOptionsResponse;
import com.certifind.service.SearchService;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

@RestController
@RequestMapping("/api/v1")
public class SearchController {

    private final SearchService searchService;

    public SearchController(SearchService searchService) {
        this.searchService = searchService;
    }

    @GetMapping("/health")
    public ResponseEntity<Map<String, String>> health() {
        return ResponseEntity.ok(Map.of("status", "UP"));
    }

    @GetMapping("/options")
    public ResponseEntity<SearchOptionsResponse> options() {
        return ResponseEntity.ok(searchService.getOptions());
    }

    @PostMapping("/search")
    public ResponseEntity<SearchResponse> search(@RequestBody SearchRequest request) {
        try {
            return ResponseEntity.ok(searchService.search(request));
        } catch (IllegalArgumentException exception) {
            return ResponseEntity.badRequest().build();
        }
    }

    @GetMapping("/companies")
    public ResponseEntity<SearchResponse> allCompanies() {
        return ResponseEntity.ok(searchService.findAllCompanies());
    }
}
