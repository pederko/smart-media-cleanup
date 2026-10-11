import { useEffect, useState } from "react";
import { api, qs } from "../api";
import { ago, bytes, num } from "../format";
import { plural, t } from "../i18n";
import { Drawer, ErrorNote, Loading, PageHeader, Seg, statusLabel, StatusDot, SwitchedOff, Tray, useFetch, useOpenTitle, useRefreshTick } from "../components/common";

type Item = { name: string; path: string; library: string; is_dir: boolean; files: number; videos: number; size: number;
  freed: number; mtime: number; age_days: number; status: string; advice: string; why: string;
  title_key: string | null; title_name: string | null };
type Bucket = { count: number; size: number; freed: number };
type Resp = { libraries: string[]; summary: { count: number; size: number; by_status: Record<string, Bucket>; by_advice: Record<string, Bucket> };
  items: Item[]; files_enabled: boolean; writable: Record<string, boolean> };

const statusText = (s: string) => ({ copied: t("Copy in the library", "Kopi i biblioteket"), hardlinked: t("Hardlinked", "Hardlenket"),
  not_imported: t("Not imported", "Ikke importert"), no_video: t("No video", "Uten video") } as Record<string, string>)[s] ?? s;
const adviceText = (a: string): [string, string] => (({ delete: [t("Can be deleted", "Kan slettes"), "risk-low"],
  consider: [t("Consider", "Vurder"), "risk-medium"], keep: [t("Keep", "Behold"), "muted"] } as Record<string, [string, string]>)[a] ?? [a, ""]);

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
  const entries = (n: number) => plural(n, ["entry", "entries"], ["oppføring", "oppføringer"]);
  const filter = (k: string) => { setStatus(k); setAdvice(""); };

  if (data && data.libraries.length === 0) {
    return (
      <>
        <PageHeader title={t("Downloads", "Nedlastinger")} />
        <div className="empty">{t("No library is set as a downloads folder. Set the type «Downloads» on it under Settings → Libraries.",
          "Ingen bibliotek er satt som nedlastingsmappe. Velg typen «Nedlastinger» under Innstillinger → Biblioteker.")}</div>
      </>
    );
  }

  return (
    <>
      <PageHeader title={t("Downloads", "Nedlastinger")}
        lede={t("What is in the downloads folder, whether it has been imported to a library, and what can safely go. Anything changed in the last 14 days is kept.",
          "Hva som ligger i nedlastingsmappen, om det er importert til et bibliotek, og hva som trygt kan fjernes. Alt som er endret de siste 14 dagene beholdes.")} />
      <ErrorNote error={error} />
      {s && (
        <section className="brief">
          <p className="brief-lead">
            {t(`${data!.libraries.join(" and ")} contains`, `${data!.libraries.join(" og ")} inneholder`)} <b>{entries(s.count)}</b> {t("using", "på")} <b>{bytes(s.size)}</b>.{" "}
            {a("delete").count > 0 && <>{t(`${num(a("delete").count)} can safely be deleted and free`, `${num(a("delete").count)} kan trygt slettes og frigjør`)} <b>{bytes(a("delete").freed)}</b>.</>}
          </p>
          <ul className="brief-points">
            {st("copied").count > 0 && <li><button className="linkish" onClick={() => filter("copied")}>{entries(st("copied").count)}</button> {t(`also exist as a copy in the library (${bytes(st("copied").freed)} can be freed).`, `finnes også som kopi i biblioteket (${bytes(st("copied").freed)} kan frigjøres).`)}</li>}
            {st("hardlinked").count > 0 && <li><button className="linkish" onClick={() => filter("hardlinked")}>{entries(st("hardlinked").count)}</button> {t(`are hardlinked to the library and take no extra space (${bytes(st("hardlinked").size)}).`, `er hardlenket til biblioteket og tar ikke ekstra plass (${bytes(st("hardlinked").size)}).`)}</li>}
            {st("not_imported").count > 0 && <li><button className="linkish" onClick={() => filter("not_imported")}>{entries(st("not_imported").count)}</button> {t(`are not imported (${bytes(st("not_imported").size)}) – check whether they were forgotten or failed.`, `er ikke importert (${bytes(st("not_imported").size)}) – sjekk om de er glemt eller feilet.`)}</li>}
            {st("no_video").count > 0 && <li>{t(`${entries(st("no_video").count)} contain no video – leftovers from downloads (${bytes(st("no_video").size)}).`, `${entries(st("no_video").count)} inneholder ingen video – rester etter nedlasting (${bytes(st("no_video").size)}).`)}</li>}
          </ul>
          <p className="small muted">{t("If something is still seeding, the torrent will report missing files after deletion. Remove it in the download client then.",
            "Ligger noe fortsatt til deling, vil torrenten melde at filene mangler etter sletting. Fjern den da i nedlastingsklienten.")}{" "}
            <a href="#/torrents">{t("See what is still seeding, and remove imported torrents, under Torrents.", "Se hva som fortsatt deler, og fjern importerte torrenter, under Torrenter.")}</a></p>
          {data && !data.files_enabled && <SwitchedOff what="files" />}
          {data && data.files_enabled && ro.length > 0 && <div className="notice">{t(`${ro.join(", ")} is mounted read-only (:ro). Remove :ro in the app's compose file to delete from here.`, `${ro.join(", ")} er montert skrivebeskyttet (:ro). Fjern :ro i appens compose-fil for å kunne slette herfra.`)}</div>}
        </section>
      )}

      <div className="toolbar" style={{ marginTop: 28 }}>
        <Seg label={t("Recommendation", "Anbefaling")} value={status ? "_status" : advice} onChange={(v) => { setAdvice(v); setStatus(""); }} options={[
          { value: "", label: t("All", "Alle") },
          { value: "delete", label: `${t("Can be deleted", "Kan slettes")}${s ? ` (${a("delete").count})` : ""}` },
          { value: "consider", label: `${t("Consider", "Vurder")}${s ? ` (${a("consider").count})` : ""}` },
          { value: "keep", label: `${t("Keep", "Behold")}${s ? ` (${a("keep").count})` : ""}` },
        ]} />
        <select value={sort} onChange={(e) => setSort(e.target.value)} aria-label={t("Sort", "Sorter")}>
          <option value="size">{t("Largest", "Størst")}</option>
          <option value="freed">{t("Most to free", "Mest å frigjøre")}</option>
          <option value="age">{t("Oldest", "Eldst")}</option>
          <option value="name">{t("Name", "Navn")}</option>
        </select>
        {status && <button className="btn small" onClick={() => setStatus("")}>{t(`Filter: ${statusText(status)} ✕`, `Filter: ${statusText(status)} ✕`)}</button>}
        {a("delete").count > 0 && <button className="btn small" onClick={() => setSel([...new Set([...sel, ...items.filter((i) => i.advice === "delete").map((i) => i.path)])])}>{t("Select all that can be deleted", "Velg alle som kan slettes")}</button>}
      </div>

      <div className="table-wrap">
        <table>
          <thead><tr><th style={{ width: 36 }} /><th>{t("Name", "Navn")}</th><th>{t("Status", "Status")}</th><th>{t("Recommendation", "Anbefaling")}</th><th>{t("Changed", "Endret")}</th><th className="r">{t("Size", "Størrelse")}</th><th className="r">{t("Freed", "Frigjøres")}</th></tr></thead>
          <tbody>
            {items.map((i) => {
              const [adv, cls] = adviceText(i.advice);
              return (
                <tr key={i.path} className="row">
                  <td>{i.status !== "hardlinked" && <input type="checkbox" checked={sel.includes(i.path)} aria-label={t(`Select ${i.name}`, `Velg ${i.name}`)}
                    onChange={() => setSel(sel.includes(i.path) ? sel.filter((x) => x !== i.path) : [...sel, i.path])} />}</td>
                  <td className="title-cell">
                    {i.name}
                    <small>{i.is_dir ? t(`Folder, ${plural(i.files, ["file", "files"], ["fil", "filer"])}`, `Mappe, ${plural(i.files, ["file", "files"], ["fil", "filer"])}`) : t("File", "Fil")}
                      {i.title_key && <> – <button className="linkish" onClick={() => openTitle(i.title_key!)}>{i.title_name}</button></>}</small>
                  </td>
                  <td><span className="tag">{statusText(i.status)}</span></td>
                  <td className="small"><span className={cls}>{adv}</span><div className="muted">{i.why}</div></td>
                  <td className="small muted">{ago(i.mtime)}</td>
                  <td className="r num">{bytes(i.size)}</td>
                  <td className="r num" style={{ fontWeight: 600 }}>{bytes(i.freed)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {data && items.length === 0 && <div className="empty">{t("Nothing in this view.", "Ingenting i dette utvalget.")}</div>}

      {sel.length > 0 && (
        <Tray figure={bytes(selFreed)} note={t(`freed by ${sel.length} selected`, `frigjøres av ${sel.length} valgte`)}>
          <button className="btn" onClick={() => setSel([])}>{t("Clear", "Tøm")}</button>
          <button className="btn danger" onClick={() => setDialog(true)}>{t("Delete selected…", "Slett valgte…")}</button>
        </Tray>
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
  const entries = (n: number) => plural(n, ["entry", "entries"], ["oppføring", "oppføringer"]);
  return (
    <Drawer label={t("Delete downloads", "Slett nedlastinger")} onClose={onClose} busy={busy}>
      {res ? (
        <>
          <h1>{res.failed ? t("Partly done", "Delvis fullført") : t("Deleted", "Slettet")}</h1>
          <p className="lede">{t(`${entries(res.done)} deleted. About ${bytes(res.freed_estimate)} freed. A full refresh has started.`, `${entries(res.done)} slettet. Omtrent ${bytes(res.freed_estimate)} frigjort. En full oppdatering er startet.`)}</p>
          <table className="compact"><tbody>{res.results.map((r) => <tr key={r.path}><td><StatusDot status={r.status} />{r.path.split("/").pop()}</td><td className="small muted">{statusLabel(r.status)}: {r.detail}</td></tr>)}</tbody></table>
          <p><button className="btn primary" onClick={onClose}>{t("Done", "Ferdig")}</button></p>
        </>
      ) : (
        <>
          <h1>{t(`Delete ${entries(ok.length)}`, `Slett ${entries(ok.length)}`)}</h1>
          {error && <div className="notice err">{error}</div>}
          {!plan ? <Loading /> : !plan.enabled ? <SwitchedOff what="files" onClose={onClose} /> : (
            <>
              <p className="lede">{ok.length > 0
                ? <>{t("The folders and files are deleted from disk.", "Mappene og filene slettes fra disk.")} <b>{bytes(plan.freed)}</b> {t("is freed. This cannot be undone.", "frigjøres. Dette kan ikke angres.")}</>
                : t("None of the selected can be deleted.", "Ingen av de valgte kan slettes.")}</p>
              {ok.some((i) => i.age_days < 14) && <div className="notice">{t("Something was changed in the last 14 days and may still be downloading, importing or seeding.", "Noe er endret de siste 14 dagene og kan fortsatt være under nedlasting, import eller deling.")}</div>}
              <table className="compact"><tbody>{ok.map((i) => <tr key={i.path}><td>{i.name}<div className="small muted">{statusText(i.status)}</div></td><td className="r num">{bytes(i.freed)}</td></tr>)}</tbody></table>
              {no.length > 0 && <details style={{ marginTop: 12 }} open={ok.length === 0}><summary className="small muted">{t(`${no.length} not included`, `${no.length} tas ikke med`)}</summary><ul className="conseq small">{no.map((i) => <li key={i.path}>{i.name}: {i.reason}</li>)}</ul></details>}
              {ok.length > 0 && <p style={{ marginTop: 20 }}><button className="btn danger" onClick={run} disabled={busy}>{busy ? t("Deleting…", "Sletter…") : t(`Delete ${entries(ok.length)} (${bytes(plan.freed)})`, `Slett ${entries(ok.length)} (${bytes(plan.freed)})`)}</button></p>}
            </>
          )}
        </>
      )}
    </Drawer>
  );
}
