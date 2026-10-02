from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import Sequence

from .config import RunConfig
from .exporters import export_all, prepare_run_directory
from .models import AggregateRecord
from .pipeline import AuditResult, run_audit
from .ranking import aggregate_label


SUMMARY_PRIORITY_LIMIT = 10


def default_dataset_directory() -> Path:
    source_tree = Path(__file__).resolve().parent.parent / "data"
    installed = Path(sys.prefix) / "share" / "chess-opening-audit" / "data"
    return source_tree if source_tree.is_dir() else installed


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD, got {value!r}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="opening_audit.py",
        description="Audit a player's opening performance from local PGN files.",
    )
    parser.add_argument("pgn_files", nargs="*", type=Path, help="One or more explicit PGN files")
    parser.add_argument("--folder", type=Path, help="Folder containing .pgn files")
    parser.add_argument(
        "--username",
        action="append",
        required=True,
        help="Audited Chess.com username; repeat for aliases",
    )
    parser.add_argument("--output", type=Path, default=Path("opening-audit-output"), help="Report base directory")
    parser.add_argument("--overwrite", action="store_true", help="Write directly into --output and replace named report files")
    parser.add_argument("--color", choices=("white", "black", "both"), default="both")
    parser.add_argument("--minimum-games", type=int, default=5)
    parser.add_argument("--prior-games", type=float, default=8.0)
    parser.add_argument("--after", type=_date, metavar="YYYY-MM-DD")
    parser.add_argument("--before", type=_date, metavar="YYYY-MM-DD")
    parser.add_argument("--last-games", type=int)
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument("--no-deduplicate", action="store_true")
    parser.add_argument(
        "--dataset-directory",
        type=Path,
        default=default_dataset_directory(),
        help=argparse.SUPPRESS,
    )
    return parser


def _configuration(arguments: argparse.Namespace) -> RunConfig:
    return RunConfig(
        explicit_files=tuple(arguments.pgn_files),
        folder=arguments.folder,
        usernames=tuple(arguments.username),
        output_base=arguments.output,
        color=arguments.color,
        minimum_games=arguments.minimum_games,
        prior_games=arguments.prior_games,
        after=arguments.after,
        before=arguments.before,
        last_games=arguments.last_games,
        recursive=arguments.recursive,
        deduplicate=not arguments.no_deduplicate,
        overwrite=arguments.overwrite,
        dataset_directory=arguments.dataset_directory,
    )


def _color_line(result: AuditResult, color: str) -> str:
    item = next(
        (aggregate for aggregate in result.aggregates if aggregate.level == "color" and aggregate.color == color),
        None,
    )
    if item is None:
        return f"  {color.title()}: no scored games"
    return (
        f"  {color.title()}: {item.wins}-{item.draws}-{item.losses}, "
        f"{item.raw_score_percentage:.1f}% score ({item.games} games)"
    )


def _summary_priority_candidates(result: AuditResult) -> list[AggregateRecord]:
    return sorted(
        (
            item
            for item in result.aggregates
            if item.level == "variation"
            and item.games >= result.config.minimum_games
            and item.is_classified
        ),
        key=lambda item: (
            -item.study_priority_score,
            -item.losses,
            item.smoothed_score_percentage,
            -item.games,
            aggregate_label(item).casefold(),
        ),
    )[:SUMMARY_PRIORITY_LIMIT]


def print_summary(result: AuditResult, paths: dict[str, Path]) -> None:
    summary = result.summary
    rate = (
        (summary.matched_games - summary.unknown_classifications) / summary.matched_games * 100.0
        if summary.matched_games
        else 0.0
    )
    skipped = summary.duplicate_games if result.config.deduplicate else 0
    print("Chess Opening Audit complete")
    print(f"  Files scanned: {summary.files_scanned}")
    if summary.files_failed:
        print(f"  Files failed: {summary.files_failed}")
    print(f"  Games found/parsed: {summary.games_parsed}")
    print(f"  Matched before filters: {summary.matched_before_filters}")
    print(f"  Matched and analyzed: {summary.matched_games}")
    print(f"  Unmatched: {summary.unmatched_games}; ambiguous: {summary.ambiguous_games}; malformed: {summary.malformed_games}")
    print(f"  Duplicates detected: {summary.duplicate_games}; skipped: {skipped}")
    print(f"  Unknown results: {summary.unknown_results}; filtered out: {summary.filtered_games}")
    print(f"  Opening classification success: {rate:.1f}%")
    print(_color_line(result, "white"))
    print(_color_line(result, "black"))

    candidates = _summary_priority_candidates(result)
    print("  Top 10 variation-level study priorities:")
    if not candidates:
        print("    none meet the minimum sample")
    for index, item in enumerate(candidates, 1):
        print(
            f"    {index}. {item.color.title()} — {aggregate_label(item)}: "
            f"priority {item.study_priority_score:.1f}, {item.games} games, "
            f"{item.losses} losses, adjusted {item.actual_minus_expected_points:+.2f} pts"
        )
    print("  Output files:")
    for key in ("html", "aggregates_csv", "games_csv", "json", "manifest"):
        print(f"    {paths[key]}")
    if result.warnings:
        print(f"  Completed with {len(result.warnings)} warning(s); see HTML/JSON for details.")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    config = _configuration(arguments)
    try:
        result = run_audit(config)
        run_directory = prepare_run_directory(config.output_base, result.run_timestamp_utc, config.overwrite)
        paths = export_all(result, run_directory)
    except (ValueError, OSError, UnicodeError) as exc:
        print(f"Chess Opening Audit error: {exc}", file=sys.stderr)
        return 2
    print_summary(result, paths)
    return 0
