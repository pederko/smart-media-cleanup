import { Fragment, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { bytes, date, num } from "../format";
import { getLang, plural, t } from "../i18n";
import { Drawer, Empty, ErrorNote, Loading, PageHeader, statusLabel, StatusDot, SwitchedOff, Tray, useFetch, useRefreshTick } from "../components/common";

// ------------------------------------------------------------------ types from /api/arr-setup

type Change = Record<string, unknown> & { op: string };
type Finding = { id: string; level: "warn" | "info"; text: string; change?: Change };
type Def = { id: number; name: string; title: string; min: number | null; preferred: number | null; max: number | null;
  presets: Record<string, [number, number, number | null]>; used: boolean };
type Profile = { id: number; name: string; upgrade_allowed: boolean; cutoff: string | null; allowed: string[];
  formats: { id: number; name: string; score: number }[]; min_format_score: number; count: number; bytes: number;
  max_mb_per_min: number | null; unlimited: string[]; findings: Finding[] };
type Recipe = { key: string; name: string; info: string; allowed: string[]; cutoff: string; exists: boolean };
type Client = { id: number; name: string; implementation: string; enabled: boolean; remove_completed: boolean; category: string | null; finding?: Finding };
type Indexer = { id: number; name: string; enabled: boolean; ratio: number | null; minutes: number | null; prowlarr: boolean };
type Svc = { configured: boolean; error?: string; runtime: number; unlimited: number; definitions: Def[];
  files: Record<string, [number, number][]>; profiles: Profile[]; recipes: Recipe[];
  seeding: { clients: Client[]; indexers: Indexer[]; categories: string[] } };
type Slot = { field: string; label: string; profile: number | null; profile_name: string | null; allows_remux: boolean; count: number | null;
  finding?: { level: string; text: string; alternatives: number[] } };
type Server = { kind: "radarr" | "sonarr"; id: number; name: string; is4k: boolean; default: boolean; same_instance: boolean;
  profiles: { id: number; name: string }[]; slots: Slot[] };
type Torrent = { hash: string; name: string; category: string; state: string; complete: boolean; ratio: number; seeding_minutes: number;
  ratio_limit: number; seeding_limit: number; size: number; import_status: string | null; title_name: string | null; freed: number;
  imported: boolean; removable: boolean };
type Qbit = { configured: boolean; error?: string; url_hint?: string | null;
  limits?: { ratio_enabled: boolean; ratio: number; time_enabled: boolean; minutes: number; action: number };
  finding?: Finding | null; torrents?: Torrent[]; summary?: { count: number; size: number; removable: number; removable_freed: number } };
type Overview = { enabled: boolean; services: Record<"radarr" | "sonarr", Svc>; presets: Record<string, { info: string }>;
  seerr: { configured: boolean; error?: string; servers: Server[] }; qbit: Qbit; seed_default: { ratio: number; minutes: number } };
type PlanRow = { service: string; area: string; what: string; before?: unknown; after?: unknown; kind?: string; skipped?: boolean; bytes?: number };
type Plan = { enabled: boolean; rows: PlanRow[]; errors: { index: number; error: string }[]; changes: number; token: string };
type ExecResult = { results: { service: string; what: string; status: string; detail: string }[]; done: number; failed: number; backup: string | null };

const SVC_NAME: Record<string, string> = { radarr: "Radarr", sonarr: "Sonarr", seerr: "Seerr", qbittorrent: "qBittorrent" };
const TABS = ["advice", "sizes", "profiles", "seerr", "seeding", "backups"] as const;
type Tab = typeof TABS[number];
const tabLabel = (id: Tab) => ({
  advice: t("Recommendations", "Anbefalinger"), sizes: t("Size limits", "Størrelsesgrenser"), profiles: t("Quality profiles", "Kvalitetsprofiler"),
  seerr: "Seerr", seeding: t("Seeding", "Deling"), backups: t("Backups", "Sikkerhetskopier"),
})[id];

/** MB per minute -> bytes for one title of the given runtime. */
const perTitle = (mbpm: number | null | undefined, runtime: number) => (mbpm == null ? null : mbpm * runtime * 1024 * 1024);
const gbText = (mbpm: number | null | undefined, runtime: number, unl: number) =>
  mbpm == null || mbpm >= unl ? t("Unlimited", "Ubegrenset") : bytes(perTitle(mbpm, runtime));

export default function RulesPage({ tab: tabParam }: { tab: string }) {
  const tick = useRefreshTick();
  const tab: Tab = (TABS as readonly string[]).includes(tabParam) ? (tabParam as Tab) : "advice";
  const [reload, setReload] = useState(0);
  const { data, error, loading } = useFetch<Overview>("/api/arr-setup", [tick, reload]);
  const [changes, setChanges] = useState<Record<string, Change>>({});
  const [review, setReview] = useState(false);
  const toggle = (id: string, ch: Change | null) => setChanges((c) => {
    const n = { ...c };
    if (ch) n[id] = ch; else delete n[id];
    return n;
  });
  const count = Object.keys(changes).length;

  const findings = useMemo(() => collect(data), [data]);
  const warn = findings.filter((f) => f.change);

  return (
    <>
      <PageHeader title={t("Download rules", "Nedlastingsregler")}
        lede={t("How Radarr, Sonarr, Seerr and qBittorrent decide what is downloaded and how long it is kept – compared with the recommendations from TRaSH Guides. Nothing changes until you review and confirm, and a backup of everything that changes is saved first.",
          "Hvordan Radarr, Sonarr, Seerr og qBittorrent bestemmer hva som lastes ned og hvor lenge det beholdes – sammenlignet med anbefalingene fra TRaSH Guides. Ingenting endres før du ser over og bekrefter, og en sikkerhetskopi av alt som endres lagres først.")} />
      <nav className="tabs" aria-label={t("Download rules", "Nedlastingsregler")}>
        {TABS.map((id) => (
          <a key={id} href={`#/rules/${id}`} aria-current={tab === id ? "page" : undefined}>
            {tabLabel(id)}{id === "advice" && warn.length ? <span className="count">{warn.length}</span> : null}
          </a>
        ))}
      </nav>
      <ErrorNote error={error} />
      {!data && loading && <Loading />}
      {data && (
        <>
          {tab === "advice" && <AdviceTab data={data} findings={findings} changes={changes} toggle={toggle} />}
          {tab === "sizes" && <SizesTab data={data} changes={changes} toggle={toggle} />}
          {tab === "profiles" && <ProfilesTab data={data} changes={changes} toggle={toggle} />}
          {tab === "seerr" && <SeerrTab data={data} changes={changes} toggle={toggle} />}
          {tab === "seeding" && <SeedingTab data={data} changes={changes} toggle={toggle} />}
          {tab === "backups" && <BackupsTab onRestored={() => setReload((r) => r + 1)} />}
        </>
      )}
      {count > 0 && <div style={{ height: 110 }} aria-hidden />}
      {count > 0 && (
        <Tray figure={plural(count, ["change", "changes"], ["endring", "endringer"])} note={t("Nothing is changed until you confirm", "Ingenting endres før du bekrefter")}>
          <button className="btn small" onClick={() => setChanges({})}>{t("Clear", "Tøm")}</button>
          <button className="btn primary" onClick={() => setReview(true)}>{t("Review…", "Se over…")}</button>
        </Tray>
      )}
      {review && <ReviewDialog changes={Object.values(changes)} enabled={!!data?.enabled} onClose={() => setReview(false)}
        onDone={() => { setChanges({}); setReload((r) => r + 1); }} />}
    </>
  );
}

type TabProps = { data: Overview; changes: Record<string, Change>; toggle: (id: string, ch: Change | null) => void };

/** Every actionable finding across the services, for the Recommendations tab and the counter. */
type Item = Finding & { where: string; service: string };
function collect(d: Overview | null): Item[] {
  if (!d) return [];
  const out: Item[] = [];
  for (const svc of ["radarr", "sonarr"] as const) {
    const s = d.services[svc];
    if (!s?.configured || s.error) continue;
    for (const p of s.profiles) for (const f of p.findings) out.push({ ...f, service: svc, where: t(`${SVC_NAME[svc]} · profile «${p.name}»`, `${SVC_NAME[svc]} · profil «${p.name}»`) });
    for (const c of s.seeding.clients) if (c.finding) out.push({ ...c.finding, service: svc, where: t(`${SVC_NAME[svc]} · download client`, `${SVC_NAME[svc]} · nedlastingsklient`) });
    const unlimited = s.definitions.filter((x) => x.used && x.presets.balanced && (x.max == null || x.max >= s.unlimited));
    if (unlimited.length) out.push({ id: `${svc}:sizes`, level: "warn", service: svc, where: t(`${SVC_NAME[svc]} · size limits`, `${SVC_NAME[svc]} · størrelsesgrenser`),
      text: t(`${unlimited.length} qualities in use have no upper size limit (${unlimited.slice(0, 3).map((x) => x.name).join(", ")}${unlimited.length > 3 ? "…" : ""}). The «Balanced» preset caps them.`,
        `${unlimited.length} kvaliteter i bruk har ingen øvre størrelsesgrense (${unlimited.slice(0, 3).map((x) => x.name).join(", ")}${unlimited.length > 3 ? "…" : ""}). Forhåndsvalget «Balansert» setter et tak.`),
      change: { op: "definitions", service: svc, values: Object.fromEntries(s.definitions.filter((x) => x.presets.balanced).map((x) => [x.name, x.presets.balanced])) } });
  }
  for (const sv of d.seerr.servers) for (const sl of sv.slots) if (sl.finding) {
    const alt = sv.profiles.find((p) => sl.finding!.alternatives.includes(p.id));
    out.push({ id: `seerr:${sv.kind}:${sv.id}:${sl.field}`, level: "warn", service: "seerr", where: `Seerr · ${sv.name}`,
      text: sl.finding.text + (alt ? t(` Suggested: «${alt.name}».`, ` Forslag: «${alt.name}».`) : ""),
      change: alt ? { op: "seerr_profile", kind: sv.kind, server: sv.id, field: sl.field, profile: alt.id, name: alt.name } : undefined });
  }
  if (d.qbit.finding) out.push({ ...d.qbit.finding, service: "qbittorrent", where: "qBittorrent" });
  if (d.qbit.summary?.removable) out.push({ id: "qbit:remove", level: "warn", service: "qbittorrent", where: "qBittorrent",
    text: t(`${d.qbit.summary.removable} finished torrents are already in your library and still seeding. Removing them with their files frees ${bytes(d.qbit.summary.removable_freed)} (hardlinked ones free nothing, but stop seeding).`,
      `${d.qbit.summary.removable} ferdige torrenter ligger allerede i biblioteket og deler fortsatt. Fjernes de med filene, frigjøres ${bytes(d.qbit.summary.removable_freed)} (hardlenkede frigjør ingenting, men slutter å dele).`),
    change: { op: "qbit_remove", hashes: (d.qbit.torrents ?? []).filter((x) => x.removable).map((x) => x.hash) } });
  return out;
}

function Check({ id, change, changes, toggle, label }: { id: string; change: Change; changes: Record<string, Change>; toggle: TabProps["toggle"]; label?: string }) {
  return (
    <label className="check small">
      <input type="checkbox" checked={!!changes[id]} onChange={(e) => toggle(id, e.target.checked ? change : null)} />
      {label ?? t("Include", "Ta med")}
    </label>
  );
}

function NotConfigured({ what }: { what: string }) {
  return <p className="muted small">{t(`${what} is not connected.`, `${what} er ikke koblet til.`)} <a href="#/settings/services">{t("Settings → Connections", "Innstillinger → Tilkoblinger")}</a></p>;
}

// ------------------------------------------------------------------ Recommendations

function AdviceTab({ data, findings, changes, toggle }: TabProps & { findings: Item[] }) {
  const actionable = findings.filter((f) => f.change);
  const notes = findings.filter((f) => !f.change);
  const all = () => actionable.forEach((f) => toggle(f.id, f.change!));
  const usage = (["radarr", "sonarr"] as const).flatMap((svc) => {
    const s = data.services[svc];
    if (!s?.configured || s.error) return [];
    const remux = s.profiles.filter((p) => p.allowed.some((q) => /remux/i.test(q)));
    return [{ svc, profiles: s.profiles.length, remux, titles: remux.reduce((a, p) => a + p.count, 0), size: remux.reduce((a, p) => a + p.bytes, 0) }];
  });
  return (
    <>
      <section className="brief">
        <p className="brief-lead">
          {actionable.length
            ? <>{t(`${actionable.length} recommended changes`, `${actionable.length} anbefalte endringer`)} {t("to keep new downloads at a sensible size and stop endless seeding.", "for å holde nye nedlastinger på en fornuftig størrelse og stoppe evig deling.")}</>
            : t("Your setup follows the recommendations.", "Oppsettet ditt følger anbefalingene.")}
        </p>
        <ul className="brief-points">
          {usage.map((u) => (
            <li key={u.svc}>{SVC_NAME[u.svc]}: {plural(u.profiles, ["profile", "profiles"], ["profil", "profiler"])}
              {u.remux.length > 0 && <>, {t(`${u.remux.length} allow remuxes – used by`, `${u.remux.length} tillater remuxer – brukt av`)} <b>{plural(u.titles, ["title", "titles"], ["tittel", "titler"])}</b> ({bytes(u.size)})</>}.</li>
          ))}
          {!data.services.radarr?.configured && <li><NotConfigured what="Radarr" /></li>}
          {!data.qbit.configured && <li className="muted">{t("Connect qBittorrent under Settings → Connections to see what is still seeding.", "Koble til qBittorrent under Innstillinger → Tilkoblinger for å se hva som fortsatt deler.")}</li>}
        </ul>
        <p className="small muted">{t("Changes only affect what is downloaded from now on. Files you already have stay as they are – use «Swap quality» to replace large ones.",
          "Endringer påvirker bare det som lastes ned fra nå av. Filer du allerede har blir som de er – bruk «Bytt kvalitet» for å erstatte store filer.")}</p>
      </section>
      {actionable.length > 0 && (
        <div className="toolbar"><button className="btn small" onClick={all}>{t("Include all recommendations", "Ta med alle anbefalingene")}</button></div>
      )}
      <div className="rules-list">
        {actionable.map((f) => (
          <div key={f.id} className={`rule ${f.level}`}>
            <div>
              <div className="small muted">{f.where}</div>
              <div>{f.text}</div>
            </div>
            <Check id={f.id} change={f.change!} changes={changes} toggle={toggle} />
          </div>
        ))}
      </div>
      {notes.length > 0 && (
        <>
          <h3 style={{ marginTop: 28 }}>{t("Good to know", "Greit å vite")}</h3>
          <ul className="conseq small muted">{notes.map((f) => <li key={f.id}><b>{f.where}:</b> {f.text}</li>)}</ul>
        </>
      )}
      <p className="small muted" style={{ marginTop: 24 }}>{t("Based on", "Basert på")} <a href="https://trash-guides.info" target="_blank" rel="noreferrer">TRaSH Guides</a>{t(". For the full custom-format setup from TRaSH (release groups, HDR, audio), use Recyclarr or Notifiarr – this page only adjusts sizes, qualities and the few scores that drive file size.",
        ". For hele custom format-oppsettet fra TRaSH (utgivergrupper, HDR, lyd), bruk Recyclarr eller Notifiarr – denne siden justerer bare størrelser, kvaliteter og de få poengene som driver filstørrelsen.")}</p>
    </>
  );
}

// ------------------------------------------------------------------ Size limits

type Vals = Record<string, [number | null, number | null, number | null]>;

function SizesTab({ data, changes, toggle }: TabProps) {
  const [svc, setSvc] = useState<"radarr" | "sonarr">("radarr");
  const s = data.services[svc];
  if (!s?.configured) return <NotConfigured what={SVC_NAME[svc]} />;
  return (
    <>
      <div className="toolbar">
        <div className="seg" role="group" aria-label={t("Service", "Tjeneste")}>
          {(["radarr", "sonarr"] as const).map((x) => <button key={x} aria-pressed={svc === x} onClick={() => setSvc(x)}>{SVC_NAME[x]}</button>)}
        </div>
      </div>
      {s.error ? <ErrorNote error={s.error} /> : <SizeEditor key={svc} svc={svc} s={s} data={data} changes={changes} toggle={toggle} />}
    </>
  );
}

function SizeEditor({ svc, s, data, changes, toggle }: TabProps & { svc: "radarr" | "sonarr"; s: Svc }) {
  const id = `${svc}:sizes`;
  const current: Vals = Object.fromEntries(s.definitions.map((d) => [d.name, [d.min,
    d.preferred != null && d.preferred >= s.unlimited - 5 ? null : d.preferred, d.max != null && d.max >= s.unlimited ? null : d.max]]));
  const norm = (v: Vals[string]): Vals[string] => [v[0], v[1] != null && v[1] >= s.unlimited - 5 ? null : v[1], v[2] != null && v[2] >= s.unlimited ? null : v[2]];
  const pending = changes[id]?.values as Vals | undefined;
  const [vals, setVals] = useState<Vals>(() => ({ ...current, ...(pending ?? {}) }));
  const [all, setAll] = useState(false);
  const unit = svc === "radarr" ? t("per movie (2 h)", "per film (2 t)") : t("per episode (45 min)", "per episode (45 min)");
  const rows = s.definitions.filter((d) => all || d.used);

  // Keep the change in the basket in step with the table
  useEffect(() => {
    const diff = Object.fromEntries(Object.entries(vals).filter(([k, v]) => JSON.stringify(v) !== JSON.stringify(current[k])));
    toggle(id, Object.keys(diff).length ? { op: "definitions", service: svc, values: diff } : null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vals]);

  const preset = (key: string) => setVals(Object.fromEntries(s.definitions.map((d) => [d.name, d.presets[key] ? norm(d.presets[key] as Vals[string]) : current[d.name]])));
  const setOne = (name: string, i: 0 | 1 | 2, gb: string) => {
    const v = gb.trim() === "" ? null : (Number(gb.replace(",", ".")) * 1024) / s.runtime;
    setVals((x) => { const n = [...(x[name] ?? [null, null, null])] as Vals[string]; n[i] = v == null || isNaN(v) ? null : Math.round(v * 10) / 10; return { ...x, [name]: n }; });
  };
  const over = (name: string, max: number | null) => {
    const f = s.files[name] ?? [];
    if (max == null) return { n: 0, size: 0 };
    const hit = f.filter(([mbpm]) => mbpm > max);
    return { n: hit.length, size: hit.reduce((a, [, sz]) => a + sz, 0) };
  };
  const totalOver = rows.reduce((a, d) => { const o = over(d.name, vals[d.name]?.[2] ?? null); return { n: a.n + o.n, size: a.size + o.size }; }, { n: 0, size: 0 });
  const gbVal = (mbpm: number | null) => {
    if (mbpm == null) return "";
    const v = String(Math.round(((mbpm * s.runtime) / 1024) * 10) / 10);
    return getLang() === "nb" ? v.replace(".", ",") : v;
  };

  return (
    <>
      <p className="muted small" style={{ maxWidth: 780 }}>{t(`Radarr and Sonarr measure size in MB per minute of runtime. Here it is shown ${unit}. A release above the maximum is refused; among the rest, the one closest to «preferred» wins when the scores are equal.`,
        `Radarr og Sonarr måler størrelse i MB per minutt spilletid. Her vises det ${unit}. En utgivelse over maksimum avvises; blant resten vinner den nærmest «foretrukket» når poengene er like.`)}</p>
      <div className="toolbar">
        {(["balanced", "small", "trash"] as const).map((k) => (
          <button key={k} className={`btn small${k === "balanced" ? " primary" : ""}`} title={data.presets[k]?.info} onClick={() => preset(k)}>
            {k === "balanced" ? t("Balanced (recommended)", "Balansert (anbefalt)") : k === "small" ? t("Space saver", "Plassbesparende") : "TRaSH Guides"}
          </button>
        ))}
        <button className="btn small" onClick={() => setVals(current)}>{t("Current values", "Nåværende verdier")}</button>
        <label className="check small"><input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} />{t("Show qualities no profile uses", "Vis kvaliteter ingen profil bruker")}</label>
      </div>
      <div className="table-wrap">
        <table className="sizes">
          <thead><tr>
            <th>{t("Quality", "Kvalitet")}</th><th className="r">{t("Now: max", "Nå: maks")}</th>
            <th className="r">{t("Minimum", "Minimum")}</th><th className="r">{t("Preferred", "Foretrukket")}</th><th className="r">{t("Maximum", "Maksimum")}</th>
            <th className="r">{t("Files above", "Filer over")}</th>
          </tr></thead>
          <tbody>
            {rows.map((d) => {
              const v = vals[d.name] ?? [null, null, null];
              const changed = JSON.stringify(v) !== JSON.stringify(current[d.name]);
              const o = over(d.name, v[2]);
              return (
                <tr key={d.name} className={changed ? "changed" : undefined}>
                  <td>{d.name}{!d.used && <span className="small muted"> · {t("not used", "ikke i bruk")}</span>}</td>
                  <td className="r small">{gbText(d.max, s.runtime, s.unlimited)}</td>
                  {([0, 1, 2] as const).map((i) => (
                    <td className="r" key={i}>
                      <input className="gb" type="text" inputMode="decimal" value={gbVal(v[i])} placeholder={i === 0 ? "0" : i === 1 ? t("max", "maks") : "∞"} aria-label={`${d.name} ${["min", "preferred", "max"][i]}`}
                        onChange={(e) => setOne(d.name, i, e.target.value)} /> <span className="small muted">GB</span>
                    </td>
                  ))}
                  <td className="r small">{o.n ? <span className="warn-text">{num(o.n)} · {bytes(o.size)}</span> : <span className="muted">–</span>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="small muted">{t("Empty maximum = unlimited.", "Tomt maksimum = ubegrenset.")}{" "}
        {totalOver.n > 0 && t(`With these limits, ${num(totalOver.n)} existing ${svc === "radarr" ? "movies" : "episodes"} (${bytes(totalOver.size)}) are above the maximum for their quality. They are kept, but will not be upgraded to anything bigger – «Swap quality» can replace them.`,
          `Med disse grensene er ${num(totalOver.n)} eksisterende ${svc === "radarr" ? "filmer" : "episoder"} (${bytes(totalOver.size)}) over maksimum for sin kvalitet. De beholdes, men oppgraderes ikke til noe større – «Bytt kvalitet» kan erstatte dem.`)}</p>
      <dl className="kv small" style={{ marginTop: 14 }}>
        <dt>{t("Balanced", "Balansert")}</dt><dd>{data.presets.balanced?.info}</dd>
        <dt>{t("Space saver", "Plassbesparende")}</dt><dd>{data.presets.small?.info}</dd>
        <dt>TRaSH Guides</dt><dd>{data.presets.trash?.info}</dd>
      </dl>
    </>
  );
}

// ------------------------------------------------------------------ Quality profiles

function ProfilesTab({ data, changes, toggle }: TabProps) {
  return (
    <>
      {(["radarr", "sonarr"] as const).map((svc) => {
        const s = data.services[svc];
        return (
          <section key={svc} style={{ marginBottom: 32 }}>
            <h2>{SVC_NAME[svc]}</h2>
            {!s?.configured ? <NotConfigured what={SVC_NAME[svc]} /> : s.error ? <ErrorNote error={s.error} /> : (
              <>
                <div className="grid cols-2" style={{ gap: 14 }}>
                  {s.profiles.map((p) => <ProfileCard key={p.id} svc={svc} s={s} p={p} changes={changes} toggle={toggle} />)}
                </div>
                <h3 style={{ marginTop: 20 }}>{t("Add a recommended profile", "Legg til en anbefalt profil")}</h3>
                <p className="small muted" style={{ maxWidth: 780 }}>{t("Qualities as recommended by TRaSH Guides. Custom formats, their scores and the language are copied from the profile you choose, so your own setup is carried over. Afterwards, choose it in Seerr and move titles to it in " + SVC_NAME[svc] + " (mass editor).",
                  "Kvaliteter slik TRaSH Guides anbefaler. Custom formats, poengene og språket kopieres fra profilen du velger, så ditt eget oppsett blir med videre. Velg den deretter i Seerr og flytt titler til den i " + SVC_NAME[svc] + " (masseredigering).")}</p>
                <div className="grid cols-3" style={{ gap: 14 }}>
                  {s.recipes.map((r) => <RecipeCard key={r.key} svc={svc} s={s} r={r} changes={changes} toggle={toggle} />)}
                </div>
              </>
            )}
          </section>
        );
      })}
    </>
  );
}

function ProfileCard({ svc, s, p, changes, toggle }: { svc: string; s: Svc; p: Profile } & Omit<TabProps, "data">) {
  const big = p.max_mb_per_min != null ? bytes(perTitle(p.max_mb_per_min, s.runtime)) : null;
  return (
    <section className="panel" style={{ display: "grid", gap: 8, alignContent: "start" }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
        <h3 style={{ margin: 0 }}>{p.name}</h3>
        <span className="small muted">{plural(p.count, svc === "radarr" ? ["movie", "movies"] : ["series", "series"], svc === "radarr" ? ["film", "filmer"] : ["serie", "serier"])} · {bytes(p.bytes)}</span>
      </div>
      <div className="chips">
        {p.allowed.map((q) => <span key={q} className={`chip${/remux|br-disk|raw-hd/i.test(q) ? " warn" : ""}`}>{q}{q === p.cutoff ? " ★" : ""}</span>)}
      </div>
      <div className="small muted">
        {p.upgrade_allowed ? t(`Upgrades until ${p.cutoff} (★).`, `Oppgraderer til ${p.cutoff} (★).`) : t("Upgrades are off.", "Oppgraderinger er av.")}{" "}
        {big ? t(`Largest allowed: about ${big} ${svc === "radarr" ? "per movie" : "per episode"}.`, `Størst tillatt: ca. ${big} ${svc === "radarr" ? "per film" : "per episode"}.`)
          : t("No upper size limit.", "Ingen øvre størrelsesgrense.")}
      </div>
      {p.formats.length > 0 && (
        <details className="small"><summary>{plural(p.formats.length, ["scored custom format", "scored custom formats"], ["custom format med poeng", "custom formats med poeng"])}</summary>
          <ul className="conseq">{p.formats.map((f) => <li key={f.id}>{f.name}: <b>{f.score > 0 ? `+${f.score}` : f.score}</b></li>)}</ul>
        </details>
      )}
      {p.findings.map((f) => (
        <div key={f.id} className={`rule ${f.level}`}>
          <div className="small">{f.text}</div>
          {f.change && <Check id={f.id} change={f.change} changes={changes} toggle={toggle} />}
        </div>
      ))}
    </section>
  );
}

function RecipeCard({ svc, s, r, changes, toggle }: { svc: string; s: Svc; r: Recipe } & Omit<TabProps, "data">) {
  const id = `${svc}:recipe:${r.key}`;
  const [base, setBase] = useState<number>(() => (changes[id]?.base as number) ?? s.profiles[0]?.id);
  const change = { op: "create_profile", service: svc, recipe: r.key, base };
  useEffect(() => { if (changes[id]) toggle(id, change); /* keep the base in step */ // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [base]);
  return (
    <section className="panel" style={{ display: "grid", gap: 8, alignContent: "start" }}>
      <h3 style={{ margin: 0 }}>{r.name}</h3>
      <div className="small">{r.info}</div>
      <div className="small muted">{r.allowed.join(", ")} · {t("upgrade until", "oppgrader til")} {r.cutoff}</div>
      {r.exists ? <div className="small ok-text">{t("Already exists", "Finnes allerede")}</div> : (
        <>
          <label className="field small"><span>{t("Custom formats and language from", "Custom formats og språk fra")}</span>
            <select value={base} onChange={(e) => setBase(Number(e.target.value))}>{s.profiles.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select>
          </label>
          <Check id={id} change={change} changes={changes} toggle={toggle} label={t("Create", "Opprett")} />
        </>
      )}
    </section>
  );
}

// ------------------------------------------------------------------ Seerr

function SeerrTab({ data, changes, toggle }: TabProps) {
  const sr = data.seerr;
  if (!sr.configured) return <NotConfigured what="Seerr" />;
  if (sr.error) return <ErrorNote error={sr.error} />;
  if (!sr.servers.length) return <Empty>{t("Seerr has no Radarr or Sonarr servers.", "Seerr har ingen Radarr- eller Sonarr-servere.")}</Empty>;
  return (
    <>
      <p className="muted small" style={{ maxWidth: 780 }}>{t("The profile Seerr gives Radarr/Sonarr for new requests decides how large they become. Users with the «Advanced requests» permission can still choose another profile per request.",
        "Profilen Seerr gir Radarr/Sonarr for nye forespørsler avgjør hvor store de blir. Brukere med tillatelsen «Advanced requests» kan fortsatt velge en annen profil per forespørsel.")}</p>
      <div className="grid cols-2" style={{ gap: 14 }}>
        {sr.servers.map((sv) => (
          <section key={`${sv.kind}${sv.id}`} className="panel" style={{ display: "grid", gap: 10, alignContent: "start" }}>
            <h3 style={{ margin: 0 }}>{sv.name} <span className="small muted">({SVC_NAME[sv.kind]}{sv.is4k ? ", 4K" : ""}{sv.default ? t(", default", ", standard") : ""})</span></h3>
            {sv.slots.map((sl) => {
              const id = `seerr:${sv.kind}:${sv.id}:${sl.field}`;
              const chosen = (changes[id]?.profile as number | undefined) ?? sl.profile ?? undefined;
              const pick = (pid: number) => {
                const p = sv.profiles.find((x) => x.id === pid);
                toggle(id, pid === sl.profile || !p ? null : { op: "seerr_profile", kind: sv.kind, server: sv.id, field: sl.field, profile: pid, name: p.name });
              };
              return (
                <div key={sl.field} style={{ display: "grid", gap: 4 }}>
                  <label className="field"><span>{sl.label}</span>
                    <select value={chosen ?? ""} onChange={(e) => pick(Number(e.target.value))}>
                      {sv.profiles.map((p) => <option key={p.id} value={p.id}>{p.name}{p.id === sl.profile ? t(" (now)", " (nå)") : ""}{sl.finding?.alternatives.includes(p.id) ? " ✓" : ""}</option>)}
                    </select>
                  </label>
                  {sl.finding && <div className="small warn-text">{sl.finding.text} {t("Profiles marked ✓ do not allow remuxes.", "Profiler merket ✓ tillater ikke remuxer.")}</div>}
                  {!sv.same_instance && <div className="small muted">{t("This server is not the Radarr/Sonarr connected to the app, so its profiles are not analysed.", "Denne serveren er ikke den Radarr/Sonarr appen er koblet til, så profilene analyseres ikke.")}</div>}
                </div>
              );
            })}
          </section>
        ))}
      </div>
    </>
  );
}

// ------------------------------------------------------------------ Seeding

function SeedingTab({ data, changes, toggle }: TabProps) {
  const q = data.qbit;
  const [ratio, setRatio] = useState<string>(() => String(q.limits?.ratio_enabled ? q.limits.ratio : data.seed_default.ratio));
  const [hours, setHours] = useState<string>(() => String(Math.round(((q.limits?.time_enabled ? q.limits.minutes : data.seed_default.minutes) / 60) * 10) / 10));
  const [only, setOnly] = useState<"all" | "removable">("removable");
  const [sel, setSel] = useState<string[]>([]);
  const torrents = (q.torrents ?? []).filter((x) => only === "all" || x.removable);
  const prefsChange = () => {
    const r = ratio.trim() === "" ? null : Number(ratio.replace(",", "."));
    const h = hours.trim() === "" ? null : Number(hours.replace(",", "."));
    return { op: "qbit_prefs", ratio: r, minutes: h == null ? null : Math.round(h * 60) };
  };
  useEffect(() => { if (changes["qbit:prefs"]) toggle("qbit:prefs", prefsChange()); // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ratio, hours]);
  const chosen = torrents.filter((x) => sel.includes(x.hash));
  const act = (x: Torrent) => (x.seeding_limit === -1 && x.ratio_limit === -1 ? t("no limit", "ingen grense") : x.seeding_limit === -2 && x.ratio_limit === -2 ? t("global", "global") : t("own", "egen"));
  const importLabel = (s: string | null) => ({ hardlinked: t("In library (hardlink)", "I biblioteket (hardlenke)"), copied: t("In library (copy)", "I biblioteket (kopi)"),
    not_imported: t("Not imported", "Ikke importert"), no_video: t("No video", "Ingen video") } as Record<string, string>)[s ?? ""] ?? t("Unknown", "Ukjent");

  return (
    <>
      <section className="brief">
        <p className="brief-lead">{t("For finished torrents to disappear by themselves, two things are needed: qBittorrent must stop a torrent when it has seeded enough, and Radarr/Sonarr must have «Remove completed» switched on. Then they remove the torrent and its downloaded files – after the import, so the library copy stays.",
          "For at ferdige torrenter skal forsvinne av seg selv, trengs to ting: qBittorrent må stoppe en torrent når den har delt nok, og Radarr/Sonarr må ha «Remove completed» slått på. Da fjerner de torrenten og de nedlastede filene – etter importen, så kopien i biblioteket blir.")}</p>
      </section>

      <h3>{t("1. Radarr and Sonarr: remove completed downloads", "1. Radarr og Sonarr: fjern fullførte nedlastinger")}</h3>
      {(["radarr", "sonarr"] as const).map((svc) => {
        const s = data.services[svc];
        if (!s?.configured || s.error) return null;
        return s.seeding.clients.map((c) => (
          <div key={`${svc}${c.id}`} className={`rule ${c.finding ? "warn" : "ok"}`}>
            <div><div className="small muted">{SVC_NAME[svc]} · {c.implementation}{c.category ? ` · ${t("category", "kategori")} ${c.category}` : ""}</div>
              <div>{c.name}: {c.remove_completed ? t("«Remove completed» is on.", "«Remove completed» er på.") : c.finding?.text}</div></div>
            {c.finding?.change && <Check id={c.finding.id} change={c.finding.change} changes={changes} toggle={toggle} label={t("Switch on", "Slå på")} />}
          </div>
        ));
      })}

      <h3 style={{ marginTop: 24 }}>{t("2. qBittorrent: stop when seeded enough", "2. qBittorrent: stopp når det er delt nok")}</h3>
      {!q.configured ? (
        <p className="small muted">{t("Connect qBittorrent under", "Koble til qBittorrent under")} <a href="#/settings/services">{t("Settings → Connections", "Innstillinger → Tilkoblinger")}</a>{q.url_hint ? t(` (Radarr uses ${q.url_hint})`, ` (Radarr bruker ${q.url_hint})`) : ""}. {t("Or set it in qBittorrent yourself: Options → BitTorrent → Seeding limits → «When ratio reaches» / «When total seeding time reaches» → «Stop torrent».",
          "Eller sett det i qBittorrent selv: Options → BitTorrent → Seeding limits → «When ratio reaches» / «When total seeding time reaches» → «Stop torrent».")}</p>
      ) : q.error ? <ErrorNote error={q.error} /> : (
        <div className={`rule ${q.finding ? "warn" : "ok"}`}>
          <div style={{ display: "grid", gap: 8 }}>
            <div>{t("Now:", "Nå:")} {q.limits?.ratio_enabled ? t(`ratio ${q.limits.ratio}`, `ratio ${q.limits.ratio}`) : t("no ratio limit", "ingen ratio-grense")}, {q.limits?.time_enabled ? t(`${num(q.limits.minutes / 60, 1)} hours`, `${num(q.limits.minutes / 60, 1)} timer`) : t("no time limit", "ingen tidsgrense")}{q.limits?.action !== 0 ? t(" – the action is not «Stop»", " – handlingen er ikke «Stopp»") : ""}.</div>
            <div className="toolbar" style={{ margin: 0 }}>
              <label className="check small">{t("Stop at ratio", "Stopp ved ratio")} <input type="text" inputMode="decimal" style={{ width: 60 }} value={ratio} onChange={(e) => setRatio(e.target.value)} /></label>
              <label className="check small">{t("or after", "eller etter")} <input type="text" inputMode="decimal" style={{ width: 60 }} value={hours} onChange={(e) => setHours(e.target.value)} /> {t("hours", "timer")}</label>
            </div>
            <div className="small muted">{t("Applies to every torrent that uses the global limit – also ones not from Radarr/Sonarr. Private trackers often require a minimum seeding time; their rules win over this.",
              "Gjelder alle torrenter som bruker den globale grensen – også de som ikke kommer fra Radarr/Sonarr. Private trackere krever ofte en minste delingstid; reglene deres går foran dette.")}</div>
          </div>
          <Check id="qbit:prefs" change={prefsChange()} changes={changes} toggle={toggle} label={t("Set", "Sett")} />
        </div>
      )}

      {(["radarr", "sonarr"] as const).some((svc) => data.services[svc]?.seeding?.indexers.some((i) => i.ratio != null || i.minutes != null || i.prowlarr)) && (
        <>
          <h3 style={{ marginTop: 24 }}>{t("Indexer seed limits", "Delingsgrenser per indekser")}</h3>
          <p className="small muted" style={{ maxWidth: 780 }}>{t("An indexer's own seed ratio/time is given to qBittorrent with each torrent and wins over the global limit. Indexers synced from Prowlarr are set in Prowlarr (Indexers → edit → Seed Ratio / Seed Time) – changes made in Radarr/Sonarr are overwritten.",
            "En indekser sin egen delingsratio/-tid sendes til qBittorrent med hver torrent og går foran den globale grensen. Indeksere synket fra Prowlarr settes i Prowlarr (Indexers → rediger → Seed Ratio / Seed Time) – endringer i Radarr/Sonarr overskrives.")}</p>
          <ul className="conseq small">
            {(["radarr", "sonarr"] as const).flatMap((svc) => (data.services[svc]?.seeding?.indexers ?? []).map((i) => (
              <li key={svc + i.id}>{SVC_NAME[svc]} · {i.name}: {i.ratio != null ? `ratio ${i.ratio}` : t("ratio: global", "ratio: global")}, {i.minutes != null ? `${i.minutes} min` : t("time: global", "tid: global")}</li>
            )))}
          </ul>
        </>
      )}

      {q.configured && !q.error && (
        <>
          <h3 style={{ marginTop: 24 }}>{t("3. Torrents from Radarr and Sonarr", "3. Torrenter fra Radarr og Sonarr")}</h3>
          <p className="small muted" style={{ maxWidth: 780 }}>{t(`${q.summary?.count ?? 0} torrents (${bytes(q.summary?.size)}). Torrents that are finished and already in a library can be removed with their downloaded files now. Not-imported ones are never removed here.`,
            `${q.summary?.count ?? 0} torrenter (${bytes(q.summary?.size)}). Torrenter som er ferdige og allerede i et bibliotek kan fjernes med de nedlastede filene nå. Ikke-importerte fjernes aldri herfra.`)}</p>
          <div className="toolbar">
            <div className="seg" role="group" aria-label={t("Show", "Vis")}>
              <button aria-pressed={only === "removable"} onClick={() => setOnly("removable")}>{t(`Can be removed (${q.summary?.removable ?? 0})`, `Kan fjernes (${q.summary?.removable ?? 0})`)}</button>
              <button aria-pressed={only === "all"} onClick={() => setOnly("all")}>{t("All", "Alle")}</button>
            </div>
            <button className="btn small" onClick={() => setSel(torrents.filter((x) => x.removable).map((x) => x.hash))}>{t("Select all removable", "Velg alle som kan fjernes")}</button>
            {chosen.length > 0 && (
              <>
                <button className="btn small" onClick={() => toggle("qbit:remove", { op: "qbit_remove", hashes: chosen.filter((x) => x.removable).map((x) => x.hash) })} disabled={!chosen.some((x) => x.removable)}>
                  {t(`Remove ${chosen.filter((x) => x.removable).length} with files`, `Fjern ${chosen.filter((x) => x.removable).length} med filer`)}</button>
                <button className="btn small" onClick={() => toggle("qbit:limits", { op: "qbit_limits", hashes: chosen.map((x) => x.hash) })}>{t("Use the global limit", "Bruk den globale grensen")}</button>
              </>
            )}
          </div>
          {torrents.length === 0 ? <Empty>{t("Nothing here.", "Ingenting her.")}</Empty> : (
            <div className="table-wrap">
              <table>
                <thead><tr><th style={{ width: 28 }} /><th>{t("Torrent", "Torrent")}</th><th>{t("In library", "I biblioteket")}</th><th className="r">{t("Size", "Størrelse")}</th><th className="r">Ratio</th><th className="r">{t("Seeded", "Delt")}</th><th>{t("Limit", "Grense")}</th><th className="r">{t("Frees", "Frigjør")}</th></tr></thead>
                <tbody>
                  {torrents.map((x) => (
                    <tr key={x.hash}>
                      <td><input type="checkbox" checked={sel.includes(x.hash)} onChange={() => setSel(sel.includes(x.hash) ? sel.filter((h) => h !== x.hash) : [...sel, x.hash])} aria-label={x.name} /></td>
                      <td className="title-cell"><span style={{ fontWeight: 560 }}>{x.name}</span><small>{x.category} · {x.state}{x.title_name ? ` · ${x.title_name}` : ""}</small></td>
                      <td className="small">{x.removable ? <span className="ok-text">{importLabel(x.import_status)}</span> : <span className="muted">{x.complete ? importLabel(x.import_status) : t("Downloading", "Lastes ned")}</span>}</td>
                      <td className="r">{bytes(x.size)}</td>
                      <td className="r">{num(x.ratio, 2)}</td>
                      <td className="r small">{num(x.seeding_minutes / 60 / 24, 1)} {t("d", "d")}</td>
                      <td className="small">{act(x)}</td>
                      <td className="r">{x.removable ? bytes(x.freed) : "–"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </>
  );
}

// ------------------------------------------------------------------ Backups

function BackupsTab({ onRestored }: { onRestored: () => void }) {
  const [reload, setReload] = useState(0);
  const { data, error } = useFetch<{ items: { name: string; ts: number; changes: number; objects: number }[] }>("/api/arr-setup/backups", [reload]);
  const [confirm, setConfirm] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<ExecResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const restore = async () => {
    if (!confirm) return;
    setBusy(true); setErr(null);
    try { setRes(await api.post<ExecResult>("/api/arr-setup/restore", { name: confirm })); onRestored(); setReload((r) => r + 1); }
    catch (e) { setErr(String((e as Error).message)); } finally { setBusy(false); }
  };
  return (
    <>
      <p className="muted small" style={{ maxWidth: 780 }}>{t("Before every change, the app saves what it is about to change in /data/backups. Restoring puts those settings back and deletes profiles the change created (if no titles use them). Removed torrents cannot be restored.",
        "Før hver endring lagrer appen det den skal endre i /data/backups. Gjenoppretting setter innstillingene tilbake og sletter profiler endringen opprettet (hvis ingen titler bruker dem). Fjernede torrenter kan ikke gjenopprettes.")}</p>
      <ErrorNote error={error} />
      {data && data.items.length === 0 && <Empty>{t("No changes made yet.", "Ingen endringer gjort ennå.")}</Empty>}
      {data && data.items.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead><tr><th>{t("When", "Når")}</th><th className="r">{t("Changes", "Endringer")}</th><th className="r">{t("Saved objects", "Lagrede objekter")}</th><th /></tr></thead>
            <tbody>{data.items.map((b) => (
              <tr key={b.name}><td>{date(b.ts)} {new Date(b.ts * 1000).toLocaleTimeString()}</td><td className="r">{b.changes}</td><td className="r">{b.objects}</td>
                <td className="r"><button className="btn small" disabled={!b.objects} onClick={() => { setRes(null); setConfirm(b.name); }}>{t("Restore…", "Gjenopprett…")}</button></td></tr>
            ))}</tbody>
          </table>
        </div>
      )}
      {confirm && (
        <Drawer label={t("Restore", "Gjenopprett")} onClose={() => setConfirm(null)} busy={busy}>
          {res ? (
            <>
              <h1>{res.failed ? t("Partly restored", "Delvis gjenopprettet") : t("Restored", "Gjenopprettet")}</h1>
              <Results res={res} />
            </>
          ) : (
            <>
              <h1>{t("Restore these settings?", "Gjenopprette disse innstillingene?")}</h1>
              <p className="lede">{t("Size limits, profiles, download clients, Seerr and qBittorrent settings in this backup are put back as they were before that change. Changes made later to the same settings are overwritten.",
                "Størrelsesgrenser, profiler, nedlastingsklienter, Seerr- og qBittorrent-innstillinger i denne kopien settes tilbake slik de var før endringen. Senere endringer i de samme innstillingene overskrives.")}</p>
              <ErrorNote error={err} />
              <div className="toolbar"><button className="btn primary" onClick={restore} disabled={busy}>{busy ? t("Restoring…", "Gjenoppretter…") : t("Restore", "Gjenopprett")}</button></div>
            </>
          )}
        </Drawer>
      )}
    </>
  );
}

function Results({ res }: { res: ExecResult }) {
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

function ReviewDialog({ changes, enabled, onClose, onDone }: { changes: Change[]; enabled: boolean; onClose: () => void; onDone: () => void }) {
  const [plan, setPlan] = useState<Plan | null>(null);
  const [res, setRes] = useState<ExecResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { api.post<Plan>("/api/arr-setup/plan", { changes }).then(setPlan).catch((e) => setError(String(e.message))); }, [changes]);
  const run = async () => {
    if (!plan) return;
    setBusy(true); setError(null);
    try { setRes(await api.post<ExecResult>("/api/arr-setup/execute", { changes, token: plan.token })); onDone(); }
    catch (e) { setError(String((e as Error).message)); } finally { setBusy(false); }
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
          <ErrorNote error={error} />
          {plan && (
            <>
              <p className="lede">{t("This is exactly what will be changed. Everything else – other profiles, custom formats, languages – stays as it is. A backup of each setting is saved first.",
                "Dette er nøyaktig det som endres. Alt annet – andre profiler, custom formats, språk – blir som det er. En sikkerhetskopi av hver innstilling lagres først.")}</p>
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

