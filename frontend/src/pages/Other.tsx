import { ago, bytes } from "../format";
import { ErrorNote, useFetch, useRefreshTick } from "../components/common";

type Row = { name: string; mountpoint: string | null; used: number; own: number; snapshots: number; libraries: string[];
  library_size: number; other: number; kind: string };
type Resp = { available: boolean; message?: string; pool: { name?: string; allocated?: number }; fetched?: number; libs_total: number;
  other?: number; datasets_other?: number; overhead?: number; snapshots?: number; items?: Row[] };

/** «Annet» i kapasitetsstolpen: plass i poolen utenfor bibliotekene. Bare visning. */
export default function OtherPage() {
  const tick = useRefreshTick();
  const { data, error } = useFetch<Resp>("/api/other-storage", [tick]);
  return (
    <>
      <h1>Annet i poolen</h1>
      <p className="lede">Plass som brukes utenfor bibliotekene: apper, appdata, opptak, snapshots og andre mapper. Appen har med vilje ikke tilgang hit og kan ikke slette noe her – dette er en oversikt så du vet hvor du kan rydde selv.</p>
      <ErrorNote error={error} />
      {data && !data.available && <div className="empty">{data.message}</div>}
      {data?.available && data.items && (
        <>
          <div className="figures">
            <div className="figure"><div className="v">{bytes(data.other ?? 0)}</div><div className="l">utenfor bibliotekene i {data.pool.name}</div></div>
            <div className="figure"><div className="v">{bytes(data.snapshots ?? 0)}</div><div className="l">holdes av snapshots</div></div>
            <div className="figure"><div className="v">{bytes(data.overhead ?? 0)}</div><div className="l">ZFS-overhead (paritet, metadata, avrunding)</div></div>
          </div>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Datasett</th><th>Hva</th><th className="r">Data utenfor bibliotekene</th><th className="r">Snapshots</th><th className="r">Sum</th></tr></thead>
              <tbody>
                {data.items.map((r) => (
                  <tr key={r.name} className="row">
                    <td>{r.name}<div className="path">{r.mountpoint}</div></td>
                    <td className="small">{r.kind}{r.libraries.length > 0 && <div className="muted">Bibliotekene {r.libraries.join(", ")} ({bytes(r.library_size)}) er trukket fra</div>}</td>
                    <td className="r num">{bytes(r.other)}</td>
                    <td className="r num">{r.snapshots ? bytes(r.snapshots) : "–"}</td>
                    <td className="r num" style={{ fontWeight: 600 }}>{bytes(r.other + r.snapshots)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <section className="section">
            <h2>Hvor rydder jeg?</h2>
            <ul className="conseq small" style={{ maxWidth: 760 }}>
              <li><b>Snapshots:</b> TrueNAS → Datasets → velg datasettet → Data Protection / Snapshots. Plassen frigjøres når snapshotene slettes eller utløper. Juster oppbevaringstiden under Data Protection → Periodic Snapshot Tasks.</li>
              <li><b>TrueNAS-apper (.ix-apps):</b> gamle images ryddes med Apps → Configuration → «Prune images» (eller <code>docker image prune -a</code> i shell).</li>
              <li><b>Appdata og opptak:</b> ryddes i appen selv (f.eks. oppbevaringstid for opptak i Frigate, cache i Plex under Settings → Troubleshooting).</li>
              <li><b>Mapper på rotdatasettet</b> utenfor FILM, TV, Barn og tmp er ikke montert i appen og vises bare som en sum her.</li>
              <li><b>ZFS-overhead</b> er forskjellen mellom det poolen har allokert og det datasettene rapporterer, og kan ikke ryddes.</li>
            </ul>
            <p className="small faint">Fra TrueNAS, hentet {ago(data.fetched)}.</p>
          </section>
        </>
      )}
    </>
  );
}
