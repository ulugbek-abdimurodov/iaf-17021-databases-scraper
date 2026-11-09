"use client";

import { useId, useState, type FormEvent, type KeyboardEvent } from "react";
import { compareStandards, demoPresets, standardOptionLabel } from "../app/search-data";
import type { SearchOptions, SearchPreset } from "../app/search-types";

type SearchFormProps = {
  iso: string;
  sector: string;
  loading: boolean;
  onIsoChange: (value: string) => void;
  onSectorChange: (value: string) => void;
  recentSearches: SearchPreset[];
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onShowAllCompanies: () => void;
  options: SearchOptions;
};

export function SearchForm({
  iso,
  sector,
  loading,
  onIsoChange,
  onSectorChange,
  recentSearches,
  onSubmit,
  onShowAllCompanies,
  options,
}: SearchFormProps) {
  const presets = recentSearches.length ? recentSearches : demoPresets;
  const [sectorFocused, setSectorFocused] = useState(false);
  const [activeSuggestion, setActiveSuggestion] = useState(-1);
  const suggestionListId = useId();
  const sectorQuery = sector.trim().toLocaleLowerCase();
  const sectorSuggestions = (options.sectorsByStandard?.[iso] ?? []).filter(
    (option) =>
      sectorQuery.length === 0 ||
      `EA ${option.code} ${option.name}`.toLocaleLowerCase().includes(sectorQuery),
  );
  const selectSuggestion = (index: number) => {
    const suggestion = sectorSuggestions[index];
    if (!suggestion) return;
    onSectorChange(`EA ${suggestion.code} - ${suggestion.name}`);
    setActiveSuggestion(-1);
    setSectorFocused(false);
  };
  const handleSectorKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (!sectorFocused || !sectorSuggestions.length) {
      if (event.key === "ArrowDown" && sectorSuggestions.length) {
        setSectorFocused(true);
        setActiveSuggestion(0);
        event.preventDefault();
      }
      return;
    }
    if (event.key === "ArrowDown") {
      setActiveSuggestion((index) => (index + 1) % sectorSuggestions.length);
      event.preventDefault();
    } else if (event.key === "ArrowUp") {
      setActiveSuggestion((index) => (index <= 0 ? sectorSuggestions.length - 1 : index - 1));
      event.preventDefault();
    } else if (event.key === "Enter" && activeSuggestion >= 0) {
      selectSuggestion(activeSuggestion);
      event.preventDefault();
    } else if (event.key === "Escape") {
      setSectorFocused(false);
      setActiveSuggestion(-1);
      event.preventDefault();
    }
  };

  return (
    <div className="search-card">
      <div className="card-kicker">
        INIZIA LA RICERCA <span>01 / 03</span>
      </div>
      <h2>Di cosa hai bisogno?</h2>
      <p className="card-subtitle">
        Inserisci lo standard e l’attività della tua azienda.
      </p>
      <div className="demo-presets">
        <div className="demo-presets-label">
          {recentSearches.length ? "RICERCHE RECENTI" : "SCENARIO DEMO RAPIDO"}
        </div>
        <div className="demo-presets-list">
          {presets.map((preset) => (
            <button
              className="demo-preset"
              key={preset.label}
              type="button"
              onClick={() => {
                onIsoChange(preset.iso);
                onSectorChange(preset.sector);
              }}
            >
              {preset.label}
            </button>
          ))}
        </div>
      </div>
      <form onSubmit={onSubmit}>
        <label htmlFor="standard">Standard ISO</label>
        <div className="input-wrap">
          <span className="input-icon">◎</span>
          <select
            id="standard"
            value={iso}
            onChange={(event) => {
              const nextIso = event.target.value;
              onIsoChange(nextIso);
              // Drop a chosen "EA nn" sector the new standard does not offer.
              const chosenCode = sector.match(/\bEA\s*(\d{1,2})\b/i)?.[1];
              const available = options.sectorsByStandard?.[nextIso] ?? [];
              if (chosenCode && !available.some((option) => option.code === Number(chosenCode))) {
                onSectorChange("");
              }
            }}
          >
            {[...options.standards].sort(compareStandards).map((standard) => (
              <option key={standard} value={standard}>
                {standardOptionLabel(standard)}
              </option>
            ))}
          </select>
          <span className="select-chevron">⌄</span>
        </div>
        <label htmlFor="sector">Settore di attività</label>
        <div className="sector-autocomplete">
          <div className="input-wrap">
          <input
            id="sector"
            value={sector}
            onChange={(event) => {
              onSectorChange(event.target.value);
              setActiveSuggestion(-1);
            }}
            onFocus={() => setSectorFocused(true)}
            onKeyDown={handleSectorKeyDown}
            onBlur={() => {
              window.setTimeout(() => setSectorFocused(false), 150);
            }}
            placeholder="EA 12 - Prodotti chimici e fibre"
            role="combobox"
            aria-autocomplete="list"
            aria-controls={suggestionListId}
            aria-expanded={sectorFocused && sectorSuggestions.length > 0}
            aria-activedescendant={
              activeSuggestion >= 0
                ? `${suggestionListId}-option-${sectorSuggestions[activeSuggestion]?.code}`
                : undefined
            }
            required
          />
          </div>
          {sectorFocused && sectorSuggestions.length > 0 && (
            <div
              className="sector-suggestions"
              id={suggestionListId}
              role="listbox"
              aria-label="Settori disponibili"
            >
              {sectorSuggestions.map((suggestion, index) => (
                <button
                  className="sector-suggestion"
                  key={suggestion.code}
                  type="button"
                  role="option"
                  id={`${suggestionListId}-option-${suggestion.code}`}
                  aria-selected={activeSuggestion === index}
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => selectSuggestion(index)}
                >
                  EA {suggestion.code} - {suggestion.name}
                </button>
              ))}
            </div>
          )}
        </div>
        <button className="search-button" type="submit" disabled={loading}>
          {loading ? (
            "Ricerca in corso…"
          ) : (
            <>
              Avvia ricerca <span>→</span>
            </>
          )}
        </button>
      </form>
      <button
        className="directory-button"
        type="button"
        onClick={onShowAllCompanies}
        disabled={loading}
      >
        Vedi tutte le aziende <span>→</span>
      </button>
      <div className="privacy-note">
        <span>♢</span> Nessun dato aziendale viene salvato
      </div>
    </div>
  );
}
