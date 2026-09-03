# zlibrary-download

[简体中文](README.md) | [English](README.en.md)

A Windows desktop utility for authorized book search, download, and fuzzy library construction. The application drives an isolated Chrome profile through Selenium, parses search results with BeautifulSoup, persists download history in SQLite, and exposes the workflow through a Tkinter GUI.

> **Scope boundary:** Use this software only for material that you are authorized to access, download, or redistribute. The project does not implement DRM cracking, login bypass, CAPTCHA bypass, access-control bypass, or credential collection. The operator is responsible for verifying copyright, redistribution permission, site terms, and applicable law.

## Capabilities

- **Metadata search:** Search by title or ISBN and display title, author, publisher, year, language, format, and the size advertised by the source.
- **Single-item download:** Download a selected format to a user-defined directory. Windows-reserved filename characters are sanitized and existing files are not overwritten.
- **Download history:** SQLite records the query, source identifier, detail URL, expected/actual byte counts, timestamps, status, and error text.
- **Fuzzy library builder:** Filter by topic, additional keywords, a 0–100 match threshold, preferred format, maximum search pages, and a target capacity.
- **Task control:** Pause, resume, and stop batch jobs. A pause or stop takes effect at the current file boundary or another safe checkpoint.
- **Request throttling:** Serial processing with a default three-second request interval, a 512 MiB free-space reserve, and explicit handling for timeouts, source limits, and insufficient disk space.
- **Automatic source discovery:** At startup, the application checks the repository-maintained public source registry at most once every six hours. A new source is filled in and persisted only after HTTPS and hostname validation; trusted site redirects are also recognized.
- **Browser compatibility policy:** Chrome first runs in native `--headless=new` mode without a desktop window. If the source explicitly rejects that mode, the application automatically retries with a hidden regular Chrome instance. Windows startup state, off-screen placement, and Win32 window hiding keep the compatibility window off both the desktop and taskbar. The mode can also be fixed to **Fully headless** or **Compatibility** in settings. Both modes use `%LOCALAPPDATA%\AuthorizedBookBuilder\chrome-profile\` instead of the user's personal Chrome profile.
- **UI and packaging:** Blue/white technical UI with a Furina-themed header accent. The EXE uses `assets/app_icon.ico`, a Hydro droplet and open-book icon.

## Matching and capacity algorithm

Fuzzy matching is implemented in `bookbuilder/utils.py`. Title sequence similarity, query-token hits, containment in title/author/publisher, and optional keyword hits produce a score from 0 to 100. The builder scans pages serially, pre-filters using the source-reported size, and keeps an additional per-file guard of `max(1 MiB, 2%)`; final accounting uses the actual downloaded size.

## Requirements

- Windows 10/11 x64 (validated on Windows 11)
- Google Chrome (current stable channel)
- Python 3.14.7 (validation version for this repository)
- PyInstaller 6.22.2 for packaging only

## Install and run

```powershell
git clone https://github.com/yifanchen12/zlibrary-download.git
Set-Location .\zlibrary-download

python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

Run the test suite:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Build the Windows EXE

The build script installs build dependencies, runs the tests, invokes PyInstaller, and performs a `--smoke-test` launch:

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

Output:

```text
dist\BookLibraryBuilder.exe
```

The build embeds `assets/` and the ChromeDriver discovered at build time. Google Chrome must still be installed on the target machine. If the Chrome major version changes, Selenium Manager attempts to resolve a compatible driver.

## Operational workflow

1. In **Settings & authorization**, confirm the source URL, download directory, request interval, and authorization acknowledgement.
2. In **Search & download**, enter a title or ISBN, search, and select an item.
3. Start a download. The application checks free space, creates a `downloading` history row, and changes it to `completed` or `failed`.
4. For batch construction, configure the topic, keywords, threshold, format, page limit, and capacity in **Fuzzy library**.

For an approximately 50 GB PDF collection on artificial intelligence, start with topic `人工智能`, additional keywords `教材, 导论, 基础, undergraduate, textbook`, threshold `55`, format `PDF`, and capacity `50`. Begin with a small page limit, review the results, and increase it incrementally.

## Local data paths

```text
%LOCALAPPDATA%\AuthorizedBookBuilder\settings.json
%LOCALAPPDATA%\AuthorizedBookBuilder\history.sqlite3
%LOCALAPPDATA%\AuthorizedBookBuilder\chrome-profile\
```

The settings file stores the source URL, automatic-check state, last-check time, directories, timeouts, and authorization acknowledgement. The history database stores the metadata and local paths described above. The application has no built-in telemetry, advertising SDK, or remote analytics service.

## Troubleshooting

### Legacy source migration

The default source is now `https://z-library.biz`. Starting with `v1.2.2`, the application automatically migrates the former default `https://z-library.bz` when loading existing settings. Other user-configured source URLs remain unchanged.

Starting with `v1.3.0`, the application also reads [`source_registry.json`](source_registry.json) from the repository in the background, at most once every six hours. A detected value is persisted only after manifest, HTTPS, hostname, and port validation. Automatic checks can be disabled, and **Check for a new source now** can be used from the settings page. Custom source URLs are never replaced by the remote registry.

Starting with `v1.3.1`, a search entry such as `https://z-library.biz/s/` is normalized to the source origin, preventing a duplicated `/s/` path.

### “Source access check failed”

Some sources reject Chrome's fully headless mode. The default **Automatic compatibility** policy first tries the windowless mode, then closes that session and retries with a hidden regular Chrome instance when this rejection is detected. The parser also supports the source's newer `z-bookcard` search-result structure. `v1.3.2` additionally hides the compatibility window from the taskbar.

If the check still fails, use **Settings & authorization** to:

1. Confirm that the source is `https://z-library.biz` or `https://z-library.biz/s/`, then save and retry.
2. Select **Compatibility (hidden Chrome)** explicitly.
3. Confirm that regular Chrome can reach the source on the current network and wait for any temporary source throttling to clear.

Compatibility mode still creates the regular-browser context required by the source, but moves it off-screen and hides it through the Windows API. It is not shown on the desktop or taskbar and does not read the personal Chrome profile.

### `ERR_CONNECTION_TIMED_OUT`

This error means that Chrome and ChromeDriver started successfully, but the background browser could not connect to the configured source. It does not indicate a driver-version mismatch. Check the following in order:

1. Open the source configured under **Settings and authorization** in a regular browser.
2. Verify the system network, DNS, proxy, and VPN state.
3. If regular Chrome relies on a proxy or VPN extension, note that this application uses an isolated Chrome profile and does not inherit personal browser extensions. Use a system proxy or a directly connected network instead.
4. Confirm that the source is still the valid HTTPS entry supplied by its administrator, save the corrected setting, and retry.

Common Chrome network failures now produce a concise diagnostic instead of placing the native ChromeDriver stack trace in the dialog or status bar. When opening an issue, include the application version, error code, and source hostname, but do not upload cookies, tokens, complete query URLs, or personal paths.

## Security and privacy statement

1. **Data flow:** Search terms, detail-page requests, and downloads are sent to the configured source. When automatic source discovery is enabled, the application retrieves the public `source_registry.json` from `raw.githubusercontent.com/yifanchen12/zlibrary-download` at most once every six hours. This request contains no query terms, download history, cookies, tokens, or local paths.
2. **Browser session data:** The isolated Chrome profile may contain cookies, cache, or site storage if the user signs in. Treat this directory as sensitive and never commit or share it.
3. **Credentials:** The application does not request passwords, API tokens, or private keys. Never place credentials, cookies, token-bearing URLs, or personal filesystem paths in the repository, logs, or issue reports.
4. **Downloaded files:** Files from external sources are untrusted input. Scan them with local security software before opening; do not execute scripts, macros, or binaries found in an ebook archive.
5. **Transport:** HTTPS is the default source scheme. If the source URL is changed, independently verify the domain, certificate, and ownership; the application does not establish source trust for the operator.
6. **Filesystem behavior:** Writes are limited to the selected download directory and the application-data directory above. Existing files are not overwritten or deleted during the normal flow.
7. **Release integrity:** After downloading an EXE from a GitHub Release, verify it with `Get-FileHash .\BookLibraryBuilder.exe -Algorithm SHA256` against the release digest.

See [`SECURITY.md`](SECURITY.md) for vulnerability reporting and operational security requirements.

## Repository layout

```text
main.py                 CLI entry point, version, and smoke test
bookbuilder/browser.py  Chrome lifecycle, parsing, and download wait logic
bookbuilder/services.py Download service and fuzzy-builder scheduler
bookbuilder/database.py SQLite history persistence
bookbuilder/config.py   Settings and local data paths
bookbuilder/source_discovery.py Remote-registry validation and trusted redirect detection
bookbuilder/gui.py      Tkinter interface
bookbuilder/models.py   Data models
bookbuilder/utils.py    Filename, size, and matching helpers
assets/                 EXE icon and header artwork
tests/                  Unit tests and HTML fixtures
source_registry.json    Repository-maintained current source registry
```

## Version and release

- Current version: `1.3.2`
- Windows package: [BookLibraryBuilder.exe v1.3.2](https://github.com/yifanchen12/zlibrary-download/releases/tag/v1.3.2)
- Default branch: `main`

This repository does not include a general open-source license file. Unless separately authorized in writing, use of the source and assets is subject to the repository owner’s permission. Third-party book content is outside the project’s license scope.
