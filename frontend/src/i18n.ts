/**
 * Two languages: English (en) and Norwegian Bokmål (nb).
 *
 * Texts are written inline as t("English", "Norsk") – no key files to keep in sync. The language is
 * chosen in the menu, remembered in localStorage, and defaults to the browser language. The API gets
 * the same language through the X-Lang header, so texts from the server match.
 */
export type Lang = "en" | "nb";

function detect(): Lang {
  try {
    const stored = localStorage.getItem("smc.lang");
    if (stored === "en" || stored === "nb") return stored;
  } catch { /* ignore */ }
  const langs = typeof navigator !== "undefined" ? navigator.languages ?? [navigator.language] : [];
  return langs.some((l) => /^(nb|no|nn)\b/i.test(l)) ? "nb" : "en";
}

let current: Lang = detect();
if (typeof document !== "undefined") document.documentElement.lang = current;

export const getLang = () => current;

export function setLang(l: Lang) {
  current = l;
  try { localStorage.setItem("smc.lang", l); } catch { /* ignore */ }
  document.documentElement.lang = l;
}

/** The text in the current language. */
export function t(en: string, nb: string): string {
  return current === "nb" ? nb : en;
}

export const locale = () => (current === "nb" ? "nb-NO" : "en-GB");

/** «1 movie» / «3 movies» – the count is formatted for the language. */
export function plural(n: number, en: [string, string], nb: [string, string]): string {
  const words = current === "nb" ? nb : en;
  return `${new Intl.NumberFormat(locale()).format(n)} ${n === 1 ? words[0] : words[1]}`;
}
