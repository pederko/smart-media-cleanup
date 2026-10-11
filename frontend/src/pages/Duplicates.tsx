import { useEffect, useMemo, useState } from "react";
import { api, qs } from "../api";
import { bytes, date, fileName, num } from "../format";
import { plural, t } from "../i18n";
import { Drawer, ErrorNote, Loading, PageHeader, Poster, Seg, statusLabel, StatusDot, SwitchedOff, Tray, useFetch, useOpenTitle, useRefreshTick } from "../components/common";

type DFile = { path: string; size: number; alloc: number | null; resolution: string | null; managed: boolean; keep: boolean;
  nlink: number; library: string | null; mtime: number | null; in_downloads: boolean; missing: boolean };
type Group = { id: string; kind: string; title_key: string | null; label: string; name: string | null; total: number; reclaimable: number;
  files: DFile[]; keep_reason: string | null; title_name: string | null; year: number | null; protected: number | null;
  in_downloads: boolean; libraries: string[] };
type Summary = Record<string, { groups: number; files: number; reclaimable: number; in_downloads: number; in_downloads_bytes: number }>;
type Resp = { summary: Summary; total: number; total_reclaimable: number; items: Group[]; files_enabled: boolean; writable: Record<string, boolean> };

function useDebounced(v: string) {
  const [d, setD] = useState(v);
  useEffect(() => { const x = setTimeout(() => setD(v), 250); return () => clearTimeout(x); }, [v]);
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
    return g.files.filter((f) => f.path !== k?.path).reduce((s, f) => s + (f.alloc ?? f.size), 0);
  };
  const groups = data?.items ?? [];
  const selectable = groups.filter((g) => g.kind !== "hardlink" && !g.protected);
  const selFreed = useMemo(() => groups.filter((g) => sel.includes(g.id)).reduce((s, g) => s + freedOf(g), 0), [sel, groups, keep]); // eslint-disable-line react-hooks/exhaustive-deps
  const s = data?.summary;
  const ro = data ? Object.entries(data.writable).filter(([, w]) => !w).map(([n]) => n) : [];
  const help: Record<string, string> = {
    identical: t("The same content in two places (equal size and partial hash), as separate files. One can go without losing anything.",
      "Samme innhold to steder (lik størrelse og delvis hash), som separate filer. Én kan fjernes uten å miste noe."),
    versions: t("The same movie or episode in different editions or resolutions. Choose which one to keep.",
      "Samme film eller episode i ulike utgaver eller oppløsninger. Velg hvilken som skal beholdes."),
    hardlink: t("The same file under several names. Takes no extra space and needs no cleanup.",
      "Samme fil under flere navn. Tar ikke ekstra plass, og trenger ingen opprydding."),
  };

  return (
    <>
      <PageHeader title={t("Duplicates and versions", "Duplikater og versjoner")} />
      <ErrorNote error={error} />
      {s && (
        <section className="brief">
          <p className="brief-lead">
            {s.identical.groups + s.versions.groups > 0
              ? <>{t("Duplicates and extra versions use", "Duplikater og ekstra versjoner bruker")} <b>{bytes(s.identical.reclaimable + s.versions.reclaimable)}</b> {t("that can be freed. A matching title alone is never counted as a duplicate.", "som kan frigjøres. Lik tittel alene regnes aldri som duplikat.")}</>
              : t("No duplicates or extra versions found.", "Ingen duplikater eller ekstra versjoner funnet.")}
          </p>
          <ul className="brief-points">
            {s.identical.groups > 0 && <li><button className="linkish" onClick={() => setKind("identical")}>{plural(s.identical.groups, ["identical copy", "identical copies"], ["identisk kopi", "identiske kopier"])}</button> ({bytes(s.identical.reclaimable)}) – {t("safe to clean up, the content still exists.", "trygt å rydde, innholdet finnes fortsatt.")}
              {s.identical.in_downloads > 0 && <> {t(`${num(s.identical.in_downloads)} of them ${s.identical.in_downloads === 1 ? "is" : "are"} in the downloads folder (${bytes(s.identical.in_downloads_bytes)}).`, `${num(s.identical.in_downloads)} av dem ligger i nedlastingsmappen (${bytes(s.identical.in_downloads_bytes)}).`)}</>}</li>}
            {s.versions.groups > 0 && <li><button className="linkish" onClick={() => setKind("versions")}>{plural(s.versions.groups, ["title with several versions", "titles with several versions"], ["tittel med flere versjoner", "titler med flere versjoner"])}</button> ({bytes(s.versions.reclaimable)}) – {t("choose which to keep.", "velg hvilken som beholdes.")}</li>}
            {s.hardlink.groups > 0 && <li>{plural(s.hardlink.groups, ["hardlink takes", "hardlinks take"], ["hardlenke tar", "hardlenker tar"])} {t("no extra space.", "ikke ekstra plass.")}</li>}
          </ul>
          {data && !data.files_enabled && <SwitchedOff what="files" />}
          {data && data.files_enabled && ro.length > 0 && (
            <div className="notice">{t("Mounted read-only (:ro):", "Montert skrivebeskyttet (:ro):")} {ro.join(", ")}. {t("Files there cannot be deleted from the app until :ro is removed in the app's compose file.", "Filer der kan ikke slettes fra appen før :ro fjernes i appens compose-fil.")}</div>
          )}
        </section>
      )}

      <div className="toolbar" style={{ marginTop: 28 }}>
        <Seg label={t("Type", "Type")} value={kind} onChange={setKind} options={[
          { value: "identical", label: `${t("Identical copies", "Identiske kopier")}${s ? ` (${s.identical?.groups ?? 0})` : ""}` },
          { value: "versions", label: `${t("Several versions", "Flere versjoner")}${s ? ` (${s.versions?.groups ?? 0})` : ""}` },
          { value: "hardlink", label: `${t("Hardlinks", "Hardlenker")}${s ? ` (${s.hardlink?.groups ?? 0})` : ""}` },
        ]} />
        <input type="search" placeholder={t("Search title or path", "Søk i tittel eller sti")} value={q} onChange={(e) => setQ(e.target.value)} aria-label={t("Search", "Søk")} />
        <select value={where} onChange={(e) => setWhere(e.target.value)} aria-label={t("Where", "Hvor")}>
          <option value="">{t("Everywhere", "Alle steder")}</option>
          <option value="downloads">{t("With a copy in the downloads folder", "Med kopi i nedlastingsmappen")}</option>
          <option value="library">{t("Only in the libraries", "Bare i bibliotekene")}</option>
        </select>
        <select value={sort} onChange={(e) => setSort(e.target.value)} aria-label={t("Sort", "Sorter")}>
          <option value="reclaimable">{t("Most to free", "Mest å frigjøre")}</option>
          <option value="size">{t("Largest in total", "Størst totalt")}</option>
          <option value="files">{t("Most files", "Flest filer")}</option>
          <option value="name">{t("Name", "Navn")}</option>
        </select>
      </div>
      <p className="muted small">{help[kind]}</p>
      {data && kind !== "hardlink" && selectable.length > 0 && (
        <p className="small">
          <button className="btn small" onClick={() => setSel([...new Set([...sel, ...selectable.map((g) => g.id)])])}>{t(`Select all ${selectable.length} visible`, `Velg alle ${selectable.length} synlige`)}</button>
          {data.total > groups.length && <span className="muted"> {t(`(${num(data.total)} in total – show more to select the rest)`, `(${num(data.total)} totalt – vis flere for å velge resten)`)}</span>}
        </p>
      )}

      <div className="grid" style={{ gap: 14 }}>
        {groups.map((g) => {
          const k = keepOf(g);
          const can = g.kind !== "hardlink" && !g.protected;
          const checked = sel.includes(g.id);
          const name = g.title_name ?? g.name ?? g.label;
          return (
            <section key={g.id} className={`panel dupe ${checked ? "checked" : ""}`}>
              <div className="dupe-head">
                {can && <input type="checkbox" checked={checked} aria-label={t(`Select ${name}`, `Velg ${name}`)}
                  onChange={() => setSel(checked ? sel.filter((x) => x !== g.id) : [...sel, g.id])} />}
                <Poster k={g.title_key} title={name} size="m" />
                <div style={{ minWidth: 0, flex: 1 }}>
                  {g.title_key ? <button className="linkish" style={{ fontWeight: 560 }} onClick={() => openTitle(g.title_key!)}>{g.title_name}{g.year ? ` (${g.year})` : ""}</button>
                    : <b>{name}</b>}
                  <div className="small muted">{plural(g.files.length, ["file", "files"], ["fil", "filer"])}, {g.libraries.join(t(" and ", " og "))}{g.protected ? t(", protected", ", beskyttet") : ""}</div>
                </div>
                {g.kind !== "hardlink" && <div className="r"><div className="num" style={{ fontWeight: 600 }}>{bytes(freedOf(g))}</div><div className="small muted">{t("freed", "frigjøres")}</div></div>}
              </div>
              <table className="compact">
                <tbody>
                  {g.files.map((f) => {
                    const isKeep = f.path === k;
                    return (
                      <tr key={f.path} className={isKeep ? "keep" : ""}>
                        {g.kind !== "hardlink" && (
                          <td style={{ width: 100 }}>
                            <label className="check small">
                              <input type="radio" name={`keep-${g.id}`} checked={isKeep} disabled={!can} onChange={() => setKeep({ ...keep, [g.id]: f.path })} />
                              {isKeep ? <b>{t("Keep", "Beholdes")}</b> : <span className="muted">{t("Delete", "Slettes")}</span>}
                            </label>
                          </td>
                        )}
                        <td>{fileName(f.path)}<div className="path">{f.path.split("/").slice(0, -1).join("/")}</div></td>
                        <td className="small">
                          {f.resolution && <span className="tag">{f.resolution}</span>}{" "}
                          {f.managed && <span className="tag" title={t("Radarr/Sonarr know this file – it is deleted through them", "Radarr/Sonarr kjenner denne filen – den slettes via dem")}>Radarr/Sonarr</span>}{" "}
                          {f.in_downloads && <span className="tag" title={t("In the downloads folder – may still be seeding", "Ligger i nedlastingsmappen – kan fortsatt deles")}>{t("Download", "Nedlasting")}</span>}
                        </td>
                        <td className="small muted">{date(f.mtime)}</td>
                        <td className="r num">{bytes(f.size)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {g.keep_reason && g.kind !== "hardlink" && !keep[g.id] && <p className="small muted" style={{ margin: "8px 0 0" }}>{t(`Suggested to keep: ${g.keep_reason}.`, `Foreslått beholdt: ${g.keep_reason}.`)}</p>}
              {g.files.some((f) => f.managed && f.path !== k) && (
                <p className="small muted" style={{ margin: "8px 0 0" }}>{t("The file Radarr/Sonarr knows is deleted through them; they then rescan the folder and use the file you keep. It must be in the same folder.",
                  "Filen Radarr/Sonarr kjenner slettes via dem; de skanner så mappen og tar i bruk filen du beholder. Den må ligge i samme mappe.")}</p>
              )}
            </section>
          );
        })}
      </div>
      {data && groups.length === 0 && <div className="empty">{t("Nothing found with these filters.", "Ingen funnet med disse filtrene.")}</div>}
      {data && data.total > groups.length && <p><button className="btn" onClick={() => setLimit(limit + 200)}>{t(`Show more (${num(data.total - groups.length)} left)`, `Vis flere (${num(data.total - groups.length)} igjen)`)}</button></p>}

      {sel.length > 0 && (
        <Tray figure={`~${bytes(selFreed)}`} note={t(`freed in ${sel.length} selected groups`, `frigjøres i ${sel.length} valgte grupper`)}>
          <span className="small muted">{t("The file marked «Keep» stays. The others are deleted.", "Filen merket «Beholdes» blir liggende. De andre slettes.")}</span>
          <button className="btn" onClick={() => setSel([])}>{t("Clear", "Tøm")}</button>
          <button className="btn danger" onClick={() => setDialog(true)}>{t("Delete redundant files…", "Slett overflødige filer…")}</button>
        </Tray>
      )}
      {dialog && (
        <DupeDeleteDialog choices={sel.map((id) => ({ id, keep: keepOf(groups.find((g) => g.id === id)!) }))}
          onClose={() => setDialog(false)} onDone={() => { setSel([]); reload(); }} />
      )}
    </>
  );
}

type PlanFile = { path: string; size: number; alloc: number | null; ok: boolean; reason: string | null; in_downloads: boolean; via: string | null };
type PlanItem = { id: string; name: string; keep: string; executable: boolean; reason: string | null; files: PlanFile[]; warn_downloads?: boolean };
type Plan = { enabled: boolean; writable: Record<string, boolean>; items: PlanItem[]; files: number; freed: number; held: number; token: string };
type Res = { results: { path: string; status: string; detail: string }[]; done: number; failed: number; freed_estimate: number };

function DupeDeleteDialog({ choices, onClose, onDone }: { choices: { id: string; keep: string }[]; onClose: () => void; onDone: () => void }) {
  const [plan, setPlan] = useState<Plan | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Res | null>(null);
  useEffect(() => { api.post<Plan>("/api/duplicates/plan", { groups: choices }).then(setPlan).catch((e) => setError(String(e.message))); }, [choices]);

  const run = async () => {
    if (!plan) return;
    setBusy(true); setError(null);
    try { setResult(await api.post<Res>("/api/duplicates/execute", { groups: choices, token: plan.token })); onDone(); }
    catch (e) { setError(String((e as Error).message)); } finally { setBusy(false); }
  };
  const okFiles = plan?.items.flatMap((i) => i.files.filter((f) => f.ok)) ?? [];
  const skipped = plan?.items.flatMap((i) => [...(i.files.length === 0 && i.reason ? [{ path: i.name, reason: i.reason }] : []), ...i.files.filter((f) => !f.ok).map((f) => ({ path: f.path, reason: f.reason }))]) ?? [];
  const files = (n: number) => plural(n, ["file", "files"], ["fil", "filer"]);

  return (
    <Drawer label={t("Delete redundant files", "Slett overflødige filer")} onClose={onClose} busy={busy}>
      {result ? (
        <>
          <h1>{result.failed ? t("Partly done", "Delvis fullført") : t("Deleted", "Slettet")}</h1>
          <p className="lede">{t(`${files(result.done)} deleted${result.failed ? `, ${result.failed} failed` : ""}. About ${bytes(result.freed_estimate)} freed. A full refresh has started.`,
            `${files(result.done)} slettet${result.failed ? `, ${result.failed} feilet` : ""}. Omtrent ${bytes(result.freed_estimate)} frigjort. En full oppdatering er startet.`)}</p>
          <table className="compact"><tbody>
            {result.results.map((r) => <tr key={r.path}><td><StatusDot status={r.status} />{fileName(r.path)}</td><td className="small muted">{statusLabel(r.status)}: {r.detail}</td></tr>)}
          </tbody></table>
          <p><button className="btn primary" onClick={onClose}>{t("Done", "Ferdig")}</button></p>
        </>
      ) : (
        <>
          <h1>{t(`Delete ${files(okFiles.length)}`, `Slett ${files(okFiles.length)}`)}</h1>
          {error && <div className="notice err">{error}</div>}
          {!plan ? <Loading /> : !plan.enabled ? <SwitchedOff what="files" onClose={onClose} /> : (
            <>
              <p className="lede">{okFiles.length > 0
                ? <>{t("The files are deleted from disk", "Filene slettes fra disk")}{okFiles.some((f) => f.via) ? t(" – files Radarr/Sonarr know are deleted through them, and they rescan the folder", " – filer Radarr/Sonarr kjenner, slettes via dem, og de skanner mappen på nytt") : ""}. <b>{bytes(plan.freed)}</b> {t("is freed. The file marked «Keep» in each group stays. This cannot be undone.", "frigjøres. Filen merket «Beholdes» i hver gruppe blir liggende. Dette kan ikke angres.")}</>
                : t("None of the files can be deleted.", "Ingen av filene kan slettes.")}</p>
              {plan.items.some((i) => i.warn_downloads) && <div className="notice">{t("Some files are in the downloads folder. If they are still seeding, the torrent will report missing files – remove it in the download client afterwards.",
                "Noen filer ligger i nedlastingsmappen. Deles de fortsatt, vil torrenten melde at filene mangler – fjern den i nedlastingsklienten etterpå.")}</div>}
              {okFiles.length > 0 && (
                <table className="compact"><tbody>
                  {plan.items.filter((i) => i.files.some((f) => f.ok)).map((i) => (
                    <tr key={i.id}>
                      <td>{i.name}<div className="small muted">{t("Keeps", "Beholder")} {fileName(i.keep)}</div></td>
                      <td>{i.files.filter((f) => f.ok).map((f) => <div key={f.path} className="small">{fileName(f.path)}{f.via && <span className="tag" style={{ marginLeft: 6 }}>{t("via", "via")} {f.via === "radarr" ? "Radarr" : "Sonarr"}</span>}</div>)}</td>
                      <td className="r num">{bytes(i.files.filter((f) => f.ok).reduce((s, f) => s + (f.alloc ?? f.size), 0))}</td>
                    </tr>
                  ))}
                </tbody></table>
              )}
              {skipped.length > 0 && (
                <details style={{ marginTop: 14 }} open={okFiles.length === 0}>
                  <summary className="small muted">{t(`${skipped.length} not included`, `${skipped.length} tas ikke med`)}</summary>
                  <ul className="conseq small">{skipped.map((f, n) => <li key={n}>{fileName(f.path)}: {f.reason}</li>)}</ul>
                </details>
              )}
              {okFiles.length > 0 && <p style={{ marginTop: 20 }}><button className="btn danger" onClick={run} disabled={busy}>{busy ? t("Deleting…", "Sletter…") : t(`Delete ${files(okFiles.length)} (${bytes(plan.freed)})`, `Slett ${files(okFiles.length)} (${bytes(plan.freed)})`)}</button></p>}
            </>
          )}
        </>
      )}
    </Drawer>
  );
}
