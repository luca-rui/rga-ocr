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
  RGA_OCR_LANG            OCR languages, BCP 47, separated by commas or blanks
                          (de-DE,en-US);
                          unset or empty: the engine's default / auto-detection
  RGA_OCR_FORCE_OCR       "1": OCR every PDF page and append to the text layer
  RGA_OCR_NO_OCR          "1": PDF text layer only, no page is rendered or
                          OCR'd, and no picture on a slide is read; wins over
                          RGA_OCR_FORCE_OCR
  RGA_OCR_MIN_TEXT_CHARS  PDF page with fewer text-layer chars is OCR'd (20)
  RGA_OCR_RENDER_DPI      PDF render resolution for OCR (200)
  RGA_OCR_MAX_PIXELS      longest image side handed to the OCR engine (3000)
  RGA_OCR_PARAGRAPH_GAP   line gap, in line heights, that starts a new output line (0.7)
  RGA_OCR_MAX_FRAMES      frames read of one multi-frame image (500)
  RGA_OCR_MAX_OFFICE_MB   unpacked text read of one office file, in MB (256)
  RGA_OCR_MAX_PICTURES    pictures read of one pptx or odp file (200)
  RGA_OCR_REPORT          path of a report file: one line is appended when a file
                          starts, one when it is done, and one per error (the
                          file cannot be read), retry (the OCR engine failed;
                          rga-ocr drops the file from the cache so that it is
                          read again) or partial (some PDF pages or pictures
                          on slides could not be OCR'd; the rest stays cached),
                          one "skipped" line in place of start and done for
                          input that is no document of the adapter's type,
                          and a last "time" line with the run's figures
  RGA_OCR_TEXT_CACHE      directory of the content cache: the text of an input
                          is stored under the SHA-256 of its bytes and of the
                          settings, and a second input with the same bytes
                          (a copy, a renamed file, a member of an archive)
                          is answered from there without parsing or OCR
  RGA_OCR_TEXT_REFRESH    "1": the content cache is written but not read

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
import time
import zipfile

T0 = time.time()        # as near to the start of the process as the adapter gets

from rga_ocr import ADAPTER_VERSION, ENV_PREFIX, PROG  # noqa: E402

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
MAX_FRAMES = _env_num("MAX_FRAMES", 500, int)         # frames read of one multi-frame image
MAX_OFFICE_MB = _env_num("MAX_OFFICE_MB", 256, int)   # unpacked XML read of one office file
MAX_PICTURES = _env_num("MAX_PICTURES", 200, int)     # pictures OCR'd of one pptx or odp
# An image with a shorter side holds no text a reader could see (a rule, a
# bullet, a tracking pixel), and Apple Vision raises on a side of 2 pixels.
MIN_SIDE = 10
MAX_PICTURE_BYTES = 64 * 1024 * 1024                  # a larger picture in a slide deck is not read
PAGE_BREAK = "\x0c"


# ----------------------------------------------------------------- text

def clean(text):
    """De-hyphenate, join wrapped lines into one, drop NUL and form feeds."""
    text = text.replace("\x00", "").replace("\x0c", "").replace("­", "")
    text = re.sub(r"-\n(?=[a-zäöüß])", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def encode_out(text):
    return text.replace("\x00", "").encode("utf-8", "replace")


def write_out(text):
    sys.stdout.buffer.write(text if isinstance(text, bytes) else encode_out(text))
    sys.stdout.buffer.flush()


# ------------------------------------------------------------------ ocr

def frames(data):
    """Yield every frame of an encoded image as an RGB Pillow image: EXIF
    orientation applied, longest side capped at MAX_PIXELS. One frame at a
    time: a TIFF of a thousand pages does not sit in memory as a whole."""
    from PIL import Image, ImageOps, ImageSequence, UnidentifiedImageError
    try:
        import pi_heif
        pi_heif.register_heif_opener()
        heif = True
    except ImportError:
        heif = False
    try:
        src = Image.open(io.BytesIO(data))
    except UnidentifiedImageError:
        if not heif and is_heif(data):
            # not the file's fault and gone once pi-heif is there: a retry,
            # so that the empty result does not stay in the cache
            raise EngineFailure(MissingDecoder(
                "HEIC and HEIF need pi-heif, which is not installed here (no wheels for "
                "Python 3.15 or Windows on arm64 yet); use Python 3.11 to 3.14")) from None
        raise RuntimeError("not a decodable image") from None
    with src:
        for frame in ImageSequence.Iterator(src):
            img = to_rgb(ImageOps.exif_transpose(frame))
            if max(img.size) > MAX_PIXELS:
                img.thumbnail((MAX_PIXELS, MAX_PIXELS))
            else:
                img.load()
            yield img


def decode(data):
    """All frames of an encoded image as a list."""
    return list(frames(data))


def to_rgb(img):
    """An RGB copy of img with transparent areas white. A plain convert drops
    the alpha channel and shows whatever colour lies under it, usually black:
    dark text on a transparent background would turn black on black."""
    if img.mode == "RGB":
        return img
    if img.mode in ("RGBA", "LA", "PA", "La", "RGBa") or "transparency" in img.info:
        from PIL import Image
        rgba = img.convert("RGBA")
        white = Image.new("RGBA", rgba.size, "white")
        return Image.alpha_composite(white, rgba).convert("RGB")
    return img.convert("RGB")


HEIF_BRANDS = (b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"hevm", b"hevs", b"mif1", b"msf1")


def is_heif(data):
    """True for an ISO media file whose brand is one of the HEIF family."""
    return data[4:8] == b"ftyp" and data[8:12] in HEIF_BRANDS


class MissingDecoder(Exception):
    pass


class EngineFailure(Exception):
    """The OCR engine could not start or could not read an image the adapter
    decoded: a problem of this run (a model download without network, missing
    language data), not of the file. Reported as "retry", so that the file's
    empty result does not stay in the cache."""

    text = ""       # what the adapter read without the engine; written out all the same

    def __init__(self, cause):
        super().__init__(f"{cause.__class__.__name__}: {cause}".replace("\n", " "))


class OCR:
    """The configured engine plus paragraph grouping of its lines."""

    def __init__(self):
        t = time.monotonic()
        STATS["starts"] += 1
        try:
            from rga_ocr import engines
            langs = engines.parse_langs(os.environ.get(ENV_PREFIX + "LANG"))
            name = os.environ.get(ENV_PREFIX + "ENGINE", "").strip() or "auto"
            self.engine = engines.resolve(name, langs)(langs)
        except Exception as e:  # noqa: BLE001
            raise EngineFailure(e) from e
        finally:
            STATS["init"] += time.monotonic() - t

    def text(self, img):
        if min(img.size) < MIN_SIDE:
            return ""
        t = time.monotonic()
        STATS["pages"] += 1
        try:
            lines = self.engine.recognize(img)
        except Exception as e:  # noqa: BLE001
            raise EngineFailure(e) from e
        finally:
            STATS["ocr"] += time.monotonic() - t
        return paragraphs(lines)

    def text_of_bytes(self, data):
        """OCR the frames of an encoded image, MAX_FRAMES at most; returns
        list of texts. Frames beyond that are left out and reported: the
        text read so far is kept, the file counts as partly read."""
        texts = []
        for number, img in enumerate(frames(data), 1):
            if number > MAX_FRAMES:
                NOTES.append(f"more than {MAX_FRAMES} frames, the rest was not read "
                             f"({ENV_PREFIX}MAX_FRAMES raises the limit)")
                break
            texts.append(self.text(img))
        return texts


def paragraphs(lines, ordered=False):
    """Join lines that sit directly beneath each other into one line.
    lines: (top, x, height, text) in a top-down frame normalised to 0..1.
    ordered: the lines are in reading order already (PDF text layer); they are
    not sorted by position, and a jump back up the page (next column) starts
    a new output line."""
    if not lines:
        return ""
    if not ordered:
        lines = sorted(lines, key=lambda l: (l[0], l[1]))
    out, cur = [], [lines[0][3]]
    prev_top, _, prev_h, _ = lines[0]
    prev_bottom = prev_top + prev_h
    for top, _x, h, s in lines[1:]:
        gap = top - prev_bottom
        if ordered:
            joined = -(prev_h + h) < gap < PARAGRAPH_GAP * max(prev_h, h)
            prev_bottom = top + h
        else:
            joined = gap < PARAGRAPH_GAP * max(prev_h, h)
            prev_bottom = max(prev_bottom, top + h) if gap < 0 else top + h
        if joined:
            cur.append(s)
        else:
            out.append("\n".join(cur))
            cur = [s]
        prev_h = h
    out.append("\n".join(cur))
    return "\n".join(clean(p) for p in out if p.strip())


# ---------------------------------------------------------------- modes

def _text_layer(page):
    """The text layer of a PDF page in PDFium's reading order, wrapped lines
    joined like OCR output.

    PDFium's own line assembly is used for the words: its text rectangles
    (one per run of equal font) split words at kerning pairs and differ in
    top and height within one printed line, so ordering them by position
    shuffles the words. The character boxes only supply each line's position
    for the paragraph grouping."""
    width, height = page.get_size()
    tp = page.get_textpage()
    try:
        # explicit range: with the defaults pypdfium2 4.x reads by bounds,
        # which gives other positions and \x02 as the hyphen mark
        text = tp.get_text_range(0, tp.count_chars())
        lines, pos = [], 0
        # U+FFFE: PDFium's marker for a hyphen at a line end, the next printed
        # line follows without a line break.
        for part in re.split(r"(\r\n|\n|\r|\ufffe|\x02)", text):
            units = len(part.encode("utf-16-le")) // 2      # char indices are UTF-16 units
            if part in ("\ufffe", "\x02") and lines:
                lines[-1][3] += "-"
            elif part.strip():
                box = _line_box(tp, pos, units)
                if box:
                    left, bottom, right, top = box
                    lines.append([(height - top) / height, left / width,
                                  (top - bottom) / height, part.strip()])
            pos += units
    finally:
        tp.close()
    return paragraphs(lines, ordered=True)


def _line_box(tp, start, count):
    """Bounding box (left, bottom, right, top) of the visible characters in
    one text-layer line, or None."""
    box = None
    for i in range(start, start + count):
        try:
            left, bottom, right, top = tp.get_charbox(i)
        except Exception:  # noqa: BLE001  generated characters have no box
            continue
        if right <= left or top <= bottom:
            continue
        box = (left, bottom, right, top) if box is None else (
            min(box[0], left), min(box[1], bottom), max(box[2], right), max(box[3], top))
    return box


def mode_pdf(data):
    import pypdfium2
    no_ocr = os.environ.get(ENV_PREFIX + "NO_OCR") == "1"
    force = not no_ocr and os.environ.get(ENV_PREFIX + "FORCE_OCR") == "1"
    ocr = None
    pages, failed, tried = [], [], 0
    doc = pypdfium2.PdfDocument(data)
    try:
        for number, page in enumerate(doc, 1):
            layer = _text_layer(page)
            if not no_ocr and (force or len(layer.replace(" ", "")) < MIN_TEXT_CHARS):
                if ocr is None:
                    ocr = OCR()
                scale = min(RENDER_DPI / 72, MAX_PIXELS / max(page.get_size()))
                tried += 1
                try:
                    text = ocr.text(to_rgb(page.render(scale=scale).to_pil()))
                except EngineFailure as e:
                    failed.append((number, e))
                    text = ""
                layer = (layer + "\n" + text).strip() if force else text
            pages.append(layer)
            page.close()
    finally:
        doc.close()
    if failed:
        number, e = failed[0]
        if len(failed) == tried:
            # no page could be OCR'd: the engine is the problem, not one page
            raise e
        NOTES.append(f"OCR failed on {len(failed)} of {tried} pages, first page {number}: {e}")
    return PAGE_BREAK.join(pages)


def mode_image(data):
    texts = OCR().text_of_bytes(data)
    return "\n\n".join(t for t in texts if t)


# Elements that stand for white space, and the ends of the cells of one row
# (xlsx value/formula/inline string, ods/odp table cell, pptx table cell).
# Text runs (a:t, t, text:span) get no separator: one word is often split
# over several runs (a spelling mark, a change of format).
_XML_SPACE = r"<(?:text:s|text:tab|text:line-break|a:br|a:tab|w:tab|w:br)\b[^>]*>"
_XML_CELL_END = r"</(?:c|table:table-cell|a:tc)>|<(?:c|table:table-cell)\b[^>]*/>"


def _strip_xml(raw, para_tags):
    raw = re.sub(r"</(?:%s)>" % "|".join(para_tags), "\n", raw)
    raw = re.sub(_XML_SPACE, " ", raw)
    raw = re.sub(_XML_CELL_END, " ", raw)
    raw = re.sub(r"</f>", " ", raw)                  # xlsx: formula, then its value
    raw = re.sub(r"<[^>]+>", "", raw)
    raw = html.unescape(raw)
    lines = [clean(l) for l in raw.split("\n")]
    return "\n".join(l for l in lines if l)


class _Members:
    """Reads the XML members of an office file up to MAX_OFFICE_MB of
    unpacked text in total. The bytes read count, not the size the archive
    states: a few kilobytes can unpack to gigabytes. What lies beyond the
    limit is left out and reported once."""

    def __init__(self, z):
        self.z = z
        self.left = max(MAX_OFFICE_MB, 0) * 1024 * 1024
        self.cut = False

    def read(self, name):
        with self.z.open(name) as f:
            raw = f.read(self.left + 1)
        if len(raw) > self.left:
            raw = raw[:self.left]
            if not self.cut:
                self.cut = True
                NOTES.append(f"more than {MAX_OFFICE_MB} MB of text, read up to there, the rest "
                             f"from {name} on was not ({ENV_PREFIX}MAX_OFFICE_MB raises the limit)")
        self.left -= len(raw)
        return raw.decode("utf-8", "replace")


_PICTURE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp", ".heic", ".heif")


class _Pictures:
    """OCR of the pictures a slide shows (pptx, odp). A picture is read once
    per file, however many slides show it; vector formats (emf, wmf, svg)
    are passed over. With RGA_OCR_NO_OCR no picture is read."""

    def __init__(self, z):
        self.z = z
        self.names = set(z.namelist())
        self.off = os.environ.get(ENV_PREFIX + "NO_OCR") == "1"
        self.ocr = None
        self.down = None        # the engine did not start: no further picture is tried
        self.done = {}
        self.failed = []        # engine failures on single pictures
        self.unread = 0         # pictures that could not be decoded, or are too large
        self.capped = False

    def text(self, name):
        if self.off or self.down or name not in self.names or not name.lower().endswith(_PICTURE_EXT):
            return ""
        if name not in self.done:
            if len(self.done) >= MAX_PICTURES:
                self.capped = True
                return ""
            self.done[name] = self._read(name)
        return self.done[name]

    def _read(self, name):
        if self.ocr is None:
            try:
                self.ocr = OCR()
            except EngineFailure as e:
                self.down = e
                return ""
        try:
            with self.z.open(name) as f:
                data = f.read(MAX_PICTURE_BYTES + 1)
            if len(data) > MAX_PICTURE_BYTES:
                raise RuntimeError("picture too large")
            return "\n".join(t for t in self.ocr.text_of_bytes(data) if t)
        except EngineFailure as e:
            self.failed.append(e)
        except Exception:  # noqa: BLE001  one broken picture must not cost the text of the file
            self.unread += 1
        return ""

    def close(self, text):
        """Called with the text of the whole file: notes what was left out.
        When the engine did not start or read none of the pictures, the
        engine is the problem: the text goes out, and the file is read again
        by the next search."""
        if self.capped:
            NOTES.append(f"more than {MAX_PICTURES} pictures, the rest was not read "
                         f"({ENV_PREFIX}MAX_PICTURES raises the limit)")
        if self.unread:
            NOTES.append(f"{self.unread} of {len(self.done)} pictures could not be read")
        if self.down or self.failed:
            if self.down or len(self.failed) + self.unread == len(self.done):
                e = self.down or self.failed[0]
                e.text = text
                raise e
            NOTES.append(f"OCR failed on {len(self.failed)} of {len(self.done)} pictures: {self.failed[0]}")


def _with(text, *more):
    return "\n".join(t for t in (text, *more) if t)


def _pptx_pictures(m, names, slide):
    """The media members slide (ppt/slides/slideN.xml) shows, in the order
    of its relationships file."""
    import posixpath
    d, base = posixpath.split(slide)
    rels = f"{d}/_rels/{base}.rels"
    if rels not in names:
        return []
    found = []
    for rel in re.findall(r"<Relationship\b[^>]*>", m.read(rels)):
        target = re.search(r'\bTarget="([^"]*)"', rel)
        if target and re.search(r'\bType="[^"]*/image"', rel) and 'TargetMode="External"' not in rel:
            t = html.unescape(target.group(1))
            found.append(t.lstrip("/") if t.startswith("/") else posixpath.normpath(posixpath.join(d, t)))
    return found


def mode_office(data):
    pages = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        m = _Members(z)
        pictures = _Pictures(z)
        names = z.namelist()
        slides = sorted(
            (n for n in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
            key=lambda n: int(re.search(r"(\d+)\.xml$", n).group(1)))
        if slides:                                                   # pptx
            for n in slides:
                pages.append(_with(_strip_xml(m.read(n), ["a:p"]),
                                   *(pictures.text(p) for p in _pptx_pictures(m, names, n))))
        elif "xl/workbook.xml" in names:                             # xlsx
            parts = []
            if "xl/sharedStrings.xml" in names:
                parts.append(_strip_xml(m.read("xl/sharedStrings.xml"), ["si"]))
            for n in sorted(n for n in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)):
                raw = m.read(n)
                raw = re.sub(r'<c\b[^>]*\bt="s"[^>]*>.*?</c>', "", raw, flags=re.S)   # shared-string refs
                parts.append(_strip_xml(raw, ["row"]))
            pages.append("\n".join(p for p in parts if p))
        elif "content.xml" in names:                                 # ods / odp
            raw = m.read("content.xml")
            draw_pages = re.split(r"</draw:page>", raw)
            if len(draw_pages) > 1:                                  # odp
                # what follows the last page is not a page; an empty slide
                # in between is one, or the page numbers after it are off
                for p in draw_pages[:-1]:
                    shown = re.findall(r'<draw:image\b[^>]*\bxlink:href="([^"]*)"', p)
                    pages.append(_with(_strip_xml(p, ["text:p", "text:h"]),
                                       *(pictures.text(html.unescape(h).removeprefix("./")) for h in shown)))
            else:                                                    # ods
                pages.append(_strip_xml(raw, ["text:p", "text:h", "table:table-row"]))
        else:
            raise RuntimeError("unrecognised office container")
        text = PAGE_BREAK.join(pages)
        pictures.close(text)
    return text


MODES = {"pdf": mode_pdf, "image": mode_image, "office": mode_office}


REPORT = os.environ.get(ENV_PREFIX + "REPORT", "")
NOTES = []      # problems that left part of a file unread; reported as "partial"
# figures of this run for the "time" line: engine starts and their seconds,
# images handed to the engine and the seconds spent on them
STATS = {"starts": 0, "init": 0.0, "pages": 0, "ocr": 0.0}


def report(event, mode, path, detail=""):
    """Append one line to the report file in a single O_APPEND write, so the
    lines of parallel adapters do not interleave (short writes stay atomic;
    on Windows a lock stands in for that)."""
    if not REPORT:
        return
    try:
        # O_BINARY: Windows would write "\r\n" and leave a "\r" on every detail
        fd = os.open(REPORT, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o600)
        try:
            line = f"{event}\t{mode}\t{path}\t{detail}\n".replace("\r", " ")
            held = _report_lock(fd)
            try:
                os.write(fd, line.encode("utf-8", "replace")[:4000])
            finally:
                _report_unlock(fd, held)
        finally:
            os.close(fd)
    except OSError:
        pass


# Windows has no atomic append: O_APPEND there is a seek and a write, and two
# adapters that end at the same moment (two copies of one file do) write over
# each other's line. One byte far behind anything the file will hold is locked
# for the write; the reader of the file never gets there.
_LOCK_AT = 1 << 30


def _report_lock(fd):
    if sys.platform != "win32":
        return False
    try:
        import msvcrt
        os.lseek(fd, _LOCK_AT, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_LOCK, 1)      # waits, up to ten seconds
        return True
    except (ImportError, OSError):
        return False                                # write without it, as before


def _report_unlock(fd, held):
    if not held:
        return
    try:
        import msvcrt
        os.lseek(fd, _LOCK_AT, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    except (ImportError, OSError):
        pass


def report_time(mode, path, what):
    """The last line of a run: when the process started and ended, and what
    the time went into. what: read, hit (content cache) or skipped."""
    report("time", mode, path,
           f"t0={T0:.3f};t1={time.time():.3f};what={what};starts={STATS['starts']};"
           f"init={STATS['init']:.3f};pages={STATS['pages']};ocr={STATS['ocr']:.3f}")


# ------------------------------------------------------- not a document

# AppleDouble (the "._name" files macOS puts next to a file on foreign file
# systems and into every zip, below __MACOSX/) and AppleSingle
_APPLE_DOUBLE = (b"\x00\x05\x16\x07", b"\x00\x05\x16\x00")
_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_IMAGE_MAGIC = (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"GIF87a", b"GIF89a", b"BM",
                b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+")


def has_magic(mode, data):
    """True when data begins the way a file of the adapter's type does. Only
    used to tell a damaged document from input that never was one; a file
    without the mark is still handed to the parser first."""
    if mode == "pdf":
        return b"%PDF-" in data[:1024]              # PDFium looks that far
    if mode == "office":
        return data[:2] == b"PK" or data[:8] == _OLE
    if mode == "image":
        return (data.startswith(_IMAGE_MAGIC) or is_heif(data) or data[4:8] == b"ftyp"
                or (data[:4] == b"RIFF" and data[8:12] == b"WEBP"))
    return True


def not_a_document(mode, path, data):
    """Why data is certainly no document, or "": checked before any parser
    is imported, so the hundreds of "._" entries of a zip made on a Mac cost
    an interpreter start each and nothing more."""
    if data[:4] in _APPLE_DOUBLE:
        return "macOS metadata (AppleDouble), not a document"
    if not data.strip():
        return "empty file"
    name = re.split(r"[/\\]", path)[-1]
    if name.startswith("~$") and not has_magic(mode, data):
        return "lock file of an office program, not a document"
    return ""


_KIND = {"pdf": "a PDF", "image": "an image", "office": "an office file"}


def explain(mode, data, e):
    """One line for a file the parser gave up on, worded so that the same
    cause reads the same for every file: the CLI groups by this text."""
    msg = f"{e.__class__.__name__}: {e}".replace("\n", " ")
    if mode == "pdf" and "password" in msg.lower():
        return "password protected, not read (" + msg + ")"
    if mode == "office" and data[:8] == _OLE:
        return ("password protected, or an old binary format under a new extension, "
                "not read (" + msg + ")")
    return msg


# -------------------------------------------------------- content cache

TEXT_CACHE = os.environ.get(ENV_PREFIX + "TEXT_CACHE", "")


def text_key(mode, data):
    """SHA-256 of everything the output text depends on: the bytes, the mode,
    the adapter version, the engine and its languages, and the settings."""
    import hashlib
    env = [os.environ.get(ENV_PREFIX + k, "") for k in ("ENGINE", "LANG", "NO_OCR", "FORCE_OCR")]
    settings = [mode, ADAPTER_VERSION, *env, MIN_TEXT_CHARS, RENDER_DPI, MAX_PIXELS,
                PARAGRAPH_GAP, MAX_FRAMES, MAX_OFFICE_MB, MAX_PICTURES]
    h = hashlib.sha256("\x00".join(str(x) for x in settings).encode("utf-8", "replace"))
    h.update(b"\x00")
    h.update(data)
    return h.hexdigest()


def text_get(key):
    """The stored output for key as bytes, or None. A file that cannot be
    read or unpacked (cut off, damaged) is no hit."""
    if not TEXT_CACHE or os.environ.get(ENV_PREFIX + "TEXT_REFRESH") == "1":
        return None
    import zlib
    try:
        with open(os.path.join(TEXT_CACHE, key[:2], key), "rb") as f:
            return zlib.decompress(f.read())
    except (OSError, zlib.error):
        return None


def text_put(key, out):
    """Store out (bytes) for key: written next to its place and renamed, so a
    reader never sees half a file; for this user only, like rga's cache. A
    failure costs the next run the work and nothing else."""
    if not TEXT_CACHE:
        return
    import zlib
    d = os.path.join(TEXT_CACHE, key[:2])
    tmp = os.path.join(d, f"{key}.{os.getpid()}.tmp")
    try:
        for new in (TEXT_CACHE, d):         # makedirs gives its mode to the last one only
            os.makedirs(new, mode=0o700, exist_ok=True)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(zlib.compress(out, 1))
        os.replace(tmp, os.path.join(d, key))
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    path = sys.argv[2] if len(sys.argv) > 2 else ""
    if mode == "--check":
        # setup starts the adapter once this way: the interpreter and its
        # flags found the package, which rga would not tell anyone
        sys.stdout.write("ok\n")
        return
    fn = MODES.get(mode)
    if fn is None:
        sys.stderr.write(f"{TAG}: unknown mode {mode!r}\n")
        return
    data = sys.stdin.buffer.read()
    if not data:
        return
    why = not_a_document(mode, path, data)
    if why:
        report("skipped", mode, path, why)
        report_time(mode, path, "skipped")
        return
    key = text_key(mode, data) if TEXT_CACHE else ""
    hit = text_get(key) if key else None
    report("start", mode, path)
    if hit is not None:
        write_out(hit)
        report("done", mode, path)
        report_time(mode, path, "hit")
        return
    try:
        out = encode_out(fn(data))
        write_out(out)
        for note in NOTES:
            sys.stderr.write(f"{TAG}[{mode}]: {note}\n")
            report("partial", mode, path, note)
        if key and not NOTES:
            # only what was read in full: a partial result, a failure of the
            # engine or of the file must not answer for other copies
            text_put(key, out)
    except EngineFailure as e:
        if e.text:
            write_out(e.text)
        sys.stderr.write(f"{TAG}[{mode}]: {e}\n")
        report("retry", mode, path, str(e))
    except Exception as e:  # noqa: BLE001
        if not has_magic(mode, data):
            # never was a document of this type (a download page saved as
            # .pdf, a text file named .jpg): nothing to tell the user about
            report("skipped", mode, path, f"not {_KIND[mode]}")
            report_time(mode, path, "skipped")
            return
        msg = explain(mode, data, e)
        sys.stderr.write(f"{TAG}[{mode}]: {msg}\n")
        report("error", mode, path, msg)
    report("done", mode, path)
    report_time(mode, path, "read")


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
