# rga-ocr

Search everything beneath a path for a string: file and directory names,
plain text, Office documents, archives, PDFs, and photos or scans of text
that have no text layer. Runs on macOS, Linux and Windows; the OCR engine
is a swappable part (Apple Vision, Windows OCR, RapidOCR, Tesseract).

```
rga-ocr "maintenance contract" ~/Documents
```

```
# names
./Offers/Maintenance_Contract_2026.pdf
./Scans/maintenance contract boiler

# contents
./Scans/IMG_4711.heic
1:…ding to the attached maintenance contract for the boiler plant, the inspection inter…

./Offers/Maintenance_Contract_2026.pdf
7:Page 2: …sfer. This maintenance contract runs until 31 December 2027 and renews automati…
```

`rga-ocr` composes two tools:

- a walk over file and directory names, matching the last path segment
- [ripgrep-all](https://github.com/phiresky/ripgrep-all) (`rga`) for
  contents, extended with three custom adapters: `ocrpdf`, `ocrimg`,
  `officexml`. The first two run the OCR engine.

Everything rga already handles stays available: docx, odt, epub and
friends via pandoc, zip/tar/gz/xz/bz2/zst archives, sqlite, optionally
mail and ffmpeg metadata. OCR results are cached, so the second search of a
folder takes a fraction of a second.

Quick start, once `rga`, `rg` and `pandoc` are installed (see Install):

```
pipx install "rga-ocr[vision]"   # or [winocr], [rapidocr], [tesseract]
rga-ocr setup --apply
rga-ocr "maintenance contract" ~/Documents
```

pi-heif ships no wheels for Python 3.15 yet. Where `python3` is 3.15, add
`--python python3.14` (any of 3.11 to 3.14) to the `pipx install` line.

## Platforms and engines

| platform | engines (in the order `auto` tries them) | tested in CI |
|----------|-------------------------------------------|--------------|
| macOS 13+ | `vision`, `rapidocr`, `tesseract` | vision, tesseract |
| Linux | `rapidocr`, `tesseract` | rapidocr, tesseract |
| Windows 10+ | `winocr`, `rapidocr`, `tesseract` | rapidocr, winocr |

| engine | what it is | needs | languages |
|--------|------------|-------|-----------|
| `vision` | Apple Vision through PyObjC | `rga-ocr[vision]` | auto-detected; `lang` pins a list of BCP 47 tags |
| `winocr` | Windows.Media.Ocr through PyWinRT | `rga-ocr[winocr]` and an OCR language pack (`Add-WindowsCapability -Online -Name "Language.OCR~~~de-DE~0.0.1.0"`, as administrator) | one language per run: the first of `lang` with a pack installed, else the user's profile languages |
| `rapidocr` | PaddleOCR models on ONNX Runtime, pure pip | `rga-ocr[rapidocr]` | the bundled multilingual model covers Latin script, Chinese and Japanese with nothing to download; `lang` with a Cyrillic, Arabic, Devanagari, Korean, Thai, Greek, Tamil, Telugu or Georgian tag switches to that script's model (fetched on first use); one script per run |
| `tesseract` | Tesseract 5 through tesserocr wheels | `rga-ocr[tesseract]` and the `.traineddata` files for `lang` (`rga-ocr setup --apply` fetches them from tessdata_fast) | any combination with language files, default `eng` |

`rga-ocr --engines` shows which engines work on this machine, why one
does not, and which `auto` picks. `--engine NAME`, the profile key
`engine`, or `RGA_OCR_ENGINE` choose one explicitly. Results are cached
per engine and language, so switching engines never serves stale text.

## Install

1. Install the tools. `rga-ocr setup` prints the command for your package
   manager; in short:

   | | |
   |-|-|
   | macOS | `brew install ripgrep ripgrep-all pandoc poppler` |
   | Debian/Ubuntu | `sudo apt-get install ripgrep pandoc poppler-utils` plus `rga` and `rga-preproc` from the [v0.10.10 release archive](https://github.com/phiresky/ripgrep-all/releases/tag/v0.10.10) on PATH |
   | Arch | `sudo pacman -S ripgrep ripgrep-all pandoc-cli poppler` |
   | Windows | `scoop install rga` (pulls ripgrep, pandoc, poppler, ffmpeg) or `choco install ripgrep-all ripgrep pandoc` |

   poppler's `pdftotext` serves `--no-ocr` and is optional.

2. Install `rga-ocr` with the engine extra you want, with
   [pipx](https://pipx.pypa.io) or in a venv. Python 3.11 to 3.14 (pi-heif
   ships no wheels for 3.15 yet; `pipx install --python python3.14 ...`
   picks an interpreter).

   ```
   pipx install "rga-ocr[rapidocr]"
   ```

   macOS: `rga-ocr[vision]`; Windows: `rga-ocr[winocr]`; several extras
   work too: `rga-ocr[vision,tesseract]`.

3. Wire the adapters into rga and check everything:

   ```
   rga-ocr setup            # dry run: what is missing, what --apply would write
   rga-ocr setup --apply
   ```

   `setup --apply` fetches Tesseract language files for the configured
   `lang`, initialises RapidOCR once, merges the three adapter entries into
   rga's `config.jsonc` (the first run keeps a `.bak` copy, later runs a
   timestamped one; comments in that file are not preserved; other custom
   adapters stay) and checks that `rga --rga-list-adapters` lists them.
   Package installs stay commands for you to run. Re-run it after moving
   the installation, because the entries point at the interpreter that
   runs `rga-ocr`.

   `setup --engine NAME`, `--lang L` and `--config PATH` check another
   engine, language list or profile than the configured one;
   `--rga-config-file=PATH` before `setup` targets another rga config.
   Exit status: 0 ready, 1 something to do, 2 usage error.

`rga-ocr --init-config` writes a commented profile.

### Upgrading

```
pipx upgrade rga-ocr        # or pip install -U in the venv
rga-ocr setup --apply       # refreshes the adapter entries when their version changed
```

The cache key is the file plus the adapter `version`. The engine package
version and the tuning variables below are not part of it, so after
upgrading an engine package or changing a tuning variable, clear the
affected cache (`rga-ocr --cache-info`, `rga-ocr --clear-cache ...`) to
get fresh text.

### Uninstalling

```
pipx uninstall rga-ocr
```

Then remove the three `custom_adapters` entries (`ocrpdf`, `ocrimg`,
`officexml`) from rga's `config.jsonc`, and delete the cache, profile and
Tesseract language directories; the paths are in the table under
"Profile and paths".

## Usage

```
rga-ocr [options] QUERY [PATH]        PATH defaults to .
rga-ocr [--rga-config-file=F] setup [--apply] [--engine NAME] [--lang L] [--config PATH]
rga-ocr --version | -h | --help

  -s / -i                case-sensitive / case-insensitive (default -i)
  -r                     QUERY is a regex (default literal)
  --snippet N            characters shown around a content match (default 80)
  --full                 whole lines, same as --snippet 0
  --name-blank MODE      nonletter | separators | strict (what a blank may match in names)
  --name-blank-optional  the run a blank matches may be empty
  --engine NAME          OCR engine: auto, vision, winocr, rapidocr, tesseract (default auto)
  --engines              list the engines, whether each works here, and what auto picks; exit
  --lang L               OCR languages, e.g. de-DE,en-US (default: the engine decides)
  --no-ocr               PDFs via poppler text layer only, images skipped
  --force-ocr            OCR every PDF page even if it has a text layer
  --mail                 also search .eml/.mbox
  --accurate             sniff mime types instead of trusting extensions
  --exclude LIST         directory names to skip (replaces the default list)
  --no-exclude           skip nothing
  --names-only / --no-names
  --json                 rg JSON events; name hits first as {"type":"name","path":...}
  --no-cache             do not read or write the OCR cache
  --progress / --no-progress   status line while searching and a summary after (default on)
  --init-config          write a commented profile and exit
  --cache-info           list the caches and exit
  --clear-cache CACHE-ID|DIR ...|all   delete the named caches, or every cache, and exit
  --dry-run              with --clear-cache: show what would be removed, delete nothing
  --config PATH          use this profile file (env RGA_OCR_CONFIG)
```

Anything else is passed to `rga`/`rg`: `-g '!*.log'`, `-t pdf`, `-C 2`,
`-U`, `-j 4`, `-M 300`, `--rga-config-file=...`. rg's output-format flags
(`-l`, `-c`, `--count-matches`, `--files-without-match`, `--files`, `-q`)
are refused with exit 2: the content pass reads rg's JSON events, which
those flags replace. Use `--json` and filter the events instead.

Exit status: 0 at least one hit, 1 no hit, 2 failure.

Examples:

```
rga-ocr -s "ACME GmbH" .                        # case-sensitive
rga-ocr -r 'invoice\s+\d{4}' ~/Scans            # regex, both passes
rga-ocr --lang de-DE,en-US "Kesselanlage" ~/Docs
rga-ocr --engine tesseract --lang de "Kesselanlage" ~/Docs
rga-ocr --json needle DIR | jq -r '.data.path.text // .path' | sort -u
```

### Output

On a terminal, hits are grouped per file with the match highlighted, name
hits first under `# names`. Piped, every hit is one line:
`path:line:text`. PDF pages and slides carry a `Page N:` prefix, archive
members a `member.ext:` prefix.

Content matches are shown as a **snippet window**: up to 80 characters on
each side of the match, with the prefixes kept and `…` marking cut text.
`--snippet N` changes the width, `--full` prints whole lines. `--json`
always carries whole lines.

While the content pass runs on a terminal, a **status line** on stderr
shows that the search is alive:

```
⠹ searching 12 s · 3 hits · 14 files OCR'd · Scans/IMG_4711.heic
```

Hits keep appearing above it as they are found. The file count is the
number of PDFs, images and Office files the adapters have finished in this
run; cached files are not counted, because they cost nothing. The line is
cleared before every hit, and when the content pass ends it is replaced by
a summary:

```
searched 12.4 s · 3 hits · 14 files OCR'd
```

Both go to stderr and are only shown when stdout and stderr are a
terminal and `--json` is not given, so scripts never see it.
`--no-progress` or `progress = false` in the profile switch it off. On a
console that is not UTF-8 the spinner and separators fall back to ASCII.
There is no percentage: rg reports nothing per file, and the cache hides
how much OCR work is left.

### Names

The name pass matches the last path segment of files and directories, so
`rga-ocr contract` finds a directory called `Contracts` and everything
whose own name contains the word, but not every file beneath that
directory. A blank in the query matches a run of non-letter characters by
default, so `rga-ocr "maintenance contract"` finds
`Maintenance_Contract_2026.pdf` and `maintenance-contract.docx`. The
`name_blank` setting (`nonletter`, `separators`, `strict`) and
`name_blank_optional` (the run may be empty, so `boiler plant` also finds
`boilerplant`) adjust this.

Hidden files and files ignored by `.gitignore` are always searched.
`.git`, `node_modules`, `.venv` and `__pycache__` directories are skipped
in both passes unless you change `exclude` or pass `--no-exclude`.

## Profile and paths

| | macOS | Linux | Windows |
|-|-------|-------|---------|
| profile | `~/.config/rga-ocr/config` (`$XDG_CONFIG_HOME`) | `~/.config/rga-ocr/config` (`$XDG_CONFIG_HOME`) | `%APPDATA%\rga-ocr\config` |
| OCR cache (`cache_dir`) | `~/Library/Caches/rga-ocr` | `~/.cache/rga-ocr` | `%LOCALAPPDATA%\rga-ocr\Cache` |
| Tesseract language files | `~/Library/Application Support/rga-ocr/tessdata` | `~/.local/share/rga-ocr/tessdata` | `%APPDATA%\rga-ocr\tessdata` |
| rga config (written by `setup`) | `~/Library/Application Support/ripgrep-all/config.jsonc` | `~/.config/ripgrep-all/config.jsonc` | `%APPDATA%\ripgrep-all\config\config.jsonc` |

`rga-ocr --init-config` writes a commented profile with these keys
(comments abridged here):

```
# auto | vision | winocr | rapidocr | tesseract
engine = auto
# OCR languages, comma separated BCP 47 tags. Empty: the engine's default.
lang =
# Directory names skipped in both passes (replaces the default list).
exclude = .git, node_modules, .venv, __pycache__
# insensitive | sensitive
case = insensitive
# nonletter | separators | strict
name_blank = nonletter
name_blank_optional = false
# characters on each side of a content match, 0 = whole lines
snippet = 80
cache_dir = <platform default, see above>
# extra rga adapters, e.g. mail,ffmpeg
adapters_extra =
# live status line on a terminal
progress = true
```

Every key can also be set as an environment variable, `RGA_OCR_<KEY>`
in upper case (`RGA_OCR_LANG=de-DE,en-US`). Precedence: built-in
default, then the profile, then the environment, then the flag. Unknown
keys produce a warning and are ignored.

Tuning values that rarely need changing are environment-only:

| variable                   | default | meaning |
|----------------------------|---------|---------|
| `RGA_OCR_MIN_TEXT_CHARS` | 20     | a PDF page with fewer text-layer characters is OCR'd |
| `RGA_OCR_RENDER_DPI`    | 200     | PDF render resolution for OCR |
| `RGA_OCR_MAX_PIXELS`    | 3000    | longest image side handed to the engine |
| `RGA_OCR_PARAGRAPH_GAP` | 0.7     | line gap, in line heights, that starts a new output line |
| `TESSDATA_PREFIX`       |         | directory with `.traineddata` files, checked before the tool's own |

## How the adapters work

`rga` runs `python -I -X utf8 -m rga_ocr.adapter MODE PATH` with the file
on stdin and reads the text from stdout; `PATH` is the virtual path
(archive members included) and is only used for progress reports. The
interpreter is the one `rga-ocr` was installed with, so the adapters see
the same engine packages.

| adapter     | extensions                                    | what it does |
|-------------|-----------------------------------------------|--------------|
| `ocrpdf` | pdf                                           | Text layer per page through pypdfium2 (PDFium), one line per paragraph (wrapped lines joined, de-hyphenated). Pages with fewer than 20 characters are rendered at 200 dpi and OCR'd. Pages are separated by form feed so rga prints `Page N:`. |
| `ocrimg` | jpg jpeg png heic heif tif tiff webp gif bmp  | Pillow decodes (EXIF orientation applied, longest side capped at 3000 px, HEIC through pi-heif), the engine recognises text, lines that sit directly beneath each other are joined into one line so multi-word queries match across line breaks. Multi-frame TIFF: one block per frame. |
| `officexml` | xlsx pptx ods odp                             | XML text from the zip. pptx/odp slides become pages. |

Every engine returns lines with positions in the same frame, so the
paragraph grouping is shared; how aggressively lines are joined still
depends on the boxes an engine reports. `rga-ocr` resolves `auto` once per
run and hands the engine name and languages to the adapters as
`RGA_OCR_ENGINE` and `RGA_OCR_LANG`. `--force-ocr` sets
`RGA_OCR_FORCE_OCR=1`.

## The OCR cache

rga caches adapter output per file (keyed by path, size, mtime and the
adapter's `version`). `rga-ocr` keeps one cache per engine and language
setting under `cache_dir`, because the same scan yields different text
with different settings: `vision-auto`, `vision-de-DE_en-US`,
`tesseract-deu_eng`, `rapidocr-multi`, `rapidocr-cyrillic`, each with a
`-force` twin for `--force-ocr`, and `none` for `--no-ocr`.
`rga-ocr --cache-info` lists them:

```
cache_dir: ~/Library/Caches/rga-ocr
CACHE-ID  ENGINE     LANG         FORCE  ENTRIES   SIZE  LAST ADDED        FOLDERS
9d2ca07   vision     auto         no         320  2.1 MB  2026-10-23 09:12  ~/Documents/Scans
276f047   vision     auto         yes          4  0.1 MB  2026-10-22 01:40  ~/Documents/Scans
0c4a554   tesseract  deu_eng      no        1500  5.6 MB  2026-10-22 01:27  ~/Documents/Archive/{Invoices (800), Contracts (400), Letters (200), +3 more}
```

CACHE-ID is a stable handle, the first seven hex digits of the SHA-1 of the
cache's directory name, so it stays the same across runs and machines.
LAST ADDED is when the newest entry was written; cache hits do not update
anything. FOLDERS is the common parent of the cached files and, when it
has several children, the three with the most entries.
`rga-ocr --clear-cache 276f047` (or the directory name, `vision-auto-force`)
deletes that cache, several can be given at once, and `rga-ocr
--clear-cache all` deletes every cache under `cache_dir` after listing
what it holds; files that are not caches stay, and `cache_dir` itself is
removed only when it is empty afterwards. A bare `--clear-cache` only lists the caches and exits 2, so a
forgotten argument cannot wipe everything. `--dry-run` prints what would
be removed and deletes nothing. When `adapter.py` changes the output of a
mode, bump that adapter's `version` in `setup_cmd.py` and re-run `rga-ocr
setup --apply`; only that adapter's cache entries are invalidated.

## Performance

Measured on the test fixtures (M-series Mac, 8 images, 2 PDFs, 3 Office
files, 1 zip, 3 text files):

| run                        | wall time |
|----------------------------|-----------|
| cold, Vision               | about 2 s |
| cold, Tesseract            | about 3 s |
| cold, RapidOCR             | about 10 s |
| warm (all cached)          | 0.1 s     |

Each file costs one adapter process (Python startup plus engine
initialisation) plus recognition time. Vision and Windows OCR start fast;
RapidOCR loads its ONNX models in every process, about a second, which is
why it is the slowest cold. rga runs adapters in parallel, `-j N` controls
how many. A folder with thousands of photos takes minutes the first time
and under a second afterwards.

## Limits

- The engines initialise per adapter process, one process per file. A
  long-running OCR server would remove that cost and is not planned.
- `winocr` recognises one language per run and needs the matching Windows
  language pack; without one, `auto` falls through to `rapidocr`.
- `rapidocr` handles one script per run (`lang = de,ru` is refused).
- `tesseract` needs the `.traineddata` file for every language in `lang`;
  `setup --apply` fetches them, or point `TESSDATA_PREFIX` at your own.
- `--force-ocr` is needed for PDFs with a wrong text layer (a scan that
  got a garbage OCR layer elsewhere): the adapter trusts any page with 20
  or more characters.
- `--no-ocr` reads PDFs with `pdftotext`, which keeps the layout line
  breaks, so a phrase wrapped across two lines does not match there. The
  `ocrpdf` adapter joins the lines of a paragraph, so the same phrase
  matches in the default mode.
- Multi-word matches across OCR lines rely on the paragraph grouping. Text
  spread over columns or tables may still split a phrase across output lines.
- Files larger than rga's cache blob limit are re-processed on every run
  (very large scanned PDFs).
- Direct `rga` use works too, but pass the explicit adapter list, e.g.
  `rga --rga-adapters=ocrpdf,ocrimg,officexml,pandoc,postprocpagebreaks,zip,decompress,tar,sqlite PATTERN DIR`,
  otherwise rga's own PDF adapter (poppler) may win for `.pdf`. Do not use
  `--rga-no-cache` there: in ripgrep-all 0.10.10 it makes every custom
  adapter fail with "No cache?". `rga-ocr --no-cache` works around it
  with a throwaway cache directory per run. Set `RGA_OCR_ENGINE` and
  `RGA_OCR_LANG` yourself in that case; the adapters do not read the
  profile.
- Windows: ripgrep-all's last release with a Windows build is v0.10.9; its
  custom adapters work the same way.
- rga reports its own config and usage errors with exit 1, the same as "no
  match"; `rga-ocr` maps that to exit 2 when rga's stderr contains a
  line starting with `error`.
- The engine package version and the tuning variables
  (`RGA_OCR_MIN_TEXT_CHARS`, `RGA_OCR_RENDER_DPI`, `RGA_OCR_MAX_PIXELS`,
  `RGA_OCR_PARAGRAPH_GAP`) are not part of the cache key; clear the
  affected cache after changing them.
- The cache has no size limit and never expires entries; `--cache-info`
  shows what it holds, `--clear-cache` trims it.
- A first argument of `setup` starts the subcommand; to search for the
  word itself write `rga-ocr -- setup PATH`.
- `-r`, `-s`, `-i`, `--engine`, `--full` and `--json` belong to `rga-ocr`;
  rg's `-r/--replace` and `--engine` (regex engine) cannot be reached
  through the pass-through.
- rg's output-format flags (`-l`, `-c`, `--count-matches`,
  `--files-without-match`, `--files`, `-q`) are refused with exit 2; use
  `--json` and filter the events.
- Python 3.15, and Windows on arm64: pi-heif ships no wheel there yet, so
  `pip install` tries to build it and fails without a C toolchain and
  libheif. Use Python 3.11 to 3.14.
- ripgrep-all 0.10.10 opens its SQLite cache once per file, without a
  busy timeout, creates the schema when the database is new and rebuilds
  the WAL index when it is the first to open the file. With many files
  starting at once, one of them can see `The database file is locked`;
  ripgrep-all then prints that error and skips the file's content for that
  run (exit 0, the other hits are fine). `rga-ocr` creates the database
  before ripgrep-all starts and keeps it open during the run, which removes
  the start-up collisions; two cache writes finishing in the same instant
  can still collide. If a hit is missing, rerun the search: the cache holds
  everything else.
- Not covered: `.pages`/`.numbers`, Apple Notes, text in video frames.

## Design notes

Decisions worth knowing before changing things:

- Searches are case-insensitive by default; `-s` flips it. A blank in a
  query matches a run of non-letter characters in names, so one query
  finds `Maintenance_Contract` and `maintenance contract`.
- The name pass is a Python walk, not `find` or `fd`, so hidden files,
  the `exclude` list and the blank modes behave the same on every platform.
- Content hits show a snippet window instead of whole lines because OCR
  output lines can be a page long.
- Profile precedence is built-in default, then the profile, then
  `RGA_OCR_<KEY>`, then the flag; the adapters read only the environment
  that `rga-ocr` hands them, never the profile.
- One cache per engine and language setting, because the same scan yields
  different text per engine; the adapter `version` invalidates entries
  when the output format changes.
- `--no-cache` uses a throwaway cache directory per run, because
  ripgrep-all 0.10.10's `--rga-no-cache` makes every custom adapter fail.
- `rga-ocr` creates ripgrep-all's cache database (same schema, version and
  application id as 0.10.10) before each run and holds it open until
  ripgrep-all exits, so the parallel `rga-preproc` processes neither create
  the schema nor rebuild the WAL index at the same time (see Limits).
- The adapters run as `python -I -X utf8 -m rga_ocr.adapter MODE` with the
  interpreter `rga-ocr` was installed with, so there is one place that
  knows which engine packages exist and no launcher script to keep in sync.
  An adapter ends with `os._exit(0)` after flushing its output: rg aborts
  the whole search when a preprocessor exits non-zero, and the OCR
  libraries' native teardown at interpreter exit must not decide that.

## Tests

```
python -m venv .venv
.venv/bin/pip install -e '.[vision,tesseract,rapidocr,test]'   # the extras your platform supports
.venv/bin/python -m pytest -q
RGA_OCR_ENGINE=tesseract .venv/bin/python -m pytest -q         # the same suite on another engine
```

`tests/make_fixtures.py` builds the fixtures (text, hidden file, text-layer
PDF, scanned PDF, jpg/png/heic, EXIF-rotated jpg, docx/xlsx/pptx, zip with
an image, long lines for the snippet window, decoys, excluded `.git`);
`tests/test_e2e.py` runs `rga-ocr` against them as a subprocess with its
own rga config, cache and profile, and asserts the shape of every hit, the
exit codes, the profile precedence, the status line (through
`tests/ptyrun.py`, POSIX only), adapter error forwarding and the warm-run
timing. `tests/test_adapter.py`, `tests/test_cli.py` and
`tests/test_setup.py` are unit tests for the paragraph grouping, image
decoding, language mappings, cache clearing, argument errors and the rga
config merge; they run without the toolchain. The end-to-end tests need
`rga`, `rg`, `pandoc` on PATH; Vision
needs a GUI session; the tesseract leg fetches `eng` and `deu` into its
temp root when no tessdata is present. The `--no-ocr` test is skipped
without `pdftotext`. GitHub Actions runs the matrix in the table above.

## Reporting bugs

Open an issue at <https://github.com/luca-rui/rga-ocr/issues> with the
output of `rga-ocr --version`, `rga --version`, `rga-ocr --engines` and
`rga-ocr setup`, the exact command that misbehaved and what you expected.
Please do not attach the document that triggered the problem unless it is
yours to share; a description of its type and size is enough to start.
`CONTRIBUTING.md` has the development setup.

## Layout

```
pyproject.toml              package rga-ocr, engine extras, console script
src/rga_ocr/cli.py          the CLI: profile, name pass, rga run, rendering, cache tools
src/rga_ocr/adapter.py      pdf | image | office; decoding and paragraph grouping
src/rga_ocr/engines/        registry (__init__), vision, winocr, rapidocr, tesseract
src/rga_ocr/paths.py        profile, cache, data and rga config locations per platform
src/rga_ocr/setup_cmd.py    `rga-ocr setup`: checks, install commands, rga config merge
tests/conftest.py           fixture tree, rga config, cache and profile in a temp root
tests/test_e2e.py           the CLI as a subprocess against the fixtures
tests/test_adapter.py       unit tests: decoding, grouping, language mappings
tests/test_cli.py           unit tests: cache clearing, adapter list, usage errors
tests/test_setup.py         unit tests: JSONC parsing, config merge, install commands
tests/make_fixtures.py      builds the fixture tree (PDFs written by hand, images drawn with Pillow)
tests/data/shot.heic        HEIC sample for platforms without an encoder
tests/ptyrun.py             runs a command on a pseudo-terminal for the tty tests
tools/check_licences.py     CI check: no GPL/AGPL dependency, every licence on the allow-list
docs/design/glossary.md     the terms used in the code and in this file
tools/check_tools.py        CI check: pdftotext, rga's poppler and pandoc adapters extract text
```

## Dependencies and licences

`rga-ocr` is MIT (see `LICENSE`). Its own code imports nothing under the
GPL or the AGPL. The direct dependencies:

| package | licence |
|---------|---------|
| Pillow | MIT-CMU |
| platformdirs | MIT |
| pypdfium2 | BSD-3-Clause or Apache-2.0; bundles PDFium (BSD-3-Clause) |
| pi-heif | BSD-3-Clause; bundles libheif and libde265 (LGPL-3.0) as shared libraries |
| rapidocr, its PP-OCR models | Apache-2.0 |
| onnxruntime | MIT |
| tesserocr | MIT; bundles Tesseract (Apache-2.0); tessdata_fast language files are Apache-2.0 |
| pyobjc (`vision`) | MIT |
| winrt (`winocr`) | MIT |

What the `rapidocr` extra pulls in besides: numpy, shapely, omegaconf
(BSD), pyclipper, PyYAML, tqdm (MIT; tqdm also MPL-2.0 on parts),
requests, opencv-python-headless (Apache-2.0), certifi (MPL-2.0).
The opencv-python-headless wheels bundle their own FFmpeg (LGPL); the
macOS wheel's FFmpeg includes the GPL codecs x264 and x265 (checked on
5.0.0.93; see its `LICENSE-3RD-PARTY.txt`). `rga-ocr` never calls FFmpeg,
but if a GPL library in the process matters to you, use the `vision`,
`winocr` or `tesseract` engine instead of `rapidocr`.

[ripgrep-all](https://github.com/phiresky/ripgrep-all) (AGPL-3.0) and
[pandoc](https://pandoc.org) (GPL-2.0-or-later) are separate programs that
you install and that `rga-ocr` starts as subprocesses; nothing of them is
linked or bundled, so they do not change `rga-ocr`'s licence. ripgrep
(MIT or Unlicense) and poppler (GPL-2.0 or GPL-3.0) are the same kind of
external program.

## Network access

Your documents never leave the machine. The network is used in three
places: `rapidocr` fetches the per-script recognition model from its model
host on first use of a non-Latin `lang` (the bundled model needs no
download); `rga-ocr setup --apply` fetches Tesseract `.traineddata` files
from `github.com/tesseract-ocr/tessdata_fast`; the CI workflow downloads
ripgrep-all from its GitHub releases.

One dependency would phone home on its own: the official `onnxruntime`
wheels behind the `rapidocr` engine ship Microsoft's 1DS telemetry, on by
default (a persistent device id and trace events sent over HTTPS, see
`docs/Privacy.md` in the onnxruntime repository). `rga-ocr` sets
`ORT_DISABLE_TELEMETRY=1` before the runtime loads, which keeps the
uploader and the device id from being created; a value already in the
environment is left alone. If you ran `onnxruntime` without that variable
before, it may have left its store behind (on macOS
`~/Library/Application Support/Microsoft/DeveloperTools/.onnxruntime/`).

## License

MIT, see `LICENSE`.
