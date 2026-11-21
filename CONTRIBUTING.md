# Contributing

Bug reports and pull requests are welcome. For anything larger than a fix,
open an issue first so the approach can be discussed.

## Development setup

```
git clone https://github.com/luca-rui/rga-ocr
cd rga-ocr
python -m venv .venv
.venv/bin/pip install -e '.[vision,tesseract,rapidocr,test]'   # the extras your platform supports
.venv/bin/python -m pytest -q
```

The end-to-end tests need `rga`, `rg` and `pandoc` on PATH (see the
Install section of the README) and one working OCR engine. The unit tests
in `tests/test_adapter.py`, `tests/test_cli.py` and `tests/test_setup.py`
run without them:

```
.venv/bin/python -m pytest -q tests/test_adapter.py tests/test_cli.py tests/test_setup.py
```

Run the suite per engine with `RGA_OCR_ENGINE`:

```
RGA_OCR_ENGINE=tesseract .venv/bin/python -m pytest -q
RGA_OCR_ENGINE=rapidocr  .venv/bin/python -m pytest -q
```

The tesseract leg fetches the `eng` and `deu` language files into its temp
root when it finds none; the rapidocr leg downloads nothing for the default
model. Apple Vision needs a GUI session.

## What the tests cover

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
temp root when no tessdata is present. The CI section below names the legs.

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
docs/design/glossary.md     the terms used in the code and in the README
docs/reference.md           the user reference behind the README: setup, options, output, profile, cache, limits
tools/check_tools.py        CI check: the tools are on PATH and rga's pandoc adapter extracts text
tools/release_check.py      CI and release check: version, changelog, tag, green ci run on main
tools/fetch_verified.py     CI: download a file and check its SHA-256
tools/min_constraints.py    CI: the constraints file for the minimum-versions leg
tests/test_release_check.py unit tests for tools/release_check.py
```

## Fixtures

`tests/make_fixtures.py` builds the fixture tree at test time (text files,
PDFs written by hand, images drawn with Pillow, Office files). It needs no
OCR engine, only Pillow. `tests/data/shot.heic` is the one
tracked binary: a HEIC encoding of the generated `photo.png`, used where
`sips` is not available to encode one. Regenerate it on a Mac with
`sips -s format heic photo.png --out tests/data/shot.heic` after changing
the photo text.

## Adapter versions

The three rga adapters (`ocrpdf`, `ocrimg`, `officexml`) carry a `version`
in `src/rga_ocr/setup_cmd.py`. rga keys its cache on it: bump the version
of an adapter whenever its output for the same input changes (text
extraction, paragraph grouping, page breaks), so that cached entries are
not served stale. A search through `rga-ocr` uses the new version at once;
plain `rga` picks it up after `rga-ocr setup --apply`. Say in the changelog
that the first search after the upgrade reads the files again.

## CI

GitHub Actions runs the suite on macOS (vision, tesseract), Ubuntu
(rapidocr, tesseract, and an `auto` leg that relies on `setup --apply`)
and Windows (rapidocr, winocr), plus a build job that checks the sdist and
wheel, installs the wheel into a clean venv and verifies that neither
PyMuPDF nor pillow-heif comes along. The build job also runs
`tools/check_licences.py` over an install with the `rapidocr` and
`tesseract` extras on Linux and runs the unit tests from the unpacked
sdist. The licence check reads the licence each distribution declares in
its metadata and accepts only names on its allow-list, which holds no GPL
or AGPL; it does not inspect files inside the wheels.

Further legs run beside these: macOS with rapidocr, Windows with
tesseract, Ubuntu with tesseract on Python 3.11 and 3.14, macOS with
vision on Python 3.14 (what the Homebrew formula ships), Ubuntu with
rapidocr on Python 3.13, and one Ubuntu
leg that installs the core, `rapidocr` and test dependencies at the floor
`pyproject.toml` names (`tools/min_constraints.py` writes the constraints
file). When you raise or add one of those, that leg tells you whether the
floor holds. The floors of `tesserocr`, the pyobjc packages and the winrt
packages are not tested, and neither are transitive dependencies, which
pip picks freely. The ripgrep-all archives, and in the tesseract legs the
Tesseract language files, are fetched through `tools/fetch_verified.py`,
which checks their SHA-256; the sums sit at the top of `ci.yml` next to
the versions. The `auto` leg is the exception: it lets `rga-ocr setup
--apply` and the test suite fetch the language files the way a user
would, without a pinned sum.

`lint / ruff` runs `ruff check .` with the rules named in
`pyproject.toml`. Locally: `pipx run ruff==0.17.5 check .` The same job
runs `python tools/release_check.py consistency`: `VERSION` is the newest
release `CHANGELOG.md` names, that section has a date and an entry, and
the link definitions at the foot name it.

The workflow also runs every Monday and can be started by hand. The
dependencies are open floors, so the weekly run is where a new release of
one of them shows up. A run on `main` is never cancelled by a later one:
the release workflow asks for the green run of the tagged commit.

The job names of all legs, of the build job and of `lint / ruff` are
required checks on `main`. Do not rename them without changing the
ruleset: a pull request whose check has another name waits for the old
one forever.

## Releases

`.github/workflows/release.yml` publishes through PyPI trusted publishing;
the repository holds no API token.

1. Dry run: start the workflow by hand ("Run workflow") on a branch whose
   `VERSION` in `src/rga_ocr/__init__.py` is a pre-release such as
   `0.2.0rc1`. It uploads to TestPyPI only. Install from there into a clean
   venv:
   `pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ rga-ocr==0.2.0rc1`.
2. Set `VERSION`, move the `[Unreleased]` entries in `CHANGELOG.md` under
   the new version, merge.
3. Wait for CI on the merge commit, then tag that commit on `main` as
   `vX.Y.Z` and push the tag. Before the push, the same check the workflow
   runs: `python tools/release_check.py tag vX.Y.Z --sha "$(git rev-parse origin/main)" --repo luca-rui/rga-ocr --wait 0`.
   The workflow refuses a tag that differs from `VERSION`, a changelog
   that does not name the version, a commit that is not on `main`, and a
   commit whose CI run on `main` is not green (a run still going is waited
   for, 40 minutes). Then it uploads to PyPI. Tags and PyPI versions are
   immutable: a wrong release is fixed by the next version.
4. The workflow creates the GitHub release `rga-ocr X.Y.Z` with the
   changelog section as its text.

When the tag check fails because CI on `main` was red or cancelled (a
runner that never came, for one), re-run the failed jobs of that CI run
and then re-run the release run; the tag stays. A re-run of the release
after a failed later job skips the files PyPI already holds. The check
asks for the whole CI run, so a leg that is not a required check on
`main` stops a release as well when it is red.

`tests/test_release_check.py` covers the script. The workflow itself runs
only on a tag or by hand: repeat the dry run after any change to
`release.yml`, including a Dependabot update of the actions it uses.

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
  the schema nor rebuild the WAL index at the same time (see Limits in `docs/reference.md`).
- The adapters run as `python -I -X utf8 -m rga_ocr.adapter MODE` with the
  interpreter `rga-ocr` was installed with, so there is one place that
  knows which engine packages exist and no launcher script to keep in sync.
  An adapter ends with `os._exit(0)` after flushing its output: rg aborts
  the whole search when a preprocessor exits non-zero, and the OCR
  libraries' native teardown at interpreter exit must not decide that.

## Style

Plain Python, standard library where it suffices, no framework for the
CLI. Keep the README, `docs/reference.md` and `docs/design/glossary.md` in step with
user-visible changes, and add a line to `CHANGELOG.md` under
`[Unreleased]`.
