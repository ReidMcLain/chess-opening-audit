from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from chess_audit.aggregation import with_priority_components
from chess_audit.cli import SUMMARY_PRIORITY_LIMIT, _summary_priority_candidates, main
from chess_audit.config import RunConfig
from chess_audit.exporters import export_all, prepare_run_directory
from chess_audit.html_report import render_html
from chess_audit.models import (
    AggregateRecord,
    Baseline,
    GameRecord,
    InputSummary,
    SourceFileManifest,
)
from chess_audit.pipeline import AuditResult
from chess_audit.ranking import build_rankings


EXPECTED_AGGREGATE_CSV_FIELDS = [
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
]

EXPECTED_GAME_CSV_FIELDS = [
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
]

EXPECTED_OUTPUT_NAMES = {
    "opening_audit.html",
    "opening_aggregates.csv",
    "analyzed_games.csv",
    "opening_audit.json",
    "run_manifest.json",
}


def _strict_json(text: str) -> object:
    def reject_non_finite(value: str) -> None:
        raise AssertionError(f"non-standard JSON number emitted: {value}")

    return json.loads(text, parse_constant=reject_non_finite)


def _game(source: Path, opening: str = "Ruy Lopez") -> GameRecord:
    return GameRecord(
        record_id="chesscom:123456789",
        source_file=str(source.resolve()),
        game_index=1,
        stable_game_id="chesscom:123456789",
        identity_source="chesscom_id",
        chess_com_url="https://www.chess.com/game/live/123456789",
        event="Live Chess",
        site="https://www.chess.com/game/live/123456789",
        utc_datetime="2026-07-01T10:00:00Z",
        game_date=date(2026, 7, 1),
        white_username="ReidMate",
        black_username="Opponent",
        white_rating=1500,
        black_rating=1600,
        user_color="white",
        user_rating=1500,
        opponent_rating=1600,
        rating_difference=-100,
        pgn_result="0-1",
        user_result="loss",
        time_control="600",
        termination="Normal",
        rated=True,
        eco="C60",
        opening=opening,
        variation="Morphy Defense",
        subvariation="",
        deepest_classified_ply=6,
        opening_dataset_version="test-dataset-v1",
        classification_source="dataset_prefix",
        moves_uci=("e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6"),
    )


def _aggregate(level: str, game: GameRecord) -> AggregateRecord:
    opening = game.opening if level != "color" else ""
    variation = game.variation if level in {"variation", "subvariation"} else ""
    subvariation = "Deferred Steinitz" if level == "subvariation" else ""
    return AggregateRecord(
        aggregate_id=f"{level}-test-id",
        level=level,
        color="white",
        eco="C60",
        opening=opening,
        variation=variation,
        subvariation=subvariation,
        time_control="",
        games=1,
        wins=0,
        draws=0,
        losses=1,
        points=0.0,
        raw_score_percentage=0.0,
        loss_percentage=100.0,
        smoothed_score_percentage=44.4444444444,
        baseline_score_percentage=50.0,
        baseline_source="overall_fallback",
        average_user_rating=1500.0,
        average_opponent_rating=1600.0,
        average_rating_difference=-100.0,
        earliest_game_date="2026-07-01",
        latest_game_date="2026-07-01",
        rating_adjusted_games=1,
        expected_points=0.3599350002,
        rating_adjusted_actual_points=0.0,
        actual_minus_expected_points=-0.3599350002,
        average_expected_score_percentage=35.99350002,
        actual_score_minus_expected_score=-35.99350002,
        study_priority_score=0.0,
        priority_rating_underperformance=0.0,
        priority_loss_volume=0.0,
        priority_smoothed_underperformance=0.0,
        priority_raw_rating_deficit=0.3599350002,
        priority_raw_smoothed_deficit=5.5555555556,
        is_classified=True,
        game_ids=(game.record_id,),
    )


def _audit_result(
    tmp_path: Path,
    *,
    username: str = "ReidMate",
    opening: str = "Ruy Lopez",
    warnings: tuple[str, ...] = (),
) -> AuditResult:
    source = tmp_path / "source files" / "game one.pgn"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("[Event \"fixture\"]\n\n*\n", encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    game = _game(source, opening)
    aggregates = [_aggregate(level, game) for level in ("color", "opening", "variation", "subvariation")]
    aggregates = with_priority_components(aggregates, minimum_games=1)
    config = RunConfig(
        explicit_files=(source,),
        folder=None,
        usernames=(username,),
        output_base=tmp_path / "reports",
        minimum_games=1,
        dataset_directory=tmp_path / "dataset",
    )
    summary = InputSummary(files_scanned=1, games_parsed=1, matched_games=1, matched_before_filters=1)
    baselines = {
        "white": Baseline("white", 0.5, 50.0, "overall_fallback", 1, 1),
        "black": Baseline("black", 0.5, 50.0, "overall_fallback", 0, 1),
    }
    return AuditResult(
        run_timestamp_utc="2026-07-14T23:59:58Z",
        config=config,
        dataset_metadata={"version": "test-dataset-v1", "license": "CC0-1.0"},
        source_files=(SourceFileManifest.from_path(source, digest),),
        summary=summary,
        baselines=baselines,
        games=(game,),
        aggregates=tuple(aggregates),
        rankings=build_rankings(aggregates, minimum_games=1),
        warnings=warnings,
    )


def _write_dataset(directory: Path) -> Path:
    directory.mkdir(parents=True)
    (directory / "metadata.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "version": "cli-test-dataset-v1",
                "license": "CC0-1.0",
                "files": ["openings.tsv"],
            }
        ),
        encoding="utf-8",
    )
    (directory / "openings.tsv").write_text(
        "eco\tname\tuci\n"
        "C60\tRuy Lopez: Morphy Defense\te2e4 e7e5 g1f3 b8c6 f1b5 a7a6\n",
        encoding="utf-8",
    )
    return directory


def _write_cli_pgn(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """[Event "Live Chess"]
[Site "https://www.chess.com/game/live/987654321"]
[Date "2026.07.01"]
[UTCDate "2026.07.01"]
[UTCTime "10:00:00"]
[Round "-"]
[White "ReidMate"]
[Black "Opponent"]
[Result "1-0"]
[WhiteElo "1500"]
[BlackElo "1400"]
[TimeControl "600"]
[Rated "true"]

1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 1-0
""",
        encoding="utf-8",
    )
    return path


def _write_partially_malformed_pgn(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """[Event "Broken record"]
[Site "https://www.chess.com/game/live/111111111"]
[Date "2026.06.30"]
[White "ReidMate"]
[Black "Opponent"]
[Result "0-1"]

1. e4 e5 2. Bh6 0-1

[Event "Usable record"]
[Site "https://www.chess.com/game/live/222222222"]
[Date "2026.07.01"]
[White "ReidMate"]
[Black "Opponent"]
[Result "1-0"]
[WhiteElo "1500"]
[BlackElo "1400"]

1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 1-0
""",
        encoding="utf-8",
    )
    return path


def test_export_all_has_stable_csv_columns_and_strict_json(tmp_path: Path) -> None:
    result = _audit_result(tmp_path)
    paths = export_all(result, tmp_path / "written report")

    with paths["aggregates_csv"].open(newline="", encoding="utf-8") as stream:
        aggregate_rows = list(csv.reader(stream))
    with paths["games_csv"].open(newline="", encoding="utf-8") as stream:
        game_rows = list(csv.reader(stream))

    assert aggregate_rows[0] == EXPECTED_AGGREGATE_CSV_FIELDS
    assert game_rows[0] == EXPECTED_GAME_CSV_FIELDS
    assert len(aggregate_rows) == 5
    assert len(game_rows) == 2

    audit_text = paths["json"].read_text(encoding="utf-8")
    audit = _strict_json(audit_text)
    assert "NaN" not in audit_text
    assert "Infinity" not in audit_text
    assert list(audit) == [
        "schema_version",
        "run_metadata",
        "configuration",
        "input_summary",
        "opening_dataset",
        "baselines",
        "game_records",
        "aggregate_records",
        "rankings",
        "warnings",
    ]
    assert audit["run_metadata"]["title"] == "Opening Audit: ReidMate — 1 matched games"
    assert audit["game_records"][0]["moves_uci"][-1] == "a7a6"


def test_manifest_is_reproducible_and_traces_every_input(tmp_path: Path) -> None:
    result = _audit_result(tmp_path)
    paths = export_all(result, tmp_path / "manifest report")

    manifest = _strict_json(paths["manifest"].read_text(encoding="utf-8"))
    source = result.source_files[0]
    assert manifest["run_timestamp_utc"] == result.run_timestamp_utc
    assert manifest["opening_dataset_version"] == "test-dataset-v1"
    assert manifest["supplied_usernames"] == ["ReidMate"]
    assert manifest["exact_input_files"] == [source.path]
    assert manifest["input_files"] == [
        {
            "canonical_path": source.path,
            "size_bytes": source.size_bytes,
            "modified_utc": source.modified_utc,
            "sha256": source.sha256,
        }
    ]
    assert manifest["filters_and_calculation_settings"]["minimum_games"] == 1
    assert manifest["files_scanned"] == 1
    assert manifest["games_parsed"] == 1
    assert manifest["matched_games"] == 1
    assert manifest["unmatched_games"] == 0
    assert manifest["ambiguous_games"] == 0
    assert manifest["duplicate_games"] == 0
    assert manifest["malformed_games"] == 0
    assert set(manifest["generated_output_filenames"]) == EXPECTED_OUTPUT_NAMES


def test_prepare_run_directory_never_silently_reuses_default_directory(tmp_path: Path) -> None:
    base = tmp_path / "opening audit output"
    timestamp = "2026-07-14T23:59:58Z"

    first = prepare_run_directory(base, timestamp, overwrite=False)
    (first / "sentinel.txt").write_text("keep", encoding="utf-8")
    second = prepare_run_directory(base, timestamp, overwrite=False)

    assert first == base.resolve() / "run-20260714T235958Z"
    assert second == base.resolve() / "run-20260714T235958Z-2"
    assert first != second
    assert (first / "sentinel.txt").read_text(encoding="utf-8") == "keep"

    explicit_overwrite = prepare_run_directory(base, timestamp, overwrite=True)
    assert explicit_overwrite == base.resolve()


def test_html_is_self_contained_interactive_traceable_and_escaped(tmp_path: Path) -> None:
    injection = '<img src=x onerror=alert(99)>'
    result = _audit_result(
        tmp_path,
        username=f"Reid & {injection}",
        opening=f"Ruy Lopez {injection}",
        warnings=(f"Unsafe source label: {injection}",),
    )

    document = render_html(result)

    assert f"Opening Audit: Reid &amp; &lt;img src=x onerror=alert(99)&gt; — 1 matched games" in document
    assert injection not in document
    assert "&lt;img src=x onerror=alert(99)&gt;" in document
    assert "\\u003cimg src=x onerror=alert(99)\\u003e" in document

    for section_id, heading in (
        ("executive", "Executive summary"),
        ("import-quality", "Import-quality summary"),
        ("opening-level", "Opening-level performance and weaknesses"),
        ("variation-level", "Variation-level performance and weaknesses"),
        ("subvariation-level", "Subvariation-level performance and weaknesses"),
        ("unknown", "Unknown/unclassified games"),
        ("warnings", "Data-quality warnings"),
        ("methodology", "Methodology"),
    ):
        assert f'id="{section_id}"' in document
        assert f"<h2>{heading}</h2>" in document

    for heading in (
        "Most total losses",
        "Largest rating-adjusted deficits",
        "Highest study priorities",
        "Best-performing lines for comparison",
    ):
        assert heading in document
    assert "<h3>White</h3>" in document
    assert "<h3>Black</h3>" in document

    assert 'data-filter="opening-level"' in document
    assert 'class="sortable"' in document
    assert "table.sortable th" in document
    assert "addEventListener('input'" in document
    assert 'button class="details"' in document
    assert "const GAMES=" in document
    assert "const AGGREGATES=" in document
    assert "a.href=g.chess_com_url" in document
    assert "https://www.chess.com/game/live/123456789" in document
    assert "<script src=" not in document
    assert "<link rel=\"stylesheet\"" not in document


def test_cli_handles_windows_paths_with_spaces_and_writes_all_outputs(
    tmp_path: Path,
) -> None:
    dataset = _write_dataset(tmp_path / "replaceable dataset with spaces")
    pgn = _write_cli_pgn(tmp_path / "PGN files with spaces" / "game one.pgn")
    output = tmp_path / "report output with spaces"

    project_root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [
            sys.executable,
            str(project_root / "opening_audit.py"),
            str(pgn),
            "--username",
            "ReidMate",
            "--output",
            str(output),
            "--minimum-games",
            "1",
            "--dataset-directory",
            str(dataset),
        ],
        cwd=project_root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    run_directories = sorted(path for path in output.iterdir() if path.is_dir())
    assert len(run_directories) == 1
    run_directory = run_directories[0]
    assert run_directory.name.startswith("run-")
    assert {path.name for path in run_directory.iterdir()} == EXPECTED_OUTPUT_NAMES

    manifest = _strict_json((run_directory / "run_manifest.json").read_text(encoding="utf-8"))
    audit = _strict_json((run_directory / "opening_audit.json").read_text(encoding="utf-8"))
    assert manifest["exact_input_files"] == [str(pgn.resolve())]
    assert audit["configuration"]["explicit_files"] == [str(pgn.resolve())]
    assert audit["run_metadata"]["title"] == "Opening Audit: ReidMate — 1 matched games"
    assert audit["input_summary"]["matched_games"] == 1
    assert audit["input_summary"]["unknown_classifications"] == 0
    assert "Files scanned: 1" in completed.stdout
    assert "Matched and analyzed: 1" in completed.stdout
    assert "Opening classification success: 100.0%" in completed.stdout
    assert "Top 10 variation-level study priorities:" in completed.stdout
    assert "Ruy Lopez > Morphy Defense" in completed.stdout
    for filename in EXPECTED_OUTPUT_NAMES:
        assert filename in completed.stdout


def test_cli_summary_returns_top_ten_variations_in_priority_order(tmp_path: Path) -> None:
    result = _audit_result(tmp_path)
    template = next(item for item in result.aggregates if item.level == "variation")
    variations = tuple(
        replace(
            template,
            aggregate_id=f"variation-{index}",
            variation=f"Variation {index:02d}",
            study_priority_score=float(index),
        )
        for index in range(1, 13)
    )
    result = replace(result, aggregates=variations)

    candidates = _summary_priority_candidates(result)

    assert len(candidates) == SUMMARY_PRIORITY_LIMIT
    assert [item.variation for item in candidates] == [
        f"Variation {index:02d}" for index in range(12, 2, -1)
    ]


def test_cli_returns_success_and_exports_warnings_when_some_inputs_fail(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dataset = _write_dataset(tmp_path / "dataset")
    pgn = _write_cli_pgn(tmp_path / "good game.pgn")
    missing = tmp_path / "missing game.pgn"
    output = tmp_path / "partial report"

    exit_status = main(
        [
            str(missing),
            str(pgn),
            "--username",
            "ReidMate",
            "--output",
            str(output),
            "--overwrite",
            "--minimum-games",
            "1",
            "--dataset-directory",
            str(dataset),
        ]
    )

    captured = capsys.readouterr()
    assert exit_status == 0, captured.err
    audit = _strict_json((output / "opening_audit.json").read_text(encoding="utf-8"))
    manifest = _strict_json((output / "run_manifest.json").read_text(encoding="utf-8"))
    assert audit["input_summary"]["files_scanned"] == 1
    assert audit["input_summary"]["matched_games"] == 1
    assert any("does not exist" in warning for warning in audit["warnings"])
    assert audit["warnings"] == manifest["warnings"]
    assert "Completed with 1 warning(s)" in captured.out
    assert captured.err == ""


def test_cli_continues_after_a_malformed_game_and_reports_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dataset = _write_dataset(tmp_path / "dataset")
    pgn = _write_partially_malformed_pgn(tmp_path / "mixed archive.pgn")
    output = tmp_path / "mixed archive report"

    exit_status = main(
        [
            str(pgn),
            "--username",
            "ReidMate",
            "--output",
            str(output),
            "--overwrite",
            "--minimum-games",
            "1",
            "--dataset-directory",
            str(dataset),
        ]
    )

    captured = capsys.readouterr()
    assert exit_status == 0
    audit = _strict_json((output / "opening_audit.json").read_text(encoding="utf-8"))
    assert audit["input_summary"]["games_parsed"] == 2
    assert audit["input_summary"]["malformed_games"] == 1
    assert audit["input_summary"]["matched_games"] == 1
    assert any("Malformed game excluded" in warning for warning in audit["warnings"])
    assert "Completed with 1 warning(s)" in captured.out


def test_cli_returns_nonzero_for_fatal_configuration_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_status = main(["--username", "ReidMate", "--output", str(tmp_path / "unused")])

    captured = capsys.readouterr()
    assert exit_status == 2
    assert "Chess Opening Audit error:" in captured.err
    assert "Supply at least one PGN file or --folder." in captured.err
    assert captured.out == ""
    assert not (tmp_path / "unused").exists()
