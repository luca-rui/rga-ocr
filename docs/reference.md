# Reference

The detail behind the [README](../README.md): everything `setup` does, the
flags that are passed through to `rga` and `rg`, the output format, the
profile, the cache, and the full list of limits. How the adapters work
inside is in [CONTRIBUTING.md](../CONTRIBUTING.md).

- [Setup](#setup)
- [Options](#options)
- [Output](#output)
- [Profile, paths and environment](#profile-paths-and-environment)
- [The OCR cache](#the-ocr-cache)
- [What the adapters do](#what-the-adapters-do)
- [Network access](#network-access)
- [Using plain rga](#using-plain-rga)
- [Performance](#performance)
- [Limits](#limits)

## Setup

```
rga-ocr setup            # dry run: what is missing, what --apply would write
rga-ocr setup --apply
rga-ocr setup --remove
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
it after moving the installation and after an upgrade, because the
entries point at the interpreter that runs `rga-ocr`.

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

`setup --remove` takes the three adapters out of rga's config. It keeps
a backup copy of `config.jsonc`, as `--apply` does, and leaves every
other custom adapter in it. It deletes nothing else: it prints the
commands that remove the cache, the profile and the Tesseract language
files, for you to run.

A first argument of `setup` starts the subcommand; to search for the
word itself write `rga-ocr -- setup PATH`.

## Options

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
needs the `=` form.

- `--rga-accurate` and `--rga-no-cache` mean `--accurate` and
  `--no-cache`, and `--rga-cache-path DIR` takes the place of `cache_dir`
  for that run.
- `--rga-adapters=LIST` replaces the adapters of the run,
  `--rga-adapters=+LIST` adds to them and `--rga-adapters=-LIST` takes
  some out (`--rga-adapters=-ocrimg` skips images).
- rg's output-format flags (`-l`, `-c`, `--count-matches`,
  `--files-without-match`, `--files`, `-q`) are refused with exit 2: the
  content pass reads rg's JSON events, which those flags replace. Use
  `--json` and filter the events instead.
- rg's formatting flags (`-o`, `--heading`, `--vimgrep`, `-M` ...) are
  accepted with a warning and change nothing, because the output format
  is `rga-ocr`'s own.
- `-r`, `-s`, `-i`, `--engine`, `--full` and `--json` belong to
  `rga-ocr`; rg's `-r` and `--engine` (regex engine) cannot be reached
  through the pass-through, also not bundled or with an attached value
  (`-ir`, `-rX` exit 2). `--replace` (long form) works with `--json`
  only: rg reports the replacement in the event next to the unchanged
  line, and the text output prints the line.
- `-e PATTERN` adds a pattern for the content pass. `rga-ocr` still needs
  its QUERY argument, and the name pass uses QUERY alone.

Exit status: 0 at least one hit, 1 no hit, 2 failure. A search without a
content hit in which the OCR engine failed on a file ends with 2, not 1:
those files were not read. rga reports its own config and usage errors
with exit 1, the same as "no match"; `rga-ocr` maps that to exit 2 when
rga's stderr contains a line starting with `error`.

## Output

On a terminal, hits are grouped per file with the match highlighted, name
hits first under `# names`. Piped, every hit is one line:
`path:line:text`, without colour unless `--color always` asks for it
(`NO_COLOR` switches the colour off on a terminal). PDF pages and slides
carry a `Page N:` prefix, archive members a `member.ext:` prefix.

Content matches are shown as a snippet window: up to 80 characters on
each side of the match, with the prefixes kept and `…` marking cut text.
`--snippet N` changes the width, `--full` prints whole lines. `--json`
always carries whole lines. A name hit whose file name is not valid UTF-8
(Linux) has U+FFFD in `"path"` and the exact name, base64-encoded, in
`"path_bytes"`.

When the reader of the output goes away (`rga-ocr needle DIR | head -1`)
or the search gets SIGTERM, SIGHUP or Ctrl-C, `rga`, `rg` and the adapters
are stopped as well. Content hits of a long first search arrive in
batches, not one by one: rg hands its output to `rga-ocr` through a pipe
and fills a buffer first. `| head -1` therefore waits for the first
batch.

While the content pass runs on a terminal, a status line on stderr
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
terminal and `--json` is not given, so scripts never see them.
`--no-progress` or `progress = false` in the profile switch them off. On a
console that is not UTF-8 the spinner and separators fall back to ASCII.
There is no percentage: rg reports nothing per file, and the cache hides
how much OCR work is left.

## Profile, paths and environment

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

The tuning variables and the version of the engine package are not part
of the cache key. After changing one, clear the affected cache or search
with `--refresh`.

## The OCR cache

rga caches adapter output per file, keyed by path, modification time, the
adapter with its `version`, and the adapter list of the run. `rga-ocr`
keeps one cache per engine and language setting under `cache_dir`, because
the same scan yields different text with different settings:
`vision-auto`, `vision-de-DE_en-US`, `tesseract-deu_eng`,
`rapidocr-multi`, `rapidocr-cyrillic`, each with a `-force` twin for
`--force-ocr`, and `none` for `--no-ocr`. `rga-ocr --cache-info` lists
them:

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

`rga-ocr --clear-cache 276f047` (or the directory name,
`vision-auto-force`) deletes that cache, several can be given at once,
and `rga-ocr --clear-cache all` deletes every cache under `cache_dir`
after listing what it holds (the text store below included); files that
are not caches stay, and `cache_dir` itself is removed only when it is
empty afterwards. A bare `--clear-cache` only lists the caches and exits
2, so a forgotten argument cannot wipe everything. `--dry-run` prints
what would be removed and deletes nothing.

`rga-ocr --refresh QUERY PATH` drops what the cache of the current engine
and language holds for PATH and everything below it, and reads those
files again in the same run.

Next to rga's cache, each of these directories holds a second store,
`text/`, keyed by the content of a file instead of its path: the SHA-256
of the bytes together with the adapter, its version and the settings that
change the text. A file that was copied, renamed, moved or packed into a
zip is found there and not read again, and so is the second copy of an
invoice that sits in three folders. Only complete results are stored. A
file whose read failed, in full or in part, is not. `--no-cache` leaves the
store out, `--refresh` reads the files again and writes the new text, and
`--clear-cache` removes it with the cache it belongs to.

On macOS and Linux `rga-ocr` creates the cache directories for your user
only (mode 0700). A directory that exists keeps its mode.

The cache has no size limit and never expires entries. Files larger than
rga's cache blob limit (very large scanned PDFs) are re-processed on
every run.

## What the adapters do

| adapter     | extensions                                    | what it does |
|-------------|-----------------------------------------------|--------------|
| `ocrpdf` | pdf                                           | Text layer per page through pypdfium2 (PDFium), one line per paragraph (wrapped lines joined, de-hyphenated). Pages with fewer than 20 characters are rendered at 200 dpi and OCR'd. Pages are separated by form feed so rga prints `Page N:`. |
| `ocrimg` | jpg jpeg png heic heif tif tiff webp gif bmp  | Pillow decodes (EXIF orientation applied, longest side capped at 3000 px, HEIC through pi-heif), the engine recognises text, lines that sit directly beneath each other are joined into one line so multi-word queries match across line breaks. Multi-frame TIFF: one block per frame. |
| `officexml` | xlsx pptx ods odp                             | XML text from the zip. pptx/odp slides become pages; the pictures a slide shows are OCR'd and added to its page (not with `--no-ocr`). |

## Network access

Every engine runs locally. The network is used in two places:

- `rapidocr` fetches the per-script recognition model from
  `www.modelscope.cn` on first use of a non-Latin `lang`. The bundled
  model needs no download.
- `rga-ocr setup --apply` fetches Tesseract `.traineddata` files from
  `github.com/tesseract-ocr/tessdata_fast`, at a pinned commit, and
  checks each file.

A search with `vision`, `winocr`, `tesseract` or the bundled `rapidocr`
model opens no connection.

One dependency would phone home on its own: the official `onnxruntime`
wheels behind the `rapidocr` engine ship Microsoft's 1DS telemetry, on by
default (a persistent device id and trace events sent over HTTPS, see
`docs/Privacy.md` in the onnxruntime repository). `rga-ocr` sets
`ORT_DISABLE_TELEMETRY=1` before the runtime loads, which keeps the
uploader and the device id from being created; a value already in the
environment is left alone. If you ran `onnxruntime` without that variable
before, it may have left its store behind (on macOS
`~/Library/Application Support/Microsoft/DeveloperTools/.onnxruntime/`).

## Using plain rga

After `rga-ocr setup --apply`, plain `rga` can use the adapters too. Pass
the explicit adapter list, otherwise rga's own PDF adapter (poppler) may
win for `.pdf`:

```
rga --rga-adapters=ocrpdf,ocrimg,officexml,pandoc,postprocpagebreaks,zip,decompress,tar,sqlite PATTERN DIR
```

- Do not use `--rga-no-cache` there: in ripgrep-all 0.10.10 it makes
  every custom adapter fail with "No cache?". `rga-ocr --no-cache` works
  around it with a throwaway cache directory per run.
- Set `RGA_OCR_ENGINE` and `RGA_OCR_LANG` yourself; the adapters do not
  read the profile.
- Give `RGA_OCR_FORCE_OCR=1` and `RGA_OCR_NO_OCR=1` runs their own
  `--rga-cache-path`: rga's cache key does not include the environment,
  so one mode would read back the other's text.

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
how many.

Two things keep the first search short. Input that is no document (the
`__MACOSX/._*` entries of a zip made on macOS, Office lock files) ends
before a parser is loaded, and a file whose bytes were read before, under
any name or path, comes from the content cache. `--timings` prints the
breakdown for your folder: runs, cache hits, skipped input, engine starts
and OCR time per adapter, and the slowest files.

## Limits

Engines:

- `winocr` recognises one language per run and needs the matching Windows
  language pack; without one, `auto` falls through to `rapidocr`.
- `rapidocr` handles one script per run (`lang = de,ru` is refused).
- `tesseract` needs the `.traineddata` file for every language in `lang`;
  `setup --apply` fetches them, or point `TESSDATA_PREFIX` at your own.
- The engines initialise per adapter process, one process per file.
- Windows: ripgrep-all's last release with a Windows build is v0.10.9; its
  custom adapters work the same way.
- Python 3.15, and Windows on arm64: pi-heif ships no wheel there yet, so
  it is not installed and HEIC and HEIF images are not read. A search
  names each such file with the reason, exits 2 when nothing else matched
  and reads the file again once pi-heif is there. Use Python 3.11 to 3.14
  for HEIC.

What is read:

- `--force-ocr` is needed for PDFs with a wrong text layer (a scan that
  got a garbage OCR layer elsewhere): the adapter trusts any page with 20
  or more characters.
- `--no-ocr` reads the PDF text layer and nothing else: pages without one
  (scans) and images are not searched. It uses the `ocrpdf` adapter, so
  it needs no `pdftotext`.
- Multi-word matches across OCR lines rely on the paragraph grouping. Text
  spread over columns or tables may still split a phrase across output lines.
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
  `RGA_OCR_MAX_PICTURES` raise the limits. A PDF has no page limit, and
  no file has a time limit: one very large scan can hold up a search for
  minutes.
- Not covered: `.pages`/`.numbers`, Apple Notes, text in video frames.

ripgrep-all's cache database:

- ripgrep-all 0.10.10 opens its SQLite cache once per file, without a
  busy timeout. `rga-ocr` creates the database before ripgrep-all starts
  and keeps it open during the run, which removes the start-up
  collisions; two cache writes finishing in the same instant can still
  collide. ripgrep-all then prints `The database file is locked` and
  skips that file's content for the run (exit 0, the other hits are
  fine). If a hit is missing, rerun the search: the cache holds
  everything else.
