import { useEffect, useState } from "react";
import { api } from "../api";
import { bytes, KIND_LABEL } from "../format";
import { RiskPill } from "./common";

type PlanItem = { id: string; label: string; location?: string; kind?: string; risk?: string; savings?: number;
  executable: boolean; reason?: string; how?: string; service?: string };
type Plan = { enabled: boolean; items: PlanItem[]; executable: number; freed: number; held: number; token: string };
type Result = { results: { id: string; label: string; status: string; detail: string }[]; done: number; failed: number; freed_estimate: number };

export default function DeleteDialog({ ids, onClose, onDone }: { ids: string[]; onClose: () => void; onDone: (deleted: string[]) => void }) {
  const [plan, setPlan] = useState<Plan | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Result | null>(null);

  useEffect(() => {
    api.post<Plan>("/api/actions/plan", { ids }).then(setPlan).catch((e) => setError(String(e.message)));
  }, [ids]);
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && !busy && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [busy, onClose]);

  const run = async () => {
    if (!plan) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.post<Result>("/api/actions/execute", { ids, token: plan.token });
      setResult(r);
      onDone(r.results.filter((x) => x.status === "utført").map((x) => x.id));
    } catch (e) {
      setError(String((e as Error).message));
    } finally {
      setBusy(false);
    }
  };

  const exe = plan?.items.filter((i) => i.executable) ?? [];
  const skip = plan?.items.filter((i) => !i.executable) ?? [];

  return (
    <>
      <div className="drawer-bg" onClick={() => !busy && onClose()} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-label="Slett valgte">
        <button className="btn small close" onClick={onClose} disabled={busy}>Lukk</button>
        {result ? (
          <>
            <h1>{result.failed ? "Sletting delvis fullført" : "Slettet"}</h1>
            <p className="lede">
              {result.done} slettet{result.failed ? `, ${result.failed} feilet` : ""}. Omtrent {bytes(result.freed_estimate)} frigjøres.
              En full oppdatering er startet, så tallene i appen oppdateres om litt. Plex fjerner titlene ved neste bibliotekskanning.
            </p>
            <table>
              <tbody>
                {result.results.map((r) => (
                  <tr key={r.id}>
                    <td><i className={`dot ${r.status === "utført" ? "ok" : r.status === "feilet" ? "bad" : "off"}`} />{r.label}</td>
                    <td className="small muted">{r.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p><button className="btn primary" onClick={onClose}>Ferdig</button></p>
          </>
        ) : (
          <>
            <h1>Slett {exe.length === 1 ? exe[0].label : `${exe.length} titler`}</h1>
            {error && <div className="notice err">{error}</div>}
            {!plan ? <p className="muted">Lager oppsummering…</p> : !plan.enabled ? (
              <div className="notice">Sletting er slått av. Slå den på under <a href="#/innstillinger" onClick={onClose}>Innstillinger → Sletting</a>.</div>
            ) : (
              <>
                <p className="lede">
                  {exe.length > 0
                    ? <>Slettes via Radarr og Sonarr, med filer. <b>{bytes(plan.freed)}</b> frigjøres. Dette kan ikke angres.</>
                    : "Ingen av de valgte forslagene kan slettes fra appen."}
                </p>
                {exe.length > 0 && (
                  <table>
                    <tbody>
                      {exe.map((i) => (
                        <tr key={i.id}>
                          <td>{i.label}<div className="small muted">{i.how}</div></td>
                          <td>{i.risk && <RiskPill risk={i.risk} />}</td>
                          <td className="r num">{bytes(i.savings)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
                {skip.length > 0 && (
                  <details style={{ marginTop: 16 }}>
                    <summary className="small muted">{skip.length} forslag tas ikke med</summary>
                    <ul className="conseq small">
                      {skip.map((i) => <li key={i.id}>{i.label}{i.kind ? ` (${KIND_LABEL[i.kind] ?? i.kind})` : ""}: {i.reason}</li>)}
                    </ul>
                  </details>
                )}
                {exe.length > 0 && (
                  <p style={{ marginTop: 22 }}>
                    <button className="btn danger" onClick={run} disabled={busy}>
                      {busy ? "Sletter…" : `Slett ${exe.length === 1 ? "" : `${exe.length} `}(${bytes(plan.freed)})`}
                    </button>
                  </p>
                )}
              </>
            )}
          </>
        )}
      </aside>
    </>
  );
}
