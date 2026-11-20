# rga-ocr

[![PyPI](https://img.shields.io/pypi/v/rga-ocr)](https://pypi.org/project/rga-ocr/)
[![CI](https://github.com/luca-rui/rga-ocr/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/luca-rui/rga-ocr/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

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

Quick start on macOS with [Homebrew](https://brew.sh), which pulls `rga`,
`rg`, `pandoc`, a Python and the Vision engine:

```
brew install luca-rui/tap/rga-ocr
rga-ocr "maintenance contract" ~/Documents
```

Quick start everywhere else, once `rga`, `rg` and `pandoc` are installed
(see [Install](#install)):

```
pipx install "rga-ocr[rapidocr]"   # Linux
pipx install "rga-ocr[winocr]"     # Windows
pipx install "rga-ocr[vision]"     # macOS without Homebrew
rga-ocr "maintenance contract" ~/Documents
```

`rga-ocr setup` checks the installation and names what is missing. The
`tesseract` engine needs `rga-ocr setup --apply` once, for its language
files.

HEIC and HEIF images need pi-heif, which ships no wheels for Python 3.15
yet. The install works there, without HEIC. Where `python3` is 3.15 and
HEIC matters, add `--python python3.14` (any of 3.11 to 3.14) to the
`pipx install` line.

## Contents

- [What is searched](#what-is-searched)
- [Platforms and engines](#platforms-and-engines)
- [Install](#install), [upgrading](#upgrading), [uninstalling](#uninstalling)
- [Usage](#usage): [output](#output), [names](#names)
- [Profile and paths](#profile-and-paths)
- [How the adapters work](#how-the-adapters-work)
- [The OCR cache](#the-ocr-cache)
- [Privacy and network access](#privacy-and-network-access)
- [Troubleshooting](#troubleshooting)
- [Performance](#performance)
- [Limits](#limits)
- [Reporting bugs](#reporting-bugs)
- [Dependencies and licences](#dependencies-and-licences)

Working on the code: `CONTRIBUTING.md` has the development setup, the
tests, the layout of the repository and the design notes.

## What is searched

| what | file types | read by |
|------|------------|---------|
| names of files and directories | all | `rga-ocr` |
| plain text | whatever `rg` reads as text | `rg` |
| PDFs, text layer and scanned pages | pdf | `ocrpdf` (OCR for pages without text) |
| photos, screenshots and scans | jpg jpeg png heic heif tif tiff webp gif bmp | `ocrimg` (OCR) |
| spreadsheets and slides | xlsx pptx ods odp | `officexml` (OCR for the pictures on slides) |
| text documents | docx odt epub fb2 ipynb html htm | rga through pandoc |
| archives, searched member by member | zip jar tar tgz gz xz bz2 zst | rga |
| SQLite databases | db db3 sqlite sqlite3 | rga |
| mail, with `--mail` | eml mbox mbx | rga |

Hidden files and files ignored by `.gitignore` are searched; `.git`,
`node_modules`, `.venv` and `__pycache__` directories are skipped (see
[Names](#names)). The pictures on pptx and odp slides are read by OCR;
pictures inside docx, odt, xlsx and ods files are not read, and neither
are the old binary formats `.doc`, `.xls` and `.ppt` (see
[Limits](#limits)).

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
| `tesseract` | Tesseract 5 through tesserocr wheels | `rga-ocr[tesseract]` and the `.traineddata` files for `lang` (`rga-ocr setup --apply` fetches them from tessdata_fast and checks them) | BCP 47 tags for 59 languages (`de-DE`, `fr`), or the name of any tessdata_fast file (`frk`, `chi_sim_vert`); several at once; default `eng` |

`rga-ocr --engines` shows which engines work on this machine, why one
does not, and which `auto` picks. `--engine NAME`, the profile key
`engine`, or `RGA_OCR_ENGINE` choose one explicitly. Results are cached
per engine and language, so switching engines never serves stale text.

## Install

### macOS with Homebrew

```
brew install luca-rui/tap/rga-ocr
```

The formula lives in the tap
[luca-rui/homebrew-tap](https://github.com/luca-rui/homebrew-tap). It
installs ripgrep, ripgrep-all, pandoc and its own Python, and ships the
Vision engine only. For another engine use the PyPI install below instead.

### Every platform, from PyPI

1. Install the tools. `rga-ocr setup` prints the command for your package
   manager; in short:

   | | |
   |-|-|
   | macOS | `brew install ripgrep ripgrep-all pandoc` |
   | Debian/Ubuntu | `sudo apt-get install ripgrep pandoc` plus `rga` and `rga-preproc` from the [v0.10.10 release archive](https://github.com/phiresky/ripgrep-all/releases/tag/v0.10.10) on PATH |
   | Arch | `sudo pacman -S ripgrep ripgrep-all pandoc-cli` |
   | Windows | `scoop install rga` (pulls ripgrep, pandoc, poppler, ffmpeg) or `choco install ripgrep-all ripgrep pandoc` |

2. Install `rga-ocr` with the engine extra you want, with
   [pipx](https://pipx.pypa.io) or in a venv. Python 3.11 or newer; HEIC
   needs 3.11 to 3.14 (pi-heif ships no wheels for 3.15 yet;
   `pipx install --python python3.14 ...` picks an interpreter).

   ```
   pipx install "rga-ocr[rapidocr]"
   ```

   macOS: `rga-ocr[vision]`; Windows: `rga-ocr[winocr]`; several extras
   work too: `rga-ocr[vision,tesseract]`.

3. Check everything:

   ```
   rga-ocr setup            # dry run: what is missing, what --apply would write
   rga-ocr setup --apply
   ```

   A search with `rga-ocr` works without `--apply`: rga finds custom
   adapters through its `config.jsonc`, and where that file lacks the
   three entries of this installation, or holds other ones, `rga-ocr`
   hands rga a copy with the entries put in, for that run only. The file
   itself is not touched. `--apply` is needed for the Tesseract language
   files, for calling plain `rga` with these adapters, and for searches
   that name a config with `--rga-config-file`, which is used as it is.

   `setup --apply` fetches Tesseract language files for the configured
   `lang`, initialises RapidOCR once, merges the three adapter entries into
   rga's `config.jsonc` (the first run keeps a `.bak` copy, later runs a
   timestamped one; comments in that file are not preserved; other custom
   adapters stay) and checks that `rga --rga-list-adapters` lists them.
   Package installs stay commands for you to run. For plain `rga`, re-run
   it after moving the installation, because the entries point at the
   interpreter that runs `rga-ocr`.

   `setup --engine NAME`, `--lang L` and `--config PATH` check another
   engine, language list or profile than the configured one;
   `--rga-config-file=PATH` before `setup` targets another rga config.
   Exit status: 0 ready, 1 something to do, 2 usage error.

   `setup` also names the ripgrep-all release it found. One older than
   the tested release (0.10.10, on Windows 0.10.9) gets a warning, not an
   error. `rga-preproc` has to be on PATH next to `rga`. In an
   environment made by `uv tool install`, the install hints use `uv tool`.
   Inside a Homebrew formula, `setup` writes the adapter command with
   Homebrew's `opt` path, which stays valid across `brew upgrade`.

`rga-ocr --init-config` writes a commented profile.

### Upgrading

```
pipx upgrade rga-ocr        # or pip install -U in the venv, or brew upgrade rga-ocr
rga-ocr setup --apply       # for plain rga only: refreshes the written adapter entries
```

rga keys the cache on the path and modification time of the file and on
the adapter `version`. The engine package version and the tuning variables
below are not part of it, so after
upgrading an engine package or changing a tuning variable, clear the
affected cache (`rga-ocr --cache-info`, `rga-ocr --clear-cache ...`) to
get fresh text. For one file or one folder, `rga-ocr --refresh QUERY PATH`
drops what the cache of the current engine and language holds for PATH and
everything below it, and reads those files again in the same run.

### Uninstalling

```
rga-ocr setup --remove      # takes the three adapters out of rga's config
pipx uninstall rga-ocr      # or uv tool uninstall rga-ocr, or brew uninstall rga-ocr
```

`setup --remove` keeps a backup copy of rga's `config.jsonc`, as `--apply`
does, and leaves every other custom adapter in it. It deletes nothing
else: it prints the commands that remove the cache, the profile and the
Tesseract language files, for you to run. Run the cache command
(`rga-ocr --clear-cache all`) before you uninstall the package.

## Usage

```
rga-ocr [options] QUERY [PATH ...]    PATH defaults to .
rga-ocr [--rga-config-file=F] setup [--apply] [--engine NAME] [--lang L] [--config PATH]
rga-ocr [--rga-config-file=F] setup --remove [--config PATH]
rga-ocr --version | -h | --help

  -s / -i                case-sensitive / case-insensitive (default -i)
  -r                     QUERY is a regex (default literal)
  --snippet N            characters shown around a content match (default 80)
  --full                 whole lines, same as --snippet 0
  --name-blank MODE      nonletter | separators | strict (what a blank may match in names)
  --name-blank-optional  the run a blank matches may be empty
  --engine NAME          OCR engine: auto, vision, winocr, rapidocr, tesseract (default auto)
  --engines              list the engines, whether each works here, and what auto picks; exit
                         (exit code 1 when the configured engine, or with auto every
                         engine, does not work here)
  --lang L               OCR languages, e.g. de-DE,en-US or "de-DE en-US" (default: the engine decides)
  --no-ocr               PDF text layer only; images and pictures on slides skipped
  --force-ocr            OCR every PDF page even if it has a text layer
  --mail                 also search .eml/.mbox
  --accurate             sniff mime types instead of trusting extensions
  --exclude LIST         directory names to skip (replaces the default list)
  --no-exclude           skip nothing
  --names-only / --no-names
  --json                 rg JSON events; name hits first as {"type":"name","path":...}
  --color WHEN           auto | always | never (default auto: colour on a terminal)
  --no-cache             do not read or write the OCR cache
  --refresh              read the files below PATH again and store the new text
  --progress / --no-progress   status line while searching and a summary after (default on)
  --verbose              list every file an adapter failed on or skipped, not one line per reason
  --timings              after the search: where the time of the content pass went
  --init-config          write a commented profile and exit
  --cache-info           list the caches and exit
  --clear-cache CACHE-ID|DIR ...|all   delete the named caches, or every cache, and exit
  --dry-run              with --clear-cache: show what would be removed, delete nothing
  --config PATH          use this profile file (env RGA_OCR_CONFIG)
```

Anything else is passed to `rga`/`rg`: `-g '!*.log'`, `-t pdf`, `-C 2`,
`-U`, `-j 4`, `--rga-config-file=...`. Value flags take
`--flag VALUE` or `--flag=VALUE`; in front of `setup` an `--rga-` flag
needs the `=` form. `--rga-accurate` and `--rga-no-cache` mean `--accurate`
and `--no-cache`, and `--rga-cache-path DIR` takes the place of `cache_dir`
for that run. `--rga-adapters=LIST` replaces the adapters of the run,
`--rga-adapters=+LIST` adds to them and `--rga-adapters=-LIST` takes some
out (`--rga-adapters=-ocrimg` skips images). rg's output-format flags
(`-l`, `-c`, `--count-matches`, `--files-without-match`, `--files`, `-q`)
are refused with exit 2: the content pass reads rg's JSON events, which
those flags replace. Use `--json` and filter the events instead. rg's
formatting flags (`-o`, `--heading`, `--vimgrep`, `-M` ...) are accepted
with a warning and change nothing, because the output format is
`rga-ocr`'s own.

Exit status: 0 at least one hit, 1 no hit, 2 failure. A search without a
content hit in which the OCR engine failed on a file ends with 2, not 1:
those files were not read.

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
`path:line:text`, without colour unless `--color always` asks for it
(`NO_COLOR` switches the colour off on a terminal). PDF pages and slides carry a `Page N:` prefix, archive
members a `member.ext:` prefix.

Content matches are shown as a **snippet window**: up to 80 characters on
each side of the match, with the prefixes kept and `…` marking cut text.
`--snippet N` changes the width, `--full` prints whole lines. `--json`
always carries whole lines. A name hit whose file name is not valid UTF-8
(Linux) has U+FFFD in `"path"` and the exact name, base64-encoded, in
`"path_bytes"`.

When the reader of the output goes away (`rga-ocr needle DIR | head -1`)
or the search gets SIGTERM, SIGHUP or Ctrl-C, `rga`, `rg` and the adapters
are stopped as well.

While the content pass runs on a terminal, a **status line** on stderr
shows that the search is alive:

```
⠹ searching 12 s · 3 hits · 14 files read · Scans/IMG_4711.heic
```

Hits keep appearing above it as they are found. The file count is the
number of PDFs, images and Office files the adapters have finished in this
run; cached files are not counted, because they cost nothing. The line is
cleared before every hit, and when the content pass ends it is replaced by
a summary:

```
searched 12.4 s · 3 hits · 14 files read · 2 skipped
```

"skipped" counts input that carries a document's extension and is no
document: the `__MACOSX/._*` entries macOS puts into zips, the `~$` lock
files Office leaves behind, empty files. They produce no message;
`--verbose` lists them with the reason.

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
# OCR languages, BCP 47 tags separated by commas or blanks. Empty: the engine's default.
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
# cache_dir = <platform default, see above>
# extra rga adapters, e.g. mail,ffmpeg
adapters_extra =
# live status line on a terminal
progress = true
```

Every key can also be set as an environment variable, `RGA_OCR_<KEY>`
in upper case (`RGA_OCR_LANG=de-DE,en-US`). Precedence: built-in
default, then the profile, then the environment, then the flag. Unknown
keys produce a warning and are ignored, and so does an `RGA_OCR_` variable
that is no setting (`RGA_OCR_LANGUAGE`, say). In the profile a `#` starts a
comment at the start of a line or after a blank; `exclude = build#2` keeps
its `#`.

Tuning values that rarely need changing are environment-only:

| variable                   | default | meaning |
|----------------------------|---------|---------|
| `RGA_OCR_MIN_TEXT_CHARS` | 20     | a PDF page with fewer text-layer characters is OCR'd |
| `RGA_OCR_RENDER_DPI`    | 200     | PDF render resolution for OCR |
| `RGA_OCR_MAX_PIXELS`    | 3000    | longest image side handed to the engine |
| `RGA_OCR_PARAGRAPH_GAP` | 0.7     | line gap, in line heights, that starts a new output line |
| `RGA_OCR_MAX_FRAMES`    | 500     | frames read of one multi-frame image (TIFF, GIF); the rest is left out and the file is reported as partly read |
| `RGA_OCR_MAX_OFFICE_MB` | 256     | unpacked text read of one Office file, in MB; the rest is left out and the file is reported as partly read |
| `RGA_OCR_MAX_PICTURES`  | 200     | pictures read of one pptx or odp file; the rest is left out and the file is reported as partly read |
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
| `officexml` | xlsx pptx ods odp                             | XML text from the zip. pptx/odp slides become pages; the pictures a slide shows are OCR'd and added to its page (not with `--no-ocr`). |

Every engine returns lines with positions in the same frame, so the
paragraph grouping is shared; how aggressively lines are joined still
depends on the boxes an engine reports. `rga-ocr` resolves `auto` once per
run and hands the engine name and languages to the adapters as
`RGA_OCR_ENGINE` and `RGA_OCR_LANG`. `--force-ocr` sets
`RGA_OCR_FORCE_OCR=1`, `--no-ocr` sets `RGA_OCR_NO_OCR=1`.

## The OCR cache

rga caches adapter output per file, keyed by path, modification time, the
adapter with its `version`, and the adapter list of the run. `rga-ocr` keeps one cache per engine and language
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
what it holds (the text store below included); files that are not caches stay, and `cache_dir` itself is
removed only when it is empty afterwards. A bare `--clear-cache` only lists the caches and exits 2, so a
forgotten argument cannot wipe everything. `--dry-run` prints what would
be removed and deletes nothing.

Next to rga's cache, each of these directories holds a second store,
`text/`, keyed by the content of a file instead of its path: the SHA-256
of the bytes together with the adapter, its version and the settings that
change the text. A file that was copied, renamed, moved or packed into a
zip is found there and not read again, and so is the second copy of an
invoice that sits in three folders. Only complete results are stored. A
file whose read failed, in full or in part, is not. `--no-cache` leaves the
store out, `--refresh` reads the files again and writes the new text, and
`--clear-cache` removes it with the cache it belongs to.

## Privacy and network access

Your documents never leave the machine: every engine runs locally.

The cache keeps what was read. For every PDF, image and Office file it
holds the extracted text and the full path, and in `text/` the extracted
text once more under a hash of the file's content, compressed but not encrypted,
under `cache_dir` in your user's cache directory (see
[Profile and paths](#profile-and-paths)). Whoever can read that directory
can read the text of the documents you searched. On macOS and Linux
`rga-ocr` creates the cache directories for your user only (mode 0700);
a directory that exists keeps its mode, so a cache from 0.2.4 or earlier
stays as it was until you run `chmod -R go-rwx` on it. `rga-ocr --cache-info`
shows what is there, `rga-ocr --clear-cache all` removes it, and
`--no-cache` searches without leaving anything behind.

The network is used in three places: `rapidocr` fetches the per-script
recognition model from `www.modelscope.cn` on first use of a non-Latin
`lang` (the bundled model needs no download); `rga-ocr setup --apply`
fetches Tesseract `.traineddata` files from
`github.com/tesseract-ocr/tessdata_fast`, at a pinned commit, and checks
each file; the CI workflow downloads ripgrep-all from its GitHub
releases. A search with `vision`, `winocr`, `tesseract` or the bundled
`rapidocr` model opens no connection.

One dependency would phone home on its own: the official `onnxruntime`
wheels behind the `rapidocr` engine ship Microsoft's 1DS telemetry, on by
default (a persistent device id and trace events sent over HTTPS, see
`docs/Privacy.md` in the onnxruntime repository). `rga-ocr` sets
`ORT_DISABLE_TELEMETRY=1` before the runtime loads, which keeps the
uploader and the device id from being created; a value already in the
environment is left alone. If you ran `onnxruntime` without that variable
before, it may have left its store behind (on macOS
`~/Library/Application Support/Microsoft/DeveloperTools/.onnxruntime/`).


## Troubleshooting

Start with `rga-ocr setup`: it checks the tools, the engine and the
adapters and names what is missing. `rga-ocr --engines` says for every
engine whether it works here and why not.

| what you see | what it means, what to do |
|--------------|---------------------------|
| A scan or photo you know holds the text is not found | OCR misread it, or the phrase is split over columns. Try one distinctive word, and `--lang` with the document's language. |
| A PDF with selectable text is not found, or the text shown is garbage | The PDF carries a bad text layer. `--force-ocr` reads every page with OCR as well. |
| `adapter ... failed on FILE: ... (not cached, the next search reads the file again)`, exit 2 | The engine could not read that file in this run; the reason is in the line. Hits in other files are complete. Fix the cause and search again. |
| `adapter ... failed on FILE: ...` without that note | The file itself cannot be read (damaged, password protected). It is skipped until it changes. |
| `adapter ... failed on 12 files: ... (first: FILE; --verbose lists them)` | The same failure in several files, shown once. `--verbose` prints a line per file. |
| `Unknown adapter: "ocrpdf"` | The rga config in use lacks the adapter entries: with plain `rga`, or with `--rga-config-file`, run `rga-ocr setup --apply` (for another config: `rga-ocr --rga-config-file=F setup --apply`). |
| Tesseract: language files missing | `rga-ocr setup --apply --engine tesseract --lang de,en` fetches them, or point `TESSDATA_PREFIX` at your own. |
| `winocr` does not work | No OCR language pack is installed. `rga-ocr --engines` prints the `Add-WindowsCapability` command. |
| HEIC and HEIF files are named as not read | pi-heif is missing: Python 3.15 and Windows on arm64 have no wheel yet. Install with Python 3.11 to 3.14. |
| Text is stale after an engine upgrade or a changed tuning variable | Those are not part of the cache key. `rga-ocr --cache-info`, then `rga-ocr --clear-cache CACHE-ID`, or `rga-ocr --refresh QUERY PATH` for one file or folder. |
| `The database file is locked`, one hit missing | Two cache writes collided in ripgrep-all. Search again; everything else is cached. |
| `searching for the word "setup"` | The setup command goes first: `rga-ocr setup --engine NAME`. |
| The first search of a large folder takes minutes | Every scan is read once. The status line shows progress; the second search is fast. `-j N` sets how many files are read at once, and `--timings` shows where the time went. |

For anything else see [Reporting bugs](#reporting-bugs).

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

Two things keep the first search short. Input that is no document (the
`__MACOSX/._*` entries of a zip made on macOS, Office lock files) ends
before a parser is loaded, and a file whose bytes were read before, under
any name or path, comes from the content cache. On a folder of business
documents with many copies (2500 files and 7 zips, about 3300 adapter
runs, half of them duplicates, 220 pages for OCR) the first search with
Vision went from 338 s to 65 s. `--timings` prints the same breakdown for
your folder: runs, cache hits, skipped input, engine starts and OCR time
per adapter, and the slowest files.

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
- `--no-ocr` reads the PDF text layer and nothing else: pages without one
  (scans) and images are not searched. It uses the `ocrpdf` adapter, so
  it needs no `pdftotext`.
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
  profile. Give `RGA_OCR_FORCE_OCR=1` and `RGA_OCR_NO_OCR=1` runs their
  own `--rga-cache-path`: rga's cache key does not include the
  environment, so one mode would read back the other's text.
- Windows: ripgrep-all's last release with a Windows build is v0.10.9; its
  custom adapters work the same way.
- rga reports its own config and usage errors with exit 1, the same as "no
  match"; `rga-ocr` maps that to exit 2 when rga's stderr contains a
  line starting with `error`.
- The engine package version and the tuning variables
  (`RGA_OCR_MIN_TEXT_CHARS`, `RGA_OCR_RENDER_DPI`, `RGA_OCR_MAX_PIXELS`,
  `RGA_OCR_PARAGRAPH_GAP`, `RGA_OCR_MAX_FRAMES`, `RGA_OCR_MAX_OFFICE_MB`,
  `RGA_OCR_MAX_PICTURES`)
  are not part of the cache key; clear the affected cache after changing
  them.
- The old binary Office formats (`.doc`, `.xls`, `.ppt`), `.rtf` and
  `.msg` are not read: no adapter here or in rga handles them. Their
  names are still searched.
- Pictures are read on pptx and odp slides only, and only the ones a
  slide itself shows: not those of a slide master or layout, not vector
  drawings (emf, wmf, svg), not charts. Pictures in docx and odt files
  are not read, because pandoc extracts those types; pictures in xlsx
  and ods files are not read either.
- A multi-frame image (TIFF, GIF) is read up to 500 frames, an Office
  file up to 256 MB of unpacked text, a slide deck up to 200 pictures.
  What lies beyond is left out, the summary counts the file as partly
  read, and the text read so far is found and cached.
  `RGA_OCR_MAX_FRAMES`, `RGA_OCR_MAX_OFFICE_MB` and
  `RGA_OCR_MAX_PICTURES` raise the limits. A PDF has no page limit, and no file has a time
  limit: one very large scan can hold up a search for minutes.
- The cache has no size limit and never expires entries; `--cache-info`
  shows what it holds, `--clear-cache` trims it.
- Content hits of a long first search arrive in batches, not one by one:
  rg hands its output to `rga-ocr` through a pipe and fills a buffer
  first. `| head -1` therefore waits for the first batch.
- A first argument of `setup` starts the subcommand; to search for the
  word itself write `rga-ocr -- setup PATH`.
- `-r`, `-s`, `-i`, `--engine`, `--full` and `--json` belong to `rga-ocr`;
  rg's `-r` and `--engine` (regex engine) cannot be reached through the
  pass-through, also not bundled or with an attached value (`-ir`, `-rX`
  exit 2). `--replace` (long form) works with `--json` only: rg
  reports the replacement in the event next to the unchanged line, and
  the text output prints the line.
- `-e PATTERN` adds a pattern for the content pass. `rga-ocr` still needs
  its QUERY argument, and the name pass uses QUERY alone.
- rg's output-format flags (`-l`, `-c`, `--count-matches`,
  `--files-without-match`, `--files`, `-q`) are refused with exit 2; use
  `--json` and filter the events.
- Python 3.15, and Windows on arm64: pi-heif ships no wheel there yet, so
  it is not installed and HEIC and HEIF images are not read. A search
  names each such file with the reason, exits 2 when nothing else matched
  and reads the file again once pi-heif is there. Use Python 3.11 to 3.14
  for HEIC.
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

## Reporting bugs

Open an issue at <https://github.com/luca-rui/rga-ocr/issues> with the
output of `rga-ocr --version`, `rga --version`, `rga-ocr --engines` and
`rga-ocr setup`, the exact command that misbehaved and what you expected.
Please do not attach the document that triggered the problem unless it is
yours to share; a description of its type and size is enough to start.
`CONTRIBUTING.md` has the development setup.

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
(MIT or Unlicense) is the same kind of external program.

## License

MIT, see `LICENSE`.
