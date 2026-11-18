#!/usr/bin/env python3
"""Run every country's ISO/IEC 17065 (product certification) scraper, all at once.

Each country opens in its own console window (Windows), so you can watch every
scraper live. Each window runs that country's 17065 steps in order (scrape, then
prepare), streams the output, and writes a log under logs/17065_<run time>/.
The window stays open at the end until you press Enter.

Usage:
    python run_17065_all.py                   # open one window per country, all at once
    python run_17065_all.py egypt germany     # only these countries
    python run_17065_all.py --exclude uk      # all except these
    python run_17065_all.py --list            # show countries and their steps
    python run_17065_all.py --dry-run         # print the commands without running them
    python run_17065_all.py --same-window     # no new windows: run in this terminal, in parallel, output prefixed

Exit code 1 if any country failed.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from run_all import PY, expand, prepare, scrape  # noqa: E402  (reuses run_all's step format)

# Only the ISO/IEC 17065 steps. "{DATA}" is certifind/data; paths are relative to this folder.
PIPELINES_17065: dict[str, list] = {
    "armenia": [
        scrape("armenia/armnab-armenia-17065/scrape_am_armnab_17065.py"),
        prepare("armenia/armnab-armenia-17065/prepare_certifind_17065.py", "armnab_17065", "{DATA}/armnab-armenia-17065"),
    ],
    "australia": [
        scrape("australia/jasanz-australia-17065/scrape_au_jasanz_17065.py"),
        prepare("australia/jasanz-australia-17065/prepare_certifind_17065.py", "raw/jasanz_17065_raw.json", "{DATA}/jasanz-australia-17065"),
    ],
    "austria": [
        scrape("austria/17065/scrape_at_aa_17065.py"),
        prepare("austria/17065/prepare_certifind_17065.py", "raw/aa_17065_raw.json", "{DATA}/aa-austria-17065"),
    ],
    "belgium": [
        scrape("belgium/17065/belac_prod_scraper.py"),
        prepare("belgium/17065/prepare_certifind_17065.py", "belac_prod_data", "{DATA}/belac-belgium-17065"),
    ],
    "bulgaria": [  # reads bas-bulgaria/bodies.csv from the 17021 run: run the 17021 pipeline first
        scrape("bulgaria/17065/nab_prod_scraper.py"),
        prepare("bulgaria/17065/prepare_certifind_17065.py"),
    ],
    "croatia": [
        scrape("croatia/17021/haa_scraper.py", "--scheme", "certifikaciju proizvoda", "--out", "../17065/haa_prod_data"),
        prepare("croatia/17065/prepare_certifind_17065.py", "haa_prod_data", "{DATA}/haa-croatia-17065"),
    ],
    "cyprus": [
        scrape("cyprus/cysab-cyprus-17065/scrape_cy_cysab_17065.py"),
        prepare("cyprus/cysab-cyprus-17065/prepare_certifind_17065.py", "cysab_17065/pdf", "{DATA}/cysab-cyprus-17065"),
    ],
    "egypt": [
        scrape("egypt/egac-egypt-17065/scrape_eg_egac_17065.py"),
        prepare("egypt/egac-egypt-17065/prepare_certifind_17065.py", "egac_17065", "{DATA}/egac-egypt-17065"),
    ],
    "georgia": [
        scrape("georgia/scrape_ge_gac_17065.py"),
        prepare("georgia/prepare_certifind_17065.py", "{DATA}/gac-georgia-17065"),
    ],
    "germany": [
        scrape("germany/dakks_17065_scraper.py"),
        prepare("germany/prepare_certifind_17065.py", "dakks_ZE", "{DATA}/dakks-germany-17065"),
    ],
    "italy": [
        scrape("italy/accredia-italy-17065/scrape_it_accredia_17065.py"),
        prepare("italy/accredia-italy-17065/prepare_certifind_17065.py", "accredia_17065", "{DATA}/accredia-italy-17065"),
    ],
    "tunisia": [
        scrape("tunisia/tunac-tunisia-17065/scrape_tn_tunac_17065.py"),
        prepare("tunisia/tunac-tunisia-17065/prepare_certifind_17065.py", "tunac_17065", "{DATA}/tunac-tunisia-17065"),
    ],
    "turkey": [
        scrape("turkey/17065/scrape_tr_turkak_17065.py"),
        prepare("turkey/17065/prepare_certifind_17065.py", "turkak_17065", "{DATA}/turkak-turkey-17065"),
    ],
    # Scrape-only so far: these write raw files; their CertiFind prepare step is not written yet.
    "switzerland": [scrape("switzerland/17065/scrape_ch_sas_17065.py")],
    "sweden": [scrape("sweden/17065/scrape_se_swedac_17065.py")],
    "norway": [scrape("norway/17065/scrape_no_akkreditert_17065.py")],
    "poland": [scrape("poland/17065/scrape_pl_pca_17065.py")],
    "netherlands": [scrape("netherlands/17065/scrape_nl_rva_17065.py")],
    "finland": [scrape("finland/17065/scrape_fi_finas_17065.py")],
    "saudi-arabia": [scrape("saudi-arabia/17065/scrape_sa_saac_17065.py")],
    "taiwan": [scrape("taiwan/17065/scrape_tw_taf_17065.py")],
    "mongolia": [scrape("mongolia/17065/scrape_mn_mnas_17065.py")],
    "india": [scrape("india/17065/scrape_in_nabcb_17065.py", "--no-media")],
    "malaysia": [scrape("malaysia/17065/scrape_my_jsm_17065.py")],
    "ecuador": [scrape("ecuador/17065/scrape_ec_sae_17065.py")],  # not verified: the host returned 403 from the build machine
    "usa-ias": [scrape("usa/ias_certifind/17065/scrape_us_ias_17065.py")],
    "denmark": [scrape("denmark/17065/scrape_dk_danak_17065.py")],
    "slovakia": [scrape("slovakia/17065/scrape_sk_snas_17065.py")],
    "hungary": [scrape("hungary/17065/scrape_hu_nah_17065.py")],
    "estonia": [scrape("estonia/17065/scrape_ee_eak_17065.py")],
    "czechia": [scrape("czechia/17065/scrape_cz_cai_17065.py")],  # slow: 5 s crawl delay from robots.txt
    "macedonia": [scrape("macedonia/17065/scrape_mk_iarm_17065.py")],  # English list only
    "uruguay": [scrape("uruguay/17065/scrape_uy_oua_17065.py")],
    "ukraine": [scrape("ukraine/17065/scrape_ua_naau_17065.py")],
    "portugal": [scrape("portugal/17065/scrape_pt_ipac_17065.py")],
    "ireland": [scrape("ireland/17065/scrape_ie_inab_17065.py")],
    "sri-lanka": [scrape("sri-lanka/17065/scrape_lk_slab_17065.py")],
    "japan-jab": [scrape("japan/jab-japan-17065/scrape_jp_jab_17065.py")],
    "france": [scrape("france/17065/scrape_fr_cofrac_17065.py")],
    "romania": [scrape("romania/17065/scrape_ro_renar_17065.py")],
}


def describe(step) -> str:
    kind, target, args, cwd = step
    where = f"  (in {cwd})" if cwd else ""
    return f"{kind:<8} python {target} {' '.join(expand(a) for a in args)}{where}".rstrip()


def _env():
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def run_steps(steps: list, log_path: Path, prefix: str = "") -> int:
    """Run the steps in order, echo output to this console and to the log. Returns 0 if all ok."""
    with open(log_path, "w", encoding="utf-8") as log:
        for kind, target, args, cwd in steps:
            script = HERE / target
            workdir = HERE / cwd if cwd else script.parent
            cmd = [PY, "-u", str(script), *(expand(a) for a in args)]
            header = f"$ {' '.join(cmd)}\n  (cwd {workdir})"
            print(f"{prefix}{header}", flush=True)
            log.write(header + "\n")
            log.flush()
            if not script.exists():
                msg = f"!! missing script {script}"
                print(f"{prefix}{msg}", flush=True)
                log.write(msg + "\n")
                return 1
            proc = subprocess.Popen(cmd, cwd=workdir, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, env=_env(), text=True,
                                    encoding="utf-8", errors="replace")
            for line in proc.stdout:
                print(f"{prefix}{line.rstrip()}", flush=True)
                log.write(line)
                log.flush()
            code = proc.wait()
            if code != 0:
                msg = f"!! {kind} failed, exit {code}: {target}"
                print(f"{prefix}{msg}", flush=True)
                log.write(msg + "\n")
                return code
    return 0


def child(country: str, log_path: Path) -> int:
    """Entry point for one country's console window."""
    print(f"=== 17065 scraper: {country}   started {datetime.now():%Y-%m-%d %H:%M:%S}\n", flush=True)
    start = time.time()
    code = run_steps(PIPELINES_17065[country], log_path)
    status = "OK" if code == 0 else f"FAILED (exit {code})"
    print(f"\n=== {country}: {status}  ({(time.time() - start) / 60:.1f} min)  log: {log_path}", flush=True)
    input("Press Enter to close this window...")
    return code


def launch_windows(names: list[str], logdir: Path) -> dict[str, int]:
    procs = {}
    me = str(Path(__file__).resolve())
    for name in names:
        cmd = [PY, me, "--child", name, "--log", str(logdir / f"{name}.log")]
        procs[name] = subprocess.Popen(cmd, cwd=HERE, creationflags=subprocess.CREATE_NEW_CONSOLE)
        print(f"opened window: {name}  (pid {procs[name].pid})", flush=True)
    return {name: p.wait() for name, p in procs.items()}


def launch_same_window(names: list[str], logdir: Path) -> dict[str, int]:
    results: dict[str, int] = {}

    def worker(name):
        results[name] = run_steps(PIPELINES_17065[name], logdir / f"{name}.log", prefix=f"[{name}] ")

    threads = [threading.Thread(target=worker, args=(n,)) for n in names]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def main() -> int:
    if "--child" in sys.argv:  # internal: one window's worker
        ap = argparse.ArgumentParser()
        ap.add_argument("--child", required=True)
        ap.add_argument("--log", required=True)
        a = ap.parse_args()
        return child(a.child, Path(a.log))

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("countries", nargs="*", help="countries to run (default: all)")
    ap.add_argument("--exclude", nargs="*", default=[], help="countries to leave out")
    ap.add_argument("--list", action="store_true", help="list countries and steps, then exit")
    ap.add_argument("--dry-run", action="store_true", help="print commands without running them")
    ap.add_argument("--same-window", action="store_true", help="run in this terminal instead of new windows")
    a = ap.parse_args()

    unknown = [c for c in [*a.countries, *a.exclude] if c not in PIPELINES_17065]
    if unknown:
        ap.error(f"no 17065 pipeline for: {', '.join(unknown)}  (see --list)")
    names = [c for c in (a.countries or PIPELINES_17065) if c not in a.exclude]

    if a.list or a.dry_run:
        for name in names:
            print(name)
            for step in PIPELINES_17065[name]:
                print("   ", describe(step))
        return 0

    logdir = HERE / "logs" / f"17065_{datetime.now():%Y-%m-%d_%H%M%S}"
    logdir.mkdir(parents=True, exist_ok=True)
    print(f"Starting {len(names)} 17065 scrapers. Logs: {logdir}", flush=True)
    start = time.time()
    if a.same_window or os.name != "nt":
        results = launch_same_window(names, logdir)
    else:
        results = launch_windows(names, logdir)

    failed = [n for n, c in results.items() if c != 0]
    print(f"\nDone in {(time.time() - start) / 60:.1f} min: "
          f"{len(results) - len(failed)} ok, {len(failed)} failed. Logs: {logdir}")
    for n in failed:
        print(f"  FAILED {n} (exit {results[n]})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
