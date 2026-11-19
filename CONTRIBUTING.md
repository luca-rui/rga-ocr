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
tesseract, Ubuntu with tesseract on Python 3.11 and 3.14, and one Ubuntu
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
`pyproject.toml`. Locally: `pipx run ruff==0.17.5 check .`

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
3. Tag the merge commit on `main` as `vX.Y.Z` and push the tag. The
   workflow refuses a tag that differs from `VERSION` or points at a commit
   that is not on `main`, then uploads to PyPI. Tags and PyPI versions are
   immutable: a wrong release is fixed by the next version.
4. Create the GitHub release from the tag with the changelog section.

Repeat the dry run after any change to `release.yml`, including a
Dependabot update of the actions it uses: CI does not exercise that
workflow.

## Style

Plain Python, standard library where it suffices, no framework for the
CLI. Keep the README and `docs/design/glossary.md` in step with
user-visible changes, and add a line to `CHANGELOG.md` under
`[Unreleased]`.
