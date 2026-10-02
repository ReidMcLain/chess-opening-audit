from __future__ import annotations

from datetime import date
from pathlib import Path

from chess_audit.config import RunConfig
from chess_audit.models import OpeningClassification
from chess_audit.pipeline import run_audit


FIXTURE = Path(__file__).parent / "fixtures" / "manual_audit.pgn"


class StubClassifier:
    dataset_version = "synthetic-1"
    metadata = {"version": dataset_version, "license": "test-only"}

    def classify(self, moves_uci, headers):
        return OpeningClassification(
            eco="T00",
            opening="Synthetic Opening",
            variation="Synthetic Variation",
            subvariation="",
            deepest_ply=min(2, len(tuple(moves_uci))),
            dataset_version=self.dataset_version,
            source="dataset_prefix",
        )


def config(tmp_path: Path, **changes) -> RunConfig:
    values = {
        "explicit_files": (FIXTURE,),
        "folder": None,
        "usernames": ("ReidMate", "OldReid"),
        "output_base": tmp_path / "output",
        "minimum_games": 1,
        "prior_games": 0.0,
    }
    values.update(changes)
    return RunConfig(**values)


def test_pipeline_counts_exclusions_deduplication_and_manual_totals(tmp_path: Path) -> None:
    result = run_audit(config(tmp_path), StubClassifier())

    assert result.summary.to_dict() == {
        "files_scanned": 1,
        "files_failed": 0,
        "games_parsed": 9,
        "matched_games": 6,
        "matched_before_filters": 7,
        "unmatched_games": 1,
        "ambiguous_games": 1,
        "malformed_games": 0,
        "duplicate_games": 1,
        "unknown_results": 1,
        "filtered_games": 0,
        "unknown_classifications": 0,
    }
    colors = {item.color: item for item in result.aggregates if item.level == "color"}
    assert (colors["white"].wins, colors["white"].draws, colors["white"].losses) == (1, 1, 1)
    assert colors["white"].points == 1.5
    assert abs(colors["white"].expected_points - 0.8599350001971149) < 1e-12
    assert abs(colors["white"].actual_minus_expected_points - 0.6400649998028851) < 1e-12
    assert (colors["black"].wins, colors["black"].draws, colors["black"].losses) == (1, 0, 1)
    assert colors["black"].points == 1.0
    assert abs(colors["black"].expected_points - 1.0) < 1e-12


def test_no_deduplicate_retains_unique_occurrences_but_reports_duplicate(tmp_path: Path) -> None:
    result = run_audit(config(tmp_path, deduplicate=False), StubClassifier())

    assert result.summary.duplicate_games == 1
    assert result.summary.matched_games == 7
    assert len({record.record_id for record in result.games}) == 7
    white = next(item for item in result.aggregates if item.level == "color" and item.color == "white")
    assert (white.wins, white.draws, white.losses) == (2, 1, 1)


def test_date_color_and_last_games_filters_are_inclusive_and_chronological(tmp_path: Path) -> None:
    result = run_audit(
        config(
            tmp_path,
            color="white",
            after=date(2026, 1, 2),
            before=date(2026, 1, 6),
            last_games=2,
        ),
        StubClassifier(),
    )

    assert result.summary.matched_games == 2
    assert result.summary.filtered_games == 4
    assert [record.game_date for record in result.games] == [date(2026, 1, 3), date(2026, 1, 6)]
    assert all(record.user_color == "white" for record in result.games)
    assert result.summary.unknown_results == 1

