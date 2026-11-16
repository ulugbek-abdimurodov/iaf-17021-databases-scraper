#!/usr/bin/env python3
"""Run every country's scraper and CertiFind generator to build / update ../certifind/data.

Each country is a list of steps. A "scrape" step downloads the register again; a "prepare"
step turns the saved scrape into bodies.csv / accreditations.csv / scopes.csv. Every step runs
in its own folder (so relative output folders land where the prepare step expects them).
Countries whose register can only be read from a browser have no scrape step: their prepare
step rebuilds the dataset from the snapshot that is already saved.

Usage:
    python run_all.py                        # scrape + prepare every country
    python run_all.py germany france         # only these countries
    python run_all.py --skip-scrape          # rebuild datasets from saved scrapes only
    python run_all.py --only-scrape          # download only
    python run_all.py --list                 # show countries and their steps
    python run_all.py --dry-run              # print the commands without running them
    python run_all.py --exclude india uk     # everything except these
    python run_all.py --timeout 3600         # per-step limit in seconds (default: none)

A failing step is logged and the country's later steps are skipped; other countries continue.
Logs go to logs/<run time>/<country>.log; a summary is printed at the end. Exit code 1 if
anything failed.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = (HERE.parent / "certifind" / "data").resolve()
TODAY = date.today().isoformat()
PY = sys.executable


def scrape(script, *args, cwd=None):
    return ("scrape", script, list(args), cwd)


def prepare(script, *args, cwd=None):
    return ("prepare", script, list(args), cwd)


def copy(src, dataset):
    """Copy a dataset that a generator wrote inside its own package into certifind/data."""
    return ("copy", src, [dataset], None)


# Paths are relative to this folder; "{DATA}" is certifind/data, "{TODAY}" is today's date.
# A step runs in its script's folder unless cwd= says otherwise.
PIPELINES: dict[str, list] = {
    "armenia": [scrape("armenia/armnab_scraper.py"), prepare("armenia/prepare_certifind.py")],
    "australia": [
        scrape("australia/database/australia/scrape_au_jasanz.py"),
        prepare("australia/database/australia/prepare_certifind.py", ".", "{DATA}/jasanz-australia"),
    ],
    "austria": [
        scrape("austria/scrape_akkreditierung_austria.py"),
        prepare("austria/prepare_certifind.py", "akkreditierung_output", "{DATA}/aa-austria"),
    ],
    "bahrain-gcc": [
        scrape("bahrain/database/gcc/scrape_gcc_gac.py"),
        prepare("bahrain/database/gcc/prepare_certifind.py", "{DATA}/gac-saudi-arabia"),
    ],
    "belgium": [
        scrape("belgium/belac_qms_scraper.py"),
        prepare("belgium/prepare_certifind.py", "belac_qms_data", "{DATA}/belac-belgium"),
    ],
    "bulgaria": [
        scrape("bulgaria/nab_scraper.py"),
        prepare("bulgaria/prepare_certifind.py", "--out", "{DATA}/bas-bulgaria"),
    ],
    "canada": [  # scc-ccn.ca: browser-only, rebuilt from scc_raw.tsv
        prepare("canada/prepare_certifind.py", ".", "{DATA}/scc-canada"),
    ],
    "chile": [  # directorio.inn.cl: browser-only
        prepare("chile/prepare_certifind.py", "database/chile", "{DATA}/inn-chile"),
    ],
    "colombia": [  # onac.org.co: browser-only
        prepare("colombia/prepare_certifind.py", "database/colombia/onac_raw.tsv", "{DATA}/onac-colombia"),
    ],
    "costa-rica": [  # eca.or.cr: browser-only
        prepare("costa-rica/prepare_certifind.py", "database/costa_rica", "{DATA}/eca-costa-rica"),
    ],
    "croatia": [scrape("croatia/haa_scraper.py"), prepare("croatia/prepare_certifind.py")],
    "czechia": [
        scrape("czechia/cai_scraper.py"),
        prepare("czechia/prepare_certifind.py", "cai_output", "{DATA}/cai-czechia"),
    ],
    "denmark": [
        scrape("denmark/danak_ms_scraper.py"),
        prepare("denmark/prepare_certifind.py", "danak_ms_output", "{DATA}/danak-denmark"),
    ],
    "ecuador": [
        scrape("ecuador/database/ecuador/scrape_ec_sae.py"),
        prepare("ecuador/database/ecuador/prepare_certifind.py", "{DATA}/sae-ecuador"),
    ],
    "egypt": [scrape("egypt/egac_ms_scraper.py"), prepare("egypt/prepare_certifind.py")],
    "estonia": [
        scrape("estonia/eak_scraper.py"),
        prepare("estonia/prepare_certifind.py", "eak_data", "{DATA}/eak-estonia"),
    ],
    "ethiopia": [  # eas-eth.org: browser-only
        prepare("ethiopia/prepare_certifind.py", "{DATA}/eas-ethiopia"),
    ],
    "finland": [
        scrape("finland/scrape_fi_finas.py"),
        prepare("finland/prepare_certifind.py", "fi_ms_output", "{DATA}/finas-finland"),
    ],
    "france": [
        scrape("france/cofrac_ms_scraper.py"),
        prepare("france/prepare_certifind.py", "cofrac_ms_output", "{DATA}/cofrac-france"),
    ],
    "germany": [
        scrape("germany/dakks_scraper.py"),
        prepare("germany/prepare_certifind.py", "dakks_ZM", "{DATA}/dakks-germany"),
    ],
    "greece": [
        scrape("greece/esyd_scraper.py"),
        prepare("greece/prepare_certifind.py", "--out", "{DATA}/esyd-greece"),
    ],
    "hungary": [
        scrape("hungary/nah_scraper.py"),
        prepare("hungary/prepare_certifind.py", "nah_output", "{DATA}/nah-hungary"),
    ],
    "india": [scrape("india/nabcb_ms_scraper.py"), prepare("india/prepare_certifind.py")],
    "ireland": [
        scrape("ireland/inab_scraper.py"),
        prepare("ireland/prepare_certifind.py", "inab_output", "{DATA}/inab-ireland"),
    ],
    "italy": [  # services.accredia.it: browser-only
        prepare("italy/prepare_certifind.py", ".", "{DATA}/accredia-italy"),
    ],
    "japan-jab": [
        scrape("japan/certifind_jab_japan/database/japan/scrape_jp_jab.py"),
        prepare("japan/certifind_jab_japan/database/japan/prepare_certifind.py"),
        copy("japan/certifind_jab_japan/data/jab-japan", "jab-japan"),
    ],
    "japan-isms-ac": [
        scrape("japan/isms-ac-japan/database/japan/scrape_jp_isms-ac.py"),
        prepare("japan/isms-ac-japan/database/japan/prepare_certifind.py"),
        copy("japan/isms-ac-japan/data/isms-ac-japan", "isms-ac-japan"),
    ],
    "kazakhstan": [
        scrape("kazakhstan/database/kazakhstan/scrape_kz_nca.py", "--out", "raw", cwd="kazakhstan"),
        prepare("kazakhstan/database/kazakhstan/prepare_certifind.py"),
        copy("kazakhstan/data/nca-kazakhstan", "nca-kazakhstan"),
    ],
    "kenya": [
        scrape("kenya/database/kenya/scrape_ke_kenas.py"),
        prepare("kenya/prepare_certifind.py", "database/kenya", "{DATA}/kenas-kenya"),
    ],
    "korea": [
        scrape("korea/scrape_kr_kab.py"),
        prepare("korea/prepare_certifind.py", "kab_raw.txt", "{DATA}/kab-south-korea"),
    ],
    "latvia": [scrape("latvia/latak_s2_scraper.py"), prepare("latvia/prepare_certifind.py")],
    "lithuania": [
        scrape("lithuania/nab_scraper.py"),
        prepare("lithuania/prepare_certifind.py", "--out", "{DATA}/lasa-lithuania"),
    ],
    "luxembourg": [
        scrape("luxembourg/olas_17021_scraper.py"),
        prepare("luxembourg/prepare_certifind.py", "olas_17021", "{DATA}/olas-luxembourg"),
    ],
    "macedonia": [scrape("macedonia/iarm_scraper.py"), prepare("macedonia/prepare_certifind.py")],
    "malaysia": [
        scrape("malaysia/jsm_certifind/database/malaysia/scrape_my_jsm.py"),
        prepare("malaysia/prepare_certifind.py", "jsm_certifind/data/jsm-malaysia", "{DATA}/jsm-malaysia"),
    ],
    "mauritius": [
        scrape("mauritius/scrape_mu_mauritas.py"),
        prepare("mauritius/prepare_certifind.py"),
        copy("mauritius/data/mauritas-mauritius", "mauritas-mauritius"),
    ],
    "mexico": [
        scrape("mexico/database/mexico/scrape_mx_ema.py"),
        prepare("mexico/prepare_certifind.py", "database/mexico", "{DATA}/ema-mexico"),
    ],
    "mongolia": [
        scrape("mongolia/scrape_mn_mnas.py"),
        prepare("mongolia/prepare_certifind.py", "raw_mnas.json", "{DATA}/mnas-mongolia"),
    ],
    "netherlands": [
        scrape("netherlands/rva_scraper.py"),
        prepare("netherlands/prepare_certifind.py", "rva_output", "{DATA}/rva-netherlands"),
    ],
    "norway": [
        scrape("norway/no_ms_scraper.py"),
        prepare("norway/prepare_certifind.py", "no_ms_output", "{DATA}/na-norway"),
    ],
    "pakistan": [prepare("pakistan/prepare_certifind.py")],  # PDFs saved by hand
    "poland": [
        scrape("poland/pca_scraper.py"),
        prepare("poland/prepare_certifind.py", "pca_ac_bodies", "{DATA}/pca-poland"),
    ],
    "portugal": [scrape("portugal/ipac_scraper.py"), prepare("portugal/prepare_certifind.py")],
    "saudi-arabia": [
        scrape("saudi-arabia/database/saudi-arabia/scrape_sa_saac.py"),
        prepare("saudi-arabia/prepare_certifind.py", "database", "{DATA}/saac-saudi-arabia"),
    ],
    "serbia": [prepare("serbia/prepare_certifind.py", "--out", "{DATA}/ats-serbia")],  # register saved by hand
    "slovakia": [
        scrape("slovakia/snas_scraper.py"),
        prepare("slovakia/prepare_certifind.py", "snas_output", "{DATA}/snas-slovakia"),
    ],
    "south-africa": [  # sanas.co.za: browser-only
        prepare("south africa/prepare_certifind.py", "database/south-africa", "{DATA}/sanas-south-africa"),
    ],
    "sri-lanka": [
        scrape("sri-lanka/database/sri_lanka/scrape_lk_slab.py"),
        prepare("sri-lanka/prepare_certifind.py", ".", "{DATA}/slab-sri-lanka"),
    ],
    "spain": [
        scrape("spain/database/spain/scrape_es_enac.py"),
        prepare("spain/database/spain/prepare_certifind.py"),
        copy("spain/data/enac-spain", "enac-spain"),
    ],
    "sweden": [
        scrape("sweden/swedac_ms_scraper.py"),
        prepare("sweden/prepare_certifind.py", "se_ms_output", "{DATA}/swedac-sweden"),
    ],
    "switzerland": [
        scrape("switzerland/sas_scraper.py"),
        prepare("switzerland/prepare_certifind.py", "sas_data", "{DATA}/sas-switzerland"),
    ],
    "taiwan": [
        scrape("taiwan/scrape_tw_taf.py"),
        prepare("taiwan/prepare_certifind.py", ".", "{DATA}/taf-taiwan"),
    ],
    "thailand": [  # center.tisi.go.th: browser-only
        prepare("thailand/prepare_certifind.py", "v3", "{DATA}/tisi-thailand"),
    ],
    "turkey": [
        scrape("turkey/turkak_scraper.py"),
        prepare("turkey/prepare_certifind.py", "--out", "{DATA}/turkak-turkey"),
    ],
    "uae": [  # eiac.gov.ae: browser-only
        prepare("uae/database/uae/prepare_certifind.py"),
        prepare("uae/finalize_certifind.py", "{DATA}", "--today", "{TODAY}"),
    ],
    "uk": [
        scrape("uk/ukas_ms_scraper.py"),
        prepare("uk/prepare_certifind.py", "ukas_ms_data", "{DATA}/ukas-united-kingdom"),
    ],
    "ukraine": [scrape("ukraine/naau_ms_scraper.py"), prepare("ukraine/prepare_certifind.py")],
    "uruguay": [
        scrape("uruguay/database/uruguay/scrape_uy_oua.py"),
        prepare("uruguay/prepare_certifind.py", "database/uruguay/raw_oua.json", "{DATA}/oua-uruguay"),
    ],
    "usa-anab": [
        scrape("usa/anab-usa_certifind/database/usa/scrape_us_anab.py"),
        prepare("usa/anab-usa_certifind/prepare_certifind.py", ".", "{DATA}/anab-usa"),
    ],
    "usa-ias": [
        scrape("usa/ias_certifind/database/usa/scrape_us_ias.py"),
        prepare("usa/ias_certifind/prepare_certifind.py", ".", "{DATA}/ias-usa"),
    ],
    "usa-uaf": [  # UAF API: browser-only
        prepare("usa/uaf_certifind/prepare_certifind.py", ".", "{DATA}/uaf-united-states"),
    ],
    "uzbekistan": [
        scrape("uzbekistan/accred_uz_management_bodies.py"),
        prepare("uzbekistan/prepare_certifind.py"),
    ],
}

DATASET_FILES = ("bodies.csv", "accreditations.csv", "scopes.csv")


def expand(arg: str) -> str:
    return arg.replace("{DATA}", str(DATA)).replace("{TODAY}", TODAY)


def describe(step) -> str:
    kind, target, args, cwd = step
    if kind == "copy":
        return f"copy     {target} -> {DATA / args[0]}"
    where = f"  (in {cwd})" if cwd else ""
    return f"{kind:<8} python {target} {' '.join(expand(a) for a in args)}{where}".rstrip()


def run_step(step, log, timeout):
    kind, target, args, cwd = step
    if kind == "copy":
        src, dst = HERE / target, DATA / args[0]
        dst.mkdir(parents=True, exist_ok=True)
        for name in DATASET_FILES:
            if not (src / name).exists():
                raise FileNotFoundError(src / name)
            shutil.copy2(src / name, dst / name)
        log.write(f"copied {src} -> {dst}\n")
        return
    script = HERE / target
    if not script.exists():
        raise FileNotFoundError(script)
    workdir = HERE / cwd if cwd else script.parent
    cmd = [PY, str(script), *(expand(a) for a in args)]
    log.write(f"$ {' '.join(cmd)}\n  (cwd {workdir})\n")
    log.flush()
    subprocess.run(cmd, cwd=workdir, stdout=log, stderr=subprocess.STDOUT,
                   timeout=timeout, check=True, env=_env())


def _env():
    import os
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("countries", nargs="*", help="countries to run (default: all)")
    ap.add_argument("--exclude", nargs="*", default=[], help="countries to leave out")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--skip-scrape", action="store_true", help="rebuild from saved scrapes only")
    mode.add_argument("--only-scrape", action="store_true", help="download only, no prepare")
    ap.add_argument("--list", action="store_true", help="list countries and steps, then exit")
    ap.add_argument("--dry-run", action="store_true", help="print commands without running them")
    ap.add_argument("--timeout", type=int, default=None, help="per-step timeout in seconds")
    a = ap.parse_args()

    unknown = [c for c in [*a.countries, *a.exclude] if c not in PIPELINES]
    if unknown:
        ap.error(f"unknown countries: {', '.join(unknown)}  (see --list)")
    names = [c for c in (a.countries or PIPELINES) if c not in a.exclude]

    def wanted(step):
        if a.skip_scrape:
            return step[0] != "scrape"
        if a.only_scrape:
            return step[0] == "scrape"
        return True

    if a.list or a.dry_run:
        for name in names:
            print(name)
            for step in filter(wanted, PIPELINES[name]):
                print("   ", describe(step))
        return 0

    logdir = HERE / "logs" / datetime.now().strftime("%Y-%m-%d_%H%M%S")
    logdir.mkdir(parents=True, exist_ok=True)
    results = []
    start_all = time.time()
    for i, name in enumerate(names, 1):
        steps = [s for s in PIPELINES[name] if wanted(s)]
        if not steps:
            continue
        print(f"[{i}/{len(names)}] {name} ...", end=" ", flush=True)
        start, status = time.time(), "ok"
        with open(logdir / f"{name}.log", "w", encoding="utf-8") as log:
            for step in steps:
                try:
                    run_step(step, log, a.timeout)
                except subprocess.TimeoutExpired:
                    status = f"timeout in {step[0]} ({step[1]})"
                except subprocess.CalledProcessError as e:
                    status = f"{step[0]} failed, exit {e.returncode} ({step[1]})"
                except Exception as e:  # noqa: BLE001
                    status = f"{step[0]} error: {e}"
                if status != "ok":
                    log.write(f"\n!! {status}\n")
                    break
        took = time.time() - start
        print(f"{status}  ({took:.0f}s)")
        results.append((name, status, took))

    failed = [r for r in results if r[1] != "ok"]
    print(f"\nDone in {(time.time() - start_all) / 60:.1f} min: "
          f"{len(results) - len(failed)} ok, {len(failed)} failed. Logs: {logdir}")
    for name, status, _ in failed:
        print(f"  FAILED {name}: {status}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
