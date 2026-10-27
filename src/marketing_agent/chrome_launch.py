"""Chrome discovery and the manual login window (no profile data is read)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
import re
import shutil
import subprocess


def _is_default_chrome_user_data_dir(path: Path) -> bool:
    """Whether Chrome 136+ will reject Playwright remote debugging for this root."""
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        candidates = [Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "User Data"]
        if local_app_data:
            candidates.append(Path(local_app_data) / "Google" / "Chrome" / "User Data")
    elif sys.platform == "darwin":
        candidates = [Path.home() / "Library" / "Application Support" / "Google" / "Chrome"]
    else:
        candidates = [Path.home() / ".config" / "google-chrome"]
    try:
        resolved = path.expanduser().resolve(strict=False)
        return any(resolved == candidate.expanduser().resolve(strict=False) for candidate in candidates)
    except OSError:
        return False


def _installed_chrome() -> Path | None:
    """Find installed Chrome without inspecting browser profile data."""
    candidates: list[Path] = []
    if os.name == "nt":
        for base in (os.getenv("PROGRAMFILES"), os.getenv("PROGRAMFILES(X86)"),
                     str(Path.home() / "AppData" / "Local")):
            if base:
                candidates.append(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe")
    elif sys.platform == "darwin":
        candidates.extend((Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                           Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome"))
    else:
        for name in ("google-chrome", "google-chrome-stable"):
            found = shutil.which(name)
            if found:
                candidates.append(Path(found))
    return next((candidate for candidate in candidates if candidate.is_file()), None)

# PDF p.2 example videos, one per "our channel". Used only as the watch page for
# account checks and the manual login window when no RSS video is loaded yet
# (ADR-0003). The program never opens YouTube home or Google account pages.
PDF_EXAMPLE_VIDEOS = {
    "UCxlc0Ky0aWoD8uI09ad44Tg": "akn-AvCeHBI",
    "UC-ee_ziASM251TMXe3P3VZA": "JjY09DSdzx0",
    "UC09L3JxGVcn7SKLa-pjTEmw": "DvxMfC_KjX0",
    "UCVdtDW-HF4KluixGaBAcI4w": "3K82-PjUeP0",
    "UCkGl2jieOVhGiHPdXF77Yyw": "WxXINTXQSd4",
}


def watch_url(video_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id or ""):
        raise ValueError("INVALID_VIDEO_ID")
    return f"https://www.youtube.com/watch?v={video_id}&hl=ko"


def _open_login_window(root: Path, video_id: str) -> subprocess.Popen:
    """Plain (non-automated) Chrome on an allowed watch page; the person signs in."""
    url = watch_url(video_id)
    chrome = _installed_chrome()
    if chrome is None:
        raise ValueError("CHROME_NOT_FOUND")
    try:
        return subprocess.Popen([str(chrome), f"--user-data-dir={root}",
                          "--profile-directory=Default", "--no-first-run",
                          "--no-default-browser-check", "--new-window", url],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, close_fds=True)
    except OSError as exc:
        raise ValueError("BROWSER_LAUNCH_FAILED") from exc
