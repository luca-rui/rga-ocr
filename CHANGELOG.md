# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `--replace TEXT` is passed to rg when `--json` is given: the events
  carry the replacement.
- `--rga-cache-path DIR` and the other `--rga-` value flags work with a
  separate value; `rga-ocr` hands them to rga in the `=` form rga needs.

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

[Unreleased]: https://github.com/luca-rui/rga-ocr/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/luca-rui/rga-ocr/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/luca-rui/rga-ocr/releases/tag/v0.1.0
