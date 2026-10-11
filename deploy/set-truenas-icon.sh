#!/bin/sh
# Setter ikonet for appen «mediacleanup» i TrueNAS Apps-oversikten (testet på 25.10).
#
# TrueNAS har ikke noe felt for ikon på egne YAML-apper. Ikonet må stå to steder:
#   1. /mnt/.ix-apps/app_configs/<app>/metadata.yaml  – appens egen metadata
#   2. /mnt/.ix-apps/metadata.yaml                     – samlet fil som Apps-siden leser
# Begge sikkerhetskopieres (.bak) før endring. Påvirker bare visningen, ikke appen.
# Kan bli tilbakestilt når appen redigeres (Edit) – kjør i så fall skriptet på nytt.
#
# Bruk (som root i TrueNAS-shell):
#   sh set-truenas-icon.sh [appnavn]
set -eu
APP="${1:-mediacleanup}"
ICON="https://raw.githubusercontent.com/pederko/smart-media-cleanup/main/docs/icon.png"
APP_META="/mnt/.ix-apps/app_configs/$APP/metadata.yaml"
GLOBAL_META="/mnt/.ix-apps/metadata.yaml"

[ -f "$APP_META" ] || { echo "Fant ikke $APP_META – er appen installert med navnet «$APP»?" >&2; exit 1; }
cp "$APP_META" "$APP_META.bak"
[ -f "$GLOBAL_META" ] && cp "$GLOBAL_META" "$GLOBAL_META.bak"

python3 - "$APP" "$ICON" "$APP_META" "$GLOBAL_META" <<'PY'
import os, re, shutil, sys
import yaml

app, icon, app_meta, global_meta = sys.argv[1:5]

# 1) Appens egen fil: liten fil, trygg å skrive ut på nytt
with open(app_meta) as f:
    data = yaml.safe_load(f) or {}
if not isinstance(data.get("metadata"), dict):
    sys.exit("Uventet format i %s (mangler «metadata:»). Ingenting er endret." % app_meta)
data["metadata"]["icon"] = icon
with open(app_meta, "w") as f:
    yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
print("OK  ikon satt i", app_meta)

# 2) Samlet fil: inneholder alle apper, så den endres med minst mulig inngrep (én linje)
if not os.path.isfile(global_meta):
    print("--  fant ikke", global_meta, "– hopper over")
    sys.exit(0)
with open(global_meta) as f:
    lines = f.read().split("\n")

app_re = re.compile(r'^"?%s"?:\s*$' % re.escape(app))
start = next((i for i, l in enumerate(lines) if app_re.match(l)), None)
if start is None:
    print("--  fant ikke «%s» i %s – hopper over" % (app, global_meta))
    sys.exit(0)
end = next((i for i in range(start + 1, len(lines)) if lines[i] and not lines[i].startswith(" ")), len(lines))
meta_i = next((i for i in range(start + 1, end) if re.match(r'^  "?metadata"?:\s*$', lines[i])), None)
if meta_i is None:
    sys.exit("Fant ikke «metadata:» for %s i %s. Den samlede filen er ikke endret." % (app, global_meta))
child_end = next((i for i in range(meta_i + 1, end) if not lines[i].startswith("    ")), end)
icon_line = '    "icon": "%s"' % icon
existing = next((i for i in range(meta_i + 1, child_end) if re.match(r'^    "?icon"?:', lines[i])), None)
if existing is not None:
    lines[existing] = icon_line
else:
    lines.insert(meta_i + 1, icon_line)
new = "\n".join(lines)

# Kontroller før vi skriver: gyldig YAML, ikonet på plass, alle andre apper uendret
with open(global_meta) as f:
    before = yaml.safe_load(f)
after = yaml.safe_load(new)
ok = (isinstance(after, dict) and set(after) == set(before)
      and after[app]["metadata"].get("icon") == icon
      and all(after[k] == before[k] for k in before if k != app))
if not ok:
    sys.exit("Kontrollen feilet – %s er IKKE endret." % global_meta)
tmp = global_meta + ".tmp"
with open(tmp, "w") as f:
    f.write(new)
shutil.copymode(global_meta, tmp)
os.replace(tmp, global_meta)
print("OK  ikon satt i", global_meta)
PY
echo "Sikkerhetskopier: $APP_META.bak og $GLOBAL_META.bak"
echo "Last Apps-siden på nytt i nettleseren (Ctrl+F5)."
