import { useEffect, useMemo, useState } from "react";
import { api, qs } from "../api";
import { bytes, date, fileName, num } from "../format";
import { ErrorNote, Poster, useFetch, useOpenTitle, useRefreshTick } from "../components/common";

type DFile = { path: string; size: number; alloc: number | null; resolution: string | null; managed: boolean; keep: boolean;
  nlink: number; library: string | null; mtime: number | null; in_downloads: boolean; missing: boolean };
type Group = { id: string; kind: string; title_key: string | null; label: string; total: number; reclaimable: number;
  files: DFile[]; keep_reason: string | null; title_name: string | null; year: number | null; protected: number | null;
  in_downloads: boolean; libraries: string[] };
type Summary = Record<string, { groups: number; files: number; reclaimable: number; in_downloads: number; in_downloads_bytes: number }>;
type Resp = { summary: Summary; total: number; total_reclaimable: number; items: Group[]; files_enabled: boolean; writable: Record<string, boolean> };

const KINDS: [string, string][] = [["identical", "Identiske kopier"], ["versions", "Flere versjoner"], ["hardlink", "Hardlenker"]];
const HELP: Record<string, string> = {
  identical: "Samme innhold to steder (lik størrelse og delvis hash), som separate filer. Én kan fjernes uten å miste noe.",
  versions: "Samme film eller episode i ulike utgaver eller oppløsninger. Velg hvilken som skal beholdes.",
  hardlink: "Samme fil under flere navn. Tar ikke ekstra plass, og trenger ingen opprydding.",
};

function pl(n: number, one: string, many: string) { return `${num(n)} ${n === 1 ? one : many}`; }

function useDebounced(v: string) {
  const [d, setD] = useState(v);
  useEffect(() => { const t = setTimeout(() => setD(v), 250); return () => clearTimeout(t); }, [v]);
  return d;
}

export default function DuplicatesPage() {
  const tick = useRefreshTick();
  const openTitle = useOpenTitle();
  const [kind, setKind] = useState("identical");
  const [q, setQ] = useState("");
  const [where, setWhere] = useState("");
  const [sort, setSort] = useState("reclaimable");
  const [limit, setLimit] = useState(100);
  const [keep, setKeep] = useState<Record<string, string>>({});
  const [sel, setSel] = useState<string[]>([]);
  const [dialog, setDialog] = useState(false);
  const dq = useDebounced(q);
  const { data, error, reload } = useFetch<Resp>(`/api/duplicates${qs({ kind, q: dq, where, sort, limit })}`, [tick]);
  useEffect(() => { setSel([]); }, [kind]);

  const keepOf = (g: Group) => keep[g.id] ?? g.files.find((f) => f.keep)?.path ?? g.files[0]?.path;
  const freedOf = (g: Group) => {
    const k = g.files.find((f) => f.path === keepOf(g));
    return g.files.filter((f) => f.path !== k?.path && !f.managed).reduce((s, f) => s + (f.alloc ?? f.size), 0);
  };
  const groups = data?.items ?? [];
  const selectable = groups.filter((g) => g.kind !== "hardlink" && !g.protected);
  const selFreed = useMemo(() => groups.filter((g) => sel.includes(g.id)).reduce((s, g) => s + freedOf(g), 0), [sel, groups, keep]); // eslint-disable-line react-hooks/exhaustive-deps
  const s = data?.summary;
  const ro = data ? Object.entries(data.writable).filter(([, w]) => !w).map(([n]) => n) : [];

  return (
    <>
      <h1>Duplikater og versjoner</h1>
      <ErrorNote error={error} />
      {s && (
        <section className="brief">
          <p className="brief-lead">
            {s.identical.groups + s.versions.groups > 0
              ? <>Duplikater og ekstra versjoner bruker <b>{bytes(s.identical.reclaimable + s.versions.reclaimable)}</b> som kan frigjøres. Lik tittel alene regnes aldri som duplikat.</>
              : <>Ingen duplikater eller ekstra versjoner funnet.</>}
          </p>
          <ul className="brief-points">
            {s.identical.groups > 0 && <li><button className="linkish" onClick={() => setKind("identical")}>{pl(s.identical.groups, "identisk kopi", "identiske kopier")}</button> ({bytes(s.identical.reclaimable)}) – trygt å rydde, innholdet finnes fortsatt.
              {s.identical.in_downloads > 0 && <> {num(s.identical.in_downloads)} av dem ligger i nedlastingsmappen ({bytes(s.identical.in_downloads_bytes)}).</>}</li>}
            {s.versions.groups > 0 && <li><button className="linkish" onClick={() => setKind("versions")}>{pl(s.versions.groups, "tittel", "titler")} med flere versjoner</button> ({bytes(s.versions.reclaimable)}) – velg hvilken som beholdes.</li>}
            {s.hardlink.groups > 0 && <li>{pl(s.hardlink.groups, "hardlenke", "hardlenker")} tar ikke ekstra plass.</li>}
          </ul>
          {data && !data.files_enabled && (
            <div className="notice">Sletting av duplikatfiler er av. Den slås på under <a href="#/innstillinger">Innstillinger → Sletting</a>, og krever at mappene er montert med skrivetilgang.</div>
          )}
          {data && data.files_enabled && ro.length > 0 && (
            <div className="notice">Montert uten skrivetilgang (<code>:ro</code>): {ro.join(", ")}. Filer der kan ikke slettes fra appen før <code>:ro</code> fjernes i appens YAML.</div>
          )}
        </section>
      )}

      <div className="toolbar" style={{ marginTop: 28 }}>
        <div className="seg" role="group" aria-label="Type">
          {KINDS.map(([k, l]) => <button key={k} aria-pressed={kind === k} onClick={() => setKind(k)}>{l}{s ? ` (${s[k]?.groups ?? 0})` : ""}</button>)}
        </div>
        <input type="search" placeholder="Søk i tittel eller sti" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Søk" />
        <select value={where} onChange={(e) => setWhere(e.target.value)} aria-label="Hvor">
          <option value="">Alle steder</option>
          <option value="downloads">Med kopi i nedlastingsmappen</option>
          <option value="library">Bare i bibliotekene</option>
        </select>
        <select value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sorter">
          <option value="reclaimable">Mest å frigjøre</option>
          <option value="size">Størst totalt</option>
          <option value="files">Flest filer</option>
          <option value="name">Navn</option>
        </select>
      </div>
      <p className="muted small">{HELP[kind]}</p>
      {data && kind !== "hardlink" && selectable.length > 0 && (
        <p className="small">
          <button className="btn small" onClick={() => setSel([...new Set([...sel, ...selectable.map((g) => g.id)])])}>{selectable.length === 1 ? "Velg den" : `Velg alle ${selectable.length} synlige`}</button>
          {data.total > groups.length && <span className="muted"> ({num(data.total)} totalt, vis flere for å velge resten)</span>}
        </p>
      )}

      <div className="grid" style={{ gap: 14 }}>
        {groups.map((g) => {
          const k = keepOf(g);
          const can = g.kind !== "hardlink" && !g.protected;
          const checked = sel.includes(g.id);
          return (
            <section key={g.id} className={`panel dupe ${checked ? "checked" : ""}`}>
              <div className="dupe-head">
                {can && <input type="checkbox" checked={checked} aria-label={`Velg ${g.title_name ?? g.label}`}
                  onChange={() => setSel(checked ? sel.filter((x) => x !== g.id) : [...sel, g.id])} />}
                <Poster k={g.title_key} title={g.title_name ?? g.label} size="m" />
                <div style={{ minWidth: 0, flex: 1 }}>
                  {g.title_key ? <button className="btn small linkish" onClick={() => openTitle(g.title_key!)}>{g.title_name}{g.year ? ` (${g.year})` : ""}</button>
                    : <b>{g.label}</b>}
                  <div className="small muted">{g.files.length} filer, {g.libraries.join(" og ")}{g.protected ? ", beskyttet" : ""}</div>
                </div>
                {g.kind !== "hardlink" && <div className="r"><div className="num" style={{ fontWeight: 600 }}>{bytes(freedOf(g))}</div><div className="small muted">frigjøres</div></div>}
              </div>
              <table className="compact">
                <tbody>
                  {g.files.map((f) => {
                    const isKeep = f.path === k;
                    return (
                      <tr key={f.path} className={isKeep ? "keep" : ""}>
                        {g.kind !== "hardlink" && (
                          <td style={{ width: 90 }}>
                            <label className="check small">
                              <input type="radio" name={`keep-${g.id}`} checked={isKeep} disabled={!can}
                                onChange={() => setKeep({ ...keep, [g.id]: f.path })} />
                              {isKeep ? <b>Beholdes</b> : <span className="muted">Slettes</span>}
                            </label>
                          </td>
                        )}
                        <td>
                          {fileName(f.path)}
                          <div className="path">{f.path.split("/").slice(0, -1).join("/")}</div>
                        </td>
                        <td className="small">
                          {f.resolution && <span className="tag">{f.resolution}</span>}{" "}
                          {f.managed && <span className="tag" title="Radarr/Sonarr kjenner denne filen. Den kan bare slettes der.">Radarr/Sonarr</span>}{" "}
                          {f.in_downloads && <span className="tag" title="Ligger i nedlastingsmappen – kan fortsatt deles i qBittorrent">Nedlasting</span>}
                        </td>
                        <td className="small muted">{date(f.mtime)}</td>
                        <td className="r num">{bytes(f.size)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {g.keep_reason && g.kind !== "hardlink" && !keep[g.id] && <p className="small muted" style={{ margin: "8px 0 0" }}>Foreslått beholdt fordi den {g.keep_reason}.</p>}
              {g.files.some((f) => f.managed && f.path !== k) && (
                <p className="small" style={{ margin: "8px 0 0", color: "var(--risk-middels)" }}>Filen Radarr/Sonarr kjenner er satt til å slettes. Den hoppes over – velg den som «Beholdes», eller slett i Radarr/Sonarr.</p>
              )}
            </section>
          );
        })}
      </div>
      {data && groups.length === 0 && <div className="empty">Ingen funnet med disse filtrene.</div>}
      {data && data.total > groups.length && <p><button className="btn" onClick={() => setLimit(limit + 200)}>Vis flere ({num(data.total - groups.length)} igjen)</button></p>}

      {sel.length > 0 && (
        <div className="tray" role="region" aria-label="Valgte grupper">
          <div><div className="big">ca. {bytes(selFreed)}</div><div className="small muted">frigjøres i {pl(sel.length, "valgt gruppe", "valgte grupper")}</div></div>
          <div className="grow small muted">Filen merket «Beholdes» blir liggende. De andre slettes fra disk.</div>
          <button className="btn" onClick={() => setSel([])}>Tøm utvalget</button>
          <button className="btn danger" onClick={() => setDialog(true)}>Slett overflødige filer…</button>
        </div>
      )}
      {dialog && (
        <DupeDeleteDialog choices={sel.map((id) => ({ id, keep: keepOf(groups.find((g) => g.id === id)!) }))}
          onClose={() => setDialog(false)} onDone={() => { setSel([]); reload(); }} />
      )}
    </>
  );
}

type PlanFile = { path: string; size: number; alloc: number | null; ok: boolean; reason: string | null; in_downloads: boolean };
type PlanItem = { id: string; label: string; keep: string; executable: boolean; reason: string | null; files: PlanFile[]; warn_downloads?: boolean };
type Plan = { enabled: boolean; writable: Record<string, boolean>; items: PlanItem[]; files: number; freed: number; held: number; token: string };

function DupeDeleteDialog({ choices, onClose, onDone }: { choices: { id: string; keep: string }[]; onClose: () => void; onDone: () => void }) {
  const [plan, setPlan] = useState<Plan | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ results: { path: string; status: string; detail: string }[]; done: number; failed: number; freed_estimate: number } | null>(null);
  useEffect(() => { api.post<Plan>("/api/duplicates/plan", { groups: choices }).then(setPlan).catch((e) => setError(String(e.message))); }, [choices]);

  const run = async () => {
    if (!plan) return;
    setBusy(true); setError(null);
    try {
      const r = await api.post<typeof result>("/api/duplicates/execute", { groups: choices, token: plan.token });
      setResult(r); onDone();
    } catch (e) { setError(String((e as Error).message)); } finally { setBusy(false); }
  };
  const okFiles = plan?.items.flatMap((i) => i.files.filter((f) => f.ok)) ?? [];
  const skipped = plan?.items.flatMap((i) => [...(i.files.length === 0 && i.reason ? [{ path: i.label, reason: i.reason }] : []), ...i.files.filter((f) => !f.ok).map((f) => ({ path: f.path, reason: f.reason }))]) ?? [];
  const dl = plan?.items.some((i) => i.warn_downloads);

  return (
    <>
      <div className="drawer-bg" onClick={() => !busy && onClose()} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-label="Slett overflødige filer">
        <button className="btn small close" onClick={onClose} disabled={busy}>Lukk</button>
        {result ? (
          <>
            <h1>{result.failed ? "Delvis fullført" : "Slettet"}</h1>
            <p className="lede">{pl(result.done, "fil", "filer")} slettet{result.failed ? `, ${result.failed} feilet` : ""}. Omtrent {bytes(result.freed_estimate)} frigjort. En full oppdatering er startet.</p>
            <table className="compact"><tbody>
              {result.results.map((r) => <tr key={r.path}><td><i className={`dot ${r.status === "utført" ? "ok" : r.status === "feilet" ? "bad" : "off"}`} />{fileName(r.path)}</td><td className="small muted">{r.detail}</td></tr>)}
            </tbody></table>
            <p><button className="btn primary" onClick={onClose}>Ferdig</button></p>
          </>
        ) : (
          <>
            <h1>Slett {okFiles.length} {okFiles.length === 1 ? "fil" : "filer"}</h1>
            {error && <div className="notice err">{error}</div>}
            {!plan ? <p className="muted">Lager oppsummering…</p> : !plan.enabled ? (
              <div className="notice">Sletting av duplikatfiler er slått av. Slå den på under <a href="#/innstillinger" onClick={onClose}>Innstillinger → Sletting</a>.</div>
            ) : (
              <>
                <p className="lede">{okFiles.length > 0 ? <>Filene slettes fra disk. <b>{bytes(plan.freed)}</b> frigjøres. Filen merket «Beholdes» i hver gruppe blir liggende. Dette kan ikke angres.</> : "Ingen av filene kan slettes."}</p>
                {dl && <div className="notice">Noen filer ligger i nedlastingsmappen. Deles de fortsatt i qBittorrent, vil torrenten melde at filene mangler – fjern den der etterpå.</div>}
                {okFiles.length > 0 && (
                  <table className="compact"><tbody>
                    {plan.items.filter((i) => i.files.some((f) => f.ok)).map((i) => (
                      <tr key={i.id}>
                        <td>{i.label}<div className="small muted">Beholder {fileName(i.keep)}</div></td>
                        <td>{i.files.filter((f) => f.ok).map((f) => <div key={f.path} className="small">{fileName(f.path)}</div>)}</td>
                        <td className="r num">{bytes(i.files.filter((f) => f.ok).reduce((s, f) => s + (f.alloc ?? f.size), 0))}</td>
                      </tr>
                    ))}
                  </tbody></table>
                )}
                {skipped.length > 0 && (
                  <details style={{ marginTop: 14 }}>
                    <summary className="small muted">{skipped.length} tas ikke med</summary>
                    <ul className="conseq small">{skipped.map((f, n) => <li key={n}>{fileName(f.path)}: {f.reason}</li>)}</ul>
                  </details>
                )}
                {okFiles.length > 0 && <p style={{ marginTop: 20 }}><button className="btn danger" onClick={run} disabled={busy}>{busy ? "Sletter…" : `Slett ${okFiles.length} ${okFiles.length === 1 ? "fil" : "filer"} (${bytes(plan.freed)})`}</button></p>}
              </>
            )}
          </>
        )}
      </aside>
    </>
  );
}
