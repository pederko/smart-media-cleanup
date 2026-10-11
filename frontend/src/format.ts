import { locale, t } from "./i18n";

export const TB = 1024 ** 4;
export const GB = 1024 ** 3;

const cache: Record<string, Intl.NumberFormat> = {};
function nf(min: number, max: number) {
  const k = `${locale()}|${min}|${max}`;
  return (cache[k] ??= new Intl.NumberFormat(locale(), { minimumFractionDigits: min, maximumFractionDigits: max }));
}

/** Binary units (TiB/GiB) – the same as TrueNAS and `zfs list` show, written as T/G like there. */
export function bytes(b: number | null | undefined): string {
  if (b == null) return "–";
  if (b === 0) return "0 GB";
  const a = Math.abs(b);
  if (a >= TB) return `${nf(2, 2).format(b / TB)} TB`;
  if (a >= GB) return `${(a >= 100 * GB ? nf(0, 0) : nf(1, 1)).format(b / GB)} GB`;
  if (a >= 1024 ** 2) return `${nf(0, 0).format(b / 1024 ** 2)} MB`;
  return `${nf(0, 0).format(b / 1024)} kB`;
}

export function num(n: number | null | undefined, decimals = 0): string {
  return n == null ? "–" : nf(0, decimals).format(n);
}

export function date(ts: number | null | undefined): string {
  if (!ts) return "–";
  return new Date(ts * 1000).toLocaleDateString(locale(), { day: "numeric", month: "short", year: "numeric" });
}

export function ago(ts: number | null | undefined): string {
  if (!ts) return t("never", "aldri");
  const s = Date.now() / 1000 - ts;
  if (s < 90) return t("just now", "nå nettopp");
  if (s < 3600) return t(`${Math.round(s / 60)} min ago`, `${Math.round(s / 60)} min siden`);
  if (s < 86400) return t(`${Math.round(s / 3600)} h ago`, `${Math.round(s / 3600)} t siden`);
  const d = s / 86400;
  if (d < 60) return t(`${Math.round(d)} days ago`, `${Math.round(d)} dager siden`);
  const m = d / 30.44;
  if (m < 24) return t(`${Math.round(m)} months ago`, `${Math.round(m)} mnd siden`);
  return t(`${nf(1, 1).format(m / 12)} years ago`, `${nf(1, 1).format(m / 12)} år siden`);
}

export function kindLabel(kind: string): string {
  const labels: Record<string, [string, string]> = {
    delete_title: ["Delete title", "Slett tittel"],
    delete_season: ["Delete season", "Slett sesong"],
    replace: ["Replace with smaller", "Erstatt med mindre"],
    remove_versions: ["Keep one version", "Behold én versjon"],
    remove_copy: ["Identical copy", "Identisk kopi"],
    download: ["Old download", "Gammel nedlasting"],
  };
  const l = labels[kind];
  return l ? t(l[0], l[1]) : kind;
}

export function libKindLabel(kind: string): string {
  return ({ movies: t("Movies", "Filmer"), series: t("Series", "Serier"), mixed: t("Mixed", "Blandet"),
    downloads: t("Downloads", "Nedlastinger") } as Record<string, string>)[kind] ?? kind;
}

const PALETTE = ["var(--lib-1)", "var(--lib-2)", "var(--lib-3)", "var(--lib-4)", "var(--lib-5)", "var(--lib-6)"];

/** A stable colour per library: by position in the configuration, downloads always grey. */
export function libColor(kind: string | null | undefined, i = 0): string {
  return kind === "downloads" ? "var(--lib-dl)" : PALETTE[i % PALETTE.length];
}

export function fileName(p: string) {
  return p.split("/").pop() ?? p;
}
