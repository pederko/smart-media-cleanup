import { useEffect, useState } from "react";
import { api } from "../api";
import { bytes, kindLabel } from "../format";
import { t } from "../i18n";
import { Drawer, Loading, RiskPill, statusLabel, StatusDot, SwitchedOff } from "./common";

type PlanItem = { id: string; label: string; name: string; location?: string; kind?: string; risk?: string; savings?: number;
  executable: boolean; reason?: string; how?: string; service?: string };
type Plan = { enabled: boolean; items: PlanItem[]; executable: number; freed: number; held: number; token: string };
type Result = { results: { id: string; label: string; name: string; status: string; detail: string }[]; done: number; failed: number; freed_estimate: number };

/** Delete titles and seasons through Radarr/Sonarr: summary first, one confirmation. */
export default function DeleteDialog({ ids, onClose, onDone }: { ids: string[]; onClose: () => void; onDone: (deleted: string[]) => void }) {
  const [plan, setPlan] = useState<Plan | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Result | null>(null);

  useEffect(() => {
    api.post<Plan>("/api/actions/plan", { ids }).then(setPlan).catch((e) => setError(String(e.message)));
  }, [ids]);

  const run = async () => {
    if (!plan) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.post<Result>("/api/actions/execute", { ids, token: plan.token });
      setResult(r);
      onDone(r.results.filter((x) => x.status === "done").map((x) => x.id));
    } catch (e) {
      setError(String((e as Error).message));
    } finally {
      setBusy(false);
    }
  };

  const exe = plan?.items.filter((i) => i.executable) ?? [];
  const skip = plan?.items.filter((i) => !i.executable) ?? [];

  return (
    <Drawer label={t("Delete selected", "Slett valgte")} onClose={onClose} busy={busy}>
      {result ? (
        <>
          <h1>{result.failed ? t("Partly done", "Delvis fullført") : t("Deleted", "Slettet")}</h1>
          <p className="lede">
            {t(`${result.done} deleted${result.failed ? `, ${result.failed} failed` : ""}. About ${bytes(result.freed_estimate)} is freed. A full refresh has started, and Plex removes the titles at its next library scan.`,
              `${result.done} slettet${result.failed ? `, ${result.failed} feilet` : ""}. Omtrent ${bytes(result.freed_estimate)} frigjøres. En full oppdatering er startet, og Plex fjerner titlene ved neste bibliotekskanning.`)}
          </p>
          <table><tbody>
            {result.results.map((r) => (
              <tr key={r.id}><td><StatusDot status={r.status} />{r.name}</td><td className="small muted">{statusLabel(r.status)}: {r.detail}</td></tr>
            ))}
          </tbody></table>
          <p><button className="btn primary" onClick={onClose}>{t("Done", "Ferdig")}</button></p>
        </>
      ) : (
        <>
          <h1>{exe.length === 1 ? `${exe[0].label}: ${exe[0].name}` : t(`Delete ${exe.length} titles`, `Slett ${exe.length} titler`)}</h1>
          {error && <div className="notice err">{error}</div>}
          {!plan ? <Loading /> : !plan.enabled ? <SwitchedOff what="services" onClose={onClose} /> : (
            <>
              <p className="lede">
                {exe.length > 0
                  ? <>{t("Deleted through Radarr and Sonarr, with their files.", "Slettes via Radarr og Sonarr, med filene.")} <b>{bytes(plan.freed)}</b> {t("is freed. This cannot be undone.", "frigjøres. Dette kan ikke angres.")}</>
                  : t("None of the selected suggestions can be deleted from the app.", "Ingen av de valgte forslagene kan slettes fra appen.")}
              </p>
              {exe.length > 0 && (
                <table><tbody>
                  {exe.map((i) => (
                    <tr key={i.id}>
                      <td>{i.name}<div className="small muted">{i.how}</div></td>
                      <td>{i.risk && <RiskPill risk={i.risk} />}</td>
                      <td className="r num">{bytes(i.savings)}</td>
                    </tr>
                  ))}
                </tbody></table>
              )}
              {skip.length > 0 && (
                <details style={{ marginTop: 16 }} open={exe.length === 0}>
                  <summary className="small muted">{t(`${skip.length} not included`, `${skip.length} tas ikke med`)}</summary>
                  <ul className="conseq small">
                    {skip.map((i) => <li key={i.id}>{i.name}{i.kind ? ` (${kindLabel(i.kind)})` : ""}: {i.reason}</li>)}
                  </ul>
                </details>
              )}
              {exe.length > 0 && (
                <p style={{ marginTop: 22 }}>
                  <button className="btn danger" onClick={run} disabled={busy}>
                    {busy ? t("Deleting…", "Sletter…") : t(`Delete ${exe.length === 1 ? "" : `${exe.length} `}(${bytes(plan.freed)})`, `Slett ${exe.length === 1 ? "" : `${exe.length} `}(${bytes(plan.freed)})`)}
                  </button>
                </p>
              )}
            </>
          )}
        </>
      )}
    </Drawer>
  );
}
