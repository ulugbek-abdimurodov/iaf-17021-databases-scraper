package com.certifind.importer;

import java.io.IOException;
import java.io.Reader;
import java.io.StringReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDate;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.SortedSet;
import java.util.TreeSet;
import java.util.regex.Pattern;

import org.apache.commons.csv.CSVFormat;
import org.apache.commons.csv.CSVParser;
import org.apache.commons.csv.CSVRecord;

/**
 * Reads a dataset folder and checks everything that does not need the database:
 * headers, required fields, formats, dates, EA code lists, duplicates and references
 * between the three files. Problems are collected as "file:line: message" so one run
 * reports every mistake instead of stopping at the first.
 */
public final class DatasetReader {

    static final List<String> BODY_COLUMNS = List.of(
            "name", "country", "registration_no", "phone", "email", "website", "address",
            "source_url", "verified_at");
    static final List<String> ACCREDITATION_COLUMNS = List.of(
            "ab_code", "certificate_number", "body_name", "accreditation_standard", "status",
            "issue_date", "expiry_date", "proof_url");
    static final List<String> SCOPE_COLUMNS = List.of(
            "certificate_number", "certification_standard", "ea_codes", "status", "scope_note");

    private static final Set<String> STATUSES = Set.of("ACTIVE", "SUSPENDED", "WITHDRAWN");
    private static final Pattern PHONE = Pattern.compile("\\+[0-9][0-9 ()/-]{5,}");
    private static final Pattern EMAIL = Pattern.compile("[^@\\s]+@[^@\\s]+\\.[^@\\s]+");
    private static final Pattern URL = Pattern.compile("https?://\\S+");

    private final List<String> errors = new ArrayList<>();

    public List<String> errors() {
        return errors;
    }

    public Dataset read(Path dir) {
        String name = dir.getFileName().toString();
        List<Dataset.Body> bodies = readFile(dir, "bodies.csv", BODY_COLUMNS, this::body);
        List<Dataset.Accreditation> accreditations =
                readFile(dir, "accreditations.csv", ACCREDITATION_COLUMNS, this::accreditation);
        List<Dataset.Scope> scopes = readFile(dir, "scopes.csv", SCOPE_COLUMNS, this::scope);

        // Bodies: one row per (country, name) and per (country, registration_no).
        Map<String, Dataset.Body> bodiesByName = new HashMap<>();
        Set<String> registrationNos = new HashSet<>();
        for (Dataset.Body b : bodies) {
            if (b.name() == null) continue;
            if (bodiesByName.putIfAbsent(b.name(), b) != null) {
                error(dir, "bodies.csv", b.line(), "duplicate body name '" + b.name() + "'");
            }
            if (b.registrationNo() != null && !registrationNos.add(b.country() + "|" + b.registrationNo())) {
                error(dir, "bodies.csv", b.line(), "duplicate registration_no '" + b.registrationNo() + "'");
            }
        }

        // Accreditations: certificate numbers unique, body must be in bodies.csv.
        Set<String> certificates = new HashSet<>();
        List<Dataset.Accreditation> linked = new ArrayList<>();
        for (Dataset.Accreditation a : accreditations) {
            if (a.certificateNumber() != null && !certificates.add(a.certificateNumber())) {
                error(dir, "accreditations.csv", a.line(),
                        "duplicate certificate_number '" + a.certificateNumber() + "'");
            }
            Dataset.Body body = a.bodyName() == null ? null : bodiesByName.get(a.bodyName());
            if (a.bodyName() != null && body == null) {
                error(dir, "accreditations.csv", a.line(), "body_name '" + a.bodyName() + "' is not in bodies.csv");
            }
            linked.add(new Dataset.Accreditation(a.line(), a.abCode(), a.certificateNumber(), a.bodyName(),
                    body == null ? null : body.country(), a.accreditationStandard(), a.status(),
                    a.issueDate(), a.expiryDate(), a.proofUrl()));
        }

        // Scopes: certificate must be in accreditations.csv, no EA code listed twice.
        Map<String, Set<Integer>> seen = new HashMap<>();
        for (Dataset.Scope s : scopes) {
            if (s.certificateNumber() != null && !certificates.contains(s.certificateNumber())) {
                error(dir, "scopes.csv", s.line(),
                        "certificate_number '" + s.certificateNumber() + "' is not in accreditations.csv");
            }
            Set<Integer> used = seen.computeIfAbsent(s.certificateNumber() + "|" + s.certificationStandard(),
                    k -> new HashSet<>());
            for (int ea : s.eaCodes()) {
                if (!used.add(ea)) {
                    error(dir, "scopes.csv", s.line(), "EA " + ea + " for " + s.certificationStandard()
                            + " under " + s.certificateNumber() + " is listed more than once");
                }
            }
        }
        return new Dataset(name, bodies, linked, scopes);
    }

    private interface RowParser<T> {
        T parse(Row row);
    }

    /** A CSV record with helpers that report problems against its file and line. */
    private final class Row {
        final Path dir;
        final String file;
        final int line;
        final CSVRecord record;

        Row(Path dir, String file, CSVRecord record) {
            this.dir = dir;
            this.file = file;
            this.line = (int) record.getRecordNumber() + 1; // + header line
            this.record = record;
        }

        String opt(String column) {
            String value = record.isSet(column) ? record.get(column).strip() : "";
            return value.isEmpty() ? null : value;
        }

        String req(String column) {
            String value = opt(column);
            if (value == null) fail(column + " is required");
            return value;
        }

        String matching(String column, Pattern pattern, String what) {
            String value = opt(column);
            if (value != null && !pattern.matcher(value).matches()) fail(column + " '" + value + "' is not " + what);
            return value;
        }

        String status(String column) {
            String value = opt(column);
            if (value == null) return "ACTIVE";
            if (!STATUSES.contains(value)) fail(column + " must be one of " + STATUSES + ", got '" + value + "'");
            return value;
        }

        LocalDate date(String column, boolean required) {
            String value = required ? req(column) : opt(column);
            if (value == null) return null;
            try {
                return LocalDate.parse(value);
            } catch (DateTimeParseException e) {
                fail(column + " '" + value + "' is not a date (use YYYY-MM-DD)");
                return null;
            }
        }

        void fail(String message) {
            error(dir, file, line, message);
        }
    }

    private Dataset.Body body(Row r) {
        LocalDate verifiedAt = r.date("verified_at", false);
        if (verifiedAt != null && verifiedAt.isAfter(LocalDate.now())) r.fail("verified_at is in the future");
        return new Dataset.Body(r.line, r.req("name"), r.req("country"), r.opt("registration_no"),
                r.matching("phone", PHONE, "an international number like +355 692081842"),
                r.matching("email", EMAIL, "an email address"),
                r.matching("website", URL, "an http(s) URL"),
                r.opt("address"),
                r.matching("source_url", URL, "an http(s) URL"),
                verifiedAt);
    }

    private Dataset.Accreditation accreditation(Row r) {
        LocalDate issued = r.date("issue_date", true);
        LocalDate expires = r.date("expiry_date", false);
        if (issued != null && expires != null && expires.isBefore(issued)) {
            r.fail("expiry_date " + expires + " is before issue_date " + issued);
        }
        return new Dataset.Accreditation(r.line, r.req("ab_code"), r.req("certificate_number"),
                r.req("body_name"), null, r.req("accreditation_standard"), r.status("status"),
                issued, expires, r.matching("proof_url", URL, "an http(s) URL"));
    }

    private Dataset.Scope scope(Row r) {
        String spec = r.req("ea_codes");
        SortedSet<Integer> eaCodes = new TreeSet<>();
        if (spec != null) {
            try {
                eaCodes = parseEaCodes(spec);
            } catch (IllegalArgumentException e) {
                r.fail("ea_codes: " + e.getMessage());
            }
        }
        return new Dataset.Scope(r.line, r.req("certificate_number"), r.req("certification_standard"),
                eaCodes, r.status("status"), r.opt("scope_note"));
    }

    /** Parses "ALL", "17" or "1-10;12;14-39" into EA codes 1-39. */
    public static SortedSet<Integer> parseEaCodes(String spec) {
        SortedSet<Integer> codes = new TreeSet<>();
        if (spec.strip().equalsIgnoreCase("ALL")) {
            for (int i = 1; i <= 39; i++) codes.add(i);
            return codes;
        }
        for (String part : spec.split(";")) {
            String token = part.strip();
            if (token.isEmpty()) continue;
            String[] bounds = token.split("-", -1);
            if (bounds.length > 2) throw new IllegalArgumentException("'" + token + "' is not N or N-M");
            int from = eaCode(bounds[0]);
            int to = bounds.length == 2 ? eaCode(bounds[1]) : from;
            if (to < from) throw new IllegalArgumentException("range '" + token + "' goes backwards");
            for (int i = from; i <= to; i++) codes.add(i);
        }
        if (codes.isEmpty()) throw new IllegalArgumentException("no EA codes in '" + spec + "'");
        return codes;
    }

    private static int eaCode(String text) {
        try {
            int code = Integer.parseInt(text.strip());
            if (code >= 1 && code <= 39) return code;
        } catch (NumberFormatException ignored) {
            // reported below
        }
        throw new IllegalArgumentException("'" + text.strip() + "' is not an EA code between 1 and 39");
    }

    private <T> List<T> readFile(Path dir, String file, List<String> columns, RowParser<T> rowParser) {
        Path path = dir.resolve(file);
        List<T> rows = new ArrayList<>();
        if (!Files.isRegularFile(path)) {
            error(dir, file, 0, "file is missing");
            return rows;
        }
        String text;
        try {
            text = Files.readString(path, StandardCharsets.UTF_8);
        } catch (IOException e) {
            error(dir, file, 0, "cannot read: " + e.getMessage());
            return rows;
        }
        if (text.startsWith("﻿")) text = text.substring(1); // BOM added by Excel
        CSVFormat format = CSVFormat.DEFAULT.builder().setHeader().setSkipHeaderRecord(true)
                .setIgnoreEmptyLines(true).build();
        try (Reader reader = new StringReader(text); CSVParser parser = format.parse(reader)) {
            List<String> header = parser.getHeaderNames().stream().map(String::strip).toList();
            if (!header.equals(columns)) {
                error(dir, file, 1, "header must be exactly: " + String.join(",", columns));
                return rows;
            }
            for (CSVRecord record : parser) {
                Row row = new Row(dir, file, record);
                if (record.size() != columns.size()) {
                    row.fail("expected " + columns.size() + " columns, found " + record.size()
                            + " (quote values that contain commas)");
                    continue;
                }
                rows.add(rowParser.parse(row));
            }
        } catch (IOException | IllegalStateException | IllegalArgumentException e) {
            error(dir, file, 0, "malformed CSV: " + e.getMessage());
        }
        return rows;
    }

    private void error(Path dir, String file, int line, String message) {
        errors.add(dir.getFileName() + "/" + file + (line > 0 ? ":" + line : "") + ": " + message);
    }
}
