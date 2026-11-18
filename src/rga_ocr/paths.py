"""Where rga-ocr and ripgrep-all keep their files on each platform.

                 macOS                                   Linux                       Windows
  profile        ~/.config/rga-ocr/config                same (XDG_CONFIG_HOME)      %APPDATA%\\rga-ocr\\config
  cache          ~/Library/Caches/rga-ocr                ~/.cache/rga-ocr            %LOCALAPPDATA%\\rga-ocr\\Cache
  data           ~/Library/Application Support/rga-ocr   ~/.local/share/rga-ocr      %APPDATA%\\rga-ocr
  rga config     ~/Library/Application Support/ripgrep-all/config.jsonc
                                                         ~/.config/ripgrep-all/config.jsonc
                                                                                     %APPDATA%\\ripgrep-all\\config\\config.jsonc

The profile stays under ~/.config on macOS on purpose (platformdirs would
put it under Application Support). The rga path follows the directories-next
crate rga uses, which differs from platformdirs on Windows.
"""

import os
import sys

from platformdirs import PlatformDirs

from rga_ocr import PROG

_dirs = PlatformDirs(PROG, appauthor=False, roaming=True)


def _xdg_config_home():
    return os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")


def profile_path():
    """The tool's own settings file."""
    if sys.platform == "win32":
        return os.path.join(_dirs.user_config_dir, "config")
    return os.path.join(_xdg_config_home(), PROG, "config")


def cache_dir():
    """Default OCR cache root (one sub-directory per engine and language)."""
    return _dirs.user_cache_dir


def data_dir():
    """Engine data the tool fetches itself, e.g. Tesseract language files."""
    return _dirs.user_data_dir


def tessdata_dir():
    return os.path.join(data_dir(), "tessdata")


def rga_config_path():
    """ripgrep-all's config.jsonc, where it reads custom adapters from."""
    home = os.path.expanduser("~")
    if sys.platform == "darwin":
        base = os.path.join(home, "Library", "Application Support", "ripgrep-all")
    elif sys.platform == "win32":
        base = os.path.join(os.environ.get("APPDATA") or os.path.join(home, "AppData", "Roaming"),
                            "ripgrep-all", "config")
    else:
        base = os.path.join(_xdg_config_home(), "ripgrep-all")
    return os.path.join(base, "config.jsonc")
