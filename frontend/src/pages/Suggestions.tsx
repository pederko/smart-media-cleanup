import { Fragment, useEffect, useMemo, useState } from "react";
import { api, qs, Requester, Savings, Suggestion } from "../api";
import { bytes, KIND_LABEL, num } from "../format";
import { ErrorNote, HistoryLine, RequestedBy, RiskPill, ScoreMeter, useFetch, useOpenTitle, useRefreshTick, Poster } from "../components/common";
import SuggestionDetail from "../components/SuggestionDetail";
import DeleteDialog from "../components/DeleteDialog";

type ListResp = { total: number; items: Suggestion[]; filtered_savings: Savings };
type SelResp = Savings & { items: { id: string; label: string; location: string; savings: number; risk: string; kind: string }[] };

const STORE = "smc.selection";

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
  const [q, setQ] = useState("");
  const [kind, setKind] = useState("");
  const [risk, setRisk] = useState("");
  const [library, setLibrary] = useState("");
  const [requester, setRequester] = useState(() => hashParam("etterspurt"));
  const [minScore, setMinScore] = useState<string>("");
  const [sort, setSort] = useState("score");
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const [limit, setLimit] = useState(100);
  const [open, setOpen] = useState<string | null>(null);
  const [sel, setSel] = useState<string[]>(loadSel);
  const [selInfo, setSelInfo] = useState<SelResp | null>(null);
  const [summary, setSummary] = useState(false);
  const [deleting, setDeleting] = useState<string[] | null>(null);
  const status = useFetch<{ actions_enabled: boolean }>("/api/status", [tick]);
  const canDelete = !!status.data?.actions_enabled;
  const DELETABLE = new Set(["delete_title", "delete_season"]);
  const [debounced, setDebounced] = useState("");

  useEffect(() => { const t = setTimeout(() => setDebounced(q), 250); return () => clearTimeout(t); }, [q]);
  const url = `/api/suggestions${qs({ q: debounced, kind, risk, library, requested_by: requester, min_score: minScore, sort, order, limit })}`;
  const requesters = useFetch<{ items: Requester[] }>("/api/requesters", [tick]);
  const { data, error, loading } = useFetch<ListResp>(url, [tick]);
  const settings = useFetch<{ analysis: { min_score: number }; libraries: { name: string }[] }>("/api/settings");

  useEffect(() => {
    try { localStorage.setItem(STORE, JSON.stringify(sel)); } catch { /* privat modus */ }
    if (!sel.length) { setSelInfo(null); return; }
    api.post<SelResp>("/api/selection", { ids: sel }).then(setSelInfo).catch(() => setSelInfo(null));
  }, [sel, tick]);

  // Fjern valg som ikke lenger finnes etter ny analyse
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
  const defaultMin = settings.data?.analysis.min_score;

  return (
    <>
      <h1>Oppryddingsforslag</h1>
      <p className="lede">Rangert etter prioritet. Åpne en rad for å se nøyaktig hvordan poengene er regnet ut, hvilke filer som berøres og hva det betyr for Radarr, Sonarr og Plex. Ingenting slettes herfra.</p>

      <div className="toolbar">
        <input type="search" placeholder="Søk i tittel eller sti" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Søk" />
        <select value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Type">
          <option value="">Alle typer</option>
          {Object.entries(KIND_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <div className="seg" role="group" aria-label="Risiko">
          {[["", "Alle"], ["lav", "Lav"], ["middels", "Middels"], ["høy", "Høy"]].map(([v, l]) => (
            <button key={v} aria-pressed={risk === v} onClick={() => setRisk(v)}>{l}</button>
          ))}
        </div>
        <select value={library} onChange={(e) => setLibrary(e.target.value)} aria-label="Bibliotek">
          <option value="">Alle bibliotek</option>
          {settings.data?.libraries.map((l) => <option key={l.name} value={l.name}>{l.name}</option>)}
        </select>
        {requesters.data && requesters.data.items.length > 0 && (
          <select value={requester} onChange={(e) => setRequester(e.target.value)} aria-label="Etterspurt av">
            <option value="">Alle forespørsler</option>
            {requesters.data.items.map((r) => <option key={r.name} value={r.name}>Etterspurt av {r.name} ({r.titles})</option>)}
          </select>
        )}
        <label className="check small">Min. prioritet
          <input type="number" min={0} max={100} placeholder={defaultMin != null ? String(defaultMin) : ""} value={minScore} onChange={(e) => setMinScore(e.target.value)} />
        </label>
        <a className="btn small" href={`/api/export/suggestions.csv${qs({ min_score: minScore || defaultMin })}`}>Eksporter CSV</a>
      </div>

      <ErrorNote error={error} />
      {data && (
        <p className="small muted">
          {num(data.total)} forslag. Frigjør til sammen {bytes(data.filtered_savings.freed)} uten dobbelttelling
          {data.filtered_savings.naive_sum && data.filtered_savings.naive_sum > data.filtered_savings.freed ? ` (summen av radene er ${bytes(data.filtered_savings.naive_sum)} fordi noen forslag overlapper)` : ""}.
          {loading && " Oppdaterer…"}
        </p>
      )}

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th style={{ width: 36 }}>
                <input type="checkbox" aria-label="Velg alle synlige" checked={allVisibleSelected}
                  onChange={() => setSel((s) => allVisibleSelected ? s.filter((id) => !visibleIds.includes(id)) : [...new Set([...s, ...visibleIds])])} />
              </th>
              {th("score", "Prioritet")}
              {th("name", "Tittel")}
              <th>Handling</th>
              {th("last_played", "Seing")}
              {th("risk", "Risiko")}
              {th("savings", "Frigjøres", true)}
            </tr>
          </thead>
          <tbody>
            {data?.items.map((s) => (
              <Fragment key={s.id}>
                <tr className={`row ${open === s.id ? "open" : ""}`}>
                  <td><input type="checkbox" checked={selSet.has(s.id)} onChange={() => toggle(s.id)} aria-label={`Velg ${s.label}`} /></td>
                  <td style={{ width: 70 }}><ScoreMeter score={s.score} /></td>
                  <td className="title-cell">
                    <div className="with-poster">
                      <Poster k={s.title_key} title={s.label} size="m" />
                      <div style={{ minWidth: 0 }}>
                        <button className="btn small" style={{ border: 0, background: "none", padding: 0, fontWeight: 560, textAlign: "left" }}
                          onClick={() => setOpen(open === s.id ? null : s.id)} aria-expanded={open === s.id}>
                          {s.label}{s.year ? ` (${s.year})` : ""}
                        </button>
                        <small>{s.library ?? "Nedlastinger"}{s.best_resolution ? `, ${s.best_resolution}` : ""}{s.radarr_id != null ? (s.monitored ? ", overvåket i Radarr" : ", Radarr") : s.sonarr_id != null ? (s.monitored ? ", overvåket i Sonarr" : ", Sonarr") : ""}</small>
                      </div>
                    </div>
                  </td>
                  <td>{s.action}<div><span className="tag">{KIND_LABEL[s.kind] ?? s.kind}</span></div></td>
                  <td className="small"><HistoryLine h={s.history} />{s.requests?.length ? <div><RequestedBy requests={s.requests} /></div> : null}</td>
                  <td><RiskPill risk={s.risk} /></td>
                  <td className="r num" style={{ fontWeight: 600 }}>{bytes(s.savings)}{s.savings_note && <div className="small faint" style={{ fontWeight: 400, maxWidth: 220, whiteSpace: "normal" }}>{s.savings_note}</div>}</td>
                </tr>
                {open === s.id && (
                  <tr className="detail"><td colSpan={7}><SuggestionDetail id={s.id} />
                    <p style={{ marginBottom: 0, display: "flex", gap: 10, flexWrap: "wrap" }}>
                      {s.title_key && <button className="btn small" onClick={() => openTitle(s.title_key!)}>Åpne tittel</button>}
                      {DELETABLE.has(s.kind) && (s.radarr_id != null || s.sonarr_id != null) &&
                        <button className="btn small danger" onClick={() => setDeleting([s.id])}>{s.kind === "delete_season" ? "Slett sesongen…" : "Slett…"}</button>}
                    </p>
                  </td></tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
      {data && data.items.length === 0 && (
        <div className="empty">Ingen forslag med disse filtrene. Prøv lavere minimumsprioritet eller fjern søket.</div>
      )}
      {data && data.total > data.items.length && (
        <p><button className="btn" onClick={() => setLimit(limit + 200)}>Vis flere ({num(data.total - data.items.length)} igjen)</button></p>
      )}

      {sel.length > 0 && (
        <div className="tray" role="region" aria-label="Valgte forslag">
          <div>
            <div className="big">{bytes(selInfo?.freed ?? 0)}</div>
            <div className="small muted">frigjøres av {sel.length} valgte forslag</div>
          </div>
          <div className="small muted grow">
            {selInfo && selInfo.naive_sum && selInfo.naive_sum > selInfo.freed ? `Overlapp fjernet: ${bytes(selInfo.naive_sum - selInfo.freed)}. ` : ""}
            {selInfo && selInfo.held > 0 ? `${bytes(selInfo.held)} holdes av hardlinker utenfor utvalget. ` : ""}
            {canDelete ? "Filmer og serier i Radarr/Sonarr kan slettes herfra. Resten gjøres manuelt." : "Sletting er av – slå den på under Innstillinger → Sletting, eller slett i Radarr/Sonarr."}
          </div>
          <button className="btn" onClick={() => setSummary(true)}>Vis oppsummering</button>
          <button className="btn danger" onClick={() => setDeleting(sel)}>Slett valgte…</button>
          <button className="btn" onClick={() => setSel([])}>Tøm utvalget</button>
        </div>
      )}

      {summary && selInfo && (
        <>
          <div className="drawer-bg" onClick={() => setSummary(false)} />
          <aside className="drawer" role="dialog" aria-modal="true" aria-label="Oppsummering av utvalget">
            <button className="btn small close" onClick={() => setSummary(false)}>Lukk</button>
            <h1>Oppsummering</h1>
            <p className="lede">{selInfo.count} forslag, {num(selInfo.files)} filer. {bytes(selInfo.freed)} frigjøres når alt er gjennomført.</p>
            <table>
              <thead><tr><th>Forslag</th><th>Risiko</th><th className="r">Alene</th></tr></thead>
              <tbody>
                {selInfo.items.map((i) => (
                  <tr key={i.id}><td>{i.label}<div className="path">{i.location}</div><span className="tag">{KIND_LABEL[i.kind] ?? i.kind}</span></td><td><RiskPill risk={i.risk} /></td><td className="r num">{bytes(i.savings)}</td></tr>
                ))}
              </tbody>
            </table>
            <p className="small muted">Kolonnen «Alene» viser hvert forslag for seg; totalen over teller hver fil én gang. Denne versjonen sletter ingenting. Bruk listen som arbeidsliste i Radarr/Sonarr, eller eksporter CSV.</p>
          </aside>
        </>
      )}
      {deleting && (
        <DeleteDialog ids={deleting} onClose={() => setDeleting(null)}
          onDone={(done) => setSel((cur) => cur.filter((id) => !done.includes(id)))} />
      )}
    </>
  );
}
