# Smart Media Cleanup

Find out what is filling up your Plex server – and free space safely.

Smart Media Cleanup scans the media folders on a TrueNAS SCALE server, links every file to Radarr, Sonarr, Plex, Tautulli and (optionally) Seerr, and gives you ranked, explained suggestions: titles nobody watches, 4K remuxes that could be smaller, duplicates, forgotten downloads, and files Plex never picked up. Savings are calculated per file on disk, so hardlinks and overlapping suggestions are never counted twice.

**It starts read-only.** Nothing is ever deleted automatically. Deleting is switched on separately for changes through Radarr/Sonarr/Plex and for files on disk, and every action is shown in a summary first and needs one confirmation.

The web UI is available in **English and Norwegian** (EN/NO in the menu). *[Les dette på norsk](docs/README.nb.md).*

![Overview](docs/screenshots/overview.png)

<sub>Screenshots show the demo data from the automated tests, not a real library.</sub>

---

## Contents

1. [What it does](#what-it-does)
2. [Safety model](#safety-model)
3. [Install on TrueNAS SCALE](#install-on-truenas-scale)
4. [First setup](#first-setup)
5. [Using it](#using-it)
6. [How the priority is calculated](#how-the-priority-is-calculated)
7. [Configuration](#configuration)
8. [Updating](#updating)
9. [Backup and restore](#backup-and-restore)
10. [Troubleshooting](#troubleshooting)
11. [Development](#development)
12. [Known limitations](#known-limitations)

---

## What it does

| Page | What you get |
|---|---|
| **Overview** | Capacity, how much is *recommended* to free (priority ≥ 50, not high risk), and one card per area where space can be freed. A getting-started checklist until everything is set up. |
| **Movies / Series** | A summary (never watched, not watched for 12/24/36 months, safe deletions, 4K), «look at these first» with posters, and a filterable list with a recommendation per title. |
| **Users** | Per Seerr user: what they requested and whether they watched it themselves. |
| **Largest files** | Single files by size, with «Find smaller» straight from the list. |
| **Suggestions** | Ranked suggestions. Each one shows the score line by line, the consequences for Radarr/Sonarr/Plex and the files involved. |
| **Swap quality** | Large movies and seasons. Search the indexers for many at once, see the recommended smaller release and swap several with one confirmation. |
| **Duplicates** | Identical copies, extra versions and hardlinks (which take no space) kept apart. Choose which file to keep and delete the rest. |
| **Downloads** | What is in the downloads folder, whether it was imported, and what can safely go. |
| **Plex differences** | Files on disk Plex does not know (with the likely reason), and Plex entries whose files are gone. |
| **Other storage** | With the TrueNAS integration: which datasets and snapshots use the space outside your libraries, and where to clean them up. Read only. |
| **Torrents** | Everything in qBittorrent: in library, orphaned, broken, still importing. Stop, set limits, remove (with files only when safe), and a seeding rule for Radarr/Sonarr torrents only. |
| **Download rules** | How Radarr, Sonarr, Seerr and qBittorrent are set up, compared with TRaSH Guides: size limits per quality, quality profiles (remuxes, size-heavy custom formats), Seerr's default profile and seeding limits. Change them with one confirmation; a backup is saved first. |
| **Activity** | Background jobs, swaps in progress and the log of everything the app has deleted. |

| Suggestion with explanation | Swap quality |
|---|---|
| ![Suggestions](docs/screenshots/suggestions.png) | ![Swap quality](docs/screenshots/quality.png) |

| Title panel | Settings: libraries and paths |
|---|---|
| ![Title](docs/screenshots/title.png) | ![Settings](docs/screenshots/settings.png) |

| Download rules | Size limits |
|---|---|
| ![Download rules](docs/screenshots/rules.png) | ![Size limits](docs/screenshots/rules-sizes.png) |

<img src="docs/screenshots/mobile.png" alt="Mobile" width="280">

### Suggestion types

| Type | When | Frees |
|---|---|---|
| Delete title | A movie or series over the minimum size | Every file in its folder |
| Delete season | The series is watched, but one season has not been for a long time | That season's files |
| Replace with smaller | A movie over 40 GB or an episode over 8 GB (adjustable) | Estimate: size minus the target size |
| Keep one version | Several different files for the same movie/episode | The other versions |
| Identical copy | Same size and partial hash, different inode | The copies that are not kept |
| Old download | A folder in the downloads library with no copy in a library, older than a month | The folder |

## Safety model

| Rule | How |
|---|---|
| Read-only by default | Media folders are mounted `:ro`. Both deletion switches are off. |
| Nothing automatic | The app only suggests. Every action shows a summary and needs one confirmation. The server executes exactly what was shown (a token), and refuses if anything changed since. |
| Titles are deleted through Radarr/Sonarr | Movies and series are deleted through their APIs (with files, no import exclusion), so they stay in sync and do not download them again. Single seasons are unmonitored first. |
| Checked right before | Each title is fetched again and its folder compared with the analysis; each file is checked to be unchanged since the scan, inside a library and not a symlink. A mismatch stops that action. |
| Direct file deletion is narrow | Only redundant duplicates (one file always stays), downloads and folders no service knows about – and only on folders you mount without `:ro`. |
| Swaps download first | The large file is only deleted once the smaller one is downloaded and Radarr/Sonarr can import it. Any other import problem stops the swap with the old file untouched. |
| Protection | Libraries, Radarr/Sonarr tags (`keep`), Plex labels and paths you mark as protected are never suggested for deletion or swapping. |
| Least privilege | Runs as `568:568` (apps), `cap_drop: ALL`, `no-new-privileges`, read-only root file system. Only the folders you mount are visible; app data, `ix-apps` and the like are out of reach. |
| No ZFS access | No `zfs` commands. The optional TrueNAS integration uses an API key with the *Read-Only Admin* role. Snapshots are never touched. |
| Secrets | Stored in `/data/settings.json` (mode 600) or as environment variables, masked in the API and UI. The browser only talks to the app, so the Plex token and API keys never leave the server. |
| Torrents | Removing a torrent with its files is only offered when its content is found in a library, or – for orphaned ones – when deleting files on disk is switched on. The seeding rule only sets limits, on Radarr/Sonarr torrents that use the global limit, and only while *Allow changes* is on. |
| Download rules | Size limits, profiles, Seerr and qBittorrent settings are only changed after a review, with the services re-read first. Every changed setting is backed up to `/data/backups/arr-setup-*.json` (mode 600) and can be restored from the page. Torrents are only removed when they are finished and their content is found in a library. |
| Logged | Every deletion, swap and Plex change is shown under Activity → Deletion log and stored in the database (`audit`). |

## Install on TrueNAS SCALE

Tested on TrueNAS SCALE 25.10. Custom apps are installed with **Apps → Discover Apps → the arrow next to «Custom App» → Install via YAML**.

### 1. Create the data folder

Create a dataset for the app's data (e.g. `tank/apps/mediacleanup`, preset *Apps*), then in the TrueNAS shell:

```sh
mkdir -p /mnt/tank/apps/mediacleanup/data
chown -R 568:568 /mnt/tank/apps/mediacleanup/data
```

Replace `tank` with your pool name throughout.

### 2. Install the app

1. Apps → **Discover Apps** → the arrow/menu next to **Custom App** → **Install via YAML**.
2. **Name:** `mediacleanup`.
3. **Custom Config:** paste [`deploy/truenas-app.yaml`](deploy/truenas-app.yaml) and adjust:
   - the data folder from step 1,
   - one line per media folder: `- /mnt/<pool>/<path>:/media/<Name>:ro`,
   - `TZ` to your time zone.
4. **Save.** TrueNAS pulls `ghcr.io/pederko/smart-media-cleanup:latest` and starts the app on **http://&lt;truenas-ip&gt;:30480** (the **Web UI** button opens it).

Mount the folders Radarr, Sonarr and Plex use – typically movies, TV and the downloads folder. Each folder under `/media` becomes a library named after the folder. The app works out the TrueNAS path behind each mount by itself.

<details><summary>Prefer the «Install iX App» form?</summary>

| Section | Field | Value |
|---|---|---|
| Application name | Name | `mediacleanup` |
| Image Configuration | Repository | `ghcr.io/pederko/smart-media-cleanup` |
| | Tag | `latest` |
| Container Configuration | Timezone | your time zone |
| Security Context | Privileged | off |
| | Custom User | on, User ID `568`, Group ID `568` |
| Network Configuration | Ports | container port `8000`, host port `30480`, TCP |
| Storage Configuration | Host Path | `/mnt/tank/apps/mediacleanup/data` → `/data` |
| | Host Path, Read Only | `/mnt/tank/media/Movies` → `/media/Movies` (one per folder) |
| Resources | Limits | 1 CPU, 1024 MB (optional) |

The YAML route also gives a read-only root file system, dropped capabilities and the Web UI button.
</details>

### 3. App icon (optional)

TrueNAS has no icon field for custom YAML apps. A small script sets it in the app metadata (it makes backups first):

```sh
curl -fsSLo /tmp/set-icon.sh https://raw.githubusercontent.com/pederko/smart-media-cleanup/main/deploy/set-truenas-icon.sh
sh /tmp/set-icon.sh mediacleanup
```

Reload the Apps page. Editing the app may reset the icon – run the script again then.

## First setup

The overview shows a checklist until everything is in place.

1. **Libraries** – detected on first start from the folders under `/media`. Check the names, types (movies, series, mixed, downloads) and protection under **Settings → Libraries and paths**.
2. **Connections** – under **Settings → Connections**, enter the address and key for each service and press **Test connection**:

   | Service | Address (from the container) | Key |
   |---|---|---|
   | Radarr | `http://<nas-ip>:<port>` | Settings → General → API Key |
   | Sonarr | `http://<nas-ip>:<port>` | Settings → General → API Key |
   | Plex | `http://<nas-ip>:32400` | X-Plex-Token: open an item → ⋯ → Get Info → View XML; the token is in the address |
   | Tautulli | `http://<nas-ip>:<port>` | Settings → Web Interface → API key |
   | Seerr (optional) | `http://<nas-ip>:<port>` | Settings → General → API Key |
   | TrueNAS (optional) | `https://<nas-ip>` | API key for a user with the *Read-Only Admin* role |
   | qBittorrent (optional) | `http://<nas-ip>:<port>` | Web UI username and password |

   Use the NAS's LAN IP – `localhost` points to the app's own container.
3. **Path mappings** – Radarr, Sonarr and Plex usually see the folders under other paths (e.g. `/movies` inside their containers). After the first sync, the app reads their root folders and suggests mappings by folder name; press **Use** and save.
4. **Full refresh** – Activity → **Run full refresh**. After that, the scheduler keeps everything up to date.

## Using it

- **Start on the overview.** The cards show where space can be freed; each one leads to its page.
- **Suggestions** open on *Recommended*. Open a row to see why. Select rows and press **Delete selected…**. **Export CSV** gives the same list in a spreadsheet.
- **Swap quality:** select titles, press **Search** (one at a time, at most 25 per round, to spare the indexers), then **Swap N…**. Choose what happens afterwards: leave Radarr/Sonarr as before, unmonitor, or change the quality profile so they do not «upgrade» back.
- **Duplicates:** start with *Identical copies* – always safe. Check the file marked *Keep* in each group.
- **Downloads:** filter on *Can be deleted*. Remove torrents that are still seeding in the download client first.
- **Plex differences:** ask Plex to rescan a folder, delete folders that are on disk only, or remove Plex entries whose files are gone (requires *Allow media deletion* in Plex → Settings → Library).

### Download rules: stop new large files and endless seeding

Cleaning up helps once; the rules decide what comes in next. Under **Prevent → Download rules**:

- **Recommendations** lists what differs from the recommended setup. Tick what you want, press **Review…**, check the summary and apply.
- **Size limits**: choose *Balanced* (recommended), *Space saver* or *TRaSH Guides* and adjust single values. Sizes are shown per movie (2 h) or episode (45 min). Existing files are not touched – the table shows how many are above the new limits, and *Swap quality* can replace them.
- **Quality profiles**: stop remuxes, BR-DISK and Raw-HD in a profile, or create a recommended profile based on one of yours (keeps your custom formats). TRaSH's full custom format set (release groups, HDR, audio) is best synced with [Recyclarr](https://recyclarr.dev) – this page only touches what drives file size.
- **Seerr**: choose the profile new requests get.
- **Seeding**: for finished torrents to disappear by themselves, qBittorrent must stop a torrent when it has seeded enough, and Radarr/Sonarr must have *Remove completed* on. Both can be set here. The recommended way is the **seeding rule for Radarr/Sonarr only** (ratio, time and/or hours without uploading): the app keeps it on torrents in their categories that use the global limit, checked every 5 minutes, and leaves torrents with their own limit (e.g. private trackers) and all other torrents alone. Private trackers may require a minimum seeding time – their rules win.

### Torrents

With qBittorrent connected, **Free up space → Torrents** shows every torrent and what it is: *in library*, *orphaned* (from Radarr/Sonarr, finished, not in their queue and not in any library), *error*, *being imported*, *downloading*, or from another category. Select and stop them, give them the global limit, remove the torrent only, or remove it with its files. Files are deleted only for torrents found in a library – or for orphaned ones and other categories when *Allow deleting files on disk* is on too. Torrents Radarr/Sonarr are still importing are never touched.
- **Backups**: every change saves the previous settings first; restore with one click.

Changing these needs *Allow changes through Radarr, Sonarr, Plex, Seerr and qBittorrent* under Settings → Deletion.

### Switching deletion on

Under **Settings → Deletion**:

- **Allow changes through Radarr, Sonarr, Plex, Seerr and qBittorrent** – delete movies, series and seasons, swap to smaller versions, remove Plex entries without files, and apply download rules.
- **Allow deleting files on disk** – redundant duplicates, downloads and orphaned folders. Also remove `:ro` on the folders in question (Apps → mediacleanup → Edit). The section shows write access per folder.

Duplicates Radarr/Sonarr know are deleted through them, followed by a rescan so they use the file you keep (it has to be in the same folder). Protection applies to whole titles; duplicates in protected libraries can still be cleaned up unless you switch on *Protection also applies to duplicates*.

### Requests (Seerr) and watch history

With Seerr connected, «Requested by …» appears on titles and suggestions, and **Users** shows per user what they requested and whether they watched it. Requests are linked through TMDB/TVDB ids in Radarr/Sonarr and the Plex ratingKey for other titles.

Watch history comes from Tautulli and only goes back to when Tautulli was installed. «Never watched» therefore means *no play since the history started* – the date is shown on the overview. Plays under 5 % are not counted. When a title was replaced in Plex and got a new ratingKey, plays are matched by name and year.

## How the priority is calculated

The priority (0–100) is a sum of visible points – no hidden model. Each suggestion shows its lines.

| Factor | Points |
|---|---|
| Space actually freed | 0 to +35 (logarithmic: 10 GB ≈ 12, 30 GB ≈ 24, 70 GB+ = 35) |
| Never watched since the history started | +30 (+22 if added after the history started) |
| Not watched for ≥ 36 / ≥ 24 / ≥ 12 months | +25 / +18 / +10 |
| Watched in the last 3 months | −20 |
| At most 2 plays and ≥ 20 GB | +8 |
| 10 plays or more | −10 |
| Viewers in the last 12 months | −6 per user (at most −30) |
| Monitored in Radarr/Sonarr | −8 (not monitored: +5) |
| Added within the quarantine (6 months) | −40 |
| Requested in Seerr in the last 12 months | −15 |
| Requested over 12 months ago, and nobody who requested it watched it | +8 |
| The content is kept in another version | +25 (versions/copies), +10 (replacement) |

Every threshold and weight can be changed under Settings → Analysis. Suggestions under priority 20 are hidden by default; «recommended» means priority ≥ 50 and not high risk.

**Risk:** *high* if watched in the last 12 months, by two or more users recently, recently added or recently requested. *Medium* if monitored or ever watched. Otherwise *low*. Identical copies are always low risk.

**Savings without double counting:** each file (inode) is counted once, with the largest claim among the selected suggestions. A hardlinked file only frees space when every path to it is included; otherwise it is shown as «held by hardlinks». Sizes are allocated space on ZFS (`st_blocks`), not only the logical size.

## Configuration

Settings are stored in `/data/settings.json` and edited in the app. Environment variables override and lock the fields:

| Variable | Meaning |
|---|---|
| `SMC_RADARR_URL`, `SMC_RADARR_API_KEY` | Radarr |
| `SMC_SONARR_URL`, `SMC_SONARR_API_KEY` | Sonarr |
| `SMC_PLEX_URL`, `SMC_PLEX_TOKEN` | Plex |
| `SMC_TAUTULLI_URL`, `SMC_TAUTULLI_API_KEY` | Tautulli |
| `SMC_SEERR_URL`, `SMC_SEERR_API_KEY` | Seerr/Overseerr |
| `SMC_TRUENAS_URL`, `SMC_TRUENAS_API_KEY` | TrueNAS (read-only) |
| `SMC_QBITTORRENT_URL`, `SMC_QBITTORRENT_USERNAME`, `SMC_QBITTORRENT_PASSWORD` | qBittorrent |
| `SMC_USERNAME`, `SMC_PASSWORD` | Switches on a login (basic auth) for the web UI |
| `SMC_LOG_LEVEL` | `INFO` (default) or `DEBUG` |
| `TZ` | Time zone |

**Port:** change `30480` under `ports:`. **More libraries:** add a volume `- /mnt/<pool>/<path>:/media/<Name>:ro` and press **Detect from /media** under Settings → Libraries and paths (or add the row by hand).

### Scheduled jobs

| Job | Default |
|---|---|
| Sync with the services | every 6 hours |
| Incremental scan | every 24 hours |
| Full scan (stat of every file) | every 7 days, as part of a refresh |
| Follow-up of swaps | every 5 minutes (more often while the page is open) |
| Seeding rule for Radarr/Sonarr torrents (when switched on) | every 5 minutes |
| Check for a new version on GitHub | every 6 hours |
| Backup of the database and settings | daily, 7 are kept |

Only one job runs at a time. The incremental scan only stats files in folders whose content changed (the folder's mtime), and usually takes seconds. The partial hash (12 MB per file) is only computed for files with exactly the same size as another file.

## Updating

The compose file uses `ghcr.io/pederko/smart-media-cleanup:latest`. When a new version is published:

1. The app shows a banner with a link to what is new (checked every 6 hours; can be switched off under Settings → Updates).
2. TrueNAS shows **Update available** on the app once it has checked the image.
3. Update with Apps → mediacleanup → ⋮ → **Update**. TrueNAS pulls the new image and restarts the app. The database is upgraded automatically; settings and backups in `data/` are kept.

The app never updates itself.

**How often does TrueNAS check?** TrueNAS compares the images of all apps with the registry **once a day** and when the Apps service starts, if «Check for image updates» is on under Apps → Configuration → Settings. To check right away, run this in the TrueNAS shell:

```sh
midclt -t 600 call app.image.op.check_update
```

Without `-t 600` the call may report «Call timeout» because it checks every app; the check carries on anyway. Then reload the Apps page.

**Pin a version:** replace `:latest` with a version (e.g. `:1.0.0`) under Edit. Go back to an earlier version the same way.

### Releases (development)

The version is driven by the `VERSION` file. When a new value is pushed to `main`, GitHub Actions runs the tests, publishes the image as `<version>`, `<major.minor>` and `latest`, and creates the tag `v<version>` and a GitHub release with the notes from `CHANGELOG.md`. Other pushes to `main` publish `edge`.

## Backup and restore

Everything worth keeping is in the data folder (e.g. `/mnt/tank/apps/mediacleanup/data`):

- `settings.json` – connections, thresholds, protection.
- `smc.sqlite3` – cache and analysis. Can always be rebuilt with a full refresh.
- `backups/` – daily copies of both (7 are kept).
- `posters/` – cached posters.

A periodic snapshot task on the app's dataset is a good addition. The app itself never touches snapshots.

**Restore:** stop the app, copy the wanted `backups/settings-*.json` to `data/settings.json` (and optionally `backups/smc-*.sqlite3` to `data/smc.sqlite3`), start the app.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| The app does not start, «manifest unknown» / «denied» | Wrong tag or image name (must be lower case). |
| «The folders for … were not found in the container» | The volume is missing in the compose file, or the container path under Settings → Libraries does not match. |
| `Permission denied` in the log | The data folder is not owned by 568: `chown -R 568:568 <data folder>`. The media folders must be readable for 568. |
| «No connection to …» | Use the LAN IP, not `localhost`. Check the port. |
| «Authentication refused (401)» | Wrong API key/token. The Plex token changes if you sign out of all devices. |
| Movies in Radarr are not linked to their files | The path mapping is missing. See the suggestions under Settings → Libraries and paths. |
| Many titles «never watched» that you know were watched | The Tautulli history is shorter than you think (see the date on the overview). |
| A movie frees 0 GB | The file is hardlinked from the downloads folder. Select the copy there too, or remove the torrent. |
| Delete buttons say the switch is off | Switch it on under Settings → Deletion. Files on disk also need `:ro` removed. |
| «Delete 0 files» / «mounted read-only» | The folder is mounted `:ro`. Remove `:ro` under Edit on the app. |
| A swap says «Needs help» | Radarr/Sonarr had objections to the file. The old file is untouched. Read the message, and import or remove the download under Activity → Queue in Radarr/Sonarr. |
| Sonarr sync says «Not found: /api/v3/episodefile (404)» | Fixed in 1.1: the app reads the files another way and skips series Sonarr no longer knows. If every series fails, check the Sonarr URL (including any URL base). |
| qBittorrent «refused the username or password» | Check the Web UI user. After several failed attempts qBittorrent bans the IP for a while. |
| Plex refuses to remove entries | Switch on «Allow media deletion» in Plex → Settings → Library. |
| The Update button in TrueNAS is greyed out | TrueNAS has not checked yet (once a day). Run `midclt -t 600 call app.image.op.check_update`. |

Logs: Apps → mediacleanup → Logs. Failed jobs show the full error under Activity (click the row). API documentation: `http://<nas-ip>:30480/api/docs`.

## Development

```
backend/app/
  main.py          FastAPI: API, language and error handling, static web UI
  i18n.py          bilingual messages (English/Norwegian) and number/date formatting
  settings.py      defaults ← settings.json ← environment, library detection, path mapping
  setup.py         first-run checklist and path-mapping suggestions
  db.py            SQLite (WAL), schema, migrations, backup
  jobs.py          one worker thread + scheduler
  sync.py          fetches from the services; each fails independently
  scanner.py       incremental file scan, partial hash
  clients/         radarr/sonarr (arr.py), plex, tautulli, seerr, qbit, truenas (JSON-RPC, read-only)
  analysis/
    linking.py     files → titles, watch history per title/season, protection
    engine.py      duplicates, suggestions, scores, savings without double counting
  views.py         movies/series/users views and «other storage»
  actions.py       deletion through Radarr/Sonarr (plan → token → execute), action log
  fsops.py         shared checks for direct file deletion
  dupes.py         duplicates (on disk or through Radarr/Sonarr)
  downloads.py     the downloads page and deletion there
  releases.py      search for smaller versions through Radarr/Sonarr
  swaps.py         swap: download first, swap afterwards
  quality.py       the Swap quality overview and batch swaps
  torrents.py      qBittorrent: classify torrents, seeding rule (scheduler)
  arrsetup.py      download rules: size limits, profiles, Seerr defaults, seeding (plan → token → execute, backup/restore)
  plexcheck.py     disk vs Plex, delete orphaned folders, remove missing entries from Plex
  posters.py       posters from Plex/Radarr/Sonarr with a local cache
  updates.py       checks GitHub for new releases
frontend/src/      React + TypeScript (Vite), no heavy UI libraries; texts inline as t("English", "Norsk")
deploy/            compose file and icon script for TrueNAS
```

Run locally:

```sh
cd backend && pip install -r requirements-dev.txt
python -m pytest                     # unit tests + end to end against imitated services
SMC_DATA_DIR=./data SMC_MEDIA_ROOT=/path/to/media uvicorn app.main:app --reload
cd ../frontend && npm install && npm run dev   # http://localhost:5173, proxied to :8000
```

The tests start imitations of Radarr, Sonarr, Plex, Tautulli and Seerr, create sparse files on disk (movies, series, hardlinks, identical copies, several versions, a protected library, downloads, files Plex does not know) and check suggestions, scores, protection, hardlink handling, every deletion safeguard, the full swap from download to import, and both languages.

**Languages:** server texts are written as `L("English", "Norsk")` (or `fmt(...)` with parameters) and translated per request; web UI texts as `t("English", "Norsk")`. Both live next to the code that uses them.

## Known limitations

- The search for smaller versions only runs when you ask for it, per title or season, to spare the indexers. For series, only full season packs are considered.
- A swap depends on Radarr/Sonarr being able to import the file. If the import needs manual choices, the swap stops without deleting anything.
- Identical copies are decided by size + partial hash (start, middle, end). This is safe in practice for video files, but it is not a full hash.
- Folders with an unchanged mtime are not stat'ed by the incremental scan. Files changed in place without the folder changing are caught by the weekly full scan.
- Plex labels protect movies and series, not single episodes.
- Titles that are in neither Radarr nor Sonarr cannot be deleted as a whole from the app, except as folders on disk under Plex differences.
- Only qBittorrent is supported as a torrent client for seeding cleanup. Torrents are removed only when they are finished and their content is found in a scanned library.
- Download rules do not sync TRaSH's full custom format set; use Recyclarr or Notifiarr for that.
