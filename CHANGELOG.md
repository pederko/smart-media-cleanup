# Changelog

## 1.0.0
The first complete release: everything from the 0.x series pulled together into one consistent app.

- **English and Norwegian.** The whole web UI, and every message from the server, is available in English and Norwegian Bokmål. Choose in the menu (EN/NO); the default follows the browser. Error messages, suggestion explanations and the CSV export follow the same language.
- **New structure.** The menu is grouped into *Library* (Movies, Series, Users, Largest files), *Free up space* (Suggestions, Swap quality, Duplicates, Downloads, Plex differences, Other storage) and *System* (Activity, Settings). Jobs, swaps and the deletion log are combined under **Activity**. The separate «Titles» page is gone – Movies and Series cover it.
- **Overview answers «how much, and where?»** The headline shows what is *recommended* to free (priority ≥ 50 and not high risk), with the total of all suggestions beside it. Below it, one card per area – delete titles, swap quality, duplicates, downloads, Plex differences and other storage – each linking to its page.
- **Suggestions** open on «Recommended», with «All» one click away. Each row links to the right place to act (delete, swap quality, duplicates, downloads).
- **Getting started checklist** on the overview until the libraries, services, path mappings and the first refresh are in place.
- **Libraries are detected automatically** from the folders mounted under `/media`, including the TrueNAS path behind each bind mount. No personal paths are built in any more. Existing settings are kept as they are.
- **Path mapping suggestions**: the app reads the root folders of Radarr/Sonarr and the Plex library locations and suggests mappings by folder name – one click to use.
- **Settings** in sections you can link to (`#/settings/deletion` and so on), libraries can be added, removed and re-detected, and the deletion section shows write access per folder.
- Consistent page layout, filter chips that wrap cleanly, a selection bar at the bottom on every page that can delete, side panels for every confirmation, and a menu button on small screens.
- The code, comments, tests and documentation are in English. Stored status values (swaps, the action log) are migrated automatically; derived analysis results are rebuilt at the first start after the upgrade.

## Earlier versions (summary)

- **0.13** – *Swap quality* page: large movies and seasons, search the indexers for many at once, and swap several with one confirmation.
- **0.12** – «Other» in the capacity bar opens an overview of datasets and snapshots outside the libraries (read only).
- **0.11** – Remove Plex entries whose files are missing; delete folders that are on disk only; «Find smaller» from Largest files.
- **0.10** – Swap to a smaller version: download first, swap afterwards, with optional unmonitor or quality profile change.
- **0.9** – Plex differences: on disk but not in Plex (with the likely reason), and in Plex but missing on disk; ask Plex to scan a folder.
- **0.8** – Downloads page, clickable libraries in the capacity bar, search for smaller versions through Radarr/Sonarr.
- **0.7** – Duplicates page with filters and deletion (files Radarr/Sonarr know are deleted through them, followed by a rescan); protection can be limited to whole titles.
- **0.6** – Movies, Series and per-user (Seerr) pages with summaries and filters; delete from those pages.
- **0.5** – Deletion through Radarr and Sonarr (whole movies, series and single seasons), summary first, log of every action.
- **0.4** – Posters from Plex, with Radarr/Sonarr as fallback, cached locally.
- **0.3** – Update notice in the app; the compose file uses `:latest` so TrueNAS can update with its Update button.
- **0.2** – Seerr requests, published images on ghcr.io, app icon and Web UI button; fixed «database is locked» during large scans.
- **0.1** – First read-only version: scanning, linking to Radarr/Sonarr/Plex/Tautulli, explainable suggestions, duplicates and savings without double counting.
