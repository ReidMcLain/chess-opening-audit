from __future__ import annotations

import csv
import io
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from . import __version__
from .html_report import render_html
from .pipeline import AuditResult, SCHEMA_VERSION


AGGREGATE_CSV_FIELDS = (
    "aggregate_id",
    "level",
    "color",
    "eco",
    "opening",
    "variation",
    "subvariation",
    "time_control",
    "games",
    "wins",
    "draws",
    "losses",
    "points",
    "raw_score_percentage",
    "loss_percentage",
    "smoothed_score_percentage",
    "baseline_score_percentage",
    "baseline_source",
    "average_user_rating",
    "average_opponent_rating",
    "average_rating_difference",
    "earliest_game_date",
    "latest_game_date",
    "rating_adjusted_games",
    "expected_points",
    "rating_adjusted_actual_points",
    "actual_minus_expected_points",
    "average_expected_score_percentage",
    "actual_score_minus_expected_score",
    "study_priority_score",
    "priority_rating_underperformance",
    "priority_loss_volume",
    "priority_smoothed_underperformance",
    "priority_raw_rating_deficit",
    "priority_raw_smoothed_deficit",
    "is_classified",
    "game_ids",
)

GAME_CSV_FIELDS = (
    "record_id",
    "source_file",
    "game_index",
    "stable_game_id",
    "identity_source",
    "chess_com_url",
    "event",
    "site",
    "utc_datetime",
    "game_date",
    "white_username",
    "black_username",
    "white_rating",
    "black_rating",
    "user_color",
    "user_rating",
    "opponent_rating",
    "rating_difference",
    "pgn_result",
    "user_result",
    "actual_score",
    "expected_score",
    "time_control",
    "termination",
    "rated",
    "eco",
    "opening",
    "variation",
    "subvariation",
    "deepest_classified_ply",
    "opening_dataset_version",
    "classification_source",
    "moves_uci",
)

OUTPUT_FILENAMES = {
    "html": "opening_audit.html",
    "aggregates_csv": "opening_aggregates.csv",
    "games_csv": "analyzed_games.csv",
    "json": "opening_audit.json",
    "manifest": "run_manifest.json",
}


def prepare_run_directory(base: Path, run_timestamp_utc: str, overwrite: bool) -> Path:
    base = base.expanduser().resolve()
    if overwrite:
        base.mkdir(parents=True, exist_ok=True)
        return base
    base.mkdir(parents=True, exist_ok=True)
    parsed = datetime.fromisoformat(run_timestamp_utc.replace("Z", "+00:00"))
    stem = parsed.strftime("run-%Y%m%dT%H%M%SZ")
    candidate = base / stem
    suffix = 2
    while candidate.exists():
        candidate = base / f"{stem}-{suffix}"
        suffix += 1
    candidate.mkdir()
    return candidate


def _atomic_write(path: Path, text: str) -> None:
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _safe_csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (tuple, list)):
        value = " | ".join(str(item) for item in value)
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return "'" + value
    if isinstance(value, float):
        return f"{value:.10f}".rstrip("0").rstrip(".")
    return value


def _csv_text(rows: Iterable[dict[str, Any]], fields: tuple[str, ...]) -> str:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: _safe_csv_value(row.get(field)) for field in fields})
    return stream.getvalue()


def _audit_json(result: AuditResult) -> dict[str, Any]:
    player = result.config.usernames[0]
    return {
        "schema_version": SCHEMA_VERSION,
        "run_metadata": {
            "run_timestamp_utc": result.run_timestamp_utc,
            "tool_name": "Chess Opening Audit",
            "tool_version": __version__,
            "title": f"Opening Audit: {player} — {result.summary.matched_games} matched games",
        },
        "configuration": result.config.to_dict(),
        "input_summary": result.summary.to_dict(),
        "opening_dataset": result.dataset_metadata,
        "baselines": {color: baseline.to_dict() for color, baseline in result.baselines.items()},
        "game_records": [game.to_dict() for game in result.games],
        "aggregate_records": [aggregate.to_dict() for aggregate in result.aggregates],
        "rankings": result.rankings,
        "warnings": list(result.warnings),
    }


def export_all(result: AuditResult, run_directory: Path) -> dict[str, Path]:
    run_directory.mkdir(parents=True, exist_ok=True)
    paths = {key: run_directory / name for key, name in OUTPUT_FILENAMES.items()}
    aggregate_rows = [aggregate.to_dict() for aggregate in result.aggregates]
    game_rows = [game.to_dict() for game in result.games]
    for row in aggregate_rows:
        row["game_ids"] = tuple(row["game_ids"])
    for row in game_rows:
        row["moves_uci"] = tuple(row["moves_uci"])

    _atomic_write(paths["html"], render_html(result))
    _atomic_write(paths["aggregates_csv"], _csv_text(aggregate_rows, AGGREGATE_CSV_FIELDS))
    _atomic_write(paths["games_csv"], _csv_text(game_rows, GAME_CSV_FIELDS))
    _atomic_write(
        paths["json"],
        json.dumps(_audit_json(result), indent=2, ensure_ascii=False, allow_nan=False) + "\n",
    )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "run_timestamp_utc": result.run_timestamp_utc,
        "tool_version": __version__,
        "opening_dataset_version": result.dataset_metadata.get("version"),
        "supplied_usernames": list(result.config.usernames),
        "exact_input_files": [manifest.path for manifest in result.source_files],
        "input_files": [
            {
                "canonical_path": manifest.path,
                "size_bytes": manifest.size_bytes,
                "modified_utc": manifest.modified_utc,
                "sha256": manifest.sha256,
            }
            for manifest in result.source_files
        ],
        "filters_and_calculation_settings": result.config.to_dict(),
        "input_summary": result.summary.to_dict(),
        "files_scanned": result.summary.files_scanned,
        "games_parsed": result.summary.games_parsed,
        "matched_games": result.summary.matched_games,
        "unmatched_games": result.summary.unmatched_games,
        "ambiguous_games": result.summary.ambiguous_games,
        "duplicate_games": result.summary.duplicate_games,
        "malformed_games": result.summary.malformed_games,
        "generated_output_filenames": list(OUTPUT_FILENAMES.values()),
        "warnings": list(result.warnings),
    }
    _atomic_write(
        paths["manifest"],
        json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
    )
    return paths

