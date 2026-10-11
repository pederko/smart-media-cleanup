import { Fragment, useState } from "react";
import { qs } from "../api";
import { ago, bytes, fileName, num } from "../format";
import { t } from "../i18n";
import { ErrorNote, PageHeader, useFetch, useOpenTitle, useRefreshTick } from "../components/common";
import ReleaseSearch from "../components/ReleaseSearch";

type F = { path: string; size: number; library: string; ext: string; nlink: number; mtime: number; is_extra: number;
  title_key: string | null; title_name: string | null; year?: number | null; play_count: number | null; last_played: number | null;
  radarr_id?: number | null; sonarr_id?: number | null; season?: number | null };

/** Single files sorted by size, with «Find smaller» straight from the list. */
export function FilesPage() {
  const tick = useRefreshTick();
  const openTitle = useOpenTitle();
  const [library, setLibrary] = useState("");
  const [ext, setExt] = useState("");
  const [minGb, setMinGb] = useState("20");
  const [limit, setLimit] = useState(100);
  const [search, setSearch] = useState<string | null>(null);
  const { data, error } = useFetch<{ total: number; total_bytes: number; items: F[] }>(`/api/files/largest${qs({ library, ext, min_gb: minGb, limit })}`, [tick]);
  const settings = useFetch<{ libraries: { name: string }[] }>("/api/settings");
  return (
    <>
      <PageHeader title={t("Largest files", "Største filer")}
        lede={t("Single files sorted by size. Useful for finding 4K remuxes, ISO files and unusually large episodes – and swapping them for smaller versions.",
          "Enkeltfiler sortert etter størrelse. Nyttig for å finne 4K-remuxer, ISO-filer og uvanlig store episoder – og bytte dem til mindre versjoner.")} />
      <div className="toolbar">
        <select value={library} onChange={(e) => setLibrary(e.target.value)} aria-label={t("Library", "Bibliotek")}>
          <option value="">{t("All libraries", "Alle bibliotek")}</option>
          {settings.data?.libraries.map((l) => <option key={l.name}>{l.name}</option>)}
        </select>
        <select value={ext} onChange={(e) => setExt(e.target.value)} aria-label={t("File type", "Filtype")}>
          <option value="">{t("All file types", "Alle filtyper")}</option>
          {[".mkv", ".mp4", ".iso", ".m2ts", ".ts", ".avi"].map((x) => <option key={x}>{x}</option>)}
        </select>
        <label className="check small">{t("At least", "Minst")} <input type="number" min={0} value={minGb} onChange={(e) => setMinGb(e.target.value)} /> GB</label>
      </div>
      <ErrorNote error={error} />
      {data && <p className="small muted">{t(`${num(data.total)} files, ${bytes(data.total_bytes)} in total.`, `${num(data.total)} filer, ${bytes(data.total_bytes)} til sammen.`)}</p>}
      <div className="table-wrap">
        <table>
          <thead><tr><th>{t("File", "Fil")}</th><th>{t("Title", "Tittel")}</th><th>{t("Last watched", "Sist sett")}</th><th className="r">{t("Size", "Størrelse")}</th><th /></tr></thead>
          <tbody>
            {data?.items.map((f) => (
              <Fragment key={f.path}>
                <tr className="row">
                  <td>{fileName(f.path)}{f.nlink > 1 && <span className="tag" style={{ marginLeft: 8 }}>{t(`${f.nlink} hardlinks`, `${f.nlink} hardlenker`)}</span>}{f.ext === ".iso" && <span className="tag" style={{ marginLeft: 8 }}>ISO</span>}<div className="path">{f.library}</div></td>
                  <td>{f.title_key ? <button className="linkish" onClick={() => openTitle(f.title_key!)}>{f.title_name}{f.year ? ` (${f.year})` : ""}</button> : <span className="muted">–</span>}
                    {f.season != null && <div className="small muted">{t("Season", "Sesong")} {f.season}</div>}</td>
                  <td className="muted">{f.title_key ? ago(f.last_played) : ""}</td>
                  <td className="r num">{bytes(f.size)}</td>
                  <td className="r">{f.title_key && (f.radarr_id != null || (f.sonarr_id != null && f.season != null)) &&
                    <button className="btn small" onClick={() => setSearch(search === f.path ? null : f.path)} aria-expanded={search === f.path}>{search === f.path ? t("Hide", "Skjul") : t("Find smaller", "Finn mindre")}</button>}</td>
                </tr>
                {search === f.path && f.title_key && (
                  <tr className="detail"><td colSpan={5}>
                    <ReleaseSearch titleKey={f.title_key} season={f.radarr_id != null ? undefined : f.season ?? undefined} autoStart />
                  </td></tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
      {data && data.total > data.items.length && <p><button className="btn" onClick={() => setLimit(limit + 200)}>{t("Show more", "Vis flere")}</button></p>}
    </>
  );
}
