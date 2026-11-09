package com.certifind.importer;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.stream.Stream;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Component;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * Runs with the "import" profile: reads every dataset under certifind.import.paths,
 * validates all of them, then loads them in a single transaction (all or nothing).
 * With certifind.import.dry-run=true it reports what would change and rolls back.
 */
@Component
@Profile("import")
public class ImportRunner implements ApplicationRunner {

    private static final Logger log = LoggerFactory.getLogger(ImportRunner.class);

    private final CsvImporter importer;
    private final TransactionTemplate transaction;
    private final List<String> paths;
    private final boolean dryRun;

    public ImportRunner(CsvImporter importer, TransactionTemplate transaction,
                        @Value("${certifind.import.paths:../data}") List<String> paths,
                        @Value("${certifind.import.dry-run:false}") boolean dryRun) {
        this.importer = importer;
        this.transaction = transaction;
        this.paths = paths;
        this.dryRun = dryRun;
    }

    @Override
    public void run(ApplicationArguments args) throws IOException {
        DatasetReader reader = new DatasetReader();
        List<Dataset> datasets = new ArrayList<>();
        for (Path dir : datasetDirs()) {
            datasets.add(reader.read(dir));
        }
        if (datasets.isEmpty()) {
            throw new IllegalStateException("No dataset folders (containing bodies.csv) found under " + paths);
        }
        List<String> errors = new ArrayList<>(reader.errors());

        transaction.executeWithoutResult(tx -> {
            if (errors.isEmpty()) {
                datasets.forEach(ds -> errors.addAll(importer.validate(ds)));
            }
            if (!errors.isEmpty()) {
                tx.setRollbackOnly();
                return;
            }
            for (Dataset ds : datasets) {
                log.info("{} {}:\n{}", dryRun ? "Would load" : "Loaded", ds.name(), importer.load(ds));
            }
            if (dryRun) tx.setRollbackOnly();
        });

        if (!errors.isEmpty()) {
            throw new IllegalStateException(errors.size() + " problem(s), nothing was imported:\n  "
                    + String.join("\n  ", errors));
        }
        log.info(dryRun ? "Dry run: rolled back, database unchanged." : "Import committed.");
    }

    /** Each path is a dataset folder itself, or a parent whose sub-folders are datasets. */
    private List<Path> datasetDirs() throws IOException {
        List<Path> dirs = new ArrayList<>();
        for (String p : paths) {
            Path path = Path.of(p.strip()).toAbsolutePath().normalize();
            if (Files.isRegularFile(path.resolve("bodies.csv"))) {
                dirs.add(path);
            } else if (Files.isDirectory(path)) {
                try (Stream<Path> children = Files.list(path)) {
                    children.filter(c -> Files.isRegularFile(c.resolve("bodies.csv"))).sorted().forEach(dirs::add);
                }
            } else {
                throw new IllegalStateException("Import path does not exist: " + path);
            }
        }
        return dirs;
    }
}
