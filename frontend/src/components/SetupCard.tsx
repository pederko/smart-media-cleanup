import { t } from "../i18n";

export type SetupStep = { id: string; done: boolean; title: string; detail: string };
export type SetupStatus = {
  steps: SetupStep[]; done: boolean;
  paths: { service: string; path: string; mapped: string; library: string | null; ok: boolean; suggestion: { from: string; to: string; library: string } | null }[];
  libraries: { name: string; host_path: string; container_path: string; kind: string; protected: boolean }[];
  detected: { name: string; host_path: string; container_path: string; kind: string }[];
};

const LINK: Record<string, string> = {
  libraries: "#/settings/libraries", services: "#/settings/services", services_ok: "#/settings/services",
  paths: "#/settings/libraries", refresh: "#/activity",
};

/** Checklist on the overview until everything is set up. */
export default function SetupCard({ s }: { s: SetupStatus }) {
  const left = s.steps.filter((x) => !x.done).length;
  return (
    <section className="setup" aria-label={t("Getting started", "Kom i gang")}>
      <h2 style={{ marginBottom: 2 }}>{t("Getting started", "Kom i gang")}</h2>
      <p className="small muted" style={{ margin: 0 }}>
        {t(`${left} of ${s.steps.length} steps left. The app works read-only the whole time – nothing is deleted until you switch it on.`,
          `${left} av ${s.steps.length} steg gjenstår. Appen er skrivebeskyttet hele tiden – ingenting slettes før du slår det på.`)}
      </p>
      <ol>
        {s.steps.map((x) => (
          <li key={x.id}>
            <span className={`tick${x.done ? " done" : ""}`} aria-label={x.done ? t("done", "ferdig") : t("not done", "ikke ferdig")}>{x.done ? "✓" : ""}</span>
            <span>{x.done ? x.title : <a href={LINK[x.id] ?? "#/settings"}>{x.title}</a>}<small>{x.detail}</small></span>
          </li>
        ))}
      </ol>
    </section>
  );
}
