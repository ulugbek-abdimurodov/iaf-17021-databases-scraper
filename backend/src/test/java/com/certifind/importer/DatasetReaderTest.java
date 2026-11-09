package com.certifind.importer;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

/** Pure file checks; no database needed. */
class DatasetReaderTest {

    @TempDir
    Path root;

    private Path dataset(String bodies, String accreditations, String scopes) throws IOException {
        Path dir = Files.createDirectories(root.resolve("test-ab"));
        Files.writeString(dir.resolve("bodies.csv"), String.join(",", DatasetReader.BODY_COLUMNS) + "\n" + bodies);
        Files.writeString(dir.resolve("accreditations.csv"),
                String.join(",", DatasetReader.ACCREDITATION_COLUMNS) + "\n" + accreditations);
        Files.writeString(dir.resolve("scopes.csv"), String.join(",", DatasetReader.SCOPE_COLUMNS) + "\n" + scopes);
        return dir;
    }

    @Test
    @DisplayName("EA code lists expand ranges and ALL")
    void parsesEaCodes() {
        assertEquals(39, DatasetReader.parseEaCodes("ALL").size());
        assertEquals(List.of(1, 2, 3, 12, 17), List.copyOf(DatasetReader.parseEaCodes("1-3; 12;17")));
        assertEquals(38, DatasetReader.parseEaCodes("1-10;12-39").size());
        assertThrows(IllegalArgumentException.class, () -> DatasetReader.parseEaCodes("0-5"));
        assertThrows(IllegalArgumentException.class, () -> DatasetReader.parseEaCodes("40"));
        assertThrows(IllegalArgumentException.class, () -> DatasetReader.parseEaCodes("9-3"));
        assertThrows(IllegalArgumentException.class, () -> DatasetReader.parseEaCodes("abc"));
    }

    @Test
    @DisplayName("A valid dataset reads cleanly, quoted commas included")
    void readsValidDataset() throws IOException {
        DatasetReader reader = new DatasetReader();
        Dataset ds = reader.read(dataset(
                "Test Cert,Albania,L12345678A,+355 692081842,info@test.al,https://test.al,\"Rruga 1, Tiranë\",,2026-01-15\n",
                "DPA,CS 100,Test Cert,ISO/IEC 17021-1,,2025-01-01,2029-01-01,https://www.dpa.gov.al\n",
                "CS 100,ISO 9001,1-3;17,,\nCS 100,ISO 14001,ALL,SUSPENDED,pending review\n"));
        assertEquals(List.of(), reader.errors());
        assertEquals("test-ab", ds.name());
        assertEquals("Rruga 1, Tiranë", ds.bodies().get(0).address());
        assertEquals("Albania", ds.accreditations().get(0).bodyCountry());
        assertEquals("ACTIVE", ds.accreditations().get(0).status());
        assertEquals(4, ds.scopes().get(0).eaCodes().size());
        assertEquals("SUSPENDED", ds.scopes().get(1).status());
    }

    @Test
    @DisplayName("Every problem is reported with file and line")
    void reportsAllProblems() throws IOException {
        DatasetReader reader = new DatasetReader();
        reader.read(dataset(
                "Test Cert,Albania,,0692081842,not-an-email,test.al,,,\nTest Cert,Albania,,,,,,,\n",
                "DPA,CS 100,Other Cert,ISO/IEC 17021-1,ACTIVE,2025-01-01,2024-01-01,\n"
                        + "DPA,CS 100,Test Cert,ISO/IEC 17021-1,EXPIRED,01/02/2025,,\n",
                "CS 999,ISO 9001,1-40,,\nCS 100,ISO 9001,17,,\nCS 100,ISO 9001,10-20,,\n"));
        List<String> errors = reader.errors();
        List<String> expected = List.of(
                "test-ab/bodies.csv:2: phone '0692081842'",
                "test-ab/bodies.csv:2: email 'not-an-email'",
                "test-ab/bodies.csv:2: website 'test.al'",
                "test-ab/bodies.csv:3: duplicate body name 'Test Cert'",
                "test-ab/accreditations.csv:2: expiry_date 2024-01-01 is before issue_date",
                "test-ab/accreditations.csv:2: body_name 'Other Cert' is not in bodies.csv",
                "test-ab/accreditations.csv:3: status must be one of",
                "test-ab/accreditations.csv:3: issue_date '01/02/2025' is not a date",
                "test-ab/accreditations.csv:3: duplicate certificate_number 'CS 100'",
                "test-ab/scopes.csv:2: ea_codes: '40' is not an EA code",
                "test-ab/scopes.csv:2: certificate_number 'CS 999' is not in accreditations.csv",
                "test-ab/scopes.csv:4: EA 17 for ISO 9001 under CS 100 is listed more than once");
        for (String start : expected) {
            assertTrue(errors.stream().anyMatch(e -> e.startsWith(start)), "missing: " + start + "\nin: " + errors);
        }
        assertEquals(expected.size(), errors.size(), String.join("\n", errors));
    }

    @Test
    @DisplayName("A wrong header is rejected")
    void rejectsWrongHeader() throws IOException {
        Path dir = dataset("", "", "");
        Files.writeString(dir.resolve("bodies.csv"), "company,country\nX,Albania\n");
        DatasetReader reader = new DatasetReader();
        reader.read(dir);
        assertEquals(List.of("test-ab/bodies.csv:1: header must be exactly: " + String.join(",", DatasetReader.BODY_COLUMNS)),
                reader.errors());
    }
}
