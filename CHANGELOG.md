# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `--color auto|always|never`. `always` keeps the highlighting on a pipe
  (`rga-ocr --color always needle . | less -R`).
- `--rga-adapters=LIST`, `+LIST` and `-LIST` change the adapters of one
  run. The flag was accepted before and had no effect, because the search
  passes its own list after it.
- The `tesseract` engine takes the name of a tessdata_fast file as `lang`
  (`frk`, `chi_sim_vert`), next to the BCP 47 tags.
- `rga-ocr setup` starts the adapter once, the way rga does. An install
  the adapter cannot be loaded from shows there, not as searches that
  find nothing.

### Changed

- Tesseract language files come from one fixed commit of tessdata_fast,
  and `setup --apply` checks size and content of each download. A file
  that was cut short is no longer installed.
- pi-heif is not installed on Python 3.15 and on Windows on arm64, where
  it has no wheels. The install no longer fails there; HEIC and HEIF
  images are reported as not read, and read once pi-heif is present.

- Exit status 2 instead of 1 when a search finds nothing in the contents
  and the OCR engine failed on a file. Exit 1 said "no hit" for files that
  were not read. The same holds when `rga` is killed by a signal.
- The status line and the summary say "files read", not "files OCR'd":
  the count takes in PDFs with a text layer and Office files.
- rg's formatting flags (`-o`, `--heading`, `--vimgrep`, `-M` ...) get a
  warning that they change nothing.

### Fixed

- `--json` on a pipe: the name events came after rg's events. They come
  first again, as documented.
- `rga`, `rg` and the adapters went on with the OCR after the search was
  stopped: by SIGTERM or SIGHUP, which also left the scratch directory
  behind, or by the reader of a pipe going away (`| head -1`).
- A file name the output encoding cannot show (a C locale, a redirect on
  Windows, a name that is not UTF-8 on Linux) ended the search with a
  traceback. Such names are printed as they are on disk or with a
  backslash escape; `--json` adds `"path_bytes"` for a name that is not
  UTF-8.
- A copy installed with `pip install --user` found no text in any file:
  the adapter ran with `-I`, which leaves the user site-packages out.
- "Engine not available" named `pip install 'rga-ocr[NAME]'` under pipx,
  uv and Homebrew, where that command does not reach the install. It
  names the command for the install at hand. The hint for missing
  Tesseract language files carries `--engine` and `--lang`, without
  which `setup --apply` fetched the files of the profile.
- `lang = tl` (Tagalog) with the `tesseract` engine asked for a language
  file that does not exist. It takes `fil.traineddata`.
- `rga-ocr --engine NAME setup` searched for the word "setup" silently. It
  still does, and now says how to call the setup command.

## [0.2.4] - 2026-11-19

### Fixed

- `--rga-cache-path`, `--rga-accurate` (next to `--accurate`) and
  `--rga-no-cache` ended in an rga error, because the search sets these
  flags itself. `--rga-accurate` and `--rga-no-cache` now mean `--accurate`
  and `--no-cache`. `--rga-cache-path DIR` takes the place of `cache_dir`
  for that run, with a directory per engine and language below it.
- `-r` with a regex that ripgrep reads and Python does not (`\p{Lu}`)
  stopped the search. The contents are searched now; a warning says that
  file names are not. With `--names-only` it is still an error.

## [0.2.3] - 2026-11-19

### Fixed

- PDF text layer: the words of a line come out in the order they are
  printed. Lines set in more than one font or size (a bold word, a
  superscript) were shuffled and words were split at kerning pairs, so a
  phrase search could miss text that is in the file. The text now follows
  PDFium's reading order.
- A file the OCR engine failed on (a model download without network,
  missing language data, an engine that does not start) is no longer cached
  as empty and skipped from then on. It is read again on the next search,
  and the warning says so. When such a file sits inside an archive, the
  archives below the search root are read again.
- A PDF with a page that cannot be OCR'd keeps the text of its other
  pages; a warning gives their number and the first of them, once. When no page can
  be OCR'd, the file counts as an engine failure and is read again on the
  next search.
- xlsx, pptx, ods, odp: a word split over several text runs stays one word
  ("Kesselanlage", not "Kessel anlage"), and the numeric cells of a row
  are separated ("12 34", not "1234").
- Images with transparency are placed on white before OCR. Dark text on a
  transparent background was read as black on black and gave no text.
- An rga config with `#` comments, which rga accepts, is read. Before,
  every search ended in `Unknown adapter: "ocrpdf"` unless
  `rga-ocr setup --apply` had been run.
- README: the quick start named `rga-ocr[vision]` for every platform; that
  extra installs an engine on macOS only.

### Changed

- The cache versions of the three adapters went up, because their output
  changed. Cached text from earlier releases is not used any more: the
  first search over a folder after the upgrade reads and OCRs its files
  again. `rga-ocr --clear-cache all` removes the old entries.
- A warning says so when rga's config cannot be read and the search runs
  without this installation's adapter entries.

## [0.2.2] - 2026-11-19

### Added

- A search works without `rga-ocr setup --apply`. Where rga's config lacks
  the three adapter entries of this installation, or holds other ones,
  `rga-ocr` passes rga a copy of the config with the entries put in, for
  that run only. rga's own file is not touched. `setup --apply` remains
  for the Tesseract language files, for plain `rga`, and for searches that
  name a config with `--rga-config-file`.

### Changed

- `rga-ocr setup` no longer counts the unwritten rga config as something
  to do, unless `--rga-config-file` names the file.

- The README names Homebrew as the first way to install on macOS:
  `brew install luca-rui/tap/rga-ocr`.

## [0.2.1] - 2026-11-18

### Fixed

- `setup --apply` inside a Homebrew formula wrote the versioned `Cellar`
  path of the interpreter into rga's config, which is gone after `brew
  upgrade`. It now writes the path through Homebrew's `opt` link.
- The install and uninstall hints of `setup` know a Homebrew install:
  `brew uninstall rga-ocr` instead of a `pip` line, and for another engine
  one line that swaps the formula for the PyPI install.

## [0.2.0] - 2026-11-18

### Added

- `--replace TEXT` is passed to rg when `--json` is given: the events
  carry the replacement.
- `--rga-cache-path DIR` and the other `--rga-` value flags work with a
  separate value; `rga-ocr` hands them to rga in the `=` form rga needs.
- `rga-ocr setup --remove` takes the three adapters out of rga's config,
  with the same backup copy as `--apply`, and prints the commands that
  delete the cache, the profile, the Tesseract language files and the
  package. It runs none of them. The cache command is `rga-ocr
  --clear-cache all`, which deletes cache directories only, whatever
  `cache_dir` points at.
- `rga-ocr setup` prints the ripgrep-all release it found and warns when
  it is older than the tested one (0.10.10, on Windows 0.10.9).
- In an environment made by `uv tool install`, the install hints read
  `uv tool install --force "rga-ocr[...]"`.

### Changed

- `--no-ocr` reads the PDF text layer through the `ocrpdf` adapter
  (pypdfium2), the same code the default mode uses for pages that have
  one. `pdftotext` and poppler are no longer used, checked by
  `rga-ocr setup` or named in the install hints.
- In `--no-ocr` mode a phrase wrapped across two lines of a paragraph now
  matches, as it does in the default mode.
- `--no-ocr` wins when `--force-ocr` is given too.
- The status line of a `--no-ocr` run counts "files read" instead of
  "files OCR'd".
- The `none` cache is filled again on the first `--no-ocr` run; entries
  written by the `poppler` adapter are no longer read
  (`rga-ocr --clear-cache none` removes them).
- Dependency floors raised to what works: `pillow>=10.1` (`pi-heif` 0.22
  needs it, `pillow` 10.0 could not be installed next to it) and
  `onnxruntime>=1.19` (older releases do not import with NumPy 2). CI
  now runs one leg with the core, `rapidocr` and test dependencies at
  their floor.
- The `winrt` floors read `>=2.0.1`: there is no final 2.0.0 release.
- `--replace` without `--json` is refused with exit 2: the text output
  prints the matched line as it is, so the replacement was dropped
  without a word.
- A bundle of short flags that holds `-r` or an output-format flag
  (`-ir`, `-rX`, `-il`) is refused with exit 2. It used to reach rg,
  where `-r` means replace.
- `--generate` is refused like rg's other output-replacing flags.
- `rga-ocr --engines` exits 1 when the configured engine does not work
  here, and with `engine = auto` when no engine does. It used to exit 0
  always.
- Profile: a `#` starts a comment only at the start of a line or after a
  blank, so a value such as `exclude = build#2` keeps its `#`. A comment
  that follows a value without a blank (`engine = vision#note`) is now
  part of the value.
- `lang` takes tags separated by commas or blanks (`de-DE en-US`).
- The profile written by `--init-config` carries `cache_dir` as a comment,
  so the platform default stays in charge until you set one.
- winocr names its cache after the language pack that does the work, not
  after the languages asked for: `lang = de, en` with only `en-US`
  installed is cached as `winocr-en-US`. A winocr cache that 0.1.x wrote
  under another name, for example `winocr-de_en`, is not read any more.
  `rga-ocr --cache-info` lists the directories and `rga-ocr --clear-cache
  <name>` removes one.
- An engine plugin whose name holds anything but `a-z`, `0-9` and `_` is
  ignored with a warning; its cache directory name could not be read back.
- `rga-ocr setup` checks that `rga-preproc` is on PATH and exits 1 when
  it is missing. rga starts it for every file.
- `rga-ocr --rga-config-file= setup` with an empty path exits 2. It used
  to fall back to rga's default config, which `--apply` then rewrote.
- On Windows the pip command in the install hints starts with the bare
  interpreter path, or with `&` when the path needs quotes, so it runs in
  PowerShell.

### Removed

- The hints for leftovers from the time the tool was called `rga-vision`
  are gone: the warnings about `RGA_VISION_` variables and the old
  profile, the "leftovers from rga-vision" section of `rga-ocr setup`,
  and the removal of the `visionpdf` and `visionimg` entries from rga's
  config. Such entries now stay like any other custom adapter.

### Fixed

- `--no-ocr` no longer misses PDFs silently. It used rga's `poppler`
  adapter, which runs whatever `pdftotext` is first on PATH. On Windows
  that can be the xpdf build that Git for Windows ships: it rejects the
  arguments, rga skips the file, and the search reports no hit.
- rg flags with a separate value that `rga-ocr` did not know (`-e`,
  `--regexp`, `--type-add`, `--type-clear`, `--ignore-file`, `--maxdepth`,
  `--hostname-bin`, `--hyperlink-format`, the separator flags) no longer lose their value to the QUERY or DIR
  argument.
- rg's output-format flags are refused in their `--flag=VALUE` form too.
- An `RGA_OCR_` variable that is no setting gets a warning instead of
  silence, from searches and from `setup`.
- Blanks around an engine name (`RGA_OCR_ENGINE="vision "`) are dropped;
  `--engines` accepted such a name and the search refused it.
- `rga-ocr setup` no longer removes a `,` before `}` or `]` inside a
  string of rga's config.
- Two config backups written in the same second no longer share a file
  name.

## [0.1.1] - 2026-11-18

### Added

- `rga-ocr` is on PyPI: `pipx install "rga-ocr[vision]"`. The README and the
  install hints of `rga-ocr setup` use the PyPI name instead of the git URL.
- The sdist carries the test suite and the fixture builder, so
  `python -m pytest` works from an unpacked source archive.
- A release workflow that publishes to PyPI through trusted publishing.
- CI checks the declared licence of every dependency, extras included,
  against an allow-list without GPL or AGPL.

### Changed

- The quick start names the Python 3.15 workaround (`--python python3.14`).
- The `rga_ocr.engines` entry-point hook stays in the code but is
  experimental and no longer advertised: the engine protocol is not a
  stable interface yet.

## [0.1.0] - 2026-11-18

First public release.

### Added

- macOS, Linux and Windows. OCR engines behind one protocol: `vision`
  (Apple Vision), `winocr` (Windows.Media.Ocr), `rapidocr` (PP-OCR models
  on ONNX Runtime, any platform; per-script models for Cyrillic, Arabic,
  Devanagari, Korean, Thai, Greek, Tamil, Telugu and Georgian), `tesseract`
  (tesserocr); `--engine`, the `engine` profile key and `RGA_OCR_ENGINE`;
  `--engines` lists what works on the machine and what `auto` picks;
  third-party engines via the `rga_ocr.engines` entry-point group.
- `rga-ocr setup [--apply] [--engine NAME] [--lang L] [--config PATH]`:
  checks tools and engine, prints install commands per package manager,
  fetches Tesseract language files, merges the adapter entries into rga's
  config (first run keeps a `.bak`, later runs a timestamped copy) and
  honours `--rga-config-file=PATH`; exit 0 ready, 1 something to do,
  2 usage error.
- Image decoding through Pillow and pi-heif (HEIC/HEIF) on every platform;
  PDF text layers through pypdfium2 (PDFium), pages without one are
  rendered and OCR'd.
- `rga-ocr` CLI: file-name pass plus a ripgrep-all content pass in one
  command, exit codes 0/1/2.
- ripgrep-all custom adapters `ocrpdf`, `ocrimg`, `officexml`: OCR of PDF
  pages and images through the configured engine; xlsx, pptx, ods, odp
  text extraction.
- Profile file `~/.config/rga-ocr/config` (`%APPDATA%\rga-ocr\config` on
  Windows) with keys `engine`, `lang`, `exclude`, `case`, `name_blank`,
  `name_blank_optional`, `snippet`, `cache_dir`, `adapters_extra`,
  `progress`; `RGA_OCR_<KEY>` environment mirrors; `--init-config`.
- Snippet window around content matches (`--snippet N`, `--full`) with
  `Page N:` and archive-member prefixes kept; grouped, highlighted output on
  a terminal; `--json` pass-through with name events.
- Name-pass blank handling: `nonletter` (default), `separators`, `strict`,
  optional empty run.
- Language auto-detection where the engine supports it, `--lang` to pin
  languages; one OCR cache directory per engine and language setting
  (`<engine>-<lang>[-force]`, `none` for `--no-ocr`).
- Live status line on a terminal while the content pass runs (spinner,
  elapsed time, hits, files OCR'd, current file) and a one-line summary
  after the content pass (`searched 12.4 s · 3 hits · 14 files OCR'd`);
  `--progress` /
  `--no-progress` and the `progress` profile key.
- Adapter errors are reported after the run; rg discards a preprocessor's
  stderr on exit 0, so the adapters write progress and errors to a per-run
  report file (`RGA_OCR_REPORT`).
- `--no-cache` uses a throwaway cache directory per run instead of
  `--rga-no-cache`, which fails on custom adapters in ripgrep-all 0.10.10.
- The `rapidocr` engine sets `ORT_DISABLE_TELEMETRY=1` before ONNX Runtime
  loads, so the telemetry that the official wheels switch on by default
  never starts (it also removed a hang of the adapter process at exit
  inside that telemetry's shutdown). The adapter ends with `os._exit(0)`
  after flushing its output, so native library teardown cannot change its
  exit status or keep ripgrep-all waiting.
- The cache database is created with ripgrep-all's schema before each run
  and held open until ripgrep-all exits, so parallel `rga-preproc`
  processes do not race on creating it or on rebuilding its WAL index
  (`The database file is locked`, file skipped).
- `--cache-info` lists the caches as a table with a stable cache-id (sha1
  of the directory name), engine, language, entries, size, last added date
  and the folders the entries come from; `--clear-cache CACHE-ID|DIR ...|all`
  deletes the named caches or every cache (files under `cache_dir` that are
  not caches stay), lists them first for `all`, and exits 2 without
  arguments; `--dry-run` shows what would go.
- rg's output-format flags (`-l`, `-c`, `--count-matches`,
  `--files-without-match`, `--files`, `-q`) are refused with exit 2 because
  the content pass reads rg's JSON events; usage errors exit 2.
- pytest suite split into end-to-end, adapter and setup tests, runnable
  per engine with `RGA_OCR_ENGINE`; GitHub Actions matrix across macOS,
  Ubuntu and Windows.

[Unreleased]: https://github.com/luca-rui/rga-ocr/compare/v0.2.4...HEAD
[0.2.4]: https://github.com/luca-rui/rga-ocr/compare/v0.2.3...v0.2.4
[0.2.3]: https://github.com/luca-rui/rga-ocr/compare/v0.2.2...v0.2.3
[0.2.2]: https://github.com/luca-rui/rga-ocr/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/luca-rui/rga-ocr/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/luca-rui/rga-ocr/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/luca-rui/rga-ocr/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/luca-rui/rga-ocr/releases/tag/v0.1.0
