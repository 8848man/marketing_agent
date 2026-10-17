"""macOS smoke rehearsal (IMP-12). Never signs in, never posts.

Run with the project's venv after the dashboard is up:
    .venv/bin/python .ucompany/scripts/mac_smoke.py --out smoke-artifacts

FAIL (exit 1): Chrome cannot be launched through Playwright with an app profile folder,
or the account check code path crashes. WARN: YouTube page details that depend on
YouTube's current markup or region (recorded in report.json + screenshot).
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from marketing_agent.dashboard import PDF_EXAMPLE_VIDEOS, _installed_chrome, watch_url  # noqa: E402
from marketing_agent.poster import VisibleChromePoster  # noqa: E402

PROBE = PDF_EXAMPLE_VIDEOS["UCxlc0Ky0aWoD8uI09ad44Tg"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="smoke-artifacts")
    out = Path(parser.parse_args().out)
    out.mkdir(parents=True, exist_ok=True)
    report: dict[str, object] = {"probe_video": PROBE}
    chrome = _installed_chrome()
    report["chrome_found"] = str(chrome) if chrome else ""
    if chrome is None:
        print("FAIL Google Chrome not found by the app's lookup")
        (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
        return 1
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "chrome-profile-youtube1"
        (root / "Default").mkdir(parents=True)
        # 1) the app's own account-check path on an allowed watch page
        poster = VisibleChromePoster(root, "Default", screenshot_dir=out)
        try:
            poster.inspect_account_email(PROBE)
            report["account_check"] = "SIGNED_IN (unexpected on a fresh profile)"
        except ValueError as exc:
            report["account_check"] = str(exc)
        except Exception as exc:  # launch problems surface here
            report["account_check"] = f"ERROR {type(exc).__name__}"
        # 2) page details + screenshot with the same launch options as the poster
        from playwright.sync_api import sync_playwright
        try:
            with sync_playwright() as playwright:
                context = playwright.chromium.launch_persistent_context(
                    user_data_dir=str(root), channel="chrome", headless=False,
                    no_viewport=True, locale="ko-KR", ignore_default_args=["--no-sandbox"],
                    args=["--profile-directory=Default"])
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(watch_url(PROBE), wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(6000)
                report["final_url"] = page.url
                report["html_lang"] = page.evaluate("document.documentElement.lang")
                page.mouse.wheel(0, 1600)
                page.wait_for_timeout(4000)
                report["comments_section"] = page.locator("ytd-comments#comments").count()
                report["signin_link_visible"] = page.locator(
                    "a[href*='accounts.google.com/ServiceLogin'], a[href*='youtube.com/signin']").count()
                page.screenshot(path=str(out / "watch-page-ko.png"), full_page=False)
                context.close()
            report["chrome_launch"] = "OK"
        except Exception as exc:
            report["chrome_launch"] = f"FAIL {type(exc).__name__}: {str(exc)[:200]}"
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["chrome_launch"] != "OK" or str(report["account_check"]).startswith("ERROR"):
        return 1
    for key, ok in (("account_check", report["account_check"] == "PROFILE_SIGNED_OUT"),
                    ("comments_section", report.get("comments_section", 0) >= 1),
                    ("html_lang", str(report.get("html_lang", "")).startswith("ko"))):
        if not ok:
            print(f"WARN {key}: check the screenshot (YouTube markup/region dependent)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
