# Glossary

The terms used in the code, the tests and the README. One term per entry;
related terms in *italics*.

## adapter

A program ripgrep-all runs per file: it reads the file on stdin and prints
searchable text on stdout. rga-ocr ships three custom adapters, `ocrpdf`,
`ocrimg` and `officexml`, run as `python -I -X utf8 -m rga_ocr.adapter MODE`.
rga's own adapters (pandoc, zip, tar, sqlite, poppler) are *built-in
adapters*. Each adapter entry carries a `version`; bumping it invalidates
that adapter's entries in the *cache*.

## cache

ripgrep-all's cache of adapter output, keyed by path, size, mtime and the
adapter `version`. rga-ocr keeps one cache directory per *cache tag* under
`cache_dir` (`--cache-info` lists them, `--clear-cache` removes them).

## cache tag

The name of a cache directory: `<engine>-<lang>[-force]`, e.g.
`vision-auto`, `tesseract-deu_eng`, `rapidocr-multi-force`; `none` for
`--no-ocr`. The `<lang>` part is the *engine*'s own language id, so the same
`lang` setting can map to different tags per engine. The CACHE-ID shown by
`--cache-info` is the first seven hex digits of the SHA-1 of the tag.

## content pass

The second of the two searches a *query* triggers: ripgrep-all over file
contents with the explicit *adapter* list. Produces *hits* in rg's output
format.

## engine

The OCR backend behind `ocrpdf` and `ocrimg`: `vision` (macOS), `winocr`
(Windows), `rapidocr` and `tesseract` (any platform). `auto` picks the first
engine that works on the machine, in a platform-specific order. Chosen with
`--engine`, the profile key `engine` or `RGA_OCR_ENGINE`; `--engines` lists
them. An engine turns an image into lines with positions; the adapters group
those lines into paragraphs.

## hit

One matching line as printed: `path:line:` prefix, optional `Page N:` or
`member:` prefix, then the *snippet window* of the matched text.

## name blank mode

How a blank in the *query* is interpreted by the *name pass*. Values:
`nonletter` (default: a run of non-letter characters), `separators` (blank,
`_`, `-`), `strict` (a blank only). Whether the run may be empty (so
`Kessel anlage` also finds `Kesselanlage`) is the separate key
`name_blank_optional`, default `false`. Profile key `name_blank`.

## name pass

The first search a *query* triggers: a walk over file and directory names,
matching only the last path segment. Prints under `# names` on a terminal,
as `{"type":"name"}` events with `--json`.

## profile

The user's configuration file: `~/.config/rga-ocr/config` on macOS and
Linux (`$XDG_CONFIG_HOME` honoured), `%APPDATA%\rga-ocr\config` on
Windows. `key = value` lines, `#` comments, comma-separated lists. Each key
maps to an environment variable `RGA_OCR_<KEY>`. Precedence: built-in
default, profile, environment, command-line flag. Keys: `engine`, `lang`,
`exclude`, `case`, `name_blank`, `name_blank_optional`, `snippet`,
`cache_dir`, `adapters_extra`, `progress`.

## query

The string the user searches for. Literal by default, a regex with `-r`.
Case-insensitive by default (`case = insensitive`), `-s` for case-sensitive.

## setup

The `rga-ocr setup` subcommand: checks the tools on PATH, the *engine* and
rga's config, and prints what is missing with the command that fixes it.
`--apply` fetches Tesseract language files, warms RapidOCR and merges the
three *adapter* entries into rga's `config.jsonc`; package installs stay
commands for the user.

## snippet window

The part of a matched line a *hit* shows: up to `snippet` characters (default
80) on each side of the match, with the `path:line:` and `Page N:` prefixes
kept. `0` or `--full` prints the whole line. `--json` always carries the full
line.

## text layer

The extractable text of a PDF page, read through pypdfium2. A page whose
text layer has fewer than 20 characters (`RGA_OCR_MIN_TEXT_CHARS`) is
rendered and OCR'd; `--force-ocr` OCRs every page and appends the result.
