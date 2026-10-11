const nf1 = new Intl.NumberFormat("nb-NO", { maximumFractionDigits: 1, minimumFractionDigits: 1 });
const nf0 = new Intl.NumberFormat("nb-NO", { maximumFractionDigits: 0 });
const nf2 = new Intl.NumberFormat("nb-NO", { maximumFractionDigits: 2, minimumFractionDigits: 2 });

export const TB = 1024 ** 4;
export const GB = 1024 ** 3;

/** Binære enheter (TiB/GiB) – samme som TrueNAS og `zfs list` viser, men med T/G som der. */
export function bytes(b: number | null | undefined): string {
  if (b == null) return "–";
  if (b === 0) return "0 GB";
  const a = Math.abs(b);
  if (a >= TB) return `${nf2.format(b / TB)} TB`;
  if (a >= GB) return `${(a >= 100 * GB ? nf0 : nf1).format(b / GB)} GB`;
  if (a >= 1024 ** 2) return `${nf0.format(b / 1024 ** 2)} MB`;
  return `${nf0.format(b / 1024)} kB`;
}

export function num(n: number | null | undefined): string {
  return n == null ? "–" : nf0.format(n);
}

export function date(ts: number | null | undefined): string {
  if (!ts) return "–";
  return new Date(ts * 1000).toLocaleDateString("nb-NO", { day: "numeric", month: "short", year: "numeric" });
}

export function ago(ts: number | null | undefined): string {
  if (!ts) return "aldri";
  const s = Date.now() / 1000 - ts;
  if (s < 90) return "nå nettopp";
  if (s < 3600) return `${Math.round(s / 60)} min siden`;
  if (s < 86400) return `${Math.round(s / 3600)} t siden`;
  const d = s / 86400;
  if (d < 60) return `${Math.round(d)} dager siden`;
  const m = d / 30.44;
  if (m < 24) return `${Math.round(m)} mnd siden`;
  return `${nf1.format(m / 12)} år siden`;
}

export const KIND_LABEL: Record<string, string> = {
  delete_title: "Slett tittel",
  delete_season: "Slett sesong",
  replace: "Erstatt med mindre",
  remove_versions: "Behold én versjon",
  remove_copy: "Identisk kopi",
  download: "Gammel nedlasting",
};

export const LIB_COLORS: Record<string, string> = {
  FILM: "var(--lib-film)",
  TV: "var(--lib-tv)",
  Barn: "var(--lib-barn)",
  tmp: "var(--lib-tmp)",
};

export function libColor(name: string, i = 0): string {
  return LIB_COLORS[name] ?? ["#C98FD6", "#7FB6C9", "#D6A27F"][i % 3];
}

export function fileName(p: string) {
  return p.split("/").pop() ?? p;
}
