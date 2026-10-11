import { ago, bytes } from "../format";
import { t } from "../i18n";
import { ErrorNote, PageHeader, useFetch, useRefreshTick } from "../components/common";

type Row = { name: string; mountpoint: string | null; used: number; own: number; snapshots: number; libraries: string[];
  library_size: number; other: number; kind: string };
type Resp = { available: boolean; message?: string; pool: { name?: string; allocated?: number }; fetched?: number; libs_total: number;
  other?: number; datasets_other?: number; overhead?: number; snapshots?: number; items?: Row[] };

/** «Other» in the capacity bar: space in the pool outside the libraries. Read only. */
export default function OtherPage() {
  const tick = useRefreshTick();
  const { data, error } = useFetch<Resp>("/api/other-storage", [tick]);
  return (
    <>
      <PageHeader title={t("Other storage", "Annen lagring")}
        lede={t("Space used outside the libraries: apps, app data, recordings, snapshots and other folders. The app deliberately has no access here and cannot delete anything – this is an overview so you know where to clean up yourself.",
          "Plass som brukes utenfor bibliotekene: apper, appdata, opptak, snapshots og andre mapper. Appen har med vilje ikke tilgang hit og kan ikke slette noe – dette er en oversikt så du vet hvor du kan rydde selv.")} />
      <ErrorNote error={error} />
      {data && !data.available && <div className="empty">{data.message}</div>}
      {data?.available && data.items && (
        <>
          <div className="figures">
            <div className="figure"><div className="v">{bytes(data.other ?? 0)}</div><div className="l">{t(`outside the libraries in ${data.pool.name}`, `utenfor bibliotekene i ${data.pool.name}`)}</div></div>
            <div className="figure"><div className="v">{bytes(data.snapshots ?? 0)}</div><div className="l">{t("held by snapshots", "holdes av snapshots")}</div></div>
            <div className="figure"><div className="v">{bytes(data.overhead ?? 0)}</div><div className="l">{t("ZFS overhead (parity, metadata, rounding)", "ZFS-overhead (paritet, metadata, avrunding)")}</div></div>
          </div>
          <div className="table-wrap">
            <table>
              <thead><tr><th>{t("Dataset", "Datasett")}</th><th>{t("What", "Hva")}</th><th className="r">{t("Data outside the libraries", "Data utenfor bibliotekene")}</th><th className="r">Snapshots</th><th className="r">{t("Total", "Sum")}</th></tr></thead>
              <tbody>
                {data.items.map((r) => (
                  <tr key={r.name} className="row">
                    <td>{r.name}<div className="path">{r.mountpoint}</div></td>
                    <td className="small">{r.kind}{r.libraries.length > 0 && <div className="muted">{t(`The libraries ${r.libraries.join(", ")} (${bytes(r.library_size)}) are subtracted`, `Bibliotekene ${r.libraries.join(", ")} (${bytes(r.library_size)}) er trukket fra`)}</div>}</td>
                    <td className="r num">{bytes(r.other)}</td>
                    <td className="r num">{r.snapshots ? bytes(r.snapshots) : "–"}</td>
                    <td className="r num" style={{ fontWeight: 600 }}>{bytes(r.other + r.snapshots)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <section className="section">
            <h2>{t("Where do I clean up?", "Hvor rydder jeg?")}</h2>
            <ul className="conseq small" style={{ maxWidth: 760 }}>
              <li><b>Snapshots:</b> {t("TrueNAS → Datasets → choose the dataset → Data Protection / Snapshots. The space is freed when snapshots are deleted or expire. Adjust the retention under Data Protection → Periodic Snapshot Tasks.",
                "TrueNAS → Datasets → velg datasettet → Data Protection / Snapshots. Plassen frigjøres når snapshotene slettes eller utløper. Juster oppbevaringstiden under Data Protection → Periodic Snapshot Tasks.")}</li>
              <li><b>{t("TrueNAS apps (.ix-apps):", "TrueNAS-apper (.ix-apps):")}</b> {t("old images are cleaned up with Apps → Configuration → «Prune images» (or docker image prune -a in the shell).", "gamle images ryddes med Apps → Configuration → «Prune images» (eller docker image prune -a i shell).")}</li>
              <li><b>{t("App data and recordings:", "Appdata og opptak:")}</b> {t("cleaned up in the app itself (e.g. the retention of recordings, or the Plex cache under Settings → Troubleshooting).", "ryddes i appen selv (f.eks. oppbevaringstid for opptak, eller Plex-cache under Settings → Troubleshooting).")}</li>
              <li><b>{t("Folders on the root dataset", "Mapper på rotdatasettet")}</b> {t("outside the libraries are not mounted in the app and only show up as a total here.", "utenfor bibliotekene er ikke montert i appen og vises bare som en sum her.")}</li>
              <li><b>{t("ZFS overhead", "ZFS-overhead")}</b> {t("is the difference between what the pool has allocated and what the datasets report, and cannot be cleaned up.", "er forskjellen mellom det poolen har allokert og det datasettene rapporterer, og kan ikke ryddes.")}</li>
            </ul>
            <p className="small faint">{t(`From TrueNAS, fetched ${ago(data.fetched)}.`, `Fra TrueNAS, hentet ${ago(data.fetched)}.`)}</p>
          </section>
        </>
      )}
    </>
  );
}
