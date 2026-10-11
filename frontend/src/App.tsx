import { useCallback, useEffect, useRef, useState } from "react";
import { api, Status } from "./api";
import { RefreshContext, StatusContext, TitleContext } from "./components/common";
import TitleDrawer from "./components/TitleDrawer";
import { getLang, Lang, setLang, t } from "./i18n";
import ActivityPage from "./pages/Activity";
import DownloadsPage from "./pages/Downloads";
import DuplicatesPage from "./pages/Duplicates";
import { LibraryPage, UserPage, UsersPage } from "./pages/Library";
import { FilesPage } from "./pages/Lists";
import OtherPage from "./pages/Other";
import OverviewPage from "./pages/Overview";
import PlexCheckPage from "./pages/PlexCheck";
import QualityPage from "./pages/Quality";
import SettingsPage from "./pages/Settings";
import SuggestionsPage from "./pages/Suggestions";

type NavItem = { id: string; en: string; nb: string };
const NAV: { en: string; nb: string; items: NavItem[] }[] = [
  { en: "", nb: "", items: [{ id: "", en: "Overview", nb: "Oversikt" }] },
  { en: "Library", nb: "Bibliotek", items: [
    { id: "movies", en: "Movies", nb: "Filmer" },
    { id: "series", en: "Series", nb: "Serier" },
    { id: "users", en: "Users", nb: "Brukere" },
    { id: "files", en: "Largest files", nb: "Største filer" },
  ] },
  { en: "Free up space", nb: "Frigjør plass", items: [
    { id: "suggestions", en: "Suggestions", nb: "Forslag" },
    { id: "quality", en: "Swap quality", nb: "Bytt kvalitet" },
    { id: "duplicates", en: "Duplicates", nb: "Duplikater" },
    { id: "downloads", en: "Downloads", nb: "Nedlastinger" },
    { id: "plex", en: "Plex differences", nb: "Plex-avvik" },
    { id: "other", en: "Other storage", nb: "Annen lagring" },
  ] },
  { en: "System", nb: "System", items: [
    { id: "activity", en: "Activity", nb: "Aktivitet" },
    { id: "settings", en: "Settings", nb: "Innstillinger" },
  ] },
];

// Addresses from before 1.0 (Norwegian) still work
const LEGACY: Record<string, string> = {
  forslag: "suggestions", filmer: "movies", serier: "series", brukere: "users", titler: "movies", filer: "files",
  kvalitet: "quality", duplikater: "duplicates", nedlastinger: "downloads", annet: "other", jobber: "activity",
  logg: "activity/log", innstillinger: "settings",
};

function routeFromHash() {
  const r = window.location.hash.replace(/^#\/?/, "").split("?")[0];
  const [head, ...rest] = r.split("/");
  if (LEGACY[head]) {
    const next = [LEGACY[head], ...rest].join("/");
    window.history.replaceState(null, "", `#/${next}`);
    return next;
  }
  return r;
}

type Update = { available: boolean; current: string; latest: string | null; url: string | null };

export default function App() {
  const [route, setRoute] = useState(routeFromHash());
  const [lang, setLangState] = useState<Lang>(getLang());
  const [tick, setTick] = useState(0);
  const [title, setTitle] = useState<string | null>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [update, setUpdate] = useState<Update | null>(null);
  const [menu, setMenu] = useState(false);
  const [dismissed, setDismissed] = useState<string>(() => { try { return localStorage.getItem("smc.update.dismissed") || ""; } catch { return ""; } });
  const [theme, setTheme] = useState<string>(() => { try { return localStorage.getItem("smc.theme") || "dark"; } catch { return "dark"; } });
  const wasRunning = useRef(false);

  useEffect(() => {
    const h = () => { setRoute(routeFromHash()); setMenu(false); setTitle(null); };
    window.addEventListener("hashchange", h);
    return () => window.removeEventListener("hashchange", h);
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem("smc.theme", theme); } catch { /* ignore */ }
  }, [theme]);

  const poll = useCallback(() => api.get<Status>("/api/status").then((s) => {
    setStatus(s);
    const running = s.running.length > 0;
    if (wasRunning.current && !running) setTick((x) => x + 1);
    wasRunning.current = running;
  }).catch(() => {}), []);

  useEffect(() => {
    poll();
    const iv = setInterval(poll, 3000);
    return () => clearInterval(iv);
  }, [poll]);

  useEffect(() => {
    const load = () => api.get<Update>("/api/update").then(setUpdate).catch(() => {});
    load();
    const iv = setInterval(load, 30 * 60 * 1000);
    return () => clearInterval(iv);
  }, []);

  const changeLang = (l: Lang) => { setLang(l); setLangState(l); };
  const dismissUpdate = () => {
    if (!update?.latest) return;
    setDismissed(update.latest);
    try { localStorage.setItem("smc.update.dismissed", update.latest); } catch { /* ignore */ }
  };

  const running = status?.running.find((j) => j.status === "running") ?? status?.running[0];
  const svcBad = status ? Object.values(status.services ?? {}).filter((v) => !v.ok && v.configured !== false).length : 0;
  const [section, ...rest] = route.split("/");
  const param = rest.length ? decodeURIComponent(rest.join("/")) : "";

  let page;
  switch (section) {
    case "suggestions": page = <SuggestionsPage />; break;
    case "movies": page = <LibraryPage kind="movie" />; break;
    case "series": page = <LibraryPage kind="series" />; break;
    case "users": page = param ? <UserPage name={param} /> : <UsersPage />; break;
    case "files": page = <FilesPage />; break;
    case "quality": page = <QualityPage />; break;
    case "duplicates": page = <DuplicatesPage />; break;
    case "downloads": page = <DownloadsPage />; break;
    case "plex": page = <PlexCheckPage />; break;
    case "other": page = <OtherPage />; break;
    case "activity": page = <ActivityPage tab={param || "jobs"} />; break;
    case "settings": page = <SettingsPage section={param} onSaved={poll} />; break;
    default: page = <OverviewPage />;
  }

  return (
    <StatusContext.Provider value={status}>
      <RefreshContext.Provider value={tick}>
        <TitleContext.Provider value={setTitle}>
          <div className="shell" key={lang}>
            <nav className={`side${menu ? " open" : ""}`} aria-label={t("Main menu", "Hovedmeny")}>
              <div className="side-top">
                <a href="#/" className="brand">
                  <img src="/icon.svg" alt="" width={28} height={28} />
                  <span>Smart Media Cleanup<small>{t("Storage cleanup for Plex", "Lagringsrydding for Plex")}</small></span>
                </a>
                <button className="btn small menu-btn" aria-expanded={menu} onClick={() => setMenu(!menu)}>{t("Menu", "Meny")}</button>
              </div>
              <div className="nav">
                {NAV.map((g, gi) => (
                  <div className="nav-group" key={gi}>
                    {g.en && <div className="nav-head">{t(g.en, g.nb)}</div>}
                    {g.items.map((r) => (
                      <a key={r.id} href={`#/${r.id}`} aria-current={section === r.id ? "page" : undefined}>
                        {t(r.en, r.nb)}
                        {r.id === "settings" && svcBad > 0 && <span className="count bad">{svcBad}</span>}
                        {r.id === "activity" && (running || (status?.active_swaps ?? 0) > 0) && <span className="count live">●</span>}
                      </a>
                    ))}
                  </div>
                ))}
              </div>
              <div className="side-foot">
                <a href="#/settings/deletion" className="ro-link" title={t("Changed under Settings → Deletion", "Endres under Innstillinger → Sletting")}>
                  {status?.actions_enabled || status?.files_enabled
                    ? <span className="ro on">{t("Deletion is on", "Sletting er på")}</span>
                    : <span className="ro">{t("Read-only", "Skrivebeskyttet")}</span>}
                </a>
                <div className="foot-row">
                  <div className="seg" role="group" aria-label={t("Language", "Språk")}>
                    <button aria-pressed={lang === "en"} onClick={() => changeLang("en")}>EN</button>
                    <button aria-pressed={lang === "nb"} onClick={() => changeLang("nb")}>NO</button>
                  </div>
                  <button className="btn small" onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>{theme === "dark" ? t("Light", "Lyst") : t("Dark", "Mørkt")}</button>
                </div>
                <span className="faint">{t("Version", "Versjon")} {status?.version ?? ""}</span>
                {update?.available && <a className="update-link" href={update.url ?? "#"} target="_blank" rel="noreferrer">{t(`Version ${update.latest} is out`, `Versjon ${update.latest} er ute`)}</a>}
              </div>
            </nav>
            <main className="main">
              {update?.available && update.latest !== dismissed && (
                <div className="banner update" role="status">
                  <span>
                    <b>{t(`Version ${update.latest} is available`, `Versjon ${update.latest} er tilgjengelig`)}</b>{" "}
                    {t(`(you have ${update.current}). Update in TrueNAS: Apps → the app → ⋮ → Update.`,
                      `(du har ${update.current}). Oppdater i TrueNAS: Apps → appen → ⋮ → Update.`)}
                  </span>
                  {update.url && <a href={update.url} target="_blank" rel="noreferrer" className="small">{t("What's new", "Hva er nytt")}</a>}
                  <button className="btn small" onClick={dismissUpdate}>{t("Hide", "Skjul")}</button>
                </div>
              )}
              {running && section !== "activity" && (
                <div className="banner" role="status">
                  <span>{running.status === "queued" ? t("Waiting in the queue", "Venter i kø") : running.message || t("Running", "Kjører")}</span>
                  <div className="progress"><i style={{ width: `${(running.progress ?? 0) * 100}%` }} /></div>
                  <a href="#/activity" className="small muted">{t("Details", "Detaljer")}</a>
                </div>
              )}
              {page}
            </main>
          </div>
          {title && <TitleDrawer key={`${title}|${lang}`} id={title} onClose={() => setTitle(null)} />}
        </TitleContext.Provider>
      </RefreshContext.Provider>
    </StatusContext.Provider>
  );
}
