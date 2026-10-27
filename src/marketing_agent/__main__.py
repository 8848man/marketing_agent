"""Command line entry point for the marketing agent."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys
from time import sleep

import yaml

from .config import load_config
from .logging import EventLogger
from .pipeline import run_cycle
from .storage import Store
from .watcher import cycle_times


APP_ROOT = Path(__file__).resolve().parents[2]


def _app_path(value: str | Path) -> Path:
    """Keep dashboard reads and writes inside the downloaded app folder."""
    path = Path(value)
    resolved = (APP_ROOT / path if not path.is_absolute() else path).resolve()
    if not resolved.is_relative_to(APP_ROOT):
        raise ValueError("DASHBOARD_PATH_OUTSIDE_APP")
    return resolved


def _load_test_videos(config_name: str | None) -> list[dict]:
    if not config_name:
        return []
    config_path = _app_path(config_name)
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("dashboard_test_videos"), list):
        raise ValueError("TEST_VIDEO_CONFIG_INVALID")
    entries = data["dashboard_test_videos"]
    from .posting_service import _test_cards
    _test_cards(entries)
    return entries


def _register_owned_test_video(db_path: Path, work_dir: Path, entries: list[dict],
                               video_id: str, evidence_name: str) -> None:
    from .posting_service import _test_cards
    cards = _test_cards(entries)
    if video_id not in cards:
        raise ValueError("TEST_VIDEO_NOT_CONFIGURED")
    evidence = _app_path(evidence_name)
    if not evidence.is_relative_to(work_dir) or not evidence.is_file():
        raise ValueError("OWNERSHIP_EVIDENCE_MISSING")
    card = cards[video_id]
    now = datetime.now(timezone.utc)
    with Store(db_path) as store:
        existing = store.video(video_id)
        if existing is not None and existing["channel_id"] != card.channel_id:
            raise ValueError("TEST_VIDEO_CHANNEL_CHANGED")
        store.save_video(video_id, card.channel_id, now, title=card.title)
        store.register_owned_video(video_id, card.channel_id, now,
                                   str(evidence.relative_to(work_dir)))


def _draft_service(work_dir: Path, drafts_dir: Path):
    """Same service the dashboard uses, without a poster: it cannot open Chrome."""
    from .dashboard import ConfiguredPostingService, DashboardSettings
    from .rss_feed import list_videos, recheck_video
    settings = DashboardSettings(_app_path("config.yaml"))
    return ConfiguredPostingService(
        work_dir / "posts.db", drafts_dir, poster=None, settings=settings,
        feed_loader=lambda: list_videos(channels=settings.channels(), cache_dir=work_dir / "rss_cache"),
        recheck=lambda video_id, channel_id: recheck_video(
            video_id, channel_id, channels=settings.channels()))


def _approved(card, drafts_dir: Path) -> bool:
    from .drafts import preview
    try:
        return bool(preview(card, drafts_dir).can_post)
    except (OSError, ValueError, TypeError):
        return False


def _keep_previous_draft(drafts_dir: Path, work_dir: Path, video_id: str) -> None:
    """Copy an existing draft to work_dir/draft_history before it is overwritten."""
    current = drafts_dir / f"{video_id}.json"
    if current.is_file() and not current.is_symlink():
        history = work_dir / "draft_history"
        history.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        (history / f"{video_id}.{stamp}.json").write_bytes(current.read_bytes())


def _drafts_command(argv: list[str]) -> int:
    """IMP-11: batch-generate UNAPPROVED drafts for the newest videos; never posts."""
    parser = argparse.ArgumentParser(prog="marketing_agent drafts",
                                     description="Generate unapproved AI drafts for the latest videos")
    parser.add_argument("--latest", type=int, default=3, help="videos per channel (1-15)")
    parser.add_argument("--drafts-dir", default="drafts")
    parser.add_argument("--work-dir", default="data/dashboard")
    parser.add_argument("--include-approved", action="store_true",
                        help="also regenerate videos that already have an approved draft (becomes unapproved)")
    args = parser.parse_args(argv)
    if not 1 <= args.latest <= 15:
        print("drafts error: --latest must be 1..15", file=sys.stderr)
        return 2
    try:
        drafts_dir = _app_path(args.drafts_dir)
        work_dir = _app_path(args.work_dir)
        service = _draft_service(work_dir, drafts_dir)
        result = service.list_videos()
    except (OSError, ValueError) as exc:
        print(f"drafts error: {type(exc).__name__}", file=sys.stderr)
        return 1
    by_channel: dict[str, list] = {}
    for card in result.videos:
        by_channel.setdefault(card.channel_id, []).append(card)
    counts = {"GENERATED": 0, "SKIP_APPROVED": 0, "FAILED": 0}
    for channel_id, cards in by_channel.items():
        for card in sorted(cards, key=lambda c: c.published_at, reverse=True)[:args.latest]:
            if _approved(card, drafts_dir) and not args.include_approved:
                status = "SKIP_APPROVED"
            else:
                try:
                    _keep_previous_draft(drafts_dir, work_dir, card.video_id)
                    service.generate_draft(card.video_id)
                    status = "GENERATED"
                except ValueError as exc:
                    status = f"FAILED {exc}" if str(exc).isupper() else "FAILED"
            counts[status.split()[0]] += 1
            print(f"{card.video_id} {status} [{card.channel}]")
    for channel, error in getattr(result, "errors", {}).items():
        print(f"RSS {channel}: {error}")
    print("summary " + " ".join(f"{key}={value}" for key, value in counts.items())
          + " (approve in the dashboard before posting)")
    return 0


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] == "drafts":
        return _drafts_command(argv[1:])
    if argv and argv[0] == "dashboard":
        dashboard_parser = argparse.ArgumentParser(description="Run the local dashboard")
        dashboard_parser.add_argument("--port", type=int, default=8765)
        dashboard_parser.add_argument("--review", action="store_true",
                                      help="Reviewer mode: pin one AI draft awaiting approval as '테스트용' (IMP-22)")
        dashboard_parser.add_argument("--port-tries", type=int, default=1,
                                      help="Try this many consecutive ports starting at --port (1-20)")
        dashboard_parser.add_argument("--demo", action="store_true", help="Offline UI walkthrough; never contacts YouTube or opens the posting profile")
        dashboard_parser.add_argument("--drafts-dir", default="drafts")
        dashboard_parser.add_argument("--work-dir", default="data/dashboard")
        dashboard_parser.add_argument("--test-videos-config", help="Local YAML with explicitly owned test videos")
        dashboard_parser.add_argument("--register-owned-test-video", metavar="VIDEO_ID",
                                      help="Record your manually verified ownership, then exit without posting")
        dashboard_parser.add_argument("--ownership-evidence",
                                      help="Existing evidence file inside --work-dir, required for registration")
        dashboard_args = dashboard_parser.parse_args(argv[1:])
        from .dashboard import ConfiguredPostingService, DashboardSettings, DemoService, run_dashboard
        from .logging import RequestLogger
        from .drafts import approved_draft_cards
        from .poster import VisibleChromePoster
        from .rss_feed import list_videos, recheck_video
        try:
            if dashboard_args.demo:
                if (dashboard_args.test_videos_config or dashboard_args.register_owned_test_video
                        or dashboard_args.ownership_evidence):
                    raise ValueError("DEMO_CANNOT_REGISTER_REAL_VIDEO")
                run_dashboard(port=dashboard_args.port, service=DemoService(), capture_dir=None)
                return 0
            work_dir = _app_path(dashboard_args.work_dir)
            drafts_dir = _app_path(dashboard_args.drafts_dir)
            entries = _load_test_videos(dashboard_args.test_videos_config)
            if dashboard_args.register_owned_test_video:
                if not dashboard_args.test_videos_config or not dashboard_args.ownership_evidence:
                    raise ValueError("TEST_VIDEO_CONFIG_AND_EVIDENCE_REQUIRED")
                _register_owned_test_video(work_dir / "posts.db", work_dir, entries,
                                           dashboard_args.register_owned_test_video,
                                           dashboard_args.ownership_evidence)
                print("Owned test video registered locally; no YouTube or Chrome action was performed.")
                return 0
            if dashboard_args.ownership_evidence:
                raise ValueError("OWNERSHIP_EVIDENCE_REQUIRES_REGISTRATION")
            capture_dir = work_dir / "screenshots"
            settings = DashboardSettings(_app_path("config.yaml"))
            # No Chrome path is accepted from the command line: the poster starts
            # unconfigured inside the app folder and the service applies the saved
            # app-dedicated profile (data/dashboard/chrome-profile-*) selection.
            poster = VisibleChromePoster(work_dir, "", screenshot_dir=capture_dir)
            service = ConfiguredPostingService(work_dir / "posts.db", drafts_dir,
                                               poster=poster, profile="유튜브1",
                                               test_videos=entries, settings=settings,
                                               review_mode=dashboard_args.review,
                                               feed_loader=lambda: list_videos(
                                                   channels=settings.channels(), cache_dir=work_dir / "rss_cache",
                                                   fallback=lambda channel_id: approved_draft_cards(
                                                       drafts_dir, channel_id, settings.channels().get(channel_id, ""),
                                                       include_awaiting=dashboard_args.review)),
                                               recheck=lambda video_id, channel_id: recheck_video(
                                                   video_id, channel_id, channels=settings.channels()))
            run_dashboard(port=dashboard_args.port, service=service,
                          capture_dir=capture_dir, port_tries=dashboard_args.port_tries,
                          request_log=RequestLogger(work_dir / "logs" / "dashboard-requests.jsonl"))
            return 0
        except (OSError, ValueError) as exc:
            detail = str(exc) if str(exc).startswith("PORT_IN_USE") else type(exc).__name__
            print(f"dashboard error: {detail}", file=sys.stderr)
            return 1
    parser = argparse.ArgumentParser(description="Run the guarded marketing agent")
    parser.add_argument("--config", default="config.legacy.example.yaml")
    parser.add_argument("--once", action="store_true", help="Run one immediate cycle without posting")
    parser.add_argument("--offline-fixtures", action="store_true", help="Use fixed inputs without network or posting")
    parser.add_argument("--dry-run", action="store_true", help="Run one immediate cycle without posting")
    parser.add_argument("--db", default="data/agent.db")
    parser.add_argument("--output", default="data/dry_run/comments.jsonl")
    parser.add_argument("--log", default="logs/run.log")
    parser.add_argument("--duration-hours", type=float, default=3)
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        immediate = args.once or args.offline_fixtures or args.dry_run
        start = datetime.now(timezone.utc)
        boundaries = cycle_times(start, interval_minutes=config.poll_interval_min,
                                 duration_hours=args.duration_hours, once=immediate)
        logger = EventLogger(args.log)
        with Store(args.db) as store:
            for boundary in boundaries:
                delay = (boundary - datetime.now(timezone.utc)).total_seconds()
                if delay > 0:
                    sleep(delay)
                outcome = run_cycle(config=config, store=store, logger=logger,
                                    dry_run_path=args.output, screenshot_dir=Path("data/screenshots"),
                                    offline=args.offline_fixtures, dry_run=immediate)
                print(f"run_id={outcome['run_id']} candidates={outcome['candidates']} "
                      f"comments={outcome['comments']} post_calls={outcome['post_calls']} "
                      f"errors={outcome['errors']}")
        return 0
    except Exception as exc:
        print(f"agent error: {type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
