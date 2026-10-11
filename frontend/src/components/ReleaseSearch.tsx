import { useState } from "react";
import { api } from "../api";
import { bytes, num } from "../format";

type Release = { title: string; size: number; quality: string | null; resolution: number | null; indexer: string | null;
  protocol: string | null; seeders: number | null; age_days: number | null; languages: string[]; score: number;
  reasons: string[]; warnings: string[]; savings: number; recommended: boolean; info_url: string | null };
type Result = { service: string; current_size: number; episodes: number; target: number; total: number; episode_releases: number;
  smaller: number; releases: Release[]; searched: number; cached: boolean };

/** Søk etter mindre versjoner via Radarr/Sonarr sin interaktive søk (kun visning). */
export default function ReleaseSearch({ titleKey, season, label }: { titleKey: string; season?: number; label?: string }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [res, setRes] = useState<Result | null>(null);
  const [all, setAll] = useState(false);
  const run = async (refresh = false) => {
    setOpen(true); setBusy(true); setError(null);
    try {
      const q = new URLSearchParams();
      if (season != null) q.set("season", String(season));
      if (refresh) q.set("refresh", "true");
      setRes(await api.get<Result>(`/api/releases/${encodeURIComponent(titleKey)}?${q}`));
    } catch (e) { setError(String((e as Error).message)); } finally { setBusy(false); }
  };
  const svc = res?.service === "sonarr" ? "Sonarr" : "Radarr";
  const shown = res ? (all ? res.releases : res.releases.slice(0, 8)) : [];

  if (!open) return <button className="btn small" onClick={() => run()}>{label ?? "Finn mindre versjon"}</button>;
  return (
    <div className="panel release-box">
      <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "baseline", flexWrap: "wrap" }}>
        <h3 style={{ margin: 0 }}>{season != null ? `Sesong ${season}` : "Funnet hos indekserne"}</h3>
        <span className="small">
          {res && !busy && <button className="linkish small" onClick={() => run(true)}>Søk på nytt</button>}{" "}
          <button className="linkish small" onClick={() => setOpen(false)}>Skjul</button>
        </span>
      </div>
      {busy && <p className="muted small">Søker i indekserne via {res ? svc : "Radarr/Sonarr"}… Dette kan ta opptil et minutt.</p>}
      {error && <div className="notice err">{error}</div>}
      {res && !busy && (
        <>
          <p className="small muted">
            I dag: {bytes(res.current_size)}{res.service === "sonarr" ? ` (${num(res.episodes)} episoder)` : ""}. {svc} fant {num(res.total)} utgivelser
            {res.service === "sonarr" ? " som sesongpakker" : ""}, hvorav {num(res.smaller)} er minst 15 % mindre.
            {res.episode_releases > 0 && ` ${num(res.episode_releases)} enkeltepisoder er ikke tatt med.`}
            {res.cached && " (Fra de siste 30 minuttene.)"}
          </p>
          {res.releases.length === 0 ? <p className="muted">Ingen mindre versjoner funnet hos indekserne nå.</p> : (
            <div className="table-wrap">
              <table className="compact">
                <thead><tr><th>Utgivelse</th><th>Kvalitet</th><th className="r">Størrelse</th><th className="r">Sparer</th><th>Tilgjengelighet</th></tr></thead>
                <tbody>
                  {shown.map((r) => (
                    <tr key={r.title + r.indexer} className={r.recommended ? "rec" : ""}>
                      <td style={{ maxWidth: 380 }}>
                        {r.recommended && <span className="pill risk-lav" style={{ marginRight: 6 }}>Anbefalt</span>}
                        <span style={{ wordBreak: "break-word" }}>{r.title}</span>
                        <div className="small muted">{r.reasons.join(", ")}{r.languages.length ? `, ${r.languages.join("/")}` : ""}</div>
                        {r.warnings.length > 0 && <div className="small" style={{ color: "var(--risk-middels)" }}>{r.warnings.join(". ")}</div>}
                      </td>
                      <td className="small">{r.quality}</td>
                      <td className="r num">{bytes(r.size)}</td>
                      <td className="r num" style={{ fontWeight: 600 }}>{bytes(r.savings)}</td>
                      <td className="small muted">{r.protocol === "torrent" ? `${r.seeders ?? 0} delere` : r.protocol === "usenet" ? "Usenet" : ""}{r.indexer ? `, ${r.indexer}` : ""}{r.age_days != null ? `, ${num(r.age_days)} d` : ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {res.releases.length > 8 && <p className="small"><button className="linkish" onClick={() => setAll(!all)}>{all ? "Vis færre" : `Vis alle ${res.releases.length}`}</button></p>}
          <p className="small muted" style={{ marginBottom: 0 }}>
            «Anbefalt» veier gevinst, 1080p, størrelse nær målet, antall delere og eventuelle avvisninger fra {svc}. Avvisningen «ikke en oppgradering» er forventet når man går ned i størrelse og vises ikke.
            Bytte gjøres foreløpig i {svc}: Interactive Search, velg utgivelsen og importer.
          </p>
        </>
      )}
    </div>
  );
}
