"""Windows.Media.Ocr (Windows 10+, PyWinRT).

Windows ships the OCR engine itself; each language comes as an optional
feature ("Language.OCR~~~de-DE~0.0.1.0") that an administrator installs with
Add-WindowsCapability. One engine instance recognises one language, so the
first requested language that has a pack installed wins; with no language
requested the user's profile languages decide (what Windows does for its
own apps).
"""

import asyncio
import sys

from rga_ocr.engines import Engine, sanitize

WINRT_MODULES = ("winrt.windows.media.ocr", "winrt.windows.globalization",
                 "winrt.windows.graphics.imaging", "winrt.windows.storage.streams",
                 "winrt.windows.foundation", "winrt.windows.foundation.collections")


def capability_command(tag):
    return f'Add-WindowsCapability -Online -Name "Language.OCR~~~{tag}~0.0.1.0"'


def match_language(requested, installed):
    """The first requested tag with an installed pack: an exact match
    (case-insensitive), else the first installed tag with the same primary
    subtag ("de" matches "de-DE", "de-AT" matches "de-DE"). None if nothing
    matches."""
    inst = list(installed)
    lower = {t.lower(): t for t in inst}
    for want in requested:
        hit = lower.get(want.lower())
        if hit:
            return hit
        primary = want.split("-")[0].lower()
        for t in inst:
            if t.split("-")[0].lower() == primary:
                return t
    return None


def _ocr():
    from winrt.windows.media.ocr import OcrEngine
    return OcrEngine


def _installed():
    OcrEngine = _ocr()
    langs = getattr(OcrEngine, "available_recognizer_languages", None)
    if langs is None:                                   # PyWinRT 1.x naming
        langs = OcrEngine.get_available_recognizer_languages()
    return [lg.language_tag for lg in langs]


class WinOcrEngine(Engine):
    name = "winocr"
    extra = "winocr"
    modules = tuple(WINRT_MODULES)

    @classmethod
    def available(cls, langs):
        if sys.platform != "win32":
            return False, "Windows only"
        if not cls.installed():
            return False, cls.install_hint()
        try:
            installed = _installed()
        except Exception as e:  # noqa: BLE001 - a broken WinRT install reads as unavailable
            return False, f"WinRT failed: {e}"
        if not installed:
            want = langs[0] if langs else "en-US"
            return False, f"no OCR language pack installed; run as administrator: {capability_command(want)}"
        if langs and match_language(langs, installed) is None:
            return False, (f"no OCR language pack for {', '.join(langs)} (installed: {', '.join(installed)}); "
                           f"run as administrator: {capability_command(langs[0])}")
        return True, ""

    @classmethod
    def lang_tag(cls, langs):
        """The pack that will do the work: "de,en" with only en-US installed
        is cached as en-US, so a pack installed later gets its own cache."""
        if langs:
            try:
                tag = match_language(langs, _installed())
            except Exception:  # noqa: BLE001 - no WinRT here: the requested tags name the cache
                tag = None
            if tag:
                return sanitize(tag)
        return super().lang_tag(langs)

    def __init__(self, langs):
        super().__init__(langs)
        from winrt.windows.globalization import Language
        from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
        from winrt.windows.storage.streams import DataWriter
        OcrEngine = _ocr()
        self.bitmap_cls = SoftwareBitmap
        self.pixel_format = BitmapPixelFormat.RGBA8
        self.writer_cls = DataWriter
        if self.langs:
            tag = match_language(self.langs, _installed())
            if tag is None:
                raise RuntimeError(f"no OCR language pack for {', '.join(self.langs)}")
            self.engine = OcrEngine.try_create_from_language(Language(tag))
        else:
            self.engine = OcrEngine.try_create_from_user_profile_languages()
        if self.engine is None:
            raise RuntimeError("Windows OCR engine could not be created")
        self.max_dim = int(getattr(OcrEngine, "max_image_dimension", 0) or 0)

    def _bitmap(self, img):
        if self.max_dim and max(img.size) > self.max_dim:
            img = img.copy()
            img.thumbnail((self.max_dim, self.max_dim))
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        writer = self.writer_cls()
        writer.write_bytes(img.tobytes())
        bitmap = self.bitmap_cls.create_copy_from_buffer(
            writer.detach_buffer(), self.pixel_format, img.width, img.height)
        return bitmap, img.size

    def recognize(self, img):
        bitmap, (w, h) = self._bitmap(img)

        async def run():
            return await self.engine.recognize_async(bitmap)

        result = asyncio.run(run())
        lines = []
        for line in result.lines:
            rects = [wd.bounding_rect for wd in line.words]
            if not rects:
                continue
            top = min(r.y for r in rects)
            bottom = max(r.y + r.height for r in rects)
            left = min(r.x for r in rects)
            lines.append((top / h, left / w, (bottom - top) / h, line.text))
        return lines


ENGINE = WinOcrEngine
