import { useEffect, useState } from "react";
import { api } from "../api";
import { bytes, fileName } from "../format";

type PlanItem = { key: string; name: string; ok: boolean; reason: string | null; folder?: string; size: number; freed?: number;
  files: { path: string; size: number }[]; calls?: { rating_key: string; media_id: string | null; label: string }[]; kept?: number };
type Plan = { enabled: boolean; items: PlanItem[]; count: number; token: string; freed?: number; files?: number; calls?: number };
type Res = { results: { key: string; status: string; detail: string }[]; done: number; failed: number };

function pl(n: number, one: string, many: string) { return `${n} ${n === 1 ? one : many}`; }

/**
 * mode = "disk":  slett mapper som bare ligger på disk (ikke Radarr/Sonarr, ikke Plex).
 * mode = "plex":  fjern Plex-oppføringer der filene mangler på disk.
 */
export default function CleanupDialog({ mode, keys, onClose, onDone }: { mode: "disk" | "plex"; keys: string[]; onClose: () => void; onDone: () => void }) {
  const base = mode === "disk" ? "/api/plex-check/delete" : "/api/plex-check/remove";
  const [plan, setPlan] = useState<Plan | null>(null);
  const [res, setRes] = useState<Res | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  useEffect(() => { api.post<Plan>(`${base}/plan`, { keys }).then(setPlan).catch((e) => setError(String(e.message))); }, [keys, base]);
  const run = async () => {
    if (!plan) return;
    setBusy(true); setError(null);
    try { setRes(await api.post<Res>(`${base}/execute`, { keys, token: plan.token })); onDone(); }
    catch (e) { setError(String((e as Error).message)); } finally { setBusy(false); }
  };
  const ok = plan?.items.filter((i) => i.ok) ?? [];
  const no = plan?.items.filter((i) => !i.ok) ?? [];
  const names = Object.fromEntries((plan?.items ?? []).map((i) => [i.key, i.name]));
  const verb = mode === "disk" ? "Slett" : "Fjern fra Plex:";
  return (
    <>
      <div className="drawer-bg" onClick={() => !busy && onClose()} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-label={mode === "disk" ? "Slett fra disk" : "Fjern fra Plex"}>
        <button className="btn small close" onClick={onClose} disabled={busy}>Lukk</button>
        {res ? (
          <>
            <h1>{res.failed ? "Delvis fullført" : "Ferdig"}</h1>
            <p className="lede">{mode === "disk"
              ? <>{pl(res.done, "mappe", "mapper")} slettet fra disk. En full oppdatering er startet.</>
              : <>{pl(res.done, "tittel", "titler")} fjernet fra Plex. En synk er startet.</>}</p>
            <table className="compact"><tbody>{res.results.map((r) => <tr key={r.key}><td><i className={`dot ${r.status === "utført" ? "ok" : r.status === "feilet" ? "bad" : "off"}`} />{names[r.key] ?? r.key}</td><td className="small muted">{r.detail}</td></tr>)}</tbody></table>
            <p><button className="btn primary" onClick={onClose}>Ferdig</button></p>
          </>
        ) : (
          <>
            <h1>{verb} {pl(ok.length, "tittel", "titler")}</h1>
            {error && <div className="notice err">{error}</div>}
            {!plan ? <p className="muted">Lager oppsummering…</p> : !plan.enabled ? (
              <div className="notice">{mode === "disk"
                ? <>Sletting av filer er slått av. Slå på «Tillat sletting av filer» under <a href="#/innstillinger" onClick={onClose}>Innstillinger → Sletting</a>, og fjern <code>:ro</code> på mappen i appens YAML.</>
                : <>Sletting via tjenestene er slått av. Slå den på under <a href="#/innstillinger" onClick={onClose}>Innstillinger → Sletting</a>.</>}</div>
            ) : (
              <>
                <p className="lede">{ok.length === 0 ? "Ingen av de valgte kan tas med." : mode === "disk"
                  ? <>Mappene slettes fra disk med alt innhold ({pl(plan.files ?? 0, "fil", "filer")}). <b>{bytes(plan.freed ?? 0)}</b> frigjøres. De ligger verken i Radarr, Sonarr eller Plex. Dette kan ikke angres.</>
                  : <>Oppføringene fjernes fra Plex-biblioteket. Filene finnes ikke på disk, så ingenting slettes der. Seerhistorikken i Tautulli beholdes.</>}</p>
                {mode === "plex" && ok.length > 0 && <p className="small muted">Appen kontrollerer rett før hvert kall at ingen av filene finnes. Krever at «Allow media deletion» er på i Plex → Settings → Library.</p>}
                <table className="compact"><tbody>{ok.map((i) => (
                  <tr key={i.key}>
                    <td>
                      <button className="linkish" onClick={() => setOpen(open === i.key ? null : i.key)}>{i.name}</button>
                      <div className="small muted">{mode === "disk" ? i.folder : i.calls!.length === 1 && i.calls![0].label === "Hele serien" ? "Hele serien" : `${pl(i.calls!.length, "oppføring", "oppføringer")}${i.kept ? `, ${i.kept} fil(er) som finnes beholdes` : ""}`}</div>
                      {open === i.key && <ul className="small muted" style={{ paddingLeft: 16, margin: "4px 0" }}>
                        {mode === "disk" ? i.files.map((f) => <li key={f.path}>{fileName(f.path)} ({bytes(f.size)})</li>) : i.calls!.map((c) => <li key={c.rating_key + c.media_id}>{c.label}</li>)}
                      </ul>}
                    </td>
                    <td className="r num">{mode === "disk" ? bytes(i.freed ?? 0) : ""}</td>
                  </tr>
                ))}</tbody></table>
                {no.length > 0 && <details style={{ marginTop: 12 }} open={ok.length === 0}><summary className="small muted">{no.length} tas ikke med</summary><ul className="conseq small">{no.map((i) => <li key={i.key}>{i.name}: {i.reason}</li>)}</ul></details>}
                {ok.length > 0 && <p style={{ marginTop: 20 }}><button className="btn danger" onClick={run} disabled={busy}>{busy ? "Arbeider…" : mode === "disk"
                  ? `Slett ${pl(ok.length, "mappe", "mapper")} fra disk (${bytes(plan.freed ?? 0)})`
                  : `Fjern ${pl(ok.length, "tittel", "titler")} fra Plex`}</button></p>}
              </>
            )}
          </>
        )}
      </aside>
    </>
  );
}
