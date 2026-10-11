import { SuggestionDetail as D } from "../api";
import { bytes, date, fileName } from "../format";
import { t } from "../i18n";
import { Breakdown, HistoryLine, Loading, useFetch, useOpenTitle } from "./common";

/** Why a suggestion was made, what it means for the services, and which files it covers. */
export default function SuggestionDetail({ id }: { id: string }) {
  const { data, error } = useFetch<D>(`/api/suggestions/${id}`, [id]);
  const openTitle = useOpenTitle();
  if (error) return <div className="notice err">{error}</div>;
  if (!data) return <Loading />;
  const files = data.files;
  const shown = files.slice(0, 40);
  return (
    <div className="why">
      <div>
        <h3>{t("Why this suggestion", "Hvorfor dette forslaget")}</h3>
        <Breakdown components={data.components} score={data.score} />
        {data.reasons.length > 0 && <p className="small muted">{data.reasons.join(" ")}</p>}
      </div>
      <div>
        <h3>{t("Consequences", "Konsekvenser")}</h3>
        <ul className="conseq">{data.consequences.map((c, i) => <li key={i}>{c}</li>)}</ul>
        <h3 style={{ marginTop: 18 }}>{t("Facts", "Fakta")}</h3>
        <dl className="kv">
          <dt>{t("Location", "Plassering")}</dt><dd className="path">{data.location}</dd>
          <dt>{t("Watch history", "Seerhistorikk")}</dt><dd><HistoryLine h={data.history} /></dd>
          {data.history.recent_users && data.history.recent_users.length > 0 && <><dt>{t("Recently watched by", "Sett nylig av")}</dt><dd>{data.history.recent_users.join(", ")}</dd></>}
          <dt>{t("Space affected", "Berørt plass")}</dt><dd>{bytes(data.size)}</dd>
          <dt>{t("Freed", "Frigjøres")}</dt><dd>{bytes(data.savings)}{data.savings_note && <div className="small muted">{data.savings_note}</div>}</dd>
          {data.overlaps.length > 0 && <><dt>{t("Overlaps", "Overlapper")}</dt><dd className="small">{data.overlaps.map((o) => `${o.label}${o.name ? ` (${o.name})` : ""}`).join(", ")}. {t("Shared files are counted once in totals.", "Felles filer telles bare én gang i summer.")}</dd></>}
        </dl>
        {data.title_key && <p><button className="btn small" onClick={() => openTitle(data.title_key!)}>{t("Show the whole title", "Vis hele tittelen")}</button></p>}
      </div>
      <div style={{ gridColumn: "1 / -1" }}>
        <h3>{t(`Files (${files.length})`, `Filer (${files.length})`)}</h3>
        <div className="table-wrap">
          <table>
            <thead><tr><th>{t("File", "Fil")}</th><th className="r">{t("Size", "Størrelse")}</th><th className="r">{t("Freed", "Frigjøres")}</th><th>{t("Changed", "Endret")}</th></tr></thead>
            <tbody>
              {shown.map((f) => (
                <tr key={f.path}>
                  <td><span title={f.path}>{fileName(f.path)}</span>{f.nlink > 1 && <span className="tag" style={{ marginLeft: 8 }}>{t(`${f.nlink} hardlinks`, `${f.nlink} hardlenker`)}</span>}{f.is_extra ? <span className="tag" style={{ marginLeft: 8 }}>{t("extra", "ekstra")}</span> : null}</td>
                  <td className="r num">{bytes(f.size)}</td>
                  <td className="r num">{bytes(f.claim)}</td>
                  <td className="muted small">{date(f.mtime)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {files.length > shown.length && <p className="small muted">{t(`… and ${files.length - shown.length} more files.`, `… og ${files.length - shown.length} filer til.`)}</p>}
        </div>
      </div>
    </div>
  );
}
