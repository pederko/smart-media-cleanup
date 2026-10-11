import { useCallback, useEffect, useRef, useState } from "react";
import { api, Job } from "./api";
import { RefreshContext, TitleContext } from "./components/common";
import TitleDrawer from "./components/TitleDrawer";
import OverviewPage from "./pages/Overview";
import SuggestionsPage from "./pages/Suggestions";
import { DuplicatesPage, FilesPage, TitlesPage } from "./pages/Lists";
import SettingsPage, { JobsPage, LogPage } from "./pages/Settings";
import { LibraryPage, UserPage, UsersPage } from "./pages/Library";

const ROUTES: { id: string; label: string }[] = [
  { id: "", label: "Oversikt" },
  { id: "forslag", label: "Forslag" },
  { id: "filmer", label: "Filmer" },
  { id: "serier", label: "Serier" },
  { id: "brukere", label: "Brukere" },
  { id: "titler", label: "Titler" },
  { id: "duplikater", label: "Duplikater" },
  { id: "filer", label: "Største filer" },
  { id: "jobber", label: "Jobber" },
  { id: "logg", label: "Logg" },
  { id: "innstillinger", label: "Innstillinger" },
];

function routeFromHash() {
  return window.location.hash.replace(/^#\/?/, "").split("?")[0];
}

type Status = { running: Job[]; version: string; actions_enabled?: boolean; services: Record<string, { ok: boolean; configured?: boolean }> };
type Update = { available: boolean; current: string; latest: string | null; url: string | null };

export default function App() {
  const [route, setRoute] = useState(routeFromHash());
  const [tick, setTick] = useState(0);
  const [title, setTitle] = useState<string | null>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [update, setUpdate] = useState<Update | null>(null);
  const [dismissed, setDismissed] = useState<string>(() => { try { return localStorage.getItem("smc.update.dismissed") || ""; } catch { return ""; } });
  const [theme, setTheme] = useState<string>(() => { try { return localStorage.getItem("smc.theme") || "dark"; } catch { return "dark"; } });
  const wasRunning = useRef(false);

  useEffect(() => {
    const h = () => setRoute(routeFromHash());
    window.addEventListener("hashchange", h);
    return () => window.removeEventListener("hashchange", h);
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem("smc.theme", theme); } catch { /* ignore */ }
  }, [theme]);

  useEffect(() => {
    let alive = true;
    const poll = () => api.get<Status>("/api/status").then((s) => {
      if (!alive) return;
      setStatus(s);
      const running = s.running.length > 0;
      if (wasRunning.current && !running) setTick((t) => t + 1);
      wasRunning.current = running;
    }).catch(() => {});
    poll();
    const t = setInterval(poll, 3000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  useEffect(() => {
    const load = () => api.get<Update>("/api/update").then(setUpdate).catch(() => {});
    load();
    const t = setInterval(load, 30 * 60 * 1000);
    return () => clearInterval(t);
  }, []);
  const dismissUpdate = () => {
    if (!update?.latest) return;
    setDismissed(update.latest);
    try { localStorage.setItem("smc.update.dismissed", update.latest); } catch { /* ignore */ }
  };

  const go = useCallback((id: string) => { window.location.hash = `#/${id}`; }, []);
  const running = status?.running.find((j) => j.status === "running") ?? status?.running[0];
  const svcBad = status ? Object.entries(status.services ?? {}).filter(([, v]) => !v.ok && v.configured !== false).length : 0;

  let page;
  const [section, ...rest] = route.split("/");
  const param = rest.length ? decodeURIComponent(rest.join("/")) : "";
  switch (section) {
    case "filmer": page = <LibraryPage kind="movie" />; break;
    case "serier": page = <LibraryPage kind="series" />; break;
    case "brukere": page = param ? <UserPage name={param} /> : <UsersPage />; break;
    case "forslag": page = <SuggestionsPage />; break;
    case "titler": page = <TitlesPage />; break;
    case "duplikater": page = <DuplicatesPage />; break;
    case "filer": page = <FilesPage />; break;
    case "jobber": page = <JobsPage />; break;
    case "logg": page = <LogPage />; break;
    case "innstillinger": page = <SettingsPage />; break;
    default: page = <OverviewPage go={go} />;
  }

  return (
    <RefreshContext.Provider value={tick}>
      <TitleContext.Provider value={setTitle}>
        <div className="shell">
          <nav className="side" aria-label="Hovedmeny">
            <div className="brand">Lagringsrydding<small>TrueNAS medieanalyse</small></div>
            <div className="nav">
              {ROUTES.map((r) => (
                <a key={r.id} href={`#/${r.id}`} aria-current={section === r.id ? "page" : undefined}>
                  {r.label}
                  {r.id === "innstillinger" && svcBad > 0 && <span className="count">{svcBad} feil</span>}
                  {r.id === "jobber" && running && <span className="count">kjører</span>}
                </a>
              ))}
            </div>
            <div className="side-foot">
              {status?.actions_enabled ? <span className="ro on">Sletting er på</span> : <span className="ro">Skrivebeskyttet</span>}
              <button className="btn small" onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>{theme === "dark" ? "Lyst tema" : "Mørkt tema"}</button>
              <span className="faint">Versjon {status?.version ?? ""}</span>
              {update?.available && <a className="update-link" href={update.url ?? "#"} target="_blank" rel="noreferrer">Versjon {update.latest} er ute</a>}
            </div>
          </nav>
          <main className="main">
            {update?.available && update.latest !== dismissed && (
              <div className="banner update" role="status">
                <span>
                  <b>Versjon {update.latest} er tilgjengelig</b> (du har {update.current}).{" "}
                  Oppdater i TrueNAS: Apps → mediacleanup → ⋮ → Update.
                </span>
                {update.url && <a href={update.url} target="_blank" rel="noreferrer" className="small">Hva er nytt</a>}
                <button className="btn small" onClick={dismissUpdate}>Skjul</button>
              </div>
            )}
            {running && route !== "jobber" && (
              <div className="banner" role="status">
                <span>{running.status === "queued" ? "Venter i kø" : running.message || "Kjører"}</span>
                <div className="progress"><i style={{ width: `${(running.progress ?? 0) * 100}%` }} /></div>
                <a href="#/jobber" className="small muted">Detaljer</a>
              </div>
            )}
            {page}
          </main>
        </div>
        {title && <TitleDrawer id={title} onClose={() => setTitle(null)} />}
      </TitleContext.Provider>
    </RefreshContext.Provider>
  );
}
