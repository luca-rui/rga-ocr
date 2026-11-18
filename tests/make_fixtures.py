#!/usr/bin/env python3
"""Build the end-to-end test fixtures into the directory given as argv[1].

Needle: "Wartungsvertrag Kesselanlage". Every fixture is either a hit with a
known shape or a decoy that must stay silent. Needs only Pillow: raster text
is drawn with Pillow's bundled font, PDFs are written by hand (standard
Helvetica, so no font embedding), HEIC comes from macOS `sips` or the tracked
sample in tests/data/.
"""
import io
import os
import shutil
import subprocess
import sys
import textwrap
import zipfile

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
NEEDLE = "Wartungsvertrag Kesselanlage"
FILLER = ("Lorem ipsum dolor sit amet, consectetur adipiscing elit. "
          "Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. ")


# ---------------------------------------------------------------- raster

def text_image(text, rotate=0, width=1250, height=625, size=42):
    """White image with the text in black, one line per \\n; rotate is
    counter-clockwise degrees (a page rotated 270 clockwise = 90 here)."""
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=size)
    y = 60
    for line in text.split("\n"):
        draw.text((60, y), line, fill="black", font=font)
        y += int(size * 1.4)
    if rotate:
        img = img.rotate(rotate, expand=True)
    return img


def png_bytes(img):
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def jpeg_bytes(img, orientation=None):
    """JPEG with the pixels as given and, optionally, an EXIF orientation tag."""
    buf = io.BytesIO()
    if orientation is None:
        img.save(buf, "JPEG", quality=90)
    else:
        exif = Image.Exif()
        exif[0x0112] = orientation
        img.save(buf, "JPEG", quality=90, exif=exif.tobytes())
    return buf.getvalue()


def write_heic(png, path):
    """HEIC through macOS sips, else the tracked sample (same content);
    returns False when neither is possible."""
    sample = os.path.join(HERE, "data", "shot.heic")
    if sys.platform == "darwin" and os.path.exists("/usr/bin/sips"):
        src = path + ".png"
        with open(src, "wb") as f:
            f.write(png)
        r = subprocess.run(["/usr/bin/sips", "-s", "format", "heic", src, "--out", path],
                           capture_output=True, text=True)
        os.remove(src)
        if r.returncode == 0 and os.path.exists(path):
            return True
        print("sips failed:", r.stderr.strip(), file=sys.stderr)
    if os.path.exists(sample):
        shutil.copy(sample, path)
        return True
    print("heic fixture skipped: no encoder and no sample", file=sys.stderr)
    return False


# ------------------------------------------------------------------- pdf

def _pdf_string(s):
    """A PDF literal string in WinAnsiEncoding (Helvetica's encoding here)."""
    raw = s.encode("cp1252")
    return b"(" + raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)") + b")"


def write_pdf(path, pages):
    """A minimal PDF 1.4. pages: list of dicts with
    width, height (points), lines: [(x, baseline_y, fontsize, text)],
    jpeg: bytes drawn over the whole page (image-only pages)."""
    objs = {1: b"<< /Type /Catalog /Pages 2 0 R >>",
            3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"}
    kids, n = [], 4
    for pg in pages:
        w, h = pg["width"], pg["height"]
        res, content = b"/Font << /F1 3 0 R >>", b""
        if pg.get("jpeg"):
            jpeg = pg["jpeg"]
            img = Image.open(io.BytesIO(jpeg))
            objs[n] = (b"<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceRGB "
                       b"/BitsPerComponent 8 /Filter /DCTDecode /Length %d >>\nstream\n"
                       % (img.width, img.height, len(jpeg)) + jpeg + b"\nendstream")
            res += b" /XObject << /Im1 %d 0 R >>" % n
            content += b"q %d 0 0 %d 0 0 cm /Im1 Do Q\n" % (w, h)
            n += 1
        for x, y, size, text in pg.get("lines", []):
            content += b"BT /F1 %d Tf %d %d Td %s Tj ET\n" % (size, x, y, _pdf_string(text))
        objs[n] = b"<< /Length %d >>\nstream\n" % len(content) + content + b"endstream"
        cid, n = n, n + 1
        objs[n] = (b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Resources << %s >> "
                   b"/Contents %d 0 R >>" % (w, h, res, cid))
        kids.append(n)
        n += 1
    objs[2] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (
        b" ".join(b"%d 0 R" % k for k in kids), len(kids))
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = {}
    for num in sorted(objs):
        offsets[num] = out.tell()
        out.write(b"%d 0 obj\n" % num + objs[num] + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % n)
    for num in range(1, n):
        out.write(b"%010d 00000 n \n" % offsets[num])
    out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (n, xref))
    with open(path, "wb") as f:
        f.write(out.getvalue())


def text_lines(text, size, top, left=50, width_chars=80):
    """Wrap text like a text box would: explicit newlines kept, long lines
    wrapped; returns (x, baseline, size, line) tuples at 1.2 line spacing."""
    out, y = [], top
    for para in text.split("\n"):
        for line in textwrap.wrap(para, width_chars) or [""]:
            out.append((left, y, size, line))
            y -= int(size * 1.2)
    return out


def zip_doc(path, members):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, body in members.items():
            z.writestr(name, body)


def main(root):
    if os.path.exists(root):
        shutil.rmtree(root)
    os.makedirs(os.path.join(root, "sub", ".hidden"))
    os.makedirs(os.path.join(root, "Ordner " + NEEDLE))
    os.makedirs(os.path.join(root, ".git", "objects"))
    os.makedirs(os.path.join(root, "node_modules", "pkg"))
    def j(*p):
        return os.path.join(root, *p)

    # name hits (contents are binary garbage, must not match by content)
    with open(j("Angebot_Wartungsvertrag_Kesselanlage_2026.bin"), "wb") as f:
        f.write(b"\x00\x01\x02 binary " * 100)
    # plain text, hit on line 2
    with open(j("notes.txt"), "w") as f:
        f.write("Besprechung 2026-03-01\nAngebot " + NEEDLE + " Nord liegt vor.\nNächster Termin offen.\n")
    # long line in plain text (snippet window test, no page prefix)
    with open(j("long.txt"), "w") as f:
        f.write("kurz\n" + FILLER * 3 + "Mitte " + NEEDLE + " Ende. " + FILLER * 3 + "\n")
    # hidden markdown
    with open(j("sub", ".hidden", "secret.md"), "w") as f:
        f.write("# Intern\n\n" + NEEDLE + " läuft bis 2027.\n")
    # excluded dirs
    with open(j(".git", "objects", "x"), "w") as f:
        f.write(NEEDLE + "\n")
    with open(j("node_modules", "pkg", "index.js"), "w") as f:
        f.write("// " + NEEDLE + "\n")
    # text-layer PDF: page 1 filler, page 2 the needle wrapped across two lines
    write_pdf(j("textlayer.pdf"), [
        {"width": 595, "height": 842, "lines": text_lines(FILLER * 5, 11, 790, width_chars=85)},
        {"width": 595, "height": 842, "lines": text_lines(
            "Sehr geehrte Damen und Herren, anbei der Wartungsvertrag\nKesselanlage Nord "
            "zur Unterschrift. " + FILLER, 12, 790, width_chars=40)},
    ])
    # image-only PDF (scan)
    scan = text_image("Scan: " + NEEDLE + "\nSeite eins")
    write_pdf(j("sub", "scan.pdf"), [{"width": 600, "height": 300, "jpeg": jpeg_bytes(scan)}])
    # images
    photo = text_image("Foto vom Dokument\n" + NEEDLE + "\nAbschnitt 3")
    png_photo = png_bytes(photo)
    with open(j("photo.png"), "wb") as f:
        f.write(png_photo)
    for name in ("photo.jpg", "IMG_0001.JPG"):
        with open(j(name), "wb") as f:
            f.write(jpeg_bytes(photo, orientation=1))
    with open(j("sub", "shot.png"), "wb") as f:
        f.write(png_photo)
    # rotated: pixels stored rotated 270 cw, EXIF says rotate 90 cw to display
    rotated = text_image(NEEDLE + "\ngedreht aufgenommen", rotate=90)
    with open(j("rotated.jpg"), "wb") as f:
        f.write(jpeg_bytes(rotated, orientation=6))
    # heic (skipped when neither sips nor the tracked sample is available)
    write_heic(png_photo, j("shot.heic"))
    # decoys
    with open(j("decoy.png"), "wb") as f:
        f.write(png_bytes(text_image("Rechnung Nr. 4711\nBetrag 120 EUR")))
    write_pdf(j("decoy.pdf"), [{"width": 595, "height": 842,
                                "lines": [(50, 760, 11, "Nur Filler, nichts zu finden")]}])
    # office documents
    ct = ('<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>{}</Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="{}"/></Relationships>')
    zip_doc(j("vertrag.docx"), {
        "[Content_Types].xml": ct.format('<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'),
        "_rels/.rels": rels.format("word/document.xml"),
        "word/document.xml": '<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
                             '<w:p><w:r><w:t>Vertragsentwurf</w:t></w:r></w:p>'
                             '<w:p><w:r><w:t xml:space="preserve">Gegenstand: </w:t></w:r><w:r><w:t>' + NEEDLE + '</w:t></w:r></w:p>'
                             '</w:body></w:document>',
    })
    zip_doc(j("tabelle.xlsx"), {
        "[Content_Types].xml": ct.format('<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'),
        "_rels/.rels": rels.format("xl/workbook.xml"),
        "xl/workbook.xml": '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheets><sheet name="Blatt1" sheetId="1" r:id="rId1" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/></sheets></workbook>',
        "xl/sharedStrings.xml": '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="2" uniqueCount="2"><si><t>Position</t></si><si><t>' + NEEDLE + ' Süd</t></si></sst>',
        "xl/worksheets/sheet1.xml": '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c></row><row r="2"><c r="A2" t="s"><v>1</v></c><c r="B2"><v>1500</v></c></row></sheetData></worksheet>',
    })
    slide = '<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>{}</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>'
    zip_doc(j("deck.pptx"), {
        "[Content_Types].xml": ct.format('<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'),
        "_rels/.rels": rels.format("ppt/presentation.xml"),
        "ppt/presentation.xml": '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"/>',
        "ppt/slides/slide1.xml": slide.format("Agenda"),
        "ppt/slides/slide2.xml": slide.format("Status " + NEEDLE),
        # slide 3: the needle sits deep inside a long paragraph (snippet window test)
        "ppt/slides/slide3.xml": slide.format(FILLER * 3 + "Anhang " + NEEDLE + " Ost. " + FILLER * 3),
    })
    # archive with an image inside
    with open(j("photo.jpg"), "rb") as f:
        jpg = f.read()
    with zipfile.ZipFile(j("bundle.zip"), "w") as z:
        z.writestr("readme.txt", "nothing here\n")
        z.writestr("needle.jpg", jpg)
    print("fixtures written to", root)


if __name__ == "__main__":
    main(sys.argv[1])
