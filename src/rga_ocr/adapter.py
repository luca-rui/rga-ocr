#!/usr/bin/env python3
"""ripgrep-all custom adapter: stdin -> text.

Modes (argv[1]); argv[2] is the virtual path, for progress reports only:
  pdf     text layer per page via pypdfium2 (PDFium), OCR for pages without one;
          pages separated by form feed (\\x0c) so rga's postprocpagebreaks
          adds "Page N: " prefixes
  image   OCR (jpg, png, heic, tiff, webp, gif, bmp; decoded by Pillow)
  office  xlsx, pptx, ods, odp (zip of XML); pptx/odp slides as pages

Environment (set by rga-ocr from the profile, flags, or directly):
  RGA_OCR_ENGINE          OCR engine name (vision, winocr, rapidocr, tesseract,
                          or a registered one); unset: the platform's auto pick
  RGA_OCR_LANG            comma separated OCR languages, BCP 47 (de-DE,en-US);
                          unset or empty: the engine's default / auto-detection
  RGA_OCR_FORCE_OCR       "1": OCR every PDF page and append to the text layer
  RGA_OCR_NO_OCR          "1": PDF text layer only, no page is rendered or
                          OCR'd; wins over RGA_OCR_FORCE_OCR
  RGA_OCR_MIN_TEXT_CHARS  PDF page with fewer text-layer chars is OCR'd (20)
  RGA_OCR_RENDER_DPI      PDF render resolution for OCR (200)
  RGA_OCR_MAX_PIXELS      longest image side handed to the OCR engine (3000)
  RGA_OCR_PARAGRAPH_GAP   line gap, in line heights, that starts a new output line (0.7)
  RGA_OCR_REPORT          path of a report file: one line is appended when a file
                          starts, one when it is done, one per error (rga-ocr's
                          status line and error forwarding read it)

Rules: never open the virtual path (archive members do not exist on disk),
never exit non-zero (rg would abort with exit 2), never emit NUL bytes.
rg discards the stderr of a preprocessor that exits 0, so errors are only
visible through the report file.
"""

import html
import io
import os
import re
import sys
import zipfile

from rga_ocr import ENV_PREFIX, PROG

TAG = PROG + " adapter"


def _env_num(name, default, cast):
    name = ENV_PREFIX + name
    raw = os.environ.get(name, "")
    try:
        return cast(raw) if raw.strip() else default
    except ValueError:
        sys.stderr.write(f"{TAG}: ignoring {name}={raw!r}\n")
        return default


MIN_TEXT_CHARS = _env_num("MIN_TEXT_CHARS", 20, int)   # PDF page with fewer chars -> OCR
RENDER_DPI = _env_num("RENDER_DPI", 200, int)
MAX_PIXELS = _env_num("MAX_PIXELS", 3000, int)        # longest image side handed to the engine
PARAGRAPH_GAP = _env_num("PARAGRAPH_GAP", 0.7, float)
PAGE_BREAK = "\x0c"


# ----------------------------------------------------------------- text

def clean(text):
    """De-hyphenate, join wrapped lines into one, drop NUL and form feeds."""
    text = text.replace("\x00", "").replace("\x0c", "").replace("­", "")
    text = re.sub(r"-\n(?=[a-zäöüß])", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def write_out(text):
    text = text.replace("\x00", "")
    sys.stdout.buffer.write(text.encode("utf-8", "replace"))
    sys.stdout.buffer.flush()


# ------------------------------------------------------------------ ocr

def decode(data):
    """Every frame of an encoded image as an RGB Pillow image: EXIF orientation
    applied, longest side capped at MAX_PIXELS."""
    from PIL import Image, ImageOps, ImageSequence, UnidentifiedImageError
    try:
        import pi_heif
        pi_heif.register_heif_opener()
    except ImportError:
        pass
    try:
        src = Image.open(io.BytesIO(data))
    except UnidentifiedImageError:
        raise RuntimeError("not a decodable image") from None
    frames = []
    with src:
        for frame in ImageSequence.Iterator(src):
            img = ImageOps.exif_transpose(frame)
            if img.mode != "RGB":
                img = img.convert("RGB")
            if max(img.size) > MAX_PIXELS:
                img.thumbnail((MAX_PIXELS, MAX_PIXELS))
            else:
                img.load()
            frames.append(img)
    return frames


class OCR:
    """The configured engine plus paragraph grouping of its lines."""

    def __init__(self):
        from rga_ocr import engines
        langs = engines.parse_langs(os.environ.get(ENV_PREFIX + "LANG"))
        name = os.environ.get(ENV_PREFIX + "ENGINE", "").strip() or "auto"
        self.engine = engines.resolve(name, langs)(langs)

    def text(self, img):
        return paragraphs(self.engine.recognize(img))

    def text_of_bytes(self, data):
        """OCR every frame of an encoded image; returns list of texts."""
        return [self.text(img) for img in decode(data)]


def paragraphs(lines):
    """Join lines that sit directly beneath each other into one line.
    lines: (top, x, height, text) in a top-down frame normalised to 0..1."""
    if not lines:
        return ""
    lines = sorted(lines, key=lambda l: (l[0], l[1]))
    out, cur = [], [lines[0][3]]
    prev_top, _, prev_h, _ = lines[0]
    prev_bottom = prev_top + prev_h
    for top, _x, h, s in lines[1:]:
        gap = top - prev_bottom
        if gap < PARAGRAPH_GAP * max(prev_h, h):
            cur.append(s)
        else:
            out.append("\n".join(cur))
            cur = [s]
        prev_bottom = max(prev_bottom, top + h) if gap < 0 else top + h
        prev_h = h
    out.append("\n".join(cur))
    return "\n".join(clean(p) for p in out if p.strip())


# ---------------------------------------------------------------- modes

def _text_layer(page):
    """The text lines of a PDF page, grouped like OCR output: one tuple per
    pdfium text rectangle in the (top, x, height, text) frame paragraphs()
    expects (top-down, normalised to 0..1)."""
    width, height = page.get_size()
    tp = page.get_textpage()
    try:
        lines = []
        for i in range(tp.count_rects()):
            left, bottom, right, top = tp.get_rect(i)
            s = tp.get_text_bounded(left=left, bottom=bottom, right=right, top=top).strip()
            if s:
                lines.append(((height - top) / height, left / width, (top - bottom) / height, s))
    finally:
        tp.close()
    return paragraphs(lines)


def mode_pdf(data):
    import pypdfium2
    no_ocr = os.environ.get(ENV_PREFIX + "NO_OCR") == "1"
    force = not no_ocr and os.environ.get(ENV_PREFIX + "FORCE_OCR") == "1"
    ocr = None
    pages = []
    doc = pypdfium2.PdfDocument(data)
    try:
        for page in doc:
            layer = _text_layer(page)
            if not no_ocr and (force or len(layer.replace(" ", "")) < MIN_TEXT_CHARS):
                if ocr is None:
                    ocr = OCR()
                scale = min(RENDER_DPI / 72, MAX_PIXELS / max(page.get_size()))
                img = page.render(scale=scale).to_pil()
                if img.mode != "RGB":
                    img = img.convert("RGB")
                text = ocr.text(img)
                layer = (layer + "\n" + text).strip() if force else text
            pages.append(layer)
            page.close()
    finally:
        doc.close()
    return PAGE_BREAK.join(pages)


def mode_image(data):
    texts = OCR().text_of_bytes(data)
    return "\n\n".join(t for t in texts if t)


def _strip_xml(raw, para_tags, cell_sep=" "):
    raw = re.sub(r"</(?:%s)>" % "|".join(para_tags), "\n", raw)
    raw = re.sub(r"</(?:w:t|a:t|t|text:span)>", cell_sep, raw)
    raw = re.sub(r"<[^>]+>", "", raw)
    raw = html.unescape(raw)
    lines = [clean(l) for l in raw.split("\n")]
    return "\n".join(l for l in lines if l)


def mode_office(data):
    pages = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        slides = sorted(
            (n for n in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
            key=lambda n: int(re.search(r"(\d+)\.xml$", n).group(1)))
        if slides:                                                   # pptx
            for n in slides:
                pages.append(_strip_xml(z.read(n).decode("utf-8", "replace"), ["a:p"]))
        elif "xl/workbook.xml" in names:                             # xlsx
            parts = []
            if "xl/sharedStrings.xml" in names:
                parts.append(_strip_xml(z.read("xl/sharedStrings.xml").decode("utf-8", "replace"), ["si"]))
            for n in sorted(n for n in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)):
                raw = z.read(n).decode("utf-8", "replace")
                raw = re.sub(r'<c\b[^>]*\bt="s"[^>]*>.*?</c>', "", raw, flags=re.S)   # shared-string refs
                parts.append(_strip_xml(raw, ["row"]))
            pages.append("\n".join(p for p in parts if p))
        elif "content.xml" in names:                                 # ods / odp
            raw = z.read("content.xml").decode("utf-8", "replace")
            draw_pages = re.split(r"</draw:page>", raw)
            if len(draw_pages) > 1:                                  # odp
                for p in draw_pages:
                    t = _strip_xml(p, ["text:p", "text:h"])
                    if t:
                        pages.append(t)
            else:                                                    # ods
                pages.append(_strip_xml(raw, ["text:p", "text:h", "table:table-row"]))
        else:
            raise RuntimeError("unrecognised office container")
    return PAGE_BREAK.join(pages)


MODES = {"pdf": mode_pdf, "image": mode_image, "office": mode_office}


REPORT = os.environ.get(ENV_PREFIX + "REPORT", "")


def report(event, mode, path, detail=""):
    """Append one line to the report file in a single O_APPEND write, so the
    lines of parallel adapters do not interleave (short writes stay atomic)."""
    if not REPORT:
        return
    try:
        fd = os.open(REPORT, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            line = f"{event}\t{mode}\t{path}\t{detail}\n".replace("\r", " ")
            os.write(fd, line.encode("utf-8", "replace")[:4000])
        finally:
            os.close(fd)
    except OSError:
        pass


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    path = sys.argv[2] if len(sys.argv) > 2 else ""
    fn = MODES.get(mode)
    if fn is None:
        sys.stderr.write(f"{TAG}: unknown mode {mode!r}\n")
        return
    data = sys.stdin.buffer.read()
    if not data:
        return
    report("start", mode, path)
    try:
        write_out(fn(data))
    except Exception as e:  # noqa: BLE001
        msg = f"{e.__class__.__name__}: {e}".replace("\n", " ")
        sys.stderr.write(f"{TAG}[{mode}]: {msg}\n")
        report("error", mode, path, msg)
    report("done", mode, path)


if __name__ == "__main__":
    main()
    # rg aborts the whole search (exit 2) when a preprocessor exits non-zero,
    # and the OCR libraries run native teardown code at interpreter exit
    # (seen: onnxruntime's telemetry shutdown spinning forever). Everything is
    # written and flushed by now, so end the process here.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except (OSError, ValueError):
            pass
    os._exit(0)
