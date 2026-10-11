import { useEffect, useState } from "react";
import { api, qs } from "../api";
import { ago, bytes, num } from "../format";
import { ErrorNote, useFetch, useOpenTitle, useRefreshTick } from "../components/common";

type Item = { name: string; path: string; library: string; is_dir: boolean; files: number; videos: number; size: number;
  freed: number; mtime: number; age_days: number; status: string; advice: string; why: string;
  title_key: string | null; title_name: string | null };
type Bucket = { count: number; size: number; freed: number };
type Resp = { libraries: string[]; summary: { count: number; size: number; by_status: Record<string, Bucket>; by_advice: Record<string, Bucket> };
  items: Item[]; files_enabled: boolean; writable: Record<string, boolean> };

const STATUS: Record<string, string> = { kopiert: "Kopi i biblioteket", hardlenket: "Hardlenket", ikke_importert: "Ikke importert", uten_video: "Uten video" };
const ADVICE: Record<string, [string, string]> = { slett: ["Kan slettes", "risk-lav"], vurder: ["Vurder", "risk-middels"], behold: ["Behold", "muted"] };

function pl(n: number, one: string, many: string) { return `${num(n)} ${n === 1 ? one : many}`; }

export default function DownloadsPage() {
  const tick = useRefreshTick();
  const openTitle = useOpenTitle();
  const [advice, setAdvice] = useState("");
  const [status, setStatus] = useState("");
  const [sort, setSort] = useState("size");
  const [sel, setSel] = useState<string[]>([]);
  const [dialog, setDialog] = useState(false);
  const { data, error, reload } = useFetch<Resp>(`/api/downloads${qs({ advice, status, sort })}`, [tick]);
  const s = data?.summary;
  const a = (k: string) => s?.by_advice[k] ?? { count: 0, size: 0, freed: 0 };
  const st = (k: string) => s?.by_status[k] ?? { count: 0, size: 0, freed: 0 };
  const ro = data ? data.libraries.filter((l) => data.writable[l] === false) : [];
  const items = data?.items ?? [];
  const selFreed = items.filter((i) => sel.includes(i.path)).reduce((x, i) => x + i.freed, 0);
  const deletable = items.filter((i) => i.status !== "hardlenket");

  return (
    <>
      <h1>Nedlastinger</h1>
      <ErrorNote error={error} />
      {s && (
        <section className="brief">
          <p className="brief-lead">
            {data!.libraries.join(" og ")} inneholder <b>{pl(s.count, "oppføring", "oppføringer")}</b> på <b>{bytes(s.size)}</b>.{" "}
            {a("slett").count > 0 && <>{pl(a("slett").count, "kan", "kan")} trygt slettes og frigjør <b>{bytes(a("slett").freed)}</b>.</>}
          </p>
          <ul className="brief-points">
            {st("kopiert").count > 0 && <li><button className="linkish" onClick={() => { setStatus("kopiert"); setAdvice(""); }}>{pl(st("kopiert").count, "nedlasting", "nedlastinger")}</button> finnes også som kopi i biblioteket ({bytes(st("kopiert").freed)} kan frigjøres).</li>}
            {st("hardlenket").count > 0 && <li><button className="linkish" onClick={() => { setStatus("hardlenket"); setAdvice(""); }}>{pl(st("hardlenket").count, "er hardlenket", "er hardlenket")}</button> til biblioteket og tar ikke ekstra plass ({bytes(st("hardlenket").size)}).</li>}
            {st("ikke_importert").count > 0 && <li><button className="linkish" onClick={() => { setStatus("ikke_importert"); setAdvice(""); }}>{pl(st("ikke_importert").count, "er ikke importert", "er ikke importert")}</button> ({bytes(st("ikke_importert").size)}) – sjekk om de er glemt eller feilet.</li>}
            {st("uten_video").count > 0 && <li>{pl(st("uten_video").count, "inneholder", "inneholder")} ingen video – rester etter nedlasting ({bytes(st("uten_video").size)}).</li>}
            {a("behold").count > 0 && <li>{pl(a("behold").count, "er nylig endret", "er nylig endret")} eller hardlenket, og bør få ligge.</li>}
          </ul>
          <p className="small muted">Ligger noe fortsatt til deling i qBittorrent, vil torrenten melde at filene mangler etter sletting. Fjern den da i qBittorrent.</p>
          {data && !data.files_enabled && <div className="notice">Sletting av filer er av. Slå den på under <a href="#/innstillinger">Innstillinger → Sletting</a>.</div>}
          {data && data.files_enabled && ro.length > 0 && <div className="notice">{ro.join(", ")} er montert med <code>:ro</code>. Fjern <code>:ro</code> i appens YAML for å kunne slette herfra.</div>}
        </section>
      )}

      <div className="toolbar" style={{ marginTop: 28 }}>
        <div className="seg" role="group" aria-label="Anbefaling">
          {[["", "Alle"], ["slett", "Kan slettes"], ["vurder", "Vurder"], ["behold", "Behold"]].map(([v, l]) => (
            <button key={v} aria-pressed={advice === v && !status} onClick={() => { setAdvice(v); setStatus(""); }}>{l}{v && s ? ` (${a(v).count})` : ""}</button>
          ))}
        </div>
        <select value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sorter">
          <option value="size">Størst</option>
          <option value="freed">Mest å frigjøre</option>
          <option value="age">Eldst</option>
          <option value="name">Navn</option>
        </select>
        {status && <button className="btn small" onClick={() => setStatus("")}>Vis alle statuser</button>}
        {deletable.length > 0 && <button className="btn small" onClick={() => setSel([...new Set([...sel, ...items.filter((i) => i.advice === "slett").map((i) => i.path)])])}>Velg alle som kan slettes</button>}
      </div>

      <div className="table-wrap">
        <table>
          <thead><tr><th style={{ width: 36 }} /><th>Navn</th><th>Status</th><th>Anbefaling</th><th>Endret</th><th className="r">Størrelse</th><th className="r">Frigjøres</th></tr></thead>
          <tbody>
            {items.map((i) => (
              <tr key={i.path} className="row">
                <td>{i.status !== "hardlenket" && <input type="checkbox" checked={sel.includes(i.path)} aria-label={`Velg ${i.name}`}
                  onChange={() => setSel(sel.includes(i.path) ? sel.filter((x) => x !== i.path) : [...sel, i.path])} />}</td>
                <td className="title-cell">
                  {i.name}
                  <small>{i.is_dir ? `Mappe, ${pl(i.files, "fil", "filer")}` : "Fil"}{i.title_key && <> – <button className="linkish" onClick={() => openTitle(i.title_key!)}>{i.title_name}</button></>}</small>
                </td>
                <td><span className="tag">{STATUS[i.status] ?? i.status}</span></td>
                <td className="small"><span className={ADVICE[i.advice]?.[1]}>{ADVICE[i.advice]?.[0]}</span><div className="muted">{i.why}</div></td>
                <td className="small muted">{ago(i.mtime)}</td>
                <td className="r num">{bytes(i.size)}</td>
                <td className="r num" style={{ fontWeight: 600 }}>{bytes(i.freed)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data && items.length === 0 && <div className="empty">Ingenting i dette utvalget.</div>}

      {sel.length > 0 && (
        <div className="tray" role="region" aria-label="Valgte">
          <div><div className="big">{bytes(selFreed)}</div><div className="small muted">frigjøres av {pl(sel.length, "valgt", "valgte")}</div></div>
          <div className="grow" />
          <button className="btn" onClick={() => setSel([])}>Tøm utvalget</button>
          <button className="btn danger" onClick={() => setDialog(true)}>Slett valgte…</button>
        </div>
      )}
      {dialog && <DeleteDownloads paths={sel} onClose={() => setDialog(false)} onDone={() => { setSel([]); reload(); }} />}
    </>
  );
}

type PlanItem = Item & { ok: boolean; reason: string | null };

function DeleteDownloads({ paths, onClose, onDone }: { paths: string[]; onClose: () => void; onDone: () => void }) {
  const [plan, setPlan] = useState<{ enabled: boolean; items: PlanItem[]; count: number; freed: number; token: string } | null>(null);
  const [res, setRes] = useState<{ results: { path: string; status: string; detail: string }[]; done: number; failed: number; freed_estimate: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { api.post<typeof plan>("/api/downloads/plan", { paths }).then(setPlan).catch((e) => setError(String(e.message))); }, [paths]);
  const run = async () => {
    if (!plan) return;
    setBusy(true); setError(null);
    try { setRes(await api.post("/api/downloads/execute", { paths, token: plan.token })); onDone(); }
    catch (e) { setError(String((e as Error).message)); } finally { setBusy(false); }
  };
  const ok = plan?.items.filter((i) => i.ok) ?? [];
  const no = plan?.items.filter((i) => !i.ok) ?? [];
  return (
    <>
      <div className="drawer-bg" onClick={() => !busy && onClose()} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-label="Slett nedlastinger">
        <button className="btn small close" onClick={onClose} disabled={busy}>Lukk</button>
        {res ? (
          <>
            <h1>{res.failed ? "Delvis fullført" : "Slettet"}</h1>
            <p className="lede">{pl(res.done, "oppføring", "oppføringer")} slettet. Omtrent {bytes(res.freed_estimate)} frigjort. En full oppdatering er startet.</p>
            <table className="compact"><tbody>{res.results.map((r) => <tr key={r.path}><td><i className={`dot ${r.status === "utført" ? "ok" : r.status === "feilet" ? "bad" : "off"}`} />{r.path.split("/").pop()}</td><td className="small muted">{r.detail}</td></tr>)}</tbody></table>
            <p><button className="btn primary" onClick={onClose}>Ferdig</button></p>
          </>
        ) : (
          <>
            <h1>Slett {pl(ok.length, "oppføring", "oppføringer")}</h1>
            {error && <div className="notice err">{error}</div>}
            {!plan ? <p className="muted">Lager oppsummering…</p> : !plan.enabled ? (
              <div className="notice">Sletting av filer er slått av. Slå den på under <a href="#/innstillinger" onClick={onClose}>Innstillinger → Sletting</a>.</div>
            ) : (
              <>
                <p className="lede">{ok.length > 0 ? <>Mappene og filene slettes fra disk. <b>{bytes(plan.freed)}</b> frigjøres. Dette kan ikke angres.</> : "Ingen av de valgte kan slettes."}</p>
                {ok.some((i) => i.age_days < 14) && <div className="notice">Noe er endret de siste 14 dagene og kan fortsatt være under nedlasting, import eller deling.</div>}
                <table className="compact"><tbody>{ok.map((i) => <tr key={i.path}><td>{i.name}<div className="small muted">{STATUS[i.status]}</div></td><td className="r num">{bytes(i.freed)}</td></tr>)}</tbody></table>
                {no.length > 0 && <details style={{ marginTop: 12 }}><summary className="small muted">{no.length} tas ikke med</summary><ul className="conseq small">{no.map((i) => <li key={i.path}>{i.name}: {i.reason}</li>)}</ul></details>}
                {ok.length > 0 && <p style={{ marginTop: 20 }}><button className="btn danger" onClick={run} disabled={busy}>{busy ? "Sletter…" : `Slett ${pl(ok.length, "oppføring", "oppføringer")} (${bytes(plan.freed)})`}</button></p>}
              </>
            )}
          </>
        )}
      </aside>
    </>
  );
}
