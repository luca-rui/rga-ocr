# rga-ocr

[![PyPI](https://img.shields.io/pypi/v/rga-ocr)](https://pypi.org/project/rga-ocr/)
[![CI](https://github.com/luca-rui/rga-ocr/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/luca-rui/rga-ocr/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

Search everything beneath a path for a string: file and directory names,
plain text, Office documents, archives, PDFs, and photos or scans of text
that have no text layer. Runs on macOS, Linux and Windows.

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

It is [ripgrep-all](https://github.com/phiresky/ripgrep-all) (`rga`) plus
OCR and a search over names. The OCR runs on your machine, with Apple
Vision, Windows OCR, RapidOCR or Tesseract. Results are cached, so the
first search of a folder reads every scan once and the second takes a
fraction of a second.

## Install

macOS with [Homebrew](https://brew.sh). This pulls `rga`, `rg`, `pandoc`,
a Python and the Vision engine:

```
brew install luca-rui/tap/rga-ocr
```

Everywhere else, or for another engine than Vision, from PyPI:

1. Install the tools:

   | | |
   |-|-|
   | macOS | `brew install ripgrep ripgrep-all pandoc` |
   | Debian/Ubuntu | `sudo apt-get install ripgrep pandoc` plus `rga` and `rga-preproc` from the [v0.10.10 release archive](https://github.com/phiresky/ripgrep-all/releases/tag/v0.10.10) on PATH |
   | Arch | `sudo pacman -S ripgrep ripgrep-all pandoc-cli` |
   | Windows | `scoop install rga` (pulls ripgrep, pandoc, poppler, ffmpeg) or `choco install ripgrep-all ripgrep pandoc` |

2. Install `rga-ocr` with the engine you want, with
   [pipx](https://pipx.pypa.io) or in a venv (Python 3.11 or newer):

   ```
   pipx install "rga-ocr[rapidocr]"   # Linux
   pipx install "rga-ocr[winocr]"     # Windows
   pipx install "rga-ocr[vision]"     # macOS
   ```

   Several extras work too: `rga-ocr[vision,tesseract]`.

3. Check the installation. `setup` names what is missing and prints the
   command for it:

   ```
   rga-ocr setup
   ```

   The `tesseract` engine needs `rga-ocr setup --apply` once, which
   fetches its language files.

HEIC and HEIF images need pi-heif, which ships no wheels for Python 3.15
yet. The install works there, without HEIC. Where HEIC matters, add
`--python python3.14` (any of 3.11 to 3.14) to the `pipx install` line.

Upgrade with `brew upgrade rga-ocr` or `pipx upgrade rga-ocr`. To
uninstall:

```
rga-ocr --clear-cache all   # the cached text
rga-ocr setup --remove      # the adapter entries in rga's config, if setup --apply wrote them
pipx uninstall rga-ocr      # or brew uninstall rga-ocr
```

## What is searched

| what | file types |
|------|------------|
| names of files and directories | all |
| plain text | whatever `rg` reads as text |
| PDFs, text layer and scanned pages | pdf |
| photos, screenshots and scans | jpg jpeg png heic heif tif tiff webp gif bmp |
| spreadsheets and slides, with the pictures on slides | xlsx pptx ods odp |
| text documents | docx odt epub fb2 ipynb html htm |
| archives, searched member by member | zip jar tar tgz gz xz bz2 zst |
| SQLite databases | db db3 sqlite sqlite3 |
| mail, with `--mail` | eml mbox mbx |

Hidden files and files ignored by `.gitignore` are searched. `.git`,
`node_modules`, `.venv` and `__pycache__` directories are skipped unless
you change `exclude` or pass `--no-exclude`.

Not read: the old binary formats `.doc`, `.xls` and `.ppt`, `.rtf`,
`.msg`, `.pages` and `.numbers`, and pictures inside docx, odt, xlsx and
ods files. Their names are still searched.

## Engines

| engine | platform | install | languages |
|--------|----------|---------|-----------|
| `vision` | macOS 13+ | `rga-ocr[vision]` | detected automatically |
| `winocr` | Windows 10+ | `rga-ocr[winocr]` and a Windows OCR language pack | one per run |
| `rapidocr` | all | `rga-ocr[rapidocr]` | Latin script, Chinese and Japanese built in; other scripts are downloaded on first use; one script per run |
| `tesseract` | all | `rga-ocr[tesseract]`, then `rga-ocr setup --apply` | several at once; default `eng` |

`auto`, the default, takes the first engine in this order that works on
the machine. `rga-ocr --engines` shows which engines work here, why one
does not, and which `auto` picks. Choose another with `--engine NAME`,
and name the languages of your documents with `--lang de-DE,en-US`
(BCP 47 tags). Results are cached per engine and language, so switching
never serves stale text.

## Usage

```
rga-ocr [options] QUERY [PATH ...]    PATH defaults to .
```

```
rga-ocr "ACME GmbH" .                           # literal, case-insensitive
rga-ocr -s "ACME GmbH" .                        # case-sensitive
rga-ocr -r 'invoice\s+\d{4}' ~/Scans            # regex
rga-ocr --lang de-DE,en-US "Kesselanlage" ~/Docs
rga-ocr --names-only contract ~/Docs            # names only; --no-names for contents only
rga-ocr -g '*.pdf' -j 4 contract ~/Docs         # other flags go to rga and rg
rga-ocr --json needle DIR | jq -r '.data.path.text // .path' | sort -u
```

The options used most:

```
  -s / -i                case-sensitive / case-insensitive (default -i)
  -r                     QUERY is a regex (default literal)
  --snippet N            characters shown around a content match (default 80)
  --full                 whole lines, same as --snippet 0
  --engine NAME          OCR engine: auto, vision, winocr, rapidocr, tesseract (default auto)
  --lang L               OCR languages, e.g. de-DE,en-US or "de-DE en-US" (default: the engine decides)
  --no-ocr               PDF text layer only; images and pictures on slides skipped
  --force-ocr            OCR every PDF page even if it has a text layer
  --mail                 also search .eml/.mbox
  --exclude LIST         directory names to skip (replaces the default list)
  --names-only / --no-names
  --json                 rg JSON events; name hits first as {"type":"name","path":...}
  --no-cache             do not read or write the OCR cache
  --refresh              read the files below PATH again and store the new text
  --verbose              list every file an adapter failed on or skipped, not one line per reason
  --timings              after the search: where the time of the content pass went
```

`rga-ocr --help` lists all of them. rg's flags that change the output
format (`-l`, `-c`, `-q`, `--files` ...) are refused; use `--json` and
filter the events.

Exit status: 0 at least one hit, 1 no hit, 2 failure. A search without a
hit in which the OCR engine failed on a file ends with 2, because those
files were not read.

**Output.** On a terminal, hits are grouped per file, name hits first.
Piped, every hit is one line, `path:line:text`. PDF pages and slides
carry a `Page N:` prefix, archive members a `member.ext:` prefix. A
content hit shows 80 characters on each side of the match. While a search
runs on a terminal, a status line shows the time, the hits and the file
being read; scripts never see it.

**Names.** The name pass matches the last path segment, so
`rga-ocr contract` finds a directory called `Contracts`, but not every
file beneath it. A blank in the query matches any run of non-letter
characters, so `"maintenance contract"` finds
`Maintenance_Contract_2026.pdf` and `maintenance-contract.docx`.
`--name-blank` and `--name-blank-optional` adjust this.

## Configuration

`rga-ocr --init-config` writes a commented profile to
`~/.config/rga-ocr/config` (Windows: `%APPDATA%\rga-ocr\config`). The
keys: `engine`, `lang`, `exclude`, `case`, `name_blank`,
`name_blank_optional`, `snippet`, `cache_dir`, `adapters_extra`,
`progress`. Each can also be set as `RGA_OCR_<KEY>` in the environment
(`RGA_OCR_LANG=de-DE,en-US`). A flag wins over the environment, the
environment over the profile.

## Cache and privacy

Your documents never leave the machine: every engine runs locally. The
network is used for two downloads only: the Tesseract language files
during `setup --apply`, and a RapidOCR model on first use of a non-Latin
`lang`. The usage telemetry of onnxruntime, which the
`rapidocr` engine runs on, is switched off.

The cache keeps the extracted text and the path of every PDF, image and
Office file that was read, compressed but not encrypted:

| macOS | Linux | Windows |
|-------|-------|---------|
| `~/Library/Caches/rga-ocr` | `~/.cache/rga-ocr` | `%LOCALAPPDATA%\rga-ocr\Cache` |

Whoever can read that directory can read the text of the documents you
searched. On macOS and Linux it is created for your user only.

```
rga-ocr --cache-info                # what is there
rga-ocr --clear-cache CACHE-ID      # delete one cache; `all` deletes every one
rga-ocr --refresh QUERY PATH        # read the files below PATH again
rga-ocr --no-cache QUERY PATH       # search without reading or writing the cache
```

The cache has no size limit and never expires. A file that changes is
read again. A file that was copied, renamed, moved or packed into a zip
is recognised by its content and not read again.

## Troubleshooting

Start with `rga-ocr setup` and `rga-ocr --engines`: they check the tools,
the engines and the adapters and name what is missing.

| what you see | what it means, what to do |
|--------------|---------------------------|
| A scan or photo you know holds the text is not found | OCR misread it, or the phrase is split over columns. Try one distinctive word, and `--lang` with the document's language. |
| A PDF with selectable text is not found, or the text shown is garbage | The PDF carries a bad text layer. `--force-ocr` reads every page with OCR as well. |
| `adapter ... failed on FILE: ... (not cached, the next search reads the file again)`, exit 2 | The engine could not read that file in this run; the reason is in the line. Hits in other files are complete. Fix the cause and search again. |
| `adapter ... failed on FILE: ...` without that note | The file itself cannot be read (damaged, password protected). It is skipped until it changes. |
| `adapter ... failed on 12 files: ...` | The same failure in several files, shown once. `--verbose` prints a line per file. |
| `Unknown adapter: "ocrpdf"` | Plain `rga`, or a config named with `--rga-config-file`, lacks the adapter entries. Run `rga-ocr setup --apply` (for another config: `rga-ocr --rga-config-file=F setup --apply`). |
| Tesseract: language files missing | `rga-ocr setup --apply --engine tesseract --lang de,en` fetches them, or point `TESSDATA_PREFIX` at your own. |
| `winocr` does not work | No OCR language pack is installed. `rga-ocr --engines` prints the `Add-WindowsCapability` command. |
| HEIC and HEIF files are named as not read | pi-heif is missing: Python 3.15 and Windows on arm64 have no wheel yet. Install with Python 3.11 to 3.14. |
| Text is stale after an upgrade of the engine package | The engine version is not part of the cache key. `rga-ocr --refresh QUERY PATH` for one folder, or `rga-ocr --clear-cache CACHE-ID`. |
| `The database file is locked`, one hit missing | Two cache writes collided in ripgrep-all. Search again; everything else is cached. |
| `searching for the word "setup"` | The setup command goes first: `rga-ocr setup --engine NAME`. To search for the word: `rga-ocr -- setup PATH`. |
| The first search of a large folder takes minutes | Every scan is read once, and a folder with thousands of photos takes minutes. The second search is fast. `-j N` sets how many files are read at once, and `--timings` shows where the time went. |

## More

- [docs/reference.md](https://github.com/luca-rui/rga-ocr/blob/main/docs/reference.md):
  everything `setup` does, all options and the flags passed through to
  `rga` and `rg`, the output format, the profile and tuning variables,
  the cache, using plain `rga` with the adapters, timings, and the full
  list of limits.
- [CONTRIBUTING.md](https://github.com/luca-rui/rga-ocr/blob/main/CONTRIBUTING.md):
  development setup, tests and design notes.
- [CHANGELOG.md](https://github.com/luca-rui/rga-ocr/blob/main/CHANGELOG.md)

## Reporting bugs

Open an issue at <https://github.com/luca-rui/rga-ocr/issues> with the
output of `rga-ocr --version`, `rga --version`, `rga-ocr --engines` and
`rga-ocr setup`, the exact command that misbehaved and what you expected.
Please do not attach the document that triggered the problem unless it is
yours to share; a description of its type and size is enough to start.

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

The `rapidocr` extra also pulls in opencv-python-headless, whose wheels
bundle their own FFmpeg (LGPL); the macOS wheel's FFmpeg includes the GPL
codecs x264 and x265 (checked on 5.0.0.93; see its
`LICENSE-3RD-PARTY.txt`). `rga-ocr` never calls FFmpeg, but if a GPL
library in the process matters to you, use the `vision`, `winocr` or
`tesseract` engine instead of `rapidocr`.

[ripgrep-all](https://github.com/phiresky/ripgrep-all) (AGPL-3.0) and
[pandoc](https://pandoc.org) (GPL-2.0-or-later) are separate programs that
you install and that `rga-ocr` starts as subprocesses; nothing of them is
linked or bundled, so they do not change `rga-ocr`'s licence. ripgrep
(MIT or Unlicense) is the same kind of external program.
