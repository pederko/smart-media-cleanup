import { Fragment, useEffect, useMemo, useState } from "react";
import { api, qs, Requester, Savings, Suggestion } from "../api";
import { bytes, kindLabel, num } from "../format";
import { t } from "../i18n";
import { ErrorNote, HistoryLine, PageHeader, Poster, RequestedBy, RiskPill, ScoreMeter, Seg, Tray, useFetch, useOpenTitle, useRefreshTick, useStatus } from "../components/common";
import SuggestionDetail from "../components/SuggestionDetail";
import DeleteDialog from "../components/DeleteDialog";

type ListResp = { total: number; items: Suggestion[]; filtered_savings: Savings; min_score: number; recommended_score: number };
type SelResp = Savings & { items: { id: string; kind: string }[] };

const STORE = "smc.selection";
const KINDS = ["delete_title", "delete_season", "replace", "remove_versions", "remove_copy", "download"];
const DELETABLE = new Set(["delete_title", "delete_season"]);

function hashParam(name: string): string {
  const q = window.location.hash.split("?")[1] ?? "";
  return new URLSearchParams(q).get(name) ?? "";
}

function loadSel(): string[] {
  try { return JSON.parse(localStorage.getItem(STORE) || "[]"); } catch { return []; }
}

export default function SuggestionsPage() {
  const tick = useRefreshTick();
  const openTitle = useOpenTitle();
  const status = useStatus();
  const [scope, setScope] = useState<"recommended" | "all">(() => (hashParam("all") ? "all" : "recommended"));
  const [q, setQ] = useState("");
  const [kind, setKind] = useState(() => hashParam("kind"));
  const [risk, setRisk] = useState("");
  const [library, setLibrary] = useState("");
  const [requester, setRequester] = useState(() => hashParam("by"));
  const [minScore, setMinScore] = useState<string>("");
  const [sort, setSort] = useState("score");
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const [limit, setLimit] = useState(100);
  const [open, setOpen] = useState<string | null>(null);
  const [sel, setSel] = useState<string[]>(loadSel);
  const [selInfo, setSelInfo] = useState<SelResp | null>(null);
  const [deleting, setDeleting] = useState<string[] | null>(null);
  const [debounced, setDebounced] = useState("");

  useEffect(() => { const x = setTimeout(() => setDebounced(q), 250); return () => clearTimeout(x); }, [q]);
  const url = `/api/suggestions${qs({ q: debounced, kind, risk, library, requested_by: requester, min_score: minScore,
    recommended: scope === "recommended", sort, order, limit })}`;
  const requesters = useFetch<{ items: Requester[] }>("/api/requesters", [tick]);
  const { data, error, loading } = useFetch<ListResp>(url, [tick]);
  const settings = useFetch<{ libraries: { name: string }[] }>("/api/settings");

  useEffect(() => {
    try { localStorage.setItem(STORE, JSON.stringify(sel)); } catch { /* private mode */ }
    if (!sel.length) { setSelInfo(null); return; }
    api.post<SelResp>("/api/selection", { ids: sel }).then(setSelInfo).catch(() => setSelInfo(null));
  }, [sel, tick]);

  // Drop selections that no longer exist after a new analysis
  useEffect(() => {
    if (selInfo && selInfo.items.length < sel.length) {
      const ok = new Set(selInfo.items.map((i) => i.id));
      setSel((s) => s.filter((id) => ok.has(id)));
    }
  }, [selInfo]); // eslint-disable-line react-hooks/exhaustive-deps

  const selSet = useMemo(() => new Set(sel), [sel]);
  const toggle = (id: string) => setSel((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));
  const sortBy = (col: string) => {
    if (sort === col) setOrder(order === "desc" ? "asc" : "desc");
    else { setSort(col); setOrder(col === "name" || col === "risk" ? "asc" : "desc"); }
  };
  const th = (col: string, label: string, right = false) => (
    <th className={right ? "r" : undefined}>
      <button onClick={() => sortBy(col)} aria-sort={sort === col ? (order === "asc" ? "ascending" : "descending") : undefined}>
        {label}{sort === col ? (order === "asc" ? " ↑" : " ↓") : ""}
      </button>
    </th>
  );
  const visibleIds = data?.items.map((s) => s.id) ?? [];
  const allVisibleSelected = visibleIds.length > 0 && visibleIds.every((id) => selSet.has(id));
  const selDeletable = selInfo?.items.filter((i) => DELETABLE.has(i.kind)).length ?? 0;

  return (
    <>
      <PageHeader title={t("Suggestions", "Forslag")}
        lede={t("Ranked by priority. Open a row to see exactly how the points were calculated, which files are affected and what it means for Radarr, Sonarr and Plex.",
          "Rangert etter prioritet. Åpne en rad for å se nøyaktig hvordan poengene er regnet ut, hvilke filer som berøres og hva det betyr for Radarr, Sonarr og Plex.")}>
        <a className="btn small" href={`/api/export/suggestions.csv${qs({ min_score: data?.min_score })}`}>{t("Export CSV", "Eksporter CSV")}</a>
      </PageHeader>

      <div className="toolbar">
        <Seg label={t("Scope", "Utvalg")} value={scope} onChange={(v) => setScope(v)} options={[
          { value: "recommended", label: t("Recommended", "Anbefalt") },
          { value: "all", label: t("All", "Alle") },
        ]} />
        <input type="search" placeholder={t("Search title or path", "Søk i tittel eller sti")} value={q} onChange={(e) => setQ(e.target.value)} aria-label={t("Search", "Søk")} />
        <select value={kind} onChange={(e) => setKind(e.target.value)} aria-label={t("Type", "Type")}>
          <option value="">{t("All types", "Alle typer")}</option>
          {KINDS.map((k) => <option key={k} value={k}>{kindLabel(k)}</option>)}
        </select>
        <Seg label={t("Risk", "Risiko")} value={risk} onChange={setRisk} options={[
          { value: "", label: t("Any risk", "All risiko") }, { value: "low", label: t("Low", "Lav") },
          { value: "medium", label: t("Medium", "Middels") }, { value: "high", label: t("High", "Høy") },
        ]} />
        <select value={library} onChange={(e) => setLibrary(e.target.value)} aria-label={t("Library", "Bibliotek")}>
          <option value="">{t("All libraries", "Alle bibliotek")}</option>
          {settings.data?.libraries.map((l) => <option key={l.name} value={l.name}>{l.name}</option>)}
        </select>
        {requesters.data && requesters.data.items.length > 0 && (
          <select value={requester} onChange={(e) => setRequester(e.target.value)} aria-label={t("Requested by", "Etterspurt av")}>
            <option value="">{t("All requests", "Alle forespørsler")}</option>
            {requesters.data.items.map((r) => <option key={r.name} value={r.name}>{t("Requested by", "Etterspurt av")} {r.name} ({r.titles})</option>)}
          </select>
        )}
        {scope === "all" && (
          <label className="check small">{t("Min. priority", "Min. prioritet")}
            <input type="number" min={0} max={100} placeholder={data ? String(data.min_score) : ""} value={minScore} onChange={(e) => setMinScore(e.target.value)} />
          </label>
        )}
      </div>

      <ErrorNote error={error} />
      {data && (
        <p className="small muted">
          {scope === "recommended"
            ? t(`${num(data.total)} recommended suggestions (priority ≥ ${data.recommended_score}, not high risk) free ${bytes(data.filtered_savings.freed)} without double counting.`,
              `${num(data.total)} anbefalte forslag (prioritet ≥ ${data.recommended_score}, ikke høy risiko) frigjør ${bytes(data.filtered_savings.freed)} uten dobbelttelling.`)
            : t(`${num(data.total)} suggestions free ${bytes(data.filtered_savings.freed)} without double counting.`,
              `${num(data.total)} forslag frigjør ${bytes(data.filtered_savings.freed)} uten dobbelttelling.`)}
          {data.filtered_savings.naive_sum && data.filtered_savings.naive_sum > data.filtered_savings.freed
            ? t(` (The rows add up to ${bytes(data.filtered_savings.naive_sum)} because some overlap.)`, ` (Radene summerer til ${bytes(data.filtered_savings.naive_sum)} fordi noen overlapper.)`) : ""}
          {loading && t(" Updating…", " Oppdaterer…")}
        </p>
      )}

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th style={{ width: 36 }}>
                <input type="checkbox" aria-label={t("Select all visible", "Velg alle synlige")} checked={allVisibleSelected}
                  onChange={() => setSel((s) => allVisibleSelected ? s.filter((id) => !visibleIds.includes(id)) : [...new Set([...s, ...visibleIds])])} />
              </th>
              {th("score", t("Priority", "Prioritet"))}
              {th("name", t("Title", "Tittel"))}
              <th>{t("Action", "Handling")}</th>
              {th("last_played", t("Watched", "Seing"))}
              {th("risk", t("Risk", "Risiko"))}
              {th("savings", t("Freed", "Frigjøres"), true)}
            </tr>
          </thead>
          <tbody>
            {data?.items.map((s) => {
              const name = s.name || s.title_name || s.location;
              return (
                <Fragment key={s.id}>
                  <tr className={`row ${open === s.id ? "open" : ""}`}>
                    <td><input type="checkbox" checked={selSet.has(s.id)} onChange={() => toggle(s.id)} aria-label={t(`Select ${name}`, `Velg ${name}`)} /></td>
                    <td style={{ width: 70 }}><ScoreMeter score={s.score} /></td>
                    <td className="title-cell">
                      <div className="with-poster">
                        <Poster k={s.title_key} title={name} size="m" />
                        <div style={{ minWidth: 0 }}>
                          <button className="linkish" style={{ fontWeight: 560 }} onClick={() => setOpen(open === s.id ? null : s.id)} aria-expanded={open === s.id}>
                            {name}{s.year && s.kind !== "delete_season" ? ` (${s.year})` : ""}
                          </button>
                          <small>{s.library ?? t("Downloads", "Nedlastinger")}{s.best_resolution ? `, ${s.best_resolution}` : ""}
                            {s.radarr_id != null ? (s.monitored ? t(", monitored in Radarr", ", overvåket i Radarr") : ", Radarr") : s.sonarr_id != null ? (s.monitored ? t(", monitored in Sonarr", ", overvåket i Sonarr") : ", Sonarr") : ""}</small>
                        </div>
                      </div>
                    </td>
                    <td>{s.label}<div><span className="tag">{kindLabel(s.kind)}</span></div></td>
                    <td className="small"><HistoryLine h={s.history} />{s.requests?.length ? <div><RequestedBy requests={s.requests} /></div> : null}</td>
                    <td><RiskPill risk={s.risk} /></td>
                    <td className="r num" style={{ fontWeight: 600 }}>{bytes(s.savings)}{s.savings_note && <div className="small faint" style={{ fontWeight: 400, maxWidth: 220, whiteSpace: "normal" }}>{s.savings_note}</div>}</td>
                  </tr>
                  {open === s.id && (
                    <tr className="detail"><td colSpan={7}><SuggestionDetail id={s.id} />
                      <p style={{ marginBottom: 0, display: "flex", gap: 10, flexWrap: "wrap" }}>
                        {s.title_key && <button className="btn small" onClick={() => openTitle(s.title_key!)}>{t("Open title", "Åpne tittel")}</button>}
                        {DELETABLE.has(s.kind) && (s.radarr_id != null || s.sonarr_id != null) &&
                          <button className="btn small danger" onClick={() => setDeleting([s.id])}>{s.kind === "delete_season" ? t("Delete the season…", "Slett sesongen…") : t("Delete…", "Slett…")}</button>}
                        {s.kind === "replace" && <a className="btn small" href="#/quality">{t("Swap quality…", "Bytt kvalitet…")}</a>}
                        {(s.kind === "remove_copy" || s.kind === "remove_versions") && <a className="btn small" href="#/duplicates">{t("Go to Duplicates", "Gå til Duplikater")}</a>}
                        {s.kind === "download" && <a className="btn small" href="#/downloads">{t("Go to Downloads", "Gå til Nedlastinger")}</a>}
                      </p>
                    </td></tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
      {data && data.items.length === 0 && (
        <div className="empty">{scope === "recommended"
          ? t("No recommended suggestions with these filters. Switch to «All» to see everything.", "Ingen anbefalte forslag med disse filtrene. Velg «Alle» for å se alt.")
          : t("No suggestions with these filters. Try a lower minimum priority or clear the search.", "Ingen forslag med disse filtrene. Prøv lavere minimumsprioritet eller fjern søket.")}</div>
      )}
      {data && data.total > data.items.length && (
        <p><button className="btn" onClick={() => setLimit(limit + 200)}>{t(`Show more (${num(data.total - data.items.length)} left)`, `Vis flere (${num(data.total - data.items.length)} igjen)`)}</button></p>
      )}

      {sel.length > 0 && (
        <Tray figure={bytes(selInfo?.freed ?? 0)} note={t(`freed by ${sel.length} selected`, `frigjøres av ${sel.length} valgte`)}>
          <span className="small muted" style={{ maxWidth: 420 }}>
            {selInfo && selInfo.naive_sum && selInfo.naive_sum > selInfo.freed ? t(`Overlap removed: ${bytes(selInfo.naive_sum - selInfo.freed)}. `, `Overlapp fjernet: ${bytes(selInfo.naive_sum - selInfo.freed)}. `) : ""}
            {selInfo && selInfo.held > 0 ? t(`${bytes(selInfo.held)} held by hardlinks outside the selection. `, `${bytes(selInfo.held)} holdes av hardlinker utenfor utvalget. `) : ""}
            {!status?.actions_enabled ? t("Deletion is off – the next step shows how to switch it on.", "Sletting er av – neste steg viser hvordan du slår det på.") : ""}
          </span>
          <button className="btn" onClick={() => setSel([])}>{t("Clear", "Tøm")}</button>
          <button className="btn danger" onClick={() => setDeleting(sel)}>{t(`Delete ${selDeletable || ""} selected…`, `Slett ${selDeletable || ""} valgte…`).replace("  ", " ")}</button>
        </Tray>
      )}
      {deleting && (
        <DeleteDialog ids={deleting} onClose={() => setDeleting(null)}
          onDone={(done) => setSel((cur) => cur.filter((id) => !done.includes(id)))} />
      )}
    </>
  );
}
