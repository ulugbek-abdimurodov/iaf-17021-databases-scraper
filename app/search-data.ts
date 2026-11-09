import type { AccreditationScope, Body, ResultFilter } from "./search-types";

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";

export const stages = [
  "Inserimento",
  "Ricerca",
  "Verifica",
  "Arricchimento",
  "Risultati",
];

const countryFlags: Record<string, string> = {
  Italy: "🇮🇹",
  Romania: "🇷🇴",
  Poland: "🇵🇱",
  Germany: "🇩🇪",
  "United Kingdom": "🇬🇧",
  Albania: "🇦🇱",
};

export const flagFor = (country: string) => countryFlags[country] ?? "🌐";

/** Edition and Italian title per standard code, as in "ISO 9001:2015 Sistemi di gestione per la qualità – Requisiti". */
const standardTitles: Record<string, string> = {
  "ISO 9001": "ISO 9001:2015 Sistemi di gestione per la qualità – Requisiti",
  "ISO 14001": "ISO 14001:2015 Sistemi di gestione ambientale – Requisiti e guida per l’uso",
  "ISO 45001": "ISO 45001:2018 Sistemi di gestione per la salute e sicurezza sul lavoro – Requisiti e guida per l’uso",
  "AS 9100": "AS 9100:2016 Sistemi di gestione per la qualità – Requisiti per le organizzazioni dell’aeronautica, dello spazio e della difesa",
  "ISO 22000": "ISO 22000:2018 Sistemi di gestione per la sicurezza alimentare – Requisiti per qualsiasi organizzazione nella filiera alimentare",
  "FSSC 22000": "FSSC 22000 v6 Schema di certificazione per sistemi di sicurezza alimentare",
  "ISO 50001": "ISO 50001:2018 Sistemi di gestione dell’energia – Requisiti e linee guida per l’uso",
  "ISO 22301": "ISO 22301:2019 Sicurezza e resilienza – Sistemi di gestione per la continuità operativa – Requisiti",
  "ISO 37001": "ISO 37001:2025 Sistemi di gestione per la prevenzione della corruzione – Requisiti con guida per l’utilizzo",
  "ISO 37301": "ISO 37301:2021 Sistemi di gestione della compliance – Requisiti con guida per l’utilizzo",
  "ISO 13485": "ISO 13485:2016 Dispositivi medici – Sistemi di gestione per la qualità – Requisiti per scopi regolamentari",
  "ISO 39001": "ISO 39001:2012 Sistemi di gestione per la sicurezza del traffico stradale – Requisiti e guida per l’uso",
  "ISO 41001": "ISO 41001:2018 Facility management – Sistemi di gestione – Requisiti con guida per l’utilizzo",
  "ISO 21001": "ISO 21001:2018 Organizzazioni di istruzione e formazione – Sistemi di gestione – Requisiti con guida per l’utilizzo",
  "ISO 29993": "ISO 29993:2017 Servizi di apprendimento al di fuori dell’istruzione formale – Requisiti del servizio",
  "ISO 55001": "ISO 55001:2024 Asset management – Sistemi di gestione dell’asset – Requisiti",
  "ISO 20121": "ISO 20121:2024 Sistemi di gestione sostenibile degli eventi – Requisiti con guida per l’utilizzo",
  "ISO 28000": "ISO 28000:2022 Sicurezza e resilienza – Sistemi di gestione per la sicurezza – Requisiti",
  "ISO 46001": "ISO 46001:2019 Sistemi di gestione dell’efficienza idrica – Requisiti con guida per l’utilizzo",
  "ISO 18295": "ISO 18295-1:2017 Centri di contatto con la clientela – Requisiti per i centri di contatto",
  "ISO 15378": "ISO 15378:2017 Materiali d’imballaggio primario per medicinali – Requisiti particolari per l’applicazione della ISO 9001",
  "ISO 18788": "ISO 18788:2015 Sistema di gestione per le operazioni di sicurezza privata – Requisiti con guida per l’uso",
  "ISO 19443": "ISO 19443:2018 Sistemi di gestione per la qualità – Requisiti specifici per l’applicazione della ISO 9001 da parte delle organizzazioni della catena di fornitura del settore nucleare",
  "ISO 21401": "ISO 21401:2018 Turismo e servizi correlati – Sistema di gestione della sostenibilità per le strutture ricettive – Requisiti",
  "ISO 22716": "ISO 22716:2007 Cosmetici – Pratiche di buona fabbricazione – Linee guida sulle pratiche di buona fabbricazione",
  "ISO 28001": "ISO 28001:2007 Sistemi di gestione per la sicurezza della catena di approvvigionamento – Migliori pratiche per l’attuazione della sicurezza della catena di approvvigionamento, valutazioni e piani",
  "ISO 29001": "ISO 29001:2020 Sistemi di gestione per la qualità – Requisiti specifici per le organizzazioni della catena di fornitura del petrolio, della petrolchimica e del gas naturale",
  "ISO 29994": "ISO 29994:2021 Istruzione e formazione – Servizi di apprendimento al di fuori dell’istruzione formale – Requisiti per i servizi",
  "ISO 44001": "ISO 44001:2017 Sistemi di gestione delle relazioni d’affari collaborative – Requisiti e quadro di riferimento",
  "ISO 30301": "ISO 30301:2019 Informazione e documentazione – Sistemi di gestione dei documenti – Requisiti",
  "ISO 30401": "ISO 30401:2018 Sistemi di gestione della conoscenza – Requisiti",
  "ISO 37101": "ISO 37101:2016 Sviluppo sostenibile delle comunità – Sistema di gestione per lo sviluppo sostenibile – Requisiti con guida per l’uso",
  "ISO 3834": "ISO 3834:2021 Requisiti di qualità per la saldatura per fusione dei materiali metallici",
  "ISO 56001": "ISO 56001:2024 Gestione dell’innovazione – Sistema di gestione dell’innovazione – Requisiti",
  "ISO 7101": "ISO 7101:2023 Organizzazioni sanitarie – Sistemi di gestione per la qualità – Requisiti",
  "EN 15224": "EN 15224:2016 Sistemi di gestione per la qualità – EN ISO 9001:2015 per l’assistenza sanitaria",
  "OHSAS 18001": "OHSAS 18001:2007 Sistemi di gestione della salute e sicurezza sul lavoro – Requisiti",
  "ISO/IEC 27001": "ISO/IEC 27001:2022 Sicurezza delle informazioni, cybersecurity e protezione della privacy – Sistemi di gestione per la sicurezza delle informazioni – Requisiti",
  "ISO/IEC 27701": "ISO/IEC 27701:2025 Sicurezza delle informazioni, cybersecurity e protezione della privacy – Sistemi di gestione delle informazioni privacy – Requisiti e linee guida",
  "ISO/IEC 27017": "ISO/IEC 27017:2015 Tecniche di sicurezza – Codice di condotta per i controlli di sicurezza delle informazioni basati su ISO/IEC 27002 per i servizi cloud",
  "ISO/IEC 27018": "ISO/IEC 27018:2019 Tecniche di sicurezza – Codice di condotta per la protezione dei dati personali (PII) nei cloud pubblici che agiscono come responsabili del trattamento",
  "ISO/IEC 20000-1": "ISO/IEC 20000-1:2018 Tecnologie informatiche – Gestione dei servizi – Parte 1: Requisiti per un sistema di gestione dei servizi",
  "ISO/IEC 42001": "ISO/IEC 42001:2023 Tecnologie informatiche – Intelligenza artificiale – Sistema di gestione",
};

/** Full Italian label for a standard code; unknown codes are shown as-is. */
export const standardLabel = (code: string) => standardTitles[code] ?? code;

/** UI shorthand: "ISO/IEC 27001:2022" → "ISO 27001", "ISO/IEC 17021-1" → "ISO 17021". */
export const shortStandard = (code: string) =>
  code
    .replace(/^ISO\/IEC\s+/i, "ISO ")
    .replace(/:\d{4}$/, "")
    .replace(/(\d)-\d+$/, "$1");

/** Shorthand plus Italian name: "ISO 9001 – Sistemi di gestione per la qualità – Requisiti". */
export const standardOptionLabel = (code: string) => {
  const title = standardTitles[code];
  const description = title?.replace(/^.*?(:\d{4}|\sv\d+)\s+/, "");
  return description && description !== title
    ? `${shortStandard(code)} – ${description}`
    : shortStandard(code);
};

/** Short label for a scope: "EA 37", or "ISO 17025 (non-EA)" when no EA sector applies. */
export const scopeCode = (scope: AccreditationScope) =>
  scope.eaCode == null ? `${scope.isoStandard} (non-EA)` : `EA ${scope.eaCode}`;

const EA_SECTOR_COUNT = 39;

const coversAllSectors = (scopes: AccreditationScope[]) =>
  new Set(scopes.map((scope) => scope.eaCode).filter((code) => code != null))
    .size === EA_SECTOR_COUNT;

const standardNumbers = (code: string) =>
  (code.match(/\d+/g) ?? []).map(Number);

/** Orders standards by number, ignoring the prefix: ISO 3834, ISO 9001, ISO 13485, EN 15224, … */
export const compareStandards = (a: string, b: string) => {
  const [na, nb] = [standardNumbers(a), standardNumbers(b)];
  for (let i = 0; i < Math.max(na.length, nb.length); i++) {
    const diff = (na[i] ?? -1) - (nb[i] ?? -1);
    if (diff !== 0) return diff;
  }
  return a.localeCompare(b);
};

/** Distinct ISO standards of a body's scopes, by number: "ISO 9001, ISO 14001". */
export const standardsLabel = (scopes: AccreditationScope[]) =>
  [...new Set(scopes.map((scope) => shortStandard(scope.isoStandard)))]
    .sort(compareStandards)
    .join(", ");

/** Certificate expiry as "31/12/2027"; null when unknown. */
export const formatExpiry = (date: string | null) =>
  date ? new Date(date).toLocaleDateString("it-IT") : null;

const scopeDetail =(scope: AccreditationScope) =>
  scope.eaCode == null
    ? scope.scopeSection
    : `EA ${scope.eaCode} (${scope.eaDescription})`;

/** One entry per ISO standard; a standard covering all EA sectors lists no sectors. */
export const scopeLinesByStandard = (scopes: AccreditationScope[]) => {
  const byStandard = new Map<string, AccreditationScope[]>();
  scopes.forEach((scope) => {
    byStandard.set(scope.isoStandard, [
      ...(byStandard.get(scope.isoStandard) ?? []),
      scope,
    ]);
  });
  return [...byStandard].map(([standard, group]) => ({
    standard,
    allSectors: coversAllSectors(group),
    sectors: group.map(scopeDetail),
  }));
};

export function matchesFilter(body: Body, filter: ResultFilter) {
  const isItalian = body.accreditationBodyCode === "ACCREDIA";
  if (filter === "all") return true;
  if (filter === "italy") return isItalian;
  if (filter === "foreign") return !isItalian;
  const [code, country] = filter.slice("accreditor:".length).split("|");
  return body.accreditationBodyCode === code && body.country === country;
}

export const demoPresets = [
  {
    label: "Prodotti chimici e fibre (ISO 9001 • EA 12)",
    iso: "ISO 9001",
    sector: "EA 12 - Prodotti chimici e fibre",
  },
  {
    label: "Software & IT (ISO 9001 • EA 33)",
    iso: "ISO 9001",
    sector: "Produzione di software",
  },
  {
    label: "Edilizia & Sicurezza (ISO 45001 • EA 28)",
    iso: "ISO 45001",
    sector: "Costruzione di edifici",
  },
  {
    label: "Studi Ingegneria (ISO 14001 • EA 34)",
    iso: "ISO 14001",
    sector: "Studi di ingegneria",
  },
];
