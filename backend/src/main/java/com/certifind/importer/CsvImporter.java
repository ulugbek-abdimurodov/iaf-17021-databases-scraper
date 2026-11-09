package com.certifind.importer;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

/**
 * Loads validated datasets into PostgreSQL. Every write is an idempotent upsert keyed on
 * natural keys, so loading the same CSVs twice changes nothing:
 * <ul>
 *   <li>body: (country, registration_no) when given, otherwise (country, name)</li>
 *   <li>accreditation: (accreditation body, certificate_number)</li>
 *   <li>scope: (accreditation, certification standard, EA code)</li>
 * </ul>
 * Nothing is deleted. An accreditation or scope that disappears from its dataset's CSVs
 * is set to WITHDRAWN, which already removes it from search (v_issuing_rights).
 * Callers run {@link #validate} and {@link #load} inside one transaction.
 */
@Component
public class CsvImporter {

    private final JdbcTemplate jdbc;

    public CsvImporter(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    /** Inserted / updated / withdrawn / unchanged counts per table, for the import log. */
    public static final class Report {
        final Map<String, int[]> counts = new HashMap<>();

        void add(String table, int column) {
            counts.computeIfAbsent(table, t -> new int[4])[column]++;
        }

        @Override
        public String toString() {
            StringBuilder out = new StringBuilder();
            for (String table : List.of("bodies", "accreditations", "scopes")) {
                int[] c = counts.getOrDefault(table, new int[4]);
                out.append(String.format("  %-15s %5d inserted, %5d updated, %5d withdrawn, %5d unchanged%n",
                        table, c[0], c[1], c[2], c[3]));
            }
            return out.toString();
        }
    }

    private static final int INSERTED = 0, UPDATED = 1, WITHDRAWN = 2, UNCHANGED = 3;

    /** Checks a dataset against reference data and rows owned by other datasets. */
    public List<String> validate(Dataset ds) {
        List<String> errors = new ArrayList<>();
        Set<String> abCodes = new HashSet<>(jdbc.queryForList("SELECT code FROM accreditation_bodies", String.class));
        Set<String> accreditationStandards = new HashSet<>(jdbc.queryForList(
                "SELECT code FROM standards WHERE kind = 'ACCREDITATION'", String.class));
        Set<String> rules = new HashSet<>(jdbc.queryForList(
                "SELECT accreditation_standard || '|' || certification_standard FROM accreditation_scheme_rules",
                String.class));
        Map<String, String> owners = new HashMap<>();
        jdbc.query("SELECT ab.code, a.certificate_number, a.data_source FROM accreditations a "
                        + "JOIN accreditation_bodies ab ON ab.id = a.accreditation_body_id",
                rs -> {
                    owners.put(rs.getString(1) + "|" + rs.getString(2), Objects.toString(rs.getString(3), "(none)"));
                });

        Map<String, String> standardByCertificate = new HashMap<>();
        for (Dataset.Accreditation a : ds.accreditations()) {
            String where = ds.name() + "/accreditations.csv:" + a.line() + ": ";
            if (!abCodes.contains(a.abCode())) {
                errors.add(where + "unknown ab_code '" + a.abCode() + "' (known: " + abCodes
                        + "; add new accreditation bodies with a Flyway migration)");
            }
            if (!accreditationStandards.contains(a.accreditationStandard())) {
                errors.add(where + "unknown accreditation_standard '" + a.accreditationStandard() + "'");
            }
            String owner = owners.get(a.abCode() + "|" + a.certificateNumber());
            if (owner != null && !owner.equals(ds.name())) {
                errors.add(where + a.abCode() + " " + a.certificateNumber() + " already belongs to dataset " + owner);
            }
            standardByCertificate.put(a.certificateNumber(), a.accreditationStandard());
        }
        for (Dataset.Scope s : ds.scopes()) {
            String accreditationStandard = standardByCertificate.get(s.certificateNumber());
            if (accreditationStandard != null
                    && !rules.contains(accreditationStandard + "|" + s.certificationStandard())) {
                errors.add(ds.name() + "/scopes.csv:" + s.line() + ": an " + accreditationStandard
                        + " accreditation cannot cover " + s.certificationStandard()
                        + " (see accreditation_scheme_rules)");
            }
        }
        return errors;
    }

    public Report load(Dataset ds) {
        Report report = new Report();
        Map<String, Integer> bodyIds = new HashMap<>();
        for (Dataset.Body b : ds.bodies()) {
            bodyIds.put(b.name(), upsertBody(b, report));
        }
        Map<String, Integer> accreditationIds = new HashMap<>();
        Map<String, String> standards = new HashMap<>();
        for (Dataset.Accreditation a : ds.accreditations()) {
            accreditationIds.put(a.certificateNumber(), upsertAccreditation(ds.name(), a, bodyIds, report));
            standards.put(a.certificateNumber(), a.accreditationStandard());
        }
        withdrawMissingAccreditations(ds.name(), accreditationIds.values(), report);
        loadScopes(ds, accreditationIds, standards, report);
        return report;
    }

    private int upsertBody(Dataset.Body b, Report report) {
        List<Integer> ids = b.registrationNo() == null ? List.of() : jdbc.queryForList(
                "SELECT id FROM certification_bodies WHERE country = ? AND registration_no = ?",
                Integer.class, b.country(), b.registrationNo());
        if (ids.isEmpty()) {
            ids = jdbc.queryForList("SELECT id FROM certification_bodies WHERE country = ? AND name = ?",
                    Integer.class, b.country(), b.name());
        }
        Object[] values = {b.name(), b.country(), b.registrationNo(), b.phone(), b.email(), b.website(),
                b.address(), b.sourceUrl(), b.verifiedAt()};
        if (ids.isEmpty()) {
            report.add("bodies", INSERTED);
            return jdbc.queryForObject("INSERT INTO certification_bodies (name, country, registration_no, phone, "
                    + "email, website, address, source_url, verified_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    + "RETURNING id", Integer.class, values);
        }
        int id = ids.get(0);
        int changed = jdbc.update("UPDATE certification_bodies SET name = ?, country = ?, registration_no = ?, "
                + "phone = ?, email = ?, website = ?, address = ?, source_url = ?, verified_at = ? "
                + "WHERE id = ? AND (name, country, registration_no, phone, email, website, address, source_url, "
                + "verified_at) IS DISTINCT FROM (?, ?, ?, ?, ?, ?, ?, ?, ?::date)", flat(values, id, values));
        report.add("bodies", changed > 0 ? UPDATED : UNCHANGED);
        return id;
    }

    private int upsertAccreditation(String source, Dataset.Accreditation a, Map<String, Integer> bodyIds,
                                    Report report) {
        Integer abId = jdbc.queryForObject("SELECT id FROM accreditation_bodies WHERE code = ?",
                Integer.class, a.abCode());
        List<Integer> ids = jdbc.queryForList(
                "SELECT id FROM accreditations WHERE accreditation_body_id = ? AND certificate_number = ?",
                Integer.class, abId, a.certificateNumber());
        Object[] values = {bodyIds.get(a.bodyName()), a.accreditationStandard(), a.status(), a.issueDate(),
                a.expiryDate(), a.proofUrl()};
        if (ids.isEmpty()) {
            report.add("accreditations", INSERTED);
            return jdbc.queryForObject("INSERT INTO accreditations (certification_body_id, accreditation_standard, "
                    + "status, issue_date, expiry_date, proof_url, accreditation_body_id, certificate_number, "
                    + "data_source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id", Integer.class,
                    flat(values, abId, a.certificateNumber(), source));
        }
        int id = ids.get(0);
        int changed = jdbc.update("UPDATE accreditations SET certification_body_id = ?, accreditation_standard = ?, "
                + "status = ?, issue_date = ?, expiry_date = ?, proof_url = ?, data_source = ? "
                + "WHERE id = ? AND (certification_body_id, accreditation_standard, status, issue_date, expiry_date, "
                + "proof_url, data_source) IS DISTINCT FROM (?, ?, ?, ?::date, ?::date, ?, ?)",
                flat(values, source, id, values, source));
        report.add("accreditations", changed > 0 ? UPDATED : UNCHANGED);
        return id;
    }

    private void withdrawMissingAccreditations(String source, Iterable<Integer> keep, Report report) {
        Set<Integer> kept = new HashSet<>();
        keep.forEach(kept::add);
        List<Integer> owned = jdbc.queryForList(
                "SELECT id FROM accreditations WHERE data_source = ? AND status <> 'WITHDRAWN'", Integer.class, source);
        for (int id : owned) {
            if (!kept.contains(id)) {
                jdbc.update("UPDATE accreditations SET status = 'WITHDRAWN' WHERE id = ?", id);
                report.add("accreditations", WITHDRAWN);
            }
        }
    }

    private record ScopeState(String status, String note) {
    }

    private void loadScopes(Dataset ds, Map<String, Integer> accreditationIds, Map<String, String> standards,
                            Report report) {
        // Desired state: accreditation id -> "standard|ea" -> (status, note).
        Map<Integer, Map<String, ScopeState>> desired = new HashMap<>();
        accreditationIds.values().forEach(id -> desired.put(id, new HashMap<>()));
        for (Dataset.Scope s : ds.scopes()) {
            Map<String, ScopeState> target = desired.get(accreditationIds.get(s.certificateNumber()));
            for (int ea : s.eaCodes()) {
                target.put(s.certificationStandard() + "|" + ea, new ScopeState(s.status(), s.scopeNote()));
            }
        }

        List<Object[]> inserts = new ArrayList<>();
        List<Object[]> updates = new ArrayList<>();
        for (Map.Entry<String, Integer> entry : accreditationIds.entrySet()) {
            int accreditationId = entry.getValue();
            Map<String, ScopeState> want = desired.get(accreditationId);
            Map<String, Object[]> have = new HashMap<>();
            jdbc.query("SELECT id, certification_standard, ea_code, status, scope_note FROM accredited_scopes "
                    + "WHERE accreditation_id = ?", rs -> {
                        have.put(rs.getString(2) + "|" + rs.getInt(3),
                                new Object[] {rs.getInt(1), rs.getString(4), rs.getString(5)});
                    }, accreditationId);

            for (Map.Entry<String, ScopeState> w : want.entrySet()) {
                Object[] current = have.get(w.getKey());
                ScopeState state = w.getValue();
                if (current == null) {
                    String[] key = w.getKey().split("\\|");
                    inserts.add(new Object[] {accreditationId, standards.get(entry.getKey()), key[0],
                            Integer.parseInt(key[1]), state.status(), state.note()});
                    report.add("scopes", INSERTED);
                } else if (!state.status().equals(current[1]) || !Objects.equals(state.note(), current[2])) {
                    updates.add(new Object[] {state.status(), state.note(), current[0]});
                    report.add("scopes", UPDATED);
                } else {
                    report.add("scopes", UNCHANGED);
                }
            }
            for (Map.Entry<String, Object[]> h : have.entrySet()) {
                if (!want.containsKey(h.getKey()) && !"WITHDRAWN".equals(h.getValue()[1])) {
                    updates.add(new Object[] {"WITHDRAWN", h.getValue()[2], h.getValue()[0]});
                    report.add("scopes", WITHDRAWN);
                }
            }
        }
        jdbc.batchUpdate("INSERT INTO accredited_scopes (accreditation_id, accreditation_standard, "
                + "certification_standard, ea_code, status, scope_note) VALUES (?, ?, ?, ?, ?, ?)", inserts);
        jdbc.batchUpdate("UPDATE accredited_scopes SET status = ?, scope_note = ? WHERE id = ?", updates);
    }

    /** Flattens SQL parameters; Object[] parts are spread in place. */
    private static Object[] flat(Object... parts) {
        List<Object> out = new ArrayList<>();
        for (Object part : parts) {
            if (part instanceof Object[] array) out.addAll(Arrays.asList(array));
            else out.add(part);
        }
        return out.toArray();
    }
}
