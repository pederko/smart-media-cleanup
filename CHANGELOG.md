# Changelog

## 1.1.1
- **Fixed:** stopping remuxes in a profile where a remux shared a group with one other quality (e.g. an anime «Remux-1080p» group with Bluray-1080p) failed with «Groups must contain multiple qualities». The remaining quality is now kept as a plain quality, and the upgrade cutoff follows it.

## 1.1.0
**Download rules** – stop the problem at the source, not only clean up afterwards.

- New page *Prevent → Download rules* that reads how Radarr, Sonarr, Seerr and qBittorrent are set up today and compares it with [TRaSH Guides](https://trash-guides.info):
  - **Size limits** per quality, shown in GB per movie/episode instead of MB per minute. Presets: *Balanced* (recommended: TRaSH's minimums with a ceiling and a moderate preferred size), *Space saver* and *TRaSH Guides* (no ceiling). Edit any value; the page shows live how many existing files are above the new limits.
  - **Quality profiles**: allowed qualities, upgrade cutoff, scored custom formats, how many titles use each profile and how much space they take. Flags profiles that allow remuxes, BR-DISK/Raw-HD or score size-heavy custom formats (TrueHD/Atmos/DTS…), and fixes just that – everything else in your profile is left as it is.
  - **Recommended profiles** (HD Bluray + WEB, WEB-1080p, UHD Bluray + WEB; WEB-1080p/WEB-2160p for Sonarr) can be created with the custom formats, scores and language copied from one of your own profiles.
  - **Seerr**: which profile new requests get, per server – and change it.
  - **Seeding**: switch on «Remove completed» in Radarr/Sonarr, set a seeding limit in qBittorrent (ratio/time → stop), and remove finished torrents whose content is already in a library, with their downloaded files. Torrents that are not imported are never removed.
- Every change is reviewed in one summary and confirmed once. The app re-reads the services before applying and refuses if anything changed, saves a backup of every setting it changes (*Download rules → Backups*, one click to restore) and logs each change.
- **qBittorrent** is a new optional connection (URL, username, password; also `SMC_QBITTORRENT_*`).
- **Fixed:** the Sonarr sync stopped with «Endpoint not found: /api/v3/episodefile (404)» when Sonarr answered 404 for a series. The app now falls back to reading the files through the episode list, skips series Sonarr no longer knows (and says which), and shows the service's own explanation in error messages.

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
