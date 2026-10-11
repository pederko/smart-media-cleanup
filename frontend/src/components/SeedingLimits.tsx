import { useEffect, useState } from "react";
import { ago, num } from "../format";
import { getLang, plural, t } from "../i18n";
import { Change, Check, Toggle } from "./ArrChanges";
import { ErrorNote } from "./common";

export type QbitLimits = {
  configured: boolean; error?: string; url_hint?: string | null;
  limits?: { ratio_enabled: boolean; ratio: number; time_enabled: boolean; minutes: number; inactive_enabled: boolean;
    inactive: number; inactive_supported: boolean; action: number };
  rule?: { enabled: boolean; ratio: number | null; minutes: number | null; inactive: number | null };
  rule_applied?: { count: number; at: number | null; error: string | null };
  categories?: Record<string, string>;
};

const dec = (v: number) => (getLang() === "nb" ? String(v).replace(".", ",") : String(v));
const parse = (s: string) => (s.trim() === "" ? null : Number(s.trim().replace(",", ".")));
const hoursOf = (min: number | null | undefined) => (min == null || min < 0 ? "" : dec(Math.round((min / 60) * 10) / 10));
const toMin = (h: number | null) => (h == null || isNaN(h) ? null : Math.round(h * 60));

/** Three inputs: stop at ratio, after N hours, or after N hours without uploading. */
function LimitInputs({ ratio, hours, inactive, set, inactiveSupported }: {
  ratio: string; hours: string; inactive: string; inactiveSupported: boolean;
  set: (k: "ratio" | "hours" | "inactive", v: string) => void;
}) {
  return (
    <div className="toolbar" style={{ margin: 0 }}>
      <label className="check small">{t("Stop at ratio", "Stopp ved ratio")} <input type="text" inputMode="decimal" style={{ width: 56 }} value={ratio} onChange={(e) => set("ratio", e.target.value)} /></label>
      <label className="check small">{t("or after", "eller etter")} <input type="text" inputMode="decimal" style={{ width: 56 }} value={hours} onChange={(e) => set("hours", e.target.value)} /> {t("hours", "timer")}</label>
      {inactiveSupported && <label className="check small">{t("or after", "eller etter")} <input type="text" inputMode="decimal" style={{ width: 56 }} value={inactive} onChange={(e) => set("inactive", e.target.value)} /> {t("hours without uploading", "timer uten opplasting")}</label>}
    </div>
  );
}

/**
 * Seeding limits in qBittorrent: the app's rule for torrents from Radarr/Sonarr (recommended), and the
 * global limit for all torrents. Both go into the change basket and are applied only after review.
 */
export default function SeedingLimits({ q, changes, toggle }: { q: QbitLimits; changes: Record<string, Change>; toggle: Toggle }) {
  const r = q.rule;
  const l = q.limits;
  const [rule, setRule] = useState({ ratio: r?.ratio != null ? dec(r.ratio) : "1", hours: r?.minutes != null ? hoursOf(r.minutes) : "24", inactive: hoursOf(r?.inactive) });
  const [glob, setGlob] = useState({ ratio: l?.ratio_enabled ? dec(l.ratio) : "", hours: l?.time_enabled ? hoursOf(l.minutes) : "", inactive: l?.inactive_enabled ? hoursOf(l.inactive) : "" });
  const ruleChange = (enabled = true): Change => ({ op: "seed_rule", enabled, ratio: parse(rule.ratio), minutes: toMin(parse(rule.hours)), inactive: toMin(parse(rule.inactive)) });
  const globChange = (): Change => ({ op: "qbit_prefs", ratio: parse(glob.ratio), minutes: toMin(parse(glob.hours)), inactive: toMin(parse(glob.inactive)) });
  useEffect(() => { if (changes["qbit:rule"]?.enabled !== false && changes["qbit:rule"]) toggle("qbit:rule", ruleChange()); // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rule]);
  useEffect(() => { if (changes["qbit:prefs"]) toggle("qbit:prefs", globChange()); // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [glob]);

  if (!q.configured) {
    return (
      <p className="small muted">{t("Connect qBittorrent under", "Koble til qBittorrent under")} <a href="#/settings/services">{t("Settings → Connections", "Innstillinger → Tilkoblinger")}</a>{q.url_hint ? t(` (Radarr uses ${q.url_hint})`, ` (Radarr bruker ${q.url_hint})`) : ""}.{" "}
        {t("Or set it in qBittorrent yourself: Options → BitTorrent → Seeding limits → «When ratio reaches» / «When total seeding time reaches» → «Stop torrent».",
          "Eller sett det i qBittorrent selv: Options → BitTorrent → Seeding limits → «When ratio reaches» / «When total seeding time reaches» → «Stop torrent».")}</p>
    );
  }
  if (q.error) return <ErrorNote error={q.error} />;
  const cats = Object.keys(q.categories ?? {});
  const globalText = l && (l.ratio_enabled || l.time_enabled || l.inactive_enabled)
    ? [l.ratio_enabled ? `ratio ${dec(l.ratio)}` : null, l.time_enabled ? t(`${num(l.minutes / 60, 1)} h`, `${num(l.minutes / 60, 1)} t`) : null,
      l.inactive_enabled ? t(`${num(l.inactive / 60, 1)} h inactive`, `${num(l.inactive / 60, 1)} t inaktiv`) : null].filter(Boolean).join(" / ")
      + (l.action !== 0 ? t(" – but the action is not «Stop»", " – men handlingen er ikke «Stopp»") : "")
    : t("no limit", "ingen grense");

  return (
    <div style={{ display: "grid", gap: 10 }}>
      <div className={`rule ${r?.enabled ? "ok" : "warn"}`}>
        <div style={{ display: "grid", gap: 8 }}>
          <div><b>{t("Only torrents from Radarr/Sonarr", "Bare torrenter fra Radarr/Sonarr")}</b> <span className="small muted">({t("recommended", "anbefalt")})</span></div>
          <div className="small">
            {r?.enabled
              ? t(`On. Set on ${plural(q.rule_applied?.count ?? 0, ["torrent", "torrents"], ["torrent", "torrenter"])}${q.rule_applied?.at ? `, checked ${ago(q.rule_applied.at)}` : ""}.`,
                `På. Satt på ${plural(q.rule_applied?.count ?? 0, ["torrent", "torrenter"], ["torrent", "torrenter"])}${q.rule_applied?.at ? `, sjekket ${ago(q.rule_applied.at)}` : ""}.`)
              : t("Off.", "Av.")}{" "}
            {t(`Every 5 minutes the app sets this limit on torrents in ${cats.length ? cats.map((c) => `«${c}»`).join(", ") : t("Radarr/Sonarr's categories", "Radarr/Sonarr sine kategorier")} that still use the global limit. Torrents with their own limit – e.g. from an indexer with a private tracker's rules – and all your other torrents are left alone.`,
              `Hvert 5. minutt setter appen denne grensen på torrenter i ${cats.length ? cats.map((c) => `«${c}»`).join(", ") : "Radarr/Sonarr sine kategorier"} som fortsatt bruker den globale grensen. Torrenter med egen grense – f.eks. fra en indekser med en privat trackers regler – og alle dine andre torrenter røres ikke.`)}
          </div>
          {q.rule_applied?.error && <div className="small warn-text">{t("Last attempt failed:", "Siste forsøk feilet:")} {q.rule_applied.error}</div>}
          <LimitInputs {...rule} inactiveSupported={!!l?.inactive_supported} set={(k, v) => setRule({ ...rule, [k]: v })} />
        </div>
        <div style={{ display: "grid", gap: 6 }}>
          <Check id="qbit:rule" change={ruleChange()} changes={changes} toggle={toggle} label={r?.enabled ? t("Save", "Lagre") : t("Switch on", "Slå på")} />
          {r?.enabled && <label className="check small"><input type="checkbox" checked={changes["qbit:rule"]?.enabled === false} onChange={(e) => toggle("qbit:rule", e.target.checked ? ruleChange(false) : null)} />{t("Switch off", "Slå av")}</label>}
        </div>
      </div>
      <div className="rule">
        <div style={{ display: "grid", gap: 8 }}>
          <div><b>{t("All torrents (qBittorrent's global limit)", "Alle torrenter (qBittorrents globale grense)")}</b></div>
          <div className="small">{t("Now:", "Nå:")} {globalText}. {t("Leave empty for no limit. The action is always set to «Stop», so Radarr/Sonarr can remove the torrent after the import.",
            "La stå tomt for ingen grense. Handlingen settes alltid til «Stopp», så Radarr/Sonarr kan fjerne torrenten etter importen.")}</div>
          <LimitInputs {...glob} inactiveSupported={!!l?.inactive_supported} set={(k, v) => setGlob({ ...glob, [k]: v })} />
        </div>
        <Check id="qbit:prefs" change={globChange()} changes={changes} toggle={toggle} label={t("Set", "Sett")} />
      </div>
      <p className="small muted">{t("Private trackers often require a minimum seeding time or ratio. Their rules win – set them on the indexer (in Prowlarr if it syncs your indexers).",
        "Private trackere krever ofte en minste delingstid eller ratio. Reglene deres går foran – sett dem på indekseren (i Prowlarr hvis den synker indekserne dine).")}</p>
    </div>
  );
}
