import SwapList from "../components/Swaps";
import { Fragment, useEffect, useState } from "react";
import { api, Job } from "../api";
import { ago, bytes, num } from "../format";
import { ErrorNote, useFetch, useRefreshTick } from "../components/common";

type Svc = { enabled: boolean; url: string; api_key?: string; token?: string; verify_tls?: boolean; dataset?: string };
type Lib = { name: string; host_path: string; container_path: string; kind: string; protected: boolean };
type S = {
  services: Record<string, Svc>;
  libraries: Lib[];
  path_mappings: { from: string; to: string }[];
  analysis: Record<string, number | number[]>;
  weights: Record<string, number>;
  protection: { tags: string[]; plex_labels: string[]; paths: string[]; include_duplicates?: boolean };
  scanner: Record<string, number>;
  sync: { interval_hours: number };
  updates?: { check: boolean };
  actions?: { enabled: boolean; files_enabled?: boolean };
  _env_locked: string[];
};

const SVC: Record<string, { name: string; secret: "api_key" | "token"; hint: string; placeholder: string }> = {
  radarr: { name: "Radarr", secret: "api_key", hint: "Settings → General → API Key", placeholder: "http://192.168.1.10:30025" },
  sonarr: { name: "Sonarr", secret: "api_key", hint: "Settings → General → API Key", placeholder: "http://192.168.1.10:30027" },
  plex: { name: "Plex", secret: "token", hint: "X-Plex-Token fra «Get Info → View XML» på et element", placeholder: "http://192.168.1.10:32400" },
  tautulli: { name: "Tautulli", secret: "api_key", hint: "Settings → Web Interface → API key", placeholder: "http://192.168.1.10:30047" },
  seerr: { name: "Seerr (valgfritt)", secret: "api_key", hint: "Settings → General → API Key. Gir hvem som ba om hva.", placeholder: "http://192.168.1.10:30357" },
  truenas: { name: "TrueNAS (valgfritt)", secret: "api_key", hint: "API-nøkkel for en bruker med rollen Read-Only Admin. Gir pool-kapasitet og snapshots.", placeholder: "https://192.168.1.10" },
};

const WEIGHTS: Record<string, string> = {
  space: "Plass som frigjøres", staleness: "Tid siden sist sett", consumption: "Avspillinger i forhold til størrelse",
  viewers: "Antall seere nylig", monitored: "Overvåket i Radarr/Sonarr", recent: "Nylig lagt til (karantene)",
  versions: "Finnes i annen versjon", request: "Etterspurt i Seerr",
};

export default function SettingsPage() {
  const { data, error, reload } = useFetch<S>("/api/settings");
  const [s, setS] = useState<S | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [saveErr, setSaveErr] = useState<string | null>(null);
  const [tests, setTests] = useState<Record<string, { ok: boolean; error?: string; version?: string } | "…">>({});
  const status = useFetch<{ services: Record<string, { ok: boolean; message: string; checked: number; last_success: number | null }> }>("/api/status", [useRefreshTick()]);
  useEffect(() => { if (data) setS(structuredClone(data)); }, [data]);
  if (error) return <ErrorNote error={error} />;
  if (!s) return <p className="muted">Henter innstillinger…</p>;

  const locked = (path: string) => s._env_locked.includes(path);
  const setSvc = (name: string, k: string, v: unknown) => setS({ ...s, services: { ...s.services, [name]: { ...s.services[name], [k]: v } } });
  const setA = (k: string, v: number | number[]) => setS({ ...s, analysis: { ...s.analysis, [k]: v } });
  const save = async () => {
    setSaved(null); setSaveErr(null);
    try {
      await api.put("/api/settings", s);
      setSaved("Lagret. Kjør «Analyse» under Jobber for å bruke nye terskler, eller «Full oppdatering» etter endrede tilkoblinger.");
      reload();
    } catch (e) { setSaveErr(String((e as Error).message)); }
  };
  const test = async (name: string) => {
    setTests({ ...tests, [name]: "…" });
    const svc = s.services[name];
    const r = await api.post<{ ok: boolean; error?: string; version?: string }>(`/api/services/${name}/test`, svc).catch((e) => ({ ok: false, error: String(e.message) }));
    setTests((t) => ({ ...t, [name]: r }));
  };
  const list = (v: string) => v.split(",").map((x) => x.trim()).filter(Boolean);

  return (
    <>
      <h1>Innstillinger</h1>
      <p className="lede">Lagres i <code>/data/settings.json</code> i appens datasett. Verdier satt med miljøvariabler i appens YAML kan ikke endres her og vises som låst.</p>

      <h2>Tilkoblinger</h2>
      <div className="grid cols-3" style={{ gap: 14 }}>
        {Object.entries(SVC).map(([name, meta]) => {
          const svc = s.services[name];
          const st = status.data?.services?.[name];
          const t = tests[name];
          return (
            <section key={name} className="panel" style={{ display: "grid", gap: 10, alignContent: "start" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <h3 style={{ margin: 0 }}>{meta.name}</h3>
                <label className="check small"><input type="checkbox" checked={svc.enabled} onChange={(e) => setSvc(name, "enabled", e.target.checked)} />I bruk</label>
              </div>
              <label className="field"><span>Adresse{locked(`services.${name}.url`) && " (låst av miljøvariabel)"}</span>
                <input type="url" placeholder={meta.placeholder} value={svc.url} disabled={locked(`services.${name}.url`)} onChange={(e) => setSvc(name, "url", e.target.value)} />
              </label>
              <label className="field"><span>{meta.secret === "token" ? "Token" : "API-nøkkel"}{locked(`services.${name}.${meta.secret}`) && " (låst av miljøvariabel)"}</span>
                <input type="password" autoComplete="off" value={svc[meta.secret] ?? ""} disabled={locked(`services.${name}.${meta.secret}`)} onChange={(e) => setSvc(name, meta.secret, e.target.value)} />
              </label>
              {name === "truenas" && (
                <>
                  <label className="field"><span>Rotdatasett</span><input type="text" value={svc.dataset ?? ""} onChange={(e) => setSvc(name, "dataset", e.target.value)} /></label>
                  <label className="check small"><input type="checkbox" checked={!!svc.verify_tls} onChange={(e) => setSvc(name, "verify_tls", e.target.checked)} />Krev gyldig TLS-sertifikat</label>
                </>
              )}
              <div className="small muted">{meta.hint}</div>
              <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                <button className="btn small" onClick={() => test(name)} disabled={!svc.url}>Test tilkobling</button>
                <span className="small">
                  {t === "…" ? "Tester…" : t ? (t.ok ? <><i className="dot ok" />OK{t.version ? `, versjon ${t.version}` : ""}</> : <><i className="dot bad" />{t.error}</>) :
                    st ? (st.ok ? <><i className="dot ok" />Synket {ago(st.checked)}</> : <><i className={`dot ${svc.url ? "bad" : "off"}`} />{st.message}</>) : null}
                </span>
              </div>
            </section>
          );
        })}
      </div>

      <section className="section">
        <h2>Biblioteker og mounts</h2>
        <p className="muted small">Containerstien må samsvare med volumene i appens YAML. Beskyttede biblioteker vises i statistikken, men gir aldri forslag.</p>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Navn</th><th>Sti på TrueNAS</th><th>Sti i containeren</th><th>Type</th><th>Beskyttet</th></tr></thead>
            <tbody>
              {s.libraries.map((l, i) => {
                const upd = (k: keyof Lib, v: unknown) => setS({ ...s, libraries: s.libraries.map((x, j) => (j === i ? { ...x, [k]: v } : x)) });
                return (
                  <tr key={i}>
                    <td><input type="text" value={l.name} onChange={(e) => upd("name", e.target.value)} style={{ width: 90 }} /></td>
                    <td><input type="text" value={l.host_path} onChange={(e) => upd("host_path", e.target.value)} /></td>
                    <td><input type="text" value={l.container_path} onChange={(e) => upd("container_path", e.target.value)} /></td>
                    <td><select value={l.kind} onChange={(e) => upd("kind", e.target.value)}>
                      <option value="movies">Filmer</option><option value="series">Serier</option><option value="mixed">Blandet</option><option value="downloads">Nedlastinger</option>
                    </select></td>
                    <td><input type="checkbox" checked={l.protected} onChange={(e) => upd("protected", e.target.checked)} aria-label={`Beskytt ${l.name}`} /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <h3 style={{ marginTop: 20 }}>Stimapping fra tjenestene</h3>
        <p className="muted small">Hvordan Radarr, Sonarr, Plex og qBittorrent ser stiene, oversatt til stier på TrueNAS.</p>
        <div style={{ display: "grid", gap: 6, maxWidth: 560 }}>
          {s.path_mappings.map((m, i) => (
            <div key={i} style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <input type="text" value={m.from} onChange={(e) => setS({ ...s, path_mappings: s.path_mappings.map((x, j) => (j === i ? { ...x, from: e.target.value } : x)) })} />
              <span className="muted">til</span>
              <input type="text" value={m.to} onChange={(e) => setS({ ...s, path_mappings: s.path_mappings.map((x, j) => (j === i ? { ...x, to: e.target.value } : x)) })} />
              <button className="btn small" onClick={() => setS({ ...s, path_mappings: s.path_mappings.filter((_, j) => j !== i) })}>Fjern</button>
            </div>
          ))}
          <div><button className="btn small" onClick={() => setS({ ...s, path_mappings: [...s.path_mappings, { from: "", to: "" }] })}>Legg til mapping</button></div>
        </div>
      </section>

      <section className="section">
        <h2>Beskyttelse</h2>
        <div className="form-grid">
          <label className="field"><span>Tagger i Radarr/Sonarr (kommaseparert)</span><input type="text" value={s.protection.tags.join(", ")} onChange={(e) => setS({ ...s, protection: { ...s.protection, tags: list(e.target.value) } })} /></label>
          <label className="field"><span>Etiketter i Plex</span><input type="text" value={s.protection.plex_labels.join(", ")} onChange={(e) => setS({ ...s, protection: { ...s.protection, plex_labels: list(e.target.value) } })} /></label>
          <label className="field"><span>Beskyttede stier på TrueNAS</span><input type="text" placeholder="/mnt/pool1/FILM/Samling" value={s.protection.paths.join(", ")} onChange={(e) => setS({ ...s, protection: { ...s.protection, paths: list(e.target.value) } })} /></label>
        </div>
              <label className="check" style={{ marginTop: 14 }}>
          <input type="checkbox" checked={!!s.protection.include_duplicates} onChange={(e) => setS({ ...s, protection: { ...s.protection, include_duplicates: e.target.checked } })} />
          Beskyttelse gjelder også duplikater og ekstra versjoner
        </label>
        <p className="small muted" style={{ margin: "4px 0 0", maxWidth: 720 }}>Av som standard: ekstra kopier og versjoner kan ryddes også i beskyttede biblioteker og titler, fordi én fil alltid blir igjen. Beskyttelsen mot å slette hele titler gjelder uansett.</p>
</section>

      <section className="section">
        <h2>Terskler</h2>
        <div className="form-grid">
          <label className="field"><span>«Ikke sett på» (måneder, tre trinn)</span><input type="text" value={(s.analysis.stale_months as number[]).join(", ")} onChange={(e) => { const v = list(e.target.value).map(Number).filter((n) => n > 0); if (v.length === 3) setA("stale_months", v.sort((a, b) => a - b)); }} /></label>
          <Num label="Karantene for nye titler (måneder)" v={s.analysis.quarantine_months as number} on={(v) => setA("quarantine_months", v)} />
          <Num label="«Sett nylig» betyr innen (måneder)" v={s.analysis.recent_play_months as number} on={(v) => setA("recent_play_months", v)} />
          <Num label="Minste forslag (GB)" v={s.analysis.min_suggestion_gb as number} on={(v) => setA("min_suggestion_gb", v)} step={0.5} />
          <Num label="Stor film fra (GB)" v={s.analysis.large_movie_gb as number} on={(v) => setA("large_movie_gb", v)} />
          <Num label="Stor episode fra (GB)" v={s.analysis.large_episode_gb as number} on={(v) => setA("large_episode_gb", v)} step={0.5} />
          <Num label="Mål for erstattet film (GB)" v={s.analysis.target_movie_gb as number} on={(v) => setA("target_movie_gb", v)} />
          <Num label="Mål for erstattet episode (GB)" v={s.analysis.target_episode_gb as number} on={(v) => setA("target_episode_gb", v)} step={0.5} />
          <Num label="Vis forslag fra prioritet" v={s.analysis.min_score as number} on={(v) => setA("min_score", v)} />
        </div>
        <h3 style={{ marginTop: 20 }}>Vekting av prioriteten</h3>
        <p className="muted small">1 er standard. 0 slår av faktoren, 2 dobler den.</p>
        <div className="form-grid">
          {Object.entries(WEIGHTS).map(([k, l]) => <Num key={k} label={l} v={s.weights[k]} on={(v) => setS({ ...s, weights: { ...s.weights, [k]: v } })} step={0.1} />)}
        </div>
      </section>

      <section className="section">
        <h2>Skanning og synk</h2>
        <div className="form-grid">
          <Num label="Synk med tjenestene hver (timer)" v={s.sync.interval_hours} on={(v) => setS({ ...s, sync: { interval_hours: v } })} />
          <Num label="Inkrementell skanning hver (timer)" v={s.scanner.interval_hours} on={(v) => setS({ ...s, scanner: { ...s.scanner, interval_hours: v } })} />
          <Num label="Full skanning hver (dager)" v={s.scanner.full_scan_days} on={(v) => setS({ ...s, scanner: { ...s.scanner, full_scan_days: v } })} />
          <Num label="Pause per 1000 filer (ms)" v={s.scanner.throttle_ms_per_1000} on={(v) => setS({ ...s, scanner: { ...s.scanner, throttle_ms_per_1000: v } })} />
          <Num label="Sjekk duplikater fra (MB)" v={s.scanner.hash_min_size_mb} on={(v) => setS({ ...s, scanner: { ...s.scanner, hash_min_size_mb: v } })} />
        </div>
      </section>

      <section className="section">
        <h2>Sletting</h2>
        <label className="check"><input type="checkbox" checked={!!s.actions?.enabled} onChange={(e) => setS({ ...s, actions: { ...s.actions, enabled: e.target.checked } })} />Tillat sletting og bytte via Radarr og Sonarr, og opprydding i Plex</label>
        <ul className="conseq small muted" style={{ maxWidth: 720 }}>
          <li>Filmer slettes i Radarr og serier i Sonarr, med filer. Filmer legges ikke på ekskluderingslisten.</li>
          <li>Enkeltsesonger avovervåkes i Sonarr før episodefilene slettes, så de ikke lastes ned igjen.</li>
          <li>«Bytt» til en mindre versjon laster ned først. Den gamle filen slettes via Radarr/Sonarr først når den nye er ferdig og kan importeres.</li>
          <li>Beskyttede titler (Barn, tagger, etiketter) kan aldri slettes eller byttes.</li>
          <li>Plex-oppføringer der filene mangler på disk kan fjernes fra Plex (under Plex-avvik). Krever «Allow media deletion» i Plex.</li>
          <li>Alt som slettes, loggføres under Logg.</li>
        </ul>
        <label className="check" style={{ marginTop: 12 }}><input type="checkbox" checked={!!s.actions?.files_enabled} onChange={(e) => setS({ ...s, actions: { enabled: !!s.actions?.enabled, files_enabled: e.target.checked } })} />Tillat sletting av filer: duplikater, nedlastinger og mapper som verken er i Radarr, Sonarr eller Plex</label>
        <FilesAccess />
      </section>

      <section className="section">
        <h2>Oppdateringer</h2>
        <UpdateBox enabled={s.updates?.check ?? true} onToggle={(v) => setS({ ...s, updates: { check: v } })} />
      </section>

      <div className="tray">
        <div className="grow small muted">{saved ?? saveErr ?? "Endringer lagres først når du trykker «Lagre innstillinger»."}</div>
        <button className="btn" onClick={() => data && setS(structuredClone(data))}>Forkast endringer</button>
        <button className="btn primary" onClick={save}>Lagre innstillinger</button>
      </div>
    </>
  );
}

function FilesAccess() {
  const st = useFetch<{ writable: Record<string, boolean> }>("/api/status");
  const w = st.data?.writable ?? {};
  const ro = Object.entries(w).filter(([, v]) => !v).map(([k]) => k);
  return (
    <div className="small muted" style={{ maxWidth: 720 }}>
      <p style={{ margin: "6px 0" }}>Duplikater administreres normalt ikke av Radarr/Sonarr, så de slettes direkte fra disk. Det krever at mappene er montert med skrivetilgang: fjern <code>:ro</code> på de aktuelle linjene under <code>volumes</code> i appens YAML (Apps → mediacleanup → Edit). Filer Radarr/Sonarr kjenner, slettes aldri på denne måten, og filen som beholdes, blir alltid liggende.</p>
      {Object.keys(w).length > 0 && <p style={{ margin: "6px 0" }}>Skrivetilgang nå: {Object.entries(w).map(([k, v]) => `${k} ${v ? "ja" : "nei"}`).join(", ")}.{ro.length > 0 ? " Mapper uten skrivetilgang hoppes over." : ""}</p>}
    </div>
  );
}

function UpdateBox({ enabled, onToggle }: { enabled: boolean; onToggle: (v: boolean) => void }) {
  const [u, setU] = useState<{ current: string; latest: string | null; available: boolean; checked: number | null; ok: boolean | null; url: string | null } | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { api.get<typeof u>("/api/update").then(setU).catch(() => {}); }, []);
  const checkNow = async () => {
    setBusy(true);
    try { setU(await api.get("/api/update?refresh=true")); } finally { setBusy(false); }
  };
  return (
    <div style={{ display: "grid", gap: 10, maxWidth: 640 }}>
      <label className="check"><input type="checkbox" checked={enabled} onChange={(e) => onToggle(e.target.checked)} />Se etter nye versjoner på GitHub (hver 6. time)</label>
      {u && (
        <p className="small muted" style={{ margin: 0 }}>
          Du kjører {u.current}.{" "}
          {u.latest ? (u.available ? <>Versjon <a href={u.url ?? "#"} target="_blank" rel="noreferrer">{u.latest}</a> er tilgjengelig.</> : <>Siste utgivelse er {u.latest}, du er oppdatert.</>) : "Ingen informasjon om utgivelser ennå."}
          {u.checked ? ` Sjekket ${ago(u.checked)}${u.ok === false ? " (feilet – har containeren tilgang til internett?)" : ""}.` : ""}
        </p>
      )}
      <p className="small muted" style={{ margin: 0 }}>Appen oppdaterer seg aldri selv. Med <code>:latest</code> i YAML gjør du det i TrueNAS: Apps → mediacleanup → ⋮ → Update.</p>
      <div><button className="btn small" onClick={checkNow} disabled={busy || !enabled}>{busy ? "Sjekker…" : "Sjekk nå"}</button></div>
    </div>
  );
}

function Num({ label, v, on, step = 1 }: { label: string; v: number; on: (v: number) => void; step?: number }) {
  return (
    <label className="field"><span>{label}</span>
      <input type="number" step={step} min={0} value={v} onChange={(e) => on(Number(e.target.value))} />
    </label>
  );
}

export function JobsPage() {
  const tick = useRefreshTick();
  const [poll, setPoll] = useState(0);
  const { data, error } = useFetch<{ items: Job[]; kinds: Record<string, string> }>("/api/jobs", [tick, poll]);
  const status = useFetch<{ last_scan: { time: number; files: number; bytes: number; duration: number; stat_calls: number; full: boolean; missing: string[] } | null; last_sync: number | null; last_analysis: { time: number; suggestions: number } | null }>("/api/status", [tick, poll]);
  const [open, setOpen] = useState<number | null>(null);
  useEffect(() => { const t = setInterval(() => setPoll((p) => p + 1), 3000); return () => clearInterval(t); }, []);
  const start = async (k: string) => { await api.post(`/api/jobs/${k}`); setPoll((p) => p + 1); };
  const ls = status.data?.last_scan;
  return (
    <>
      <h1>Jobber</h1>
      <p className="lede">Skanning og synkronisering går automatisk i bakgrunnen. Bare én jobb kjører om gangen for å skåne poolen.</p>
      {ls?.missing?.length ? <div className="notice err">Fant ikke mappene for {ls.missing.join(", ")} i containeren. Sjekk volumene i appens YAML.</div> : null}
      <div className="figures">
        <div className="figure"><div className="v">{ago(status.data?.last_sync)}</div><div className="l">siste synk med tjenestene</div></div>
        <div className="figure"><div className="v">{ago(ls?.time)}</div><div className="l">{ls ? `${ls.full ? "full" : "inkrementell"} skanning, ${num(ls.files)} filer, ${bytes(ls.bytes)}, ${Math.round(ls.duration)} s` : "siste skanning"}</div></div>
        <div className="figure"><div className="v">{ago(status.data?.last_analysis?.time)}</div><div className="l">siste analyse</div></div>
      </div>
      <div className="toolbar">
        <button className="btn primary" onClick={() => start("refresh")}>Kjør full oppdatering</button>
        <button className="btn" onClick={() => start("sync")}>Synk tjenester</button>
        <button className="btn" onClick={() => start("scan")}>Skann endringer</button>
        <button className="btn" onClick={() => start("scan_full")}>Full skanning</button>
        <button className="btn" onClick={() => start("analyze")}>Analyse</button>
      </div>
      <ErrorNote error={error} />
      <div className="table-wrap">
        <table>
          <thead><tr><th>Jobb</th><th>Status</th><th>Fremdrift</th><th>Startet</th><th>Varighet</th></tr></thead>
          <tbody>
            {data?.items.map((j) => (
              <Fragment key={j.id}>
                <tr className="row" onClick={() => setOpen(open === j.id ? null : j.id)} style={{ cursor: "pointer" }}>
                  <td>{data.kinds[j.kind] ?? j.kind}</td>
                  <td><i className={`dot ${j.status === "done" ? "ok" : j.status === "failed" ? "bad" : "off"}`} />{({ done: "Ferdig", failed: "Feilet", running: "Kjører", queued: "I kø", aborted: "Avbrutt" } as Record<string, string>)[j.status] ?? j.status}</td>
                  <td style={{ minWidth: 200 }}>{j.status === "running" ? <><div className="progress"><i style={{ width: `${j.progress * 100}%` }} /></div><span className="small muted">{j.message}</span></> : <span className="small muted">{j.message}</span>}</td>
                  <td className="muted small">{ago(j.started)}</td>
                  <td className="muted small">{j.started && j.finished ? `${Math.round(j.finished - j.started)} s` : ""}</td>
                </tr>
                {open === j.id && (j.log || j.error) && <tr className="detail"><td colSpan={5}><pre className="log">{j.error ?? j.log}</pre></td></tr>}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
      <h2 style={{ marginTop: 32 }}>Bytter til mindre versjoner</h2>
      <p className="small muted">Startes fra «Finn mindre versjon» på en tittel. Følges opp automatisk hvert 5. minutt, og oftere mens siden er åpen.</p>
      <SwapList empty="Ingen bytter er startet." />
    </>
  );
}


type Action = { id: number; ts: number; title: string; action: string; service: string | null; status: string; detail: string; bytes: number };

export function LogPage() {
  const tick = useRefreshTick();
  const { data, error } = useFetch<{ items: Action[]; enabled: boolean }>("/api/actions/history", [tick]);
  const total = data?.items.filter((a) => a.status === "utført").reduce((s, a) => s + (a.bytes || 0), 0) ?? 0;
  return (
    <>
      <h1>Logg over slettinger</h1>
      <p className="lede">Alt appen har slettet via Radarr og Sonarr, med resultat. {data && !data.enabled && "Sletting er slått av nå."}</p>
      <ErrorNote error={error} />
      {data && data.items.length === 0 && <div className="empty">Ingenting er slettet fra appen ennå.</div>}
      {data && data.items.length > 0 && (
        <>
          <p className="small muted">{data.items.filter((a) => a.status === "utført").length} utført, omtrent {bytes(total)} frigjort.</p>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Tidspunkt</th><th>Tittel</th><th>Status</th><th>Detaljer</th><th className="r">Plass</th></tr></thead>
              <tbody>
                {data.items.map((a) => (
                  <tr key={a.id}>
                    <td className="small muted num">{new Date(a.ts * 1000).toLocaleString("nb-NO")}</td>
                    <td>{a.title}<div className="small faint">{a.action === "delete_season" ? "Sesong" : "Hel tittel"}, {a.service === "radarr" ? "Radarr" : a.service === "sonarr" ? "Sonarr" : a.service}</div></td>
                    <td><i className={`dot ${a.status === "utført" ? "ok" : a.status === "feilet" ? "bad" : "off"}`} />{a.status}</td>
                    <td className="small muted">{a.detail}</td>
                    <td className="r num">{a.status === "utført" ? bytes(a.bytes) : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </>
  );
}
