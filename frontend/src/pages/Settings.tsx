import { ReactNode, useEffect, useState } from "react";
import { api } from "../api";
import { ago, libKindLabel } from "../format";
import { t } from "../i18n";
import { ErrorNote, Loading, PageHeader, useFetch, useRefreshTick, useStatus } from "../components/common";
import { SetupStatus } from "../components/SetupCard";

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

const SECTIONS = ["services", "libraries", "deletion", "protection", "analysis", "scanning", "updates"];

function sectionTitle(id: string) {
  return ({ services: t("Connections", "Tilkoblinger"), libraries: t("Libraries and paths", "Biblioteker og stier"), deletion: t("Deletion", "Sletting"),
    protection: t("Protection", "Beskyttelse"), analysis: t("Analysis", "Analyse"), scanning: t("Scanning and sync", "Skanning og synk"),
    updates: t("Updates", "Oppdateringer") } as Record<string, string>)[id] ?? id;
}

export default function SettingsPage({ section, onSaved }: { section: string; onSaved: () => void }) {
  const tick = useRefreshTick();
  const status = useStatus();
  const { data, error, reload } = useFetch<S>("/api/settings");
  const setup = useFetch<SetupStatus>("/api/setup", [tick]);
  const [s, setS] = useState<S | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [saveErr, setSaveErr] = useState<string | null>(null);
  const [tests, setTests] = useState<Record<string, { ok: boolean; error?: string; version?: string } | "…">>({});
  useEffect(() => { if (data) setS(structuredClone(data)); }, [data]);
  useEffect(() => { if (s && section) document.getElementById(`s-${section}`)?.scrollIntoView({ behavior: "smooth", block: "start" }); }, [section, !!s]); // eslint-disable-line react-hooks/exhaustive-deps
  if (error) return <ErrorNote error={error} />;
  if (!s) return <Loading />;

  const dirty = JSON.stringify(s) !== JSON.stringify(data);
  const locked = (path: string) => s._env_locked.includes(path);
  const setSvc = (name: string, k: string, v: unknown) => setS({ ...s, services: { ...s.services, [name]: { ...s.services[name], [k]: v } } });
  const setA = (k: string, v: number | number[]) => setS({ ...s, analysis: { ...s.analysis, [k]: v } });
  const save = async () => {
    setSaved(null); setSaveErr(null);
    try {
      await api.put("/api/settings", s);
      setSaved(t("Saved. Run «Analysis» under Activity to use new thresholds, or «Full refresh» after changed connections or libraries.",
        "Lagret. Kjør «Analyse» under Aktivitet for å bruke nye terskler, eller «Full oppdatering» etter endrede tilkoblinger eller biblioteker."));
      reload(); setup.reload(); onSaved();
    } catch (e) { setSaveErr(String((e as Error).message)); }
  };
  const test = async (name: string) => {
    setTests({ ...tests, [name]: "…" });
    const r = await api.post<{ ok: boolean; error?: string; version?: string }>(`/api/services/${name}/test`, s.services[name]).catch((e) => ({ ok: false, error: String(e.message) }));
    setTests((x) => ({ ...x, [name]: r }));
  };
  const detect = async () => {
    if (!confirm(t("Replace the library list with the folders found under /media? Unsaved changes are lost.", "Erstatte biblioteklisten med mappene som finnes under /media? Ulagrede endringer går tapt."))) return;
    try { await api.post("/api/setup/detect-libraries"); reload(); setup.reload(); } catch (e) { setSaveErr(String((e as Error).message)); }
  };
  const list = (v: string) => v.split(",").map((x) => x.trim()).filter(Boolean);
  const svcMeta: Record<string, { name: string; secret: "api_key" | "token"; hint: string; placeholder: string }> = {
    radarr: { name: "Radarr", secret: "api_key", hint: "Settings → General → API Key", placeholder: "http://<nas-ip>:30025" },
    sonarr: { name: "Sonarr", secret: "api_key", hint: "Settings → General → API Key", placeholder: "http://<nas-ip>:30027" },
    plex: { name: "Plex", secret: "token", hint: t("X-Plex-Token from «Get Info → View XML» on an item", "X-Plex-Token fra «Get Info → View XML» på et element"), placeholder: "http://<nas-ip>:32400" },
    tautulli: { name: "Tautulli", secret: "api_key", hint: "Settings → Web Interface → API key", placeholder: "http://<nas-ip>:30047" },
    seerr: { name: t("Seerr (optional)", "Seerr (valgfritt)"), secret: "api_key", hint: t("Settings → General → API Key. Shows who requested what.", "Settings → General → API Key. Viser hvem som ba om hva."), placeholder: "http://<nas-ip>:30357" },
    truenas: { name: t("TrueNAS (optional)", "TrueNAS (valgfritt)"), secret: "api_key", hint: t("API key for a user with the Read-Only Admin role. Gives pool capacity, datasets and snapshots.", "API-nøkkel for en bruker med rollen Read-Only Admin. Gir pool-kapasitet, datasett og snapshots."), placeholder: "https://<nas-ip>" },
  };
  const weights: Record<string, string> = {
    space: t("Space freed", "Plass som frigjøres"), staleness: t("Time since last watched", "Tid siden sist sett"),
    consumption: t("Plays relative to size", "Avspillinger i forhold til størrelse"), viewers: t("Recent viewers", "Antall seere nylig"),
    monitored: t("Monitored in Radarr/Sonarr", "Overvåket i Radarr/Sonarr"), recent: t("Recently added (quarantine)", "Nylig lagt til (karantene)"),
    versions: t("Exists in another version", "Finnes i annen versjon"), request: t("Requested in Seerr", "Etterspurt i Seerr"),
  };
  const suggestions = (setup.data?.paths ?? []).filter((p) => !p.ok && p.suggestion && !s.path_mappings.some((m) => m.from === p.suggestion!.from));
  const unmatched = (setup.data?.paths ?? []).filter((p) => !p.ok && !p.suggestion);
  const writable = status?.writable ?? {};

  return (
    <>
      <PageHeader title={t("Settings", "Innstillinger")}
        lede={<>{t("Stored in /data/settings.json in the app's dataset. Values set with environment variables in the compose file cannot be changed here and are shown as locked.",
          "Lagres i /data/settings.json i appens datasett. Verdier satt med miljøvariabler i compose-filen kan ikke endres her og vises som låst.")}</>} />
      <nav className="settings-nav" aria-label={t("Sections", "Seksjoner")}>
        {SECTIONS.map((id) => <a key={id} href={`#/settings/${id}`}>{sectionTitle(id)}</a>)}
      </nav>

      <Section id="services">
        <div className="grid cols-3" style={{ gap: 14 }}>
          {Object.entries(svcMeta).map(([name, meta]) => {
            const svc = s.services[name];
            const st = status?.services?.[name];
            const r = tests[name];
            return (
              <section key={name} className="panel" style={{ display: "grid", gap: 10, alignContent: "start" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <h3 style={{ margin: 0 }}>{meta.name}</h3>
                  <label className="check small"><input type="checkbox" checked={svc.enabled} onChange={(e) => setSvc(name, "enabled", e.target.checked)} />{t("In use", "I bruk")}</label>
                </div>
                <label className="field"><span>{t("Address", "Adresse")}{locked(`services.${name}.url`) && t(" (locked by environment variable)", " (låst av miljøvariabel)")}</span>
                  <input type="url" placeholder={meta.placeholder} value={svc.url} disabled={locked(`services.${name}.url`)} onChange={(e) => setSvc(name, "url", e.target.value)} />
                </label>
                <label className="field"><span>{meta.secret === "token" ? "Token" : t("API key", "API-nøkkel")}{locked(`services.${name}.${meta.secret}`) && t(" (locked by environment variable)", " (låst av miljøvariabel)")}</span>
                  <input type="password" autoComplete="off" value={svc[meta.secret] ?? ""} disabled={locked(`services.${name}.${meta.secret}`)} onChange={(e) => setSvc(name, meta.secret, e.target.value)} />
                </label>
                {name === "truenas" && (
                  <>
                    <label className="field"><span>{t("Pool or root dataset (empty: from the library paths)", "Pool eller rotdatasett (tomt: fra bibliotekstiene)")}</span><input type="text" value={svc.dataset ?? ""} onChange={(e) => setSvc(name, "dataset", e.target.value)} /></label>
                    <label className="check small"><input type="checkbox" checked={!!svc.verify_tls} onChange={(e) => setSvc(name, "verify_tls", e.target.checked)} />{t("Require a valid TLS certificate", "Krev gyldig TLS-sertifikat")}</label>
                  </>
                )}
                <div className="small muted">{meta.hint}</div>
                <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                  <button className="btn small" onClick={() => test(name)} disabled={!svc.url}>{t("Test connection", "Test tilkobling")}</button>
                  <span className="small">
                    {r === "…" ? t("Testing…", "Tester…") : r ? (r.ok ? <><i className="dot ok" />OK{r.version ? t(`, version ${r.version}`, `, versjon ${r.version}`) : ""}</> : <><i className="dot bad" />{r.error}</>) :
                      st ? (st.ok ? <><i className="dot ok" />{t("Synced", "Synket")} {ago(st.checked)}</> : <><i className={`dot ${svc.url ? "bad" : "off"}`} />{st.message}</>) : null}
                  </span>
                </div>
              </section>
            );
          })}
        </div>
        <p className="small muted">{t("Use the NAS's LAN IP address – «localhost» points to this container.", "Bruk NAS-ens LAN-IP – «localhost» peker på denne containeren.")}</p>
      </Section>

      <Section id="libraries">
        <p className="muted small" style={{ maxWidth: 760 }}>{t("Each folder mounted under /media in the app's compose file becomes a library. «Path on the NAS» is where the folder is on TrueNAS, and is what the services' paths are translated to. Protected libraries are counted, but never suggested for deletion.",
          "Hver mappe som er montert under /media i appens compose-fil blir et bibliotek. «Sti på NAS» er hvor mappen ligger på TrueNAS, og er det tjenestenes stier oversettes til. Beskyttede biblioteker telles med, men foreslås aldri slettet.")}</p>
        {s.libraries.length > 0 && (
          <div className="lib-row small muted" style={{ marginBottom: 4 }}>
            <span>{t("Name", "Navn")}</span><span>{t("Path on the NAS", "Sti på NAS")}</span><span>{t("Path in the container", "Sti i containeren")}</span><span>{t("Type", "Type")}</span><span>{t("Protected", "Beskyttet")}</span><span />
          </div>
        )}
        {s.libraries.map((l, i) => {
          const upd = (k: keyof Lib, v: unknown) => setS({ ...s, libraries: s.libraries.map((x, j) => (j === i ? { ...x, [k]: v } : x)) });
          return (
            <div className="lib-row" key={i}>
              <input type="text" value={l.name} onChange={(e) => upd("name", e.target.value)} aria-label={t("Name", "Navn")} />
              <input type="text" value={l.host_path} onChange={(e) => upd("host_path", e.target.value)} aria-label={t("Path on the NAS", "Sti på NAS")} placeholder="/mnt/tank/media/Movies" />
              <input type="text" value={l.container_path} onChange={(e) => upd("container_path", e.target.value)} aria-label={t("Path in the container", "Sti i containeren")} placeholder="/media/Movies" />
              <select value={l.kind} onChange={(e) => upd("kind", e.target.value)} aria-label={t("Type", "Type")}>
                {["movies", "series", "mixed", "downloads"].map((k) => <option key={k} value={k}>{libKindLabel(k)}</option>)}
              </select>
              <label className="check small"><input type="checkbox" checked={l.protected} onChange={(e) => upd("protected", e.target.checked)} />{t("Protected", "Beskyttet")}</label>
              <button className="btn small" onClick={() => setS({ ...s, libraries: s.libraries.filter((_, j) => j !== i) })}>{t("Remove", "Fjern")}</button>
            </div>
          );
        })}
        <div className="toolbar" style={{ marginTop: 10 }}>
          <button className="btn small" onClick={() => setS({ ...s, libraries: [...s.libraries, { name: "", host_path: "", container_path: "/media/", kind: "movies", protected: false }] })}>{t("Add library", "Legg til bibliotek")}</button>
          <button className="btn small" onClick={detect}>{t("Detect from /media", "Finn fra /media")}</button>
          {setup.data && setup.data.detected.length > 0 && <span className="small muted">{t(`Found under /media: ${setup.data.detected.map((d) => d.name).join(", ")}`, `Funnet under /media: ${setup.data.detected.map((d) => d.name).join(", ")}`)}</span>}
        </div>

        <h3 style={{ marginTop: 24 }}>{t("Path mappings from the services", "Stimapping fra tjenestene")}</h3>
        <p className="muted small" style={{ maxWidth: 760 }}>{t("Radarr, Sonarr and Plex often see the folders under other paths (e.g. «/movies» inside their container). Map each of their paths to the path on the NAS. The longest match wins.",
          "Radarr, Sonarr og Plex ser ofte mappene under andre stier (f.eks. «/movies» inne i sin container). Map hver av deres stier til stien på NAS-en. Lengste treff vinner.")}</p>
        {s.path_mappings.map((m, i) => (
          <div className="map-row" key={i}>
            <input type="text" value={m.from} placeholder="/movies" aria-label={t("Path in the service", "Sti i tjenesten")} onChange={(e) => setS({ ...s, path_mappings: s.path_mappings.map((x, j) => (j === i ? { ...x, from: e.target.value } : x)) })} />
            <span className="muted" style={{ textAlign: "center" }}>→</span>
            <input type="text" value={m.to} placeholder="/mnt/tank/media/Movies" aria-label={t("Path on the NAS", "Sti på NAS")} onChange={(e) => setS({ ...s, path_mappings: s.path_mappings.map((x, j) => (j === i ? { ...x, to: e.target.value } : x)) })} />
            <button className="btn small" onClick={() => setS({ ...s, path_mappings: s.path_mappings.filter((_, j) => j !== i) })}>{t("Remove", "Fjern")}</button>
          </div>
        ))}
        <div className="toolbar" style={{ marginTop: 10 }}>
          <button className="btn small" onClick={() => setS({ ...s, path_mappings: [...s.path_mappings, { from: "", to: "" }] })}>{t("Add mapping", "Legg til mapping")}</button>
        </div>
        {(suggestions.length > 0 || unmatched.length > 0) && (
          <div className="notice">
            {suggestions.length > 0 && <>
              <b>{t("Suggested mappings", "Foreslåtte mappinger")}</b>
              <ul className="conseq small">{suggestions.map((p) => (
                <li key={p.service + p.path}><code>{p.suggestion!.from}</code> → <code>{p.suggestion!.to}</code> <span className="muted">({p.service}, {t("library", "bibliotek")} {p.suggestion!.library})</span>{" "}
                  <button className="btn small" onClick={() => setS({ ...s, path_mappings: [...s.path_mappings, { from: p.suggestion!.from, to: p.suggestion!.to }] })}>{t("Use", "Bruk")}</button></li>
              ))}</ul>
            </>}
            {unmatched.length > 0 && <p className="small" style={{ margin: "6px 0 0" }}>{t("No library matches these folders from the services:", "Ingen bibliotek passer med disse mappene fra tjenestene:")} {unmatched.map((p) => `${p.path} (${p.service})`).join(", ")}</p>}
          </div>
        )}
        {setup.data && setup.data.paths.length > 0 && suggestions.length === 0 && unmatched.length === 0 && <p className="small ok-text">{t("All the services' folders match a library.", "Alle tjenestenes mapper passer med et bibliotek.")}</p>}
      </Section>

      <Section id="deletion">
        <p className="small muted" style={{ maxWidth: 760 }}>{t("The app starts read-only. Nothing is ever deleted automatically – every action is shown in a summary first and needs one confirmation. Everything is logged under Activity → Deletion log.",
          "Appen starter skrivebeskyttet. Ingenting slettes noen gang automatisk – hver handling vises i en oppsummering først og krever én bekreftelse. Alt loggføres under Aktivitet → Slettelogg.")}</p>
        <label className="check"><input type="checkbox" checked={!!s.actions?.enabled} onChange={(e) => setS({ ...s, actions: { ...s.actions, enabled: e.target.checked } })} /><b>{t("Allow changes through Radarr, Sonarr and Plex", "Tillat endringer via Radarr, Sonarr og Plex")}</b></label>
        <ul className="conseq small muted" style={{ maxWidth: 760 }}>
          <li>{t("Movies are deleted in Radarr and series in Sonarr, with their files. No import exclusion is added.", "Filmer slettes i Radarr og serier i Sonarr, med filene. Ingen importekskludering legges til.")}</li>
          <li>{t("Single seasons are unmonitored in Sonarr before the episode files are deleted, so they are not downloaded again.", "Enkeltsesonger avovervåkes i Sonarr før episodefilene slettes, så de ikke lastes ned igjen.")}</li>
          <li>{t("«Swap» to a smaller version downloads first. The old file is only deleted through Radarr/Sonarr once the new one is finished and can be imported.", "«Bytt» til en mindre versjon laster ned først. Den gamle filen slettes via Radarr/Sonarr først når den nye er ferdig og kan importeres.")}</li>
          <li>{t("Plex entries whose files are missing on disk can be removed from Plex (requires «Allow media deletion» in Plex).", "Plex-oppføringer der filene mangler på disk kan fjernes fra Plex (krever «Allow media deletion» i Plex).")}</li>
          <li>{t("Protected titles can never be deleted or swapped.", "Beskyttede titler kan aldri slettes eller byttes.")}</li>
        </ul>
        <label className="check" style={{ marginTop: 16 }}><input type="checkbox" checked={!!s.actions?.files_enabled} onChange={(e) => setS({ ...s, actions: { enabled: !!s.actions?.enabled, files_enabled: e.target.checked } })} /><b>{t("Allow deleting files on disk", "Tillat sletting av filer på disk")}</b></label>
        <ul className="conseq small muted" style={{ maxWidth: 760 }}>
          <li>{t("For redundant duplicates (one file always stays), old downloads, and folders that are neither in Radarr, Sonarr nor Plex.", "Gjelder overflødige duplikater (én fil blir alltid igjen), gamle nedlastinger, og mapper som verken er i Radarr, Sonarr eller Plex.")}</li>
          <li>{t("Also requires the folders to be mounted with write access: remove :ro on the lines under volumes in the app's compose file (Apps → the app → Edit).", "Krever også at mappene er montert med skrivetilgang: fjern :ro på linjene under volumes i appens compose-fil (Apps → appen → Edit).")}</li>
          <li>{t("Every file is checked right before deletion: unchanged since the scan, inside a library, not a symbolic link.", "Hver fil sjekkes rett før sletting: uendret siden skanning, inne i et bibliotek, ikke en symbolsk lenke.")}</li>
        </ul>
        {Object.keys(writable).length > 0 && (
          <p className="small">{t("Write access now:", "Skrivetilgang nå:")} {Object.entries(writable).map(([k, v], i) => <span key={k}>{i > 0 && ", "}{k} <span className={v ? "ok-text" : "warn-text"}>{v ? t("yes", "ja") : t("no (:ro)", "nei (:ro)")}</span></span>)}</p>
        )}
      </Section>

      <Section id="protection">
        <div className="form-grid">
          <label className="field"><span>{t("Tags in Radarr/Sonarr (comma separated)", "Tagger i Radarr/Sonarr (kommaseparert)")}</span><input type="text" value={s.protection.tags.join(", ")} onChange={(e) => setS({ ...s, protection: { ...s.protection, tags: list(e.target.value) } })} /></label>
          <label className="field"><span>{t("Labels in Plex", "Etiketter i Plex")}</span><input type="text" value={s.protection.plex_labels.join(", ")} onChange={(e) => setS({ ...s, protection: { ...s.protection, plex_labels: list(e.target.value) } })} /></label>
          <label className="field"><span>{t("Protected paths on the NAS", "Beskyttede stier på NAS")}</span><input type="text" placeholder="/mnt/tank/media/Movies/Collection" value={s.protection.paths.join(", ")} onChange={(e) => setS({ ...s, protection: { ...s.protection, paths: list(e.target.value) } })} /></label>
        </div>
        <label className="check" style={{ marginTop: 14 }}>
          <input type="checkbox" checked={!!s.protection.include_duplicates} onChange={(e) => setS({ ...s, protection: { ...s.protection, include_duplicates: e.target.checked } })} />
          {t("Protection also applies to duplicates and extra versions", "Beskyttelse gjelder også duplikater og ekstra versjoner")}
        </label>
        <p className="small muted" style={{ margin: "4px 0 0", maxWidth: 720 }}>{t("Off by default: extra copies and versions can be cleaned up in protected libraries and titles too, because one file always remains. The protection against deleting whole titles applies regardless.",
          "Av som standard: ekstra kopier og versjoner kan ryddes også i beskyttede biblioteker og titler, fordi én fil alltid blir igjen. Beskyttelsen mot å slette hele titler gjelder uansett.")}</p>
      </Section>

      <Section id="analysis">
        <div className="form-grid">
          <label className="field"><span>{t("«Not watched for» (months, three steps)", "«Ikke sett på» (måneder, tre trinn)")}</span><input type="text" value={(s.analysis.stale_months as number[]).join(", ")} onChange={(e) => { const v = list(e.target.value).map(Number).filter((n) => n > 0); if (v.length === 3) setA("stale_months", v.sort((a, b) => a - b)); }} /></label>
          <Num label={t("Quarantine for new titles (months)", "Karantene for nye titler (måneder)")} v={s.analysis.quarantine_months as number} on={(v) => setA("quarantine_months", v)} />
          <Num label={t("«Watched recently» means within (months)", "«Sett nylig» betyr innen (måneder)")} v={s.analysis.recent_play_months as number} on={(v) => setA("recent_play_months", v)} />
          <Num label={t("Smallest suggestion (GB)", "Minste forslag (GB)")} v={s.analysis.min_suggestion_gb as number} on={(v) => setA("min_suggestion_gb", v)} step={0.5} />
          <Num label={t("Large movie from (GB)", "Stor film fra (GB)")} v={s.analysis.large_movie_gb as number} on={(v) => setA("large_movie_gb", v)} />
          <Num label={t("Large episode from (GB)", "Stor episode fra (GB)")} v={s.analysis.large_episode_gb as number} on={(v) => setA("large_episode_gb", v)} step={0.5} />
          <Num label={t("Target for a replaced movie (GB)", "Mål for erstattet film (GB)")} v={s.analysis.target_movie_gb as number} on={(v) => setA("target_movie_gb", v)} />
          <Num label={t("Target for a replaced episode (GB)", "Mål for erstattet episode (GB)")} v={s.analysis.target_episode_gb as number} on={(v) => setA("target_episode_gb", v)} step={0.5} />
          <Num label={t("Show suggestions from priority", "Vis forslag fra prioritet")} v={s.analysis.min_score as number} on={(v) => setA("min_score", v)} />
        </div>
        <h3 style={{ marginTop: 20 }}>{t("Weighting of the priority", "Vekting av prioriteten")}</h3>
        <p className="muted small">{t("1 is the default. 0 switches the factor off, 2 doubles it.", "1 er standard. 0 slår av faktoren, 2 dobler den.")}</p>
        <div className="form-grid">
          {Object.entries(weights).map(([k, l]) => <Num key={k} label={l} v={s.weights[k]} on={(v) => setS({ ...s, weights: { ...s.weights, [k]: v } })} step={0.1} />)}
        </div>
      </Section>

      <Section id="scanning">
        <div className="form-grid">
          <Num label={t("Sync with the services every (hours)", "Synk med tjenestene hver (timer)")} v={s.sync.interval_hours} on={(v) => setS({ ...s, sync: { interval_hours: v } })} />
          <Num label={t("Incremental scan every (hours)", "Inkrementell skanning hver (timer)")} v={s.scanner.interval_hours} on={(v) => setS({ ...s, scanner: { ...s.scanner, interval_hours: v } })} />
          <Num label={t("Full scan every (days)", "Full skanning hver (dager)")} v={s.scanner.full_scan_days} on={(v) => setS({ ...s, scanner: { ...s.scanner, full_scan_days: v } })} />
          <Num label={t("Pause per 1000 files (ms)", "Pause per 1000 filer (ms)")} v={s.scanner.throttle_ms_per_1000} on={(v) => setS({ ...s, scanner: { ...s.scanner, throttle_ms_per_1000: v } })} />
          <Num label={t("Check for duplicates from (MB)", "Sjekk duplikater fra (MB)")} v={s.scanner.hash_min_size_mb} on={(v) => setS({ ...s, scanner: { ...s.scanner, hash_min_size_mb: v } })} />
        </div>
      </Section>

      <Section id="updates">
        <UpdateBox enabled={s.updates?.check ?? true} onToggle={(v) => setS({ ...s, updates: { check: v } })} />
      </Section>

      {(dirty || saved || saveErr) && (
        <div className="tray">
          <div className="grow small">{saveErr ? <span className="warn-text">{saveErr}</span> : saved && !dirty ? <span className="ok-text">{saved}</span> : <span className="muted">{t("You have unsaved changes.", "Du har ulagrede endringer.")}</span>}</div>
          {dirty && <button className="btn" onClick={() => data && setS(structuredClone(data))}>{t("Discard", "Forkast")}</button>}
          {dirty ? <button className="btn primary" onClick={save}>{t("Save settings", "Lagre innstillinger")}</button>
            : <button className="btn" onClick={() => { setSaved(null); setSaveErr(null); }}>{t("OK", "OK")}</button>}
        </div>
      )}
    </>
  );
}

function Section({ id, children }: { id: string; children: ReactNode }) {
  return (
    <section className="section" id={`s-${id}`} style={{ scrollMarginTop: 16 }}>
      <h2>{sectionTitle(id)}</h2>
      {children}
    </section>
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
    <div style={{ display: "grid", gap: 10, maxWidth: 680 }}>
      <label className="check"><input type="checkbox" checked={enabled} onChange={(e) => onToggle(e.target.checked)} />{t("Look for new versions on GitHub (every 6 hours)", "Se etter nye versjoner på GitHub (hver 6. time)")}</label>
      {u && (
        <p className="small muted" style={{ margin: 0 }}>
          {t(`You are running ${u.current}.`, `Du kjører ${u.current}.`)}{" "}
          {u.latest ? (u.available ? <>{t("Version", "Versjon")} <a href={u.url ?? "#"} target="_blank" rel="noreferrer">{u.latest}</a> {t("is available.", "er tilgjengelig.")}</> : t(`The latest release is ${u.latest}, you are up to date.`, `Siste utgivelse er ${u.latest}, du er oppdatert.`)) : t("No release information yet.", "Ingen informasjon om utgivelser ennå.")}
          {u.checked ? t(` Checked ${ago(u.checked)}${u.ok === false ? " (failed – does the container have internet access?)" : ""}.`, ` Sjekket ${ago(u.checked)}${u.ok === false ? " (feilet – har containeren tilgang til internett?)" : ""}.`) : ""}
        </p>
      )}
      <p className="small muted" style={{ margin: 0 }}>{t("The app never updates itself. With :latest in the compose file you update in TrueNAS: Apps → the app → ⋮ → Update.", "Appen oppdaterer seg aldri selv. Med :latest i compose-filen oppdaterer du i TrueNAS: Apps → appen → ⋮ → Update.")}</p>
      <div><button className="btn small" onClick={checkNow} disabled={busy || !enabled}>{busy ? t("Checking…", "Sjekker…") : t("Check now", "Sjekk nå")}</button></div>
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
