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
not served stale. Users pick the new version up with
`rga-ocr setup --apply`.

## CI

GitHub Actions runs the suite on macOS (vision, tesseract), Ubuntu
(rapidocr, tesseract, and an `auto` leg that relies on `setup --apply`)
and Windows (rapidocr, winocr), plus a build job that checks the sdist and
wheel, installs the wheel into a clean venv and verifies that neither
PyMuPDF nor pillow-heif comes along.

## Style

Plain Python, standard library where it suffices, no framework for the
CLI. Keep the README and `docs/design/glossary.md` in step with
user-visible changes, and add a line to `CHANGELOG.md` under
`[Unreleased]`.
