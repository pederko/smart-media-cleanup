import { Fragment, useEffect, useState } from "react";
import { api } from "../api";
import { bytes } from "../format";
import { t } from "../i18n";
import { Drawer, Loading, statusLabel, StatusDot, SwitchedOff } from "./common";

/** Shared by Download rules and Torrents: a basket of changes, reviewed and confirmed once (plan → token → execute). */

export type Change = Record<string, unknown> & { op: string };
export type Toggle = (id: string, ch: Change | null) => void;
type PlanRow = { service: string; area: string; what: string; before?: unknown; after?: unknown; kind?: string; skipped?: boolean; bytes?: number };
type Plan = { enabled: boolean; rows: PlanRow[]; errors: { index: number; error: string }[]; changes: number; token: string };
export type ExecResult = { results: { service: string; what: string; status: string; detail: string }[]; done: number; failed: number; backup?: string | null };

export const SVC_NAME: Record<string, string> = { radarr: "Radarr", sonarr: "Sonarr", seerr: "Seerr", qbittorrent: "qBittorrent" };

/** MB per minute -> bytes for one title of the given runtime. */
export const perTitle = (mbpm: number | null | undefined, runtime: number) => (mbpm == null ? null : mbpm * runtime * 1024 * 1024);
export const gbText = (mbpm: number | null | undefined, runtime: number, unl: number) =>
  mbpm == null || mbpm >= unl ? t("Unlimited", "Ubegrenset") : bytes(perTitle(mbpm, runtime));

export function Check({ id, change, changes, toggle, label }: { id: string; change: Change; changes: Record<string, Change>; toggle: Toggle; label?: string }) {
  return (
    <label className="check small">
      <input type="checkbox" checked={!!changes[id]} onChange={(e) => toggle(id, e.target.checked ? change : null)} />
      {label ?? t("Include", "Ta med")}
    </label>
  );
}


export function Results({ res }: { res: ExecResult }) {
  return (
    <ul className="results">
      {res.results.map((r, i) => <li key={i}><StatusDot status={r.status} /> <b>{SVC_NAME[r.service] ?? r.service}</b> {r.detail} <span className="small muted">({statusLabel(r.status)})</span></li>)}
    </ul>
  );
}

// ------------------------------------------------------------------ Review and confirm

function fmtVal(row: PlanRow, v: unknown): string {
  if (v === undefined) return "";
  if (row.kind === "mbpm" && Array.isArray(v)) {
    const rt = row.service === "radarr" ? 120 : 45;
    const unl = row.service === "radarr" ? 2000 : 1000;
    const [mn, pr, mx] = v as (number | null)[];
    return `${bytes(perTitle(mn, rt))} / ${pr == null || pr >= unl - 5 ? t("max", "maks") : bytes(perTitle(pr, rt))} / ${gbText(mx, rt, unl)}`;
  }
  if (typeof v === "boolean") return v ? t("on", "på") : t("off", "av");
  return String(v ?? "–");
}

export function ReviewDialog({ changes, enabled, onClose, onDone }: { changes: Change[]; enabled: boolean; onClose: () => void; onDone: () => void }) {
  const [plan, setPlan] = useState<Plan | null>(null);
  const [res, setRes] = useState<ExecResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [refreshed, setRefreshed] = useState(false);
  const load = () => api.post<Plan>("/api/arr-setup/plan", { changes }).then(setPlan).catch((e) => setError(String(e.message)));
  useEffect(() => { load(); // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [changes]);
  const run = async () => {
    if (!plan) return;
    setBusy(true); setError(null); setRefreshed(false);
    try { setRes(await api.post<ExecResult>("/api/arr-setup/execute", { changes, token: plan.token })); onDone(); }
    catch (e) {
      if ((e as { status?: number }).status === 409) { setPlan(null); await load(); setRefreshed(true); }
      else setError(String((e as Error).message));
    } finally { setBusy(false); }
  };
  const rows = plan?.rows ?? [];
  const groups = [...new Set(rows.map((r) => r.service))];
  const freed = rows.reduce((a, r) => a + (r.bytes ?? 0), 0);
  return (
    <Drawer label={t("Review changes", "Se over endringer")} onClose={onClose} busy={busy} wide>
      {res ? (
        <>
          <h1>{res.failed ? t("Partly done", "Delvis fullført") : t("Done", "Ferdig")}</h1>
          <p className="lede">{t("Logged under Activity → Deletion log.", "Loggført under Aktivitet → Slettelogg.")}{res.backup ? t(` Backup: ${res.backup} (Download rules → Backups).`, ` Sikkerhetskopi: ${res.backup} (Nedlastingsregler → Sikkerhetskopier).`) : ""}</p>
          <Results res={res} />
        </>
      ) : (
        <>
          <h1>{t("Review changes", "Se over endringer")}</h1>
          {!plan && !error && <Loading />}
          {error && <div className="notice err">{error}</div>}
          {plan && (
            <>
              <p className="lede">{t("This is exactly what will be changed. Everything else – other profiles, custom formats, languages – stays as it is. A backup of each setting is saved first.",
                "Dette er nøyaktig det som endres. Alt annet – andre profiler, custom formats, språk – blir som det er. En sikkerhetskopi av hver innstilling lagres først.")}</p>
              {refreshed && <div className="notice">{t("Something changed in the services after the summary was shown, so it has been read again. Check it and apply.",
                "Noe ble endret i tjenestene etter at oppsummeringen ble vist, så den er lest på nytt. Sjekk den og utfør.")}</div>}
              {plan.errors.length > 0 && <div className="notice err">{plan.errors.map((e, i) => <div key={i}>{e.error}</div>)}</div>}
              {groups.map((g) => (
                <Fragment key={g}>
                  <h3>{SVC_NAME[g] ?? g}</h3>
                  <ul className="conseq">
                    {rows.filter((r) => r.service === g).map((r, i) => (
                      <li key={i} className={r.skipped ? "muted" : undefined}>{r.what}
                        {r.before !== undefined && <div className="small muted">{fmtVal(r, r.before)} → <b>{fmtVal(r, r.after)}</b></div>}
                        {r.bytes ? <span className="small muted"> · {t("frees", "frigjør")} {bytes(r.bytes)}</span> : null}
                      </li>
                    ))}
                  </ul>
                </Fragment>
              ))}
              {plan.changes === 0 && !plan.errors.length && <p>{t("Nothing to change – it is already like this.", "Ingenting å endre – det er allerede slik.")}</p>}
              {freed > 0 && <p>{t("Removing torrents frees about", "Fjerning av torrenter frigjør omtrent")} <b>{bytes(freed)}</b>.</p>}
              {!enabled && <SwitchedOff what="services" onClose={onClose} />}
              <div className="toolbar" style={{ marginTop: 16 }}>
                <button className="btn primary" onClick={run} disabled={busy || !enabled || plan.changes === 0 || plan.errors.length > 0}>
                  {busy ? t("Applying…", "Utfører…") : t(`Apply ${plan.changes} change(s)`, `Utfør ${plan.changes} endring(er)`)}
                </button>
                <button className="btn" onClick={onClose} disabled={busy}>{t("Cancel", "Avbryt")}</button>
              </div>
            </>
          )}
        </>
      )}
    </Drawer>
  );
}

