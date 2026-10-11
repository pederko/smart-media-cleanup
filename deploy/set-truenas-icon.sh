#!/bin/sh
# Setter ikonet for appen «mediacleanup» i TrueNAS Apps-oversikten.
#
# TrueNAS har ikke noe felt for ikon på egne YAML-apper. Ikonet ligger i appens
# metadatafil, og kan bli tilbakestilt når du redigerer appen (Edit) eller oppdaterer
# TrueNAS. Kjør i så fall skriptet på nytt. Påvirker bare visningen, ikke appen selv.
#
# Bruk (som root i TrueNAS-shell):
#   sh set-truenas-icon.sh [appnavn]
set -eu
APP="${1:-mediacleanup}"
ICON="https://raw.githubusercontent.com/pederko/smart-media-cleanup/main/docs/icon.png"
META="/mnt/.ix-apps/app_configs/$APP/metadata.yaml"

[ -f "$META" ] || { echo "Fant ikke $META – er appen installert med navnet «$APP»?" >&2; exit 1; }
cp "$META" "$META.bak"

python3 - "$META" "$ICON" <<'PY'
import sys, yaml
path, icon = sys.argv[1], sys.argv[2]
with open(path) as f:
    data = yaml.safe_load(f) or {}
meta = data.get("metadata")
if not isinstance(meta, dict):
    sys.exit("Uventet format i metadata.yaml (mangler «metadata:»). Ingenting er endret.")
meta["icon"] = icon
with open(path, "w") as f:
    yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
print("Ikon satt i", path)
PY
echo "Sikkerhetskopi: $META.bak"
echo "Last Apps-siden på nytt i nettleseren. Vises ikonet ikke, start appen på nytt (Stop/Start)."
