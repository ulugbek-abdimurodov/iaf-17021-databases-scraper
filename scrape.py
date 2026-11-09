#!/usr/bin/env python3
"""Unified CLI runner for ISO/IEC 17021-1 National Accreditation Registry Scrapers.

Download and convert ISO/IEC 17021-1 (Management Systems Certification Bodies)
accreditation databases across 38 countries with a single command.

Examples:
    python scrape.py --list
    python scrape.py germany
    python scrape.py armenia greece turkey --prepare
    python scrape.py uk --prepare-only --datasets-dir ./datasets
    python scrape.py turkey -- --limit 3
    python scrape.py --all
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_DATASETS_DIR = (
    ROOT.parent / "certifind" / "data"
    if (ROOT.parent / "certifind" / "data").exists()
    else ROOT / "datasets"
)


@dataclass(frozen=True)
class CountryEntry:
    folder: str
    country: str
    iso2: str
    ab_code: str
    ab_name: str
    registry_url: str
    dataset_id: str
    scraper_script: str | None = None
    scraper_default_args: tuple[str, ...] = ()
    prepare_script: str | None = None
    prepare_mode: str = "positional"  # "positional" | "data_out" | "input_dataset" | "src_out" | "out_only" | "romania"
    scrape_dir: str = "output"
    aliases: tuple[str, ...] = field(default_factory=tuple)


REGISTRY: tuple[CountryEntry, ...] = (
    CountryEntry(
        folder="albania",
        country="Albania",
        iso2="AL",
        ab_code="DPA",
        ab_name="General Directorate of Accreditation (Drejtoria e Përgjithshme e Akreditimit)",
        registry_url="https://dpa.gov.al/organe-te-akredituara/",
        dataset_id="dpa-albania",
        scraper_script="dpa_scraper.py",
        scrape_dir="dpa_output",
    ),
    CountryEntry(
        folder="algeria",
        country="Algeria",
        iso2="DZ",
        ab_code="ALGERAC",
        ab_name="Organisme Algérien d'Accréditation",
        registry_url="https://algerac.dz/organismes-de-certification/",
        dataset_id="algerac-algeria",
    ),
    CountryEntry(
        folder="armenia",
        country="Armenia",
        iso2="AM",
        ab_code="ARMNAB",
        ab_name="National Accreditation Body of Armenia",
        registry_url="https://armnab.am/management-systems",
        dataset_id="armnab-armenia",
        scraper_script="armnab_scraper.py",
        scraper_default_args=("--download-docs",),
        prepare_script="prepare_certifind.py",
        prepare_mode="input_dataset",
        scrape_dir="output",
    ),
    CountryEntry(
        folder="austria",
        country="Austria",
        iso2="AT",
        ab_code="AA",
        ab_name="Akkreditierung Austria",
        registry_url="https://akkreditierung-austria.gv.at",
        dataset_id="aa-austria",
        scraper_script="scrape_akkreditierung_austria.py",
        prepare_script="prepare_certifind.py",
        prepare_mode="positional",
        scrape_dir="akkreditierung_output",
    ),
    CountryEntry(
        folder="belgium",
        country="Belgium",
        iso2="BE",
        ab_code="BELAC",
        ab_name="Belgian Accreditation Body",
        registry_url="https://weblist.economie.fgov.be/en/belac/list/qms",
        dataset_id="belac-belgium",
        scraper_script="belac_qms_scraper.py",
        prepare_script="prepare_certifind.py",
        prepare_mode="positional",
        scrape_dir="belac_qms_data",
    ),
    CountryEntry(
        folder="bosnia",
        country="Bosnia and Herzegovina",
        iso2="BA",
        ab_code="BATA",
        ab_name="Institute for Accreditation of Bosnia and Herzegovina",
        registry_url="https://www.bata.gov.ba",
        dataset_id="bata-bosnia",
        aliases=("bih", "bosnia-herzegovina"),
    ),
    CountryEntry(
        folder="bulgaria",
        country="Bulgaria",
        iso2="BG",
        ab_code="BAS",
        ab_name="Executive Agency Bulgarian Accreditation Service",
        registry_url="https://nab-bas.bg",
        dataset_id="bas-bulgaria",
        scraper_script="nab_scraper.py",
        prepare_script="prepare_certifind.py",
        prepare_mode="data_out",
        scrape_dir="nab_management_system_bodies",
    ),
    CountryEntry(
        folder="croatia",
        country="Croatia",
        iso2="HR",
        ab_code="HAA",
        ab_name="Croatian Accreditation Agency",
        registry_url="https://akreditacija.gov.hr/frontend/registar-akreditacija",
        dataset_id="haa-croatia",
        scraper_script="haa_scraper.py",
        prepare_script="prepare_certifind.py",
        prepare_mode="data_out",
        scrape_dir="haa_data",
    ),
    CountryEntry(
        folder="czechia",
        country="Czechia",
        iso2="CZ",
        ab_code="CAI",
        ab_name="Czech Accreditation Institute (ČIA)",
        registry_url="https://www.cai.cz",
        dataset_id="cai-czechia",
        scraper_script="cai_scraper.py",
        prepare_script="prepare_certifind.py",
        prepare_mode="positional",
        scrape_dir="cai_output",
        aliases=("czech-republic", "cia"),
    ),
    CountryEntry(
        folder="denmark",
        country="Denmark",
        iso2="DK",
        ab_code="DANAK",
        ab_name="The Danish Accreditation Fund",
        registry_url="https://registry.danak.dk",
        dataset_id="danak-denmark",
        scraper_script="danak_ms_scraper.py",
        prepare_script="prepare_certifind.py",
        prepare_mode="positional",
        scrape_dir="danak_ms_output",
    ),
    CountryEntry(
        folder="egypt",
        country="Egypt",
        iso2="EG",
        ab_code="EGAC",
        ab_name="Egyptian Accreditation Council",
        registry_url="https://egac.gov.eg/en/accredited-cabs/",
        dataset_id="egac-egypt",
        scraper_script="egac_ms_scraper.py",
        prepare_script="prepare_certifind.py",
        prepare_mode="data_out",
        scrape_dir="egac_ms_bodies",
    ),
    CountryEntry(
        folder="estonia",
        country="Estonia",
        iso2="EE",
        ab_code="EAK",
        ab_name="Estonian Accreditation Centre",
        registry_url="https://www.eak.ee",
        dataset_id="eak-estonia",
        scraper_script="eak_scraper.py",
        prepare_script="prepare_certifind.py",
        prepare_mode="positional",
        scrape_dir="eak_data",
    ),
    CountryEntry(
        folder="finland",
        country="Finland",
        iso2="FI",
        ab_code="FINAS",
        ab_name="Finnish Accreditation Service",
        registry_url="https://www.finas.fi/sites/en/operators/Pages/default.aspx",
        dataset_id="finas-finland",
        scraper_script="scrape_fi_finas.py",
        prepare_script="prepare_certifind.py",
        prepare_mode="positional",
        scrape_dir="fi_ms_output",
    ),
    CountryEntry(
        folder="france",
        country="France",
        iso2="FR",
        ab_code="COFRAC",
        ab_name="Comité Français d'Accréditation",
        registry_url="https://tools.cofrac.fr/en/easysearch",
        dataset_id="cofrac-france",
        scraper_script="cofrac_ms_scraper.py",
        scrape_dir="cofrac_ms_output",
    ),
    CountryEntry(
        folder="germany",
        country="Germany",
        iso2="DE",
        ab_code="DAkkS",
        ab_name="Deutsche Akkreditierungsstelle",
        registry_url="https://www.dakks.de/en/accredited-bodies-search.html",
        dataset_id="dakks-germany",
        scraper_script="dakks_scraper.py",
        prepare_script="prepare_certifind.py",
        prepare_mode="positional",
        scrape_dir="dakks_ZM",
    ),
    CountryEntry(
        folder="greece",
        country="Greece",
        iso2="GR",
        ab_code="ESYD",
        ab_name="Hellenic Accreditation System",
        registry_url="http://www.esydops.gr/portal/p/esyd/en/",
        dataset_id="esyd-greece",
        scraper_script="esyd_scraper.py",
        scraper_default_args=("--download-docs", "en"),
        prepare_script="prepare_certifind.py",
        prepare_mode="data_out",
        scrape_dir="output",
    ),
    CountryEntry(
        folder="hungary",
        country="Hungary",
        iso2="HU",
        ab_code="NAH",
        ab_name="National Accreditation Authority (Nemzeti Akkreditáló Hatóság)",
        registry_url="https://www.nah.gov.hu",
        dataset_id="nah-hungary",
        scraper_script="nah_scraper.py",
        prepare_script="prepare_certifind.py",
        prepare_mode="positional",
        scrape_dir="nah_output",
    ),
    CountryEntry(
        folder="india",
        country="India",
        iso2="IN",
        ab_code="NABCB",
        ab_name="National Accreditation Board for Certification Bodies",
        registry_url="https://nabcb.qci.org.in",
        dataset_id="nabcb-india",
        scraper_script="nabcb_ms_scraper.py",
        prepare_script="prepare_certifind.py",
        prepare_mode="data_out",
        scrape_dir="nabcb_output",
    ),
    CountryEntry(
        folder="ireland",
        country="Ireland",
        iso2="IE",
        ab_code="INAB",
        ab_name="Irish National Accreditation Board",
        registry_url="https://www.inab.ie",
        dataset_id="inab-ireland",
        scraper_script="inab_scraper.py",
        prepare_script="prepare_certifind.py",
        prepare_mode="positional",
        scrape_dir="inab_output",
    ),
    CountryEntry(
        folder="italy",
        country="Italy",
        iso2="IT",
        ab_code="ACCREDIA",
        ab_name="L'Ente Italiano di Accreditamento",
        registry_url="https://services.accredia.it/ppsearch/accredia_orgmask.jsp?ID_LINK=1733&area=310",
        dataset_id="accredia-italy",
        scraper_script="accredia_collector.py",
        scrape_dir="accredia_output",
    ),
    CountryEntry(
        folder="latvia",
        country="Latvia",
        iso2="LV",
        ab_code="LATAK",
        ab_name="Latvian National Accreditation Bureau",
        registry_url="https://www.latak.gov.lv",
        dataset_id="latak-latvia",
        scraper_script="latak_s2_scraper.py",
        prepare_script="prepare_certifind.py",
        prepare_mode="data_out",
        scrape_dir="latak_S2",
    ),
    CountryEntry(
        folder="lithuania",
        country="Lithuania",
        iso2="LT",
        ab_code="LASA",
        ab_name="Lithuanian National Accreditation Bureau (NAB)",
        registry_url="http://db.nab.lt/ais/accreditation",
        dataset_id="lasa-lithuania",
        scraper_script="nab_scraper.py",
        prepare_script="prepare_certifind.py",
        prepare_mode="src_out",
        scrape_dir="nab_ms_bodies",
        aliases=("nab",),
    ),
    CountryEntry(
        folder="luxembourg",
        country="Luxembourg",
        iso2="LU",
        ab_code="OLAS",
        ab_name="Office Luxembourgeois d'Accréditation et de Surveillance",
        registry_url="https://portail-qualite.public.lu",
        dataset_id="olas-luxembourg",
        scraper_script="olas_17021_scraper.py",
        prepare_script="prepare_certifind.py",
        prepare_mode="positional",
        scrape_dir="olas_17021",
    ),
    CountryEntry(
        folder="macedonia",
        country="North Macedonia",
        iso2="MK",
        ab_code="IARM",
        ab_name="Institute for Accreditation of the Republic of North Macedonia",
        registry_url="https://iarm.gov.mk",
        dataset_id="iarm-north-macedonia",
        scraper_script="iarm_scraper.py",
        prepare_script="prepare_certifind.py",
        prepare_mode="data_out",
        scrape_dir="iarm_cb_management",
        aliases=("north-macedonia",),
    ),
    CountryEntry(
        folder="moldova",
        country="Moldova",
        iso2="MD",
        ab_code="MOLDAC",
        ab_name="National Accreditation Centre of the Republic of Moldova",
        registry_url="https://www.acreditare.md",
        dataset_id="moldac-moldova",
    ),
    CountryEntry(
        folder="netherlands",
        country="Netherlands",
        iso2="NL",
        ab_code="RvA",
        ab_name="Dutch Accreditation Council (Raad voor Accreditatie)",
        registry_url="https://www.rva.nl",
        dataset_id="rva-netherlands",
        scraper_script="rva_scraper.py",
        prepare_script="prepare_certifind.py",
        prepare_mode="positional",
        scrape_dir="rva_output",
        aliases=("holland",),
    ),
    CountryEntry(
        folder="norway",
        country="Norway",
        iso2="NO",
        ab_code="NA",
        ab_name="Norsk Akkreditering",
        registry_url="https://www.akkreditert.no/en/akkrediterte-organisasjoner/?scope=SysCert",
        dataset_id="na-norway",
        scraper_script="no_ms_scraper.py",
        prepare_script="prepare_certifind.py",
        prepare_mode="positional",
        scrape_dir="no_ms_output",
    ),
    CountryEntry(
        folder="poland",
        country="Poland",
        iso2="PL",
        ab_code="PCA",
        ab_name="Polish Centre for Accreditation (Polskie Centrum Akredytacji)",
        registry_url="https://www.pca.gov.pl",
        dataset_id="pca-poland",
        scraper_script="pca_scraper.py",
        prepare_script="prepare_certifind.py",
        prepare_mode="positional",
        scrape_dir="pca_ac_bodies",
    ),
    CountryEntry(
        folder="portugal",
        country="Portugal",
        iso2="PT",
        ab_code="IPAC",
        ab_name="Portuguese Institute for Accreditation (Instituto Português de Acreditação)",
        registry_url="https://www.ipac.pt",
        dataset_id="ipac-portugal",
        scraper_script="ipac_scraper.py",
        prepare_script="prepare_certifind.py",
        prepare_mode="positional",
        scrape_dir="ipac_data",
    ),
    CountryEntry(
        folder="romania",
        country="Romania",
        iso2="RO",
        ab_code="RENAR",
        ab_name="Romanian Accreditation Association (Asociația de Acreditare din România)",
        registry_url="https://www.renar.ro/index.php/oec",
        dataset_id="renar-romania",
        scraper_script="scraper.py",
        prepare_script="extract_renar_v2.py",
        prepare_mode="romania",
        scrape_dir="output",
    ),
    CountryEntry(
        folder="serbia",
        country="Serbia",
        iso2="RS",
        ab_code="ATS",
        ab_name="Accreditation Body of Serbia",
        registry_url="https://www.ats.rs",
        dataset_id="ats-serbia",
        prepare_script="prepare_certifind.py",
        prepare_mode="out_only",
        scrape_dir=".",
    ),
    CountryEntry(
        folder="slovakia",
        country="Slovakia",
        iso2="SK",
        ab_code="SNAS",
        ab_name="Slovak National Accreditation Service",
        registry_url="https://ais.snas.sk/web-report",
        dataset_id="snas-slovakia",
        scraper_script="snas_scraper.py",
        prepare_script="prepare_certifind.py",
        prepare_mode="positional",
        scrape_dir="snas_output",
    ),
    CountryEntry(
        folder="sweden",
        country="Sweden",
        iso2="SE",
        ab_code="SWEDAC",
        ab_name="Swedish Board for Accreditation and Conformity Assessment",
        registry_url="https://ackrediteringar.swedac.se/en",
        dataset_id="swedac-sweden",
        scraper_script="swedac_ms_scraper.py",
        prepare_script="prepare_certifind.py",
        prepare_mode="positional",
        scrape_dir="se_ms_output",
    ),
    CountryEntry(
        folder="switzerland",
        country="Switzerland",
        iso2="CH",
        ab_code="SAS",
        ab_name="Swiss Accreditation Service",
        registry_url="https://www.sas.admin.ch",
        dataset_id="sas-switzerland",
        scraper_script="sas_scraper.py",
        prepare_script="prepare_certifind.py",
        prepare_mode="positional",
        scrape_dir="sas_data/SCESm",
    ),
    CountryEntry(
        folder="tunisia",
        country="Tunisia",
        iso2="TN",
        ab_code="TUNAC",
        ab_name="Tunisian Accreditation Council (Conseil National d'Accréditation)",
        registry_url="https://www.tunac.tn",
        dataset_id="tunac-tunisia",
        scraper_script="tunac_scraper.py",
        scrape_dir="tunac_data",
    ),
    CountryEntry(
        folder="turkey",
        country="Turkey",
        iso2="TR",
        ab_code="TURKAK",
        ab_name="Turkish Accreditation Agency (Türk Akreditasyon Kurumu)",
        registry_url="https://asist.turkak.org.tr/en/accreditation/accreditationagencysearch?institutionType=YS",
        dataset_id="turkak-turkey",
        scraper_script="turkak_scraper.py",
        prepare_script="prepare_certifind.py",
        prepare_mode="data_out",
        scrape_dir="turkak_data",
        aliases=("turkiye",),
    ),
    CountryEntry(
        folder="uk",
        country="United Kingdom",
        iso2="GB",
        ab_code="UKAS",
        ab_name="United Kingdom Accreditation Service",
        registry_url="https://www.ukas.com",
        dataset_id="ukas-united-kingdom",
        scraper_script="ukas_ms_scraper.py",
        prepare_script="prepare_certifind.py",
        prepare_mode="positional",
        scrape_dir="ukas_ms_data",
        aliases=("united-kingdom", "great-britain", "gb"),
    ),
    CountryEntry(
        folder="ukraine",
        country="Ukraine",
        iso2="UA",
        ab_code="NAAU",
        ab_name="National Accreditation Agency of Ukraine",
        registry_url="https://naau.org.ua",
        dataset_id="naau-ukraine",
        scraper_script="naau_ms_scraper.py",
        prepare_script="prepare_certifind.py",
        prepare_mode="data_out",
        scrape_dir="naau_ms_certification_bodies",
    ),
)


def resolve_country(query: str) -> CountryEntry:
    q = query.strip().lower()
    for entry in REGISTRY:
        keys = {
            entry.folder.lower(),
            entry.country.lower(),
            entry.iso2.lower(),
            entry.ab_code.lower(),
            entry.dataset_id.lower(),
            *(a.lower() for a in entry.aliases),
        }
        if q in keys:
            return entry
    raise SystemExit(
        f"Unknown country/accreditation body '{query}'. Run `python scrape.py --list` to see all supported targets."
    )


def print_registry() -> None:
    header = f"{'Folder':<14} {'ISO':<4} {'AB Code':<9} {'Country':<22} {'Scraper':<34} {'Converter':<22} {'Dataset ID'}"
    print(header)
    print("-" * len(header))
    for e in REGISTRY:
        scraper = e.scraper_script or "(manual PDFs)"
        converter = e.prepare_script or "-"
        print(
            f"{e.folder:<14} {e.iso2:<4} {e.ab_code:<9} {e.country:<22} "
            f"{scraper:<34} {converter:<22} {e.dataset_id}"
        )
    active_scrapers = sum(1 for e in REGISTRY if e.scraper_script)
    active_converters = sum(1 for e in REGISTRY if e.prepare_script)
    print("-" * len(header))
    print(
        f"Total: {len(REGISTRY)} countries | {active_scrapers} automated scrapers | {active_converters} dataset converters"
    )


def build_prepare_cmd(entry: CountryEntry, datasets_dir: Path) -> list[str]:
    assert entry.prepare_script is not None
    country_dir = ROOT / entry.folder
    script_path = country_dir / entry.prepare_script
    out_dir = (datasets_dir / entry.dataset_id).resolve()
    scrape_path = (country_dir / entry.scrape_dir).resolve()

    if entry.prepare_mode == "positional":
        return [sys.executable, str(script_path), str(scrape_path), str(out_dir)]
    if entry.prepare_mode == "data_out":
        return [sys.executable, str(script_path), "--data", str(scrape_path), "--out", str(out_dir)]
    if entry.prepare_mode == "input_dataset":
        return [sys.executable, str(script_path), "--input", str(scrape_path), "--dataset", str(out_dir)]
    if entry.prepare_mode == "src_out":
        return [sys.executable, str(script_path), "--src", str(scrape_path / "bodies.json"), "--out", str(out_dir)]
    if entry.prepare_mode == "out_only":
        return [sys.executable, str(script_path), "--out", str(out_dir)]
    if entry.prepare_mode == "romania":
        return [sys.executable, str(script_path)]
    raise ValueError(f"Unsupported prepare_mode: {entry.prepare_mode}")


def run_step(label: str, cmd: list[str], cwd: Path, dry_run: bool = False) -> int:
    rel_cwd = cwd.relative_to(ROOT) if cwd != ROOT else Path(".")
    cmd_str = " ".join(f'"{c}"' if " " in c else c for c in cmd)
    print(f"\n==> [{label}] (cwd: {rel_cwd})")
    print(f"    $ {cmd_str}")
    if dry_run:
        return 0
    t0 = time.monotonic()
    proc = subprocess.run(cmd, cwd=cwd)
    elapsed = time.monotonic() - t0
    status = "OK" if proc.returncode == 0 else f"FAILED (exit {proc.returncode})"
    print(f"<== [{label}] {status} in {elapsed:.1f}s")
    return proc.returncode


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    extra_scraper_args: list[str] = []
    if "--" in raw_argv:
        idx = raw_argv.index("--")
        extra_scraper_args = raw_argv[idx + 1 :]
        raw_argv = raw_argv[:idx]

    parser = argparse.ArgumentParser(
        description="Unified one-command scraper & dataset converter for ISO/IEC 17021-1 accreditation registries.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "targets",
        nargs="*",
        help="Country names, folder names, ISO codes, or accreditation body codes (e.g., germany, uk, turkak, esyd).",
    )
    parser.add_argument(
        "-l",
        "--list",
        action="store_true",
        help="List all 38 supported countries, accreditation bodies, and scripts.",
    )
    parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="Run all available country scrapers.",
    )
    parser.add_argument(
        "-p",
        "--prepare",
        action="store_true",
        help="Also run prepare_certifind.py after scraping to generate normalized CSV datasets.",
    )
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Skip scraping and only run the dataset converter (prepare_certifind.py) on existing scraped outputs.",
    )
    parser.add_argument(
        "--datasets-dir",
        type=Path,
        default=DEFAULT_DATASETS_DIR,
        help=f"Output root directory for converted CertiFind datasets (default: {DEFAULT_DATASETS_DIR}).",
    )
    parser.add_argument(
        "--prune",
        nargs="+",
        type=Path,
        metavar="DATASET_DIR",
        help="Run prune_inactive.py on one or more dataset folders to remove inactive/expired bodies.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the commands that would be executed without running them.",
    )

    args = parser.parse_args(raw_argv)

    if args.list:
        print_registry()
        return 0

    if args.prune:
        prune_cmd = [sys.executable, str(ROOT / "prune_inactive.py"), *(str(p) for p in args.prune)]
        return run_step("prune_inactive", prune_cmd, ROOT, dry_run=args.dry_run)

    if args.all:
        entries = [
            e
            for e in REGISTRY
            if (e.prepare_script if args.prepare_only else e.scraper_script)
        ]
    elif args.targets:
        entries = [resolve_country(t) for t in args.targets]
    else:
        parser.print_help()
        return 0

    failures: list[str] = []
    for entry in entries:
        country_dir = ROOT / entry.folder
        if not args.prepare_only:
            if not entry.scraper_script:
                print(
                    f"\n[SKIP] {entry.country} ({entry.ab_code}): no automated web scraper "
                    f"(uses local source documents in `{entry.folder}/`)."
                )
            else:
                scraper_path = country_dir / entry.scraper_script
                cmd = [
                    sys.executable,
                    str(scraper_path),
                    *(extra_scraper_args if extra_scraper_args else entry.scraper_default_args),
                ]
                rc = run_step(f"{entry.country} ({entry.ab_code}) - scrape", cmd, country_dir, dry_run=args.dry_run)
                if rc != 0:
                    failures.append(f"{entry.folder}:scrape")
                    continue

        if args.prepare or args.prepare_only:
            if not entry.prepare_script:
                print(f"\n[SKIP] {entry.country} ({entry.ab_code}): no prepare_certifind.py converter configured.")
            else:
                prep_cmd = build_prepare_cmd(entry, args.datasets_dir.resolve())
                rc = run_step(f"{entry.country} ({entry.ab_code}) - prepare", prep_cmd, country_dir, dry_run=args.dry_run)
                if rc != 0:
                    failures.append(f"{entry.folder}:prepare")

    if failures:
        print(f"\nCompleted with {len(failures)} failure(s): {', '.join(failures)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
