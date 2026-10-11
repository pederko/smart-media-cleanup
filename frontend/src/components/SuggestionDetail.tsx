import { SuggestionDetail as D } from "../api";
import { bytes, date, fileName } from "../format";
import { Breakdown, HistoryLine, useFetch, useOpenTitle } from "./common";

export default function SuggestionDetail({ id }: { id: string }) {
  const { data, error } = useFetch<D>(`/api/suggestions/${id}`, [id]);
  const openTitle = useOpenTitle();
  if (error) return <div className="notice err">{error}</div>;
  if (!data) return <div className="muted small">Henter…</div>;
  const files = data.files;
  const shown = files.slice(0, 40);
  return (
    <div className="why">
      <div>
        <h3>Hvorfor dette forslaget</h3>
        <Breakdown components={data.components} score={data.score} />
        {data.reasons.length > 0 && <p className="small muted">{data.reasons.join(" ")}</p>}
      </div>
      <div>
        <h3>Konsekvenser</h3>
        <ul className="conseq">{data.consequences.map((c, i) => <li key={i}>{c}</li>)}</ul>
        <h3 style={{ marginTop: 18 }}>Fakta</h3>
        <dl className="kv">
          <dt>Plassering</dt><dd className="path">{data.location}</dd>
          <dt>Seerhistorikk</dt><dd><HistoryLine h={data.history} /></dd>
          {data.history.recent_users && data.history.recent_users.length > 0 && <><dt>Sett nylig av</dt><dd>{data.history.recent_users.join(", ")}</dd></>}
          <dt>Berørt plass</dt><dd>{bytes(data.size)}</dd>
          <dt>Frigjøres</dt><dd>{bytes(data.savings)}{data.savings_note && <div className="small muted">{data.savings_note}</div>}</dd>
          {data.overlaps.length > 0 && <><dt>Overlapper</dt><dd className="small">{data.overlaps.map((o) => `${o.label} (${o.action.toLowerCase()})`).join(", ")}. Felles filer telles bare én gang i summer.</dd></>}
        </dl>
        {data.title_key && <p><button className="btn small" onClick={() => openTitle(data.title_key!)}>Vis hele tittelen</button></p>}
      </div>
      <div style={{ gridColumn: "1 / -1" }}>
        <h3>Filer ({files.length})</h3>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Fil</th><th className="r">Størrelse</th><th className="r">Frigjøres</th><th>Endret</th></tr></thead>
            <tbody>
              {shown.map((f) => (
                <tr key={f.path}>
                  <td><span title={f.path}>{fileName(f.path)}</span>{f.nlink > 1 && <span className="tag" style={{ marginLeft: 8 }}>{f.nlink} hardlenker</span>}{f.is_extra ? <span className="tag" style={{ marginLeft: 8 }}>ekstra</span> : null}</td>
                  <td className="r num">{bytes(f.size)}</td>
                  <td className="r num">{bytes(f.claim)}</td>
                  <td className="muted small">{date(f.mtime)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {files.length > shown.length && <p className="small muted">… og {files.length - shown.length} filer til.</p>}
        </div>
      </div>
    </div>
  );
}
