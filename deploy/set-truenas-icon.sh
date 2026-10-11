#!/bin/sh
# Sets the icon of the app (default name «mediacleanup») in the TrueNAS Apps list (tested on 25.10).
#
# TrueNAS has no icon field for custom YAML apps. The icon has to be set in two places:
#   1. /mnt/.ix-apps/app_configs/<app>/metadata.yaml  – the app's own metadata
#   2. /mnt/.ix-apps/metadata.yaml                     – the combined file the Apps page reads
# Both are backed up (.bak) before changing. Only affects how the app is shown, not the app.
# May be reset when the app is edited (Edit) – run the script again then.
#
# Usage (as root in the TrueNAS shell):
#   sh set-truenas-icon.sh [app name]
set -eu
APP="${1:-mediacleanup}"
ICON="https://raw.githubusercontent.com/pederko/smart-media-cleanup/main/docs/icon.png"
APP_META="/mnt/.ix-apps/app_configs/$APP/metadata.yaml"
GLOBAL_META="/mnt/.ix-apps/metadata.yaml"

[ -f "$APP_META" ] || { echo "$APP_META not found – is the app installed with the name «$APP»?" >&2; exit 1; }
cp "$APP_META" "$APP_META.bak"
[ -f "$GLOBAL_META" ] && cp "$GLOBAL_META" "$GLOBAL_META.bak"

python3 - "$APP" "$ICON" "$APP_META" "$GLOBAL_META" <<'PY'
import os, re, shutil, sys
import yaml

app, icon, app_meta, global_meta = sys.argv[1:5]

# 1) The app's own file: small, safe to write out again
with open(app_meta) as f:
    data = yaml.safe_load(f) or {}
if not isinstance(data.get("metadata"), dict):
    sys.exit("Unexpected format in %s (no «metadata:»). Nothing was changed." % app_meta)
data["metadata"]["icon"] = icon
with open(app_meta, "w") as f:
    yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
print("OK  icon set in", app_meta)

# 2) The combined file holds every app, so it is changed as little as possible (one line)
if not os.path.isfile(global_meta):
    print("--  not found:", global_meta, "– skipping")
    sys.exit(0)
with open(global_meta) as f:
    lines = f.read().split("\n")

app_re = re.compile(r'^"?%s"?:\s*$' % re.escape(app))
start = next((i for i, l in enumerate(lines) if app_re.match(l)), None)
if start is None:
    print("--  «%s» not found in %s – skipping" % (app, global_meta))
    sys.exit(0)
end = next((i for i in range(start + 1, len(lines)) if lines[i] and not lines[i].startswith(" ")), len(lines))
meta_i = next((i for i in range(start + 1, end) if re.match(r'^  "?metadata"?:\s*$', lines[i])), None)
if meta_i is None:
    sys.exit("No «metadata:» for %s in %s. The combined file was not changed." % (app, global_meta))
child_end = next((i for i in range(meta_i + 1, end) if not lines[i].startswith("    ")), end)
icon_line = '    "icon": "%s"' % icon
existing = next((i for i in range(meta_i + 1, child_end) if re.match(r'^    "?icon"?:', lines[i])), None)
if existing is not None:
    lines[existing] = icon_line
else:
    lines.insert(meta_i + 1, icon_line)
new = "\n".join(lines)

# Check before writing: valid YAML, the icon in place, every other app unchanged
with open(global_meta) as f:
    before = yaml.safe_load(f)
after = yaml.safe_load(new)
ok = (isinstance(after, dict) and set(after) == set(before)
      and after[app]["metadata"].get("icon") == icon
      and all(after[k] == before[k] for k in before if k != app))
if not ok:
    sys.exit("The check failed – %s was NOT changed." % global_meta)
tmp = global_meta + ".tmp"
with open(tmp, "w") as f:
    f.write(new)
shutil.copymode(global_meta, tmp)
os.replace(tmp, global_meta)
print("OK  icon set in", global_meta)
PY
echo "Backups: $APP_META.bak and $GLOBAL_META.bak"
echo "Reload the Apps page in the browser (Ctrl+F5)."
