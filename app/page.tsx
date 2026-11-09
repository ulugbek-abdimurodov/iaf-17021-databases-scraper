"use client";

import { FormEvent, useEffect, useState } from "react";
import { OrganizationDrawer } from "../components/OrganizationDrawer";
import { ResultsSection } from "../components/ResultsSection";
import { SearchForm } from "../components/SearchForm";
import { ThemeToggle } from "../components/ThemeToggle";
import { Workflow } from "../components/Workflow";
import { API_URL, stages } from "./search-data";
import type {
  Body,
  ResultFilter,
  SearchPreset,
  SearchResponse,
  SearchOptions,
} from "./search-types";

const RECENT_SEARCHES_KEY = "certifind:recent-searches:v2";
const MAX_RECENT_SEARCHES = 5;
const SERVICE_UNAVAILABLE =
  "Impossibile raggiungere il servizio. Verifica che l’API sia avviata.";

export default function Home() {
  const [iso, setIso] = useState("ISO 9001");
  const [sector, setSector] = useState("EA 12 - Prodotti chimici e fibre");
  const [step, setStep] = useState(-1);
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<SearchResponse | null>(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<Body | null>(null);
  const [resultFilter, setResultFilter] = useState<ResultFilter>("all");
  const [recentSearches, setRecentSearches] = useState<SearchPreset[]>([]);
  const [options, setOptions] = useState<SearchOptions>({
    standards: [],
    sectorsByStandard: {},
  });

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      setRecentSearches(readRecentSearches());
    }, 0);
    return () => window.clearTimeout(timeoutId);
  }, []);

  useEffect(() => {
    fetch(`${API_URL}/api/v1/options`)
      .then((response) => {
        if (!response.ok) throw new Error("Impossibile caricare le opzioni dal database.");
        return response.json() as Promise<SearchOptions>;
      })
      .then(setOptions)
      .catch(() => setError("Impossibile caricare standard e settori dal database."));
  }, []);

  useEffect(() => {
    if (!selected) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSelected(null);
    };
    window.addEventListener("keydown", closeOnEscape);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", closeOnEscape);
      document.body.style.overflow = "";
    };
  }, [selected]);

  /** Shared flow for every results request: reset state, animate, fetch, report errors. */
  async function runSearch(
    request: () => Promise<Response>,
    errorFor: (status: number) => string,
    onSuccess?: () => void,
  ) {
    if (loading) return;
    setLoading(true);
    setError("");
    setData(null);
    setSelected(null);
    setResultFilter("all");
    setStep(0);

    const animation = animateWorkflow();
    try {
      const response = await request();
      if (!response.ok) throw new Error(errorFor(response.status));
      setData((await response.json()) as SearchResponse);
      onSuccess?.();
    } catch (cause) {
      // fetch() rejects with a TypeError when the API cannot be reached.
      setError(
        cause instanceof Error && !(cause instanceof TypeError)
          ? cause.message
          : SERVICE_UNAVAILABLE,
      );
    } finally {
      await animation;
      setStep(stages.length - 1);
      setLoading(false);
      document
        .getElementById("results")
        ?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  async function animateWorkflow() {
    for (let index = 1; index < stages.length; index += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, 300));
      setStep(index);
    }
  }

  function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    return runSearch(
      () =>
        fetch(`${API_URL}/api/v1/search`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            isoStandard: iso,
            sectorActivity: sector,
          }),
        }),
      (status) =>
        status === 400
          ? "Settore non riconosciuto. Controlla la descrizione del settore."
          : "Ricerca non riuscita. Riprova tra poco.",
      () => saveRecentSearch({ iso, sector }),
    );
  }

  function showAllCompanies() {
    return runSearch(
      () => fetch(`${API_URL}/api/v1/companies`),
      () => "Impossibile caricare l'elenco delle aziende.",
    );
  }

  function saveRecentSearch(searchPreset: Omit<SearchPreset, "label">) {
    const nextSearch: SearchPreset = {
      ...searchPreset,
      label: `${searchPreset.sector} (${searchPreset.iso})`,
    };
    const nextSearches = [
      nextSearch,
      ...recentSearches.filter(
        (recent) =>
          recent.iso !== nextSearch.iso || recent.sector !== nextSearch.sector,
      ),
    ].slice(0, MAX_RECENT_SEARCHES);

    setRecentSearches(nextSearches);
    window.localStorage.setItem(
      RECENT_SEARCHES_KEY,
      JSON.stringify(nextSearches),
    );
  }

  return (
    <main>
      <header className="topbar">
        <Brand className="brand" />
        <div className="topbar-note">
          <span className="status-dot" /> Ricerca organismi accreditati
        </div>
        <div className="topbar-actions">
          <ThemeToggle />
          <a className="help-link" href="mailto:info@certifind.it">
            Hai bisogno di aiuto? <span>↗</span>
          </a>
        </div>
      </header>
      <section className="hero" id="top">
        <div className="hero-copy">
          <div className="eyebrow">
            <span className="eyebrow-line" /> CERTIFICAZIONI, SENZA
            COMPLICAZIONI
          </div>
          <h1>
            Il partner giusto
            <br />
            per <em>certificarti.</em>
          </h1>
          <p>
            Trova gli organismi accreditati per il tuo settore. Confronta le
            competenze, verifica gli accreditamenti, scegli con consapevolezza.
          </p>
          <div className="hero-proof">
            <span className="proof-icon">✓</span>
            <span>
              Dati di accreditamento e contatti{" "}
              <strong>in un unico posto</strong>
            </span>
          </div>
        </div>
        <SearchForm
          iso={iso}
          sector={sector}
          loading={loading}
          onIsoChange={setIso}
          onSectorChange={setSector}
          recentSearches={recentSearches}
          onSubmit={search}
          onShowAllCompanies={showAllCompanies}
          options={options}
        />
      </section>
      <Workflow step={step} loading={loading} />
      <ResultsSection
        data={data}
        error={error}
        iso={iso}
        resultFilter={resultFilter}
        onFilterChange={setResultFilter}
        onSelect={setSelected}
      />
      <footer>
        <Brand className="brand footer-brand" />
        <span>Organismi, competenze, trasparenza.</span>
        <span>© 2026 CertiFind</span>
      </footer>
      <OrganizationDrawer body={selected} iso={iso} onClose={() => setSelected(null)} />
    </main>
  );
}

function Brand({ className }: { className: string }) {
  return (
    <a className={className} href="#top">
      <span className="brand-mark">C</span>certi<span>find</span>
    </a>
  );
}

function isSearchPreset(value: unknown): value is SearchPreset {
  if (!value || typeof value !== "object") return false;
  const preset = value as Partial<SearchPreset>;
  return (
    typeof preset.label === "string" &&
    typeof preset.iso === "string" &&
    typeof preset.sector === "string"
  );
}

function readRecentSearches(): SearchPreset[] {
  try {
    const stored = window.localStorage.getItem(RECENT_SEARCHES_KEY);
    if (!stored) return [];

    const parsed = JSON.parse(stored);
    return Array.isArray(parsed)
      ? parsed.filter(isSearchPreset).slice(0, MAX_RECENT_SEARCHES)
      : [];
  } catch {
    window.localStorage.removeItem(RECENT_SEARCHES_KEY);
    return [];
  }
}
