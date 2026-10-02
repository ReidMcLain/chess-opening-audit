from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Literal


Color = Literal["white", "black"]
UserResult = Literal["win", "draw", "loss", "unknown"]


@dataclass(frozen=True, slots=True)
class OpeningClassification:
    eco: str
    opening: str
    variation: str
    subvariation: str
    deepest_ply: int
    dataset_version: str
    source: str

    @property
    def is_classified(self) -> bool:
        return self.opening != "Unknown"


@dataclass(frozen=True, slots=True)
class ParsedGame:
    source_file: Path
    game_index: int
    headers: dict[str, str]
    moves_uci: tuple[str, ...]
    classification: OpeningClassification


@dataclass(frozen=True, slots=True)
class GameRecord:
    record_id: str
    source_file: str
    game_index: int
    stable_game_id: str
    identity_source: str
    chess_com_url: str
    event: str
    site: str
    utc_datetime: str | None
    game_date: date | None
    white_username: str
    black_username: str
    white_rating: int | None
    black_rating: int | None
    user_color: Color
    user_rating: int | None
    opponent_rating: int | None
    rating_difference: int | None
    pgn_result: str
    user_result: UserResult
    time_control: str
    termination: str
    rated: bool | None
    eco: str
    opening: str
    variation: str
    subvariation: str
    deepest_classified_ply: int
    opening_dataset_version: str
    classification_source: str
    moves_uci: tuple[str, ...]

    @property
    def actual_score(self) -> float | None:
        return {"win": 1.0, "draw": 0.5, "loss": 0.0}.get(self.user_result)

    @property
    def expected_score(self) -> float | None:
        if self.rating_difference is None:
            return None
        return 1.0 / (1.0 + 10.0 ** (-self.rating_difference / 400.0))

    @property
    def is_classified(self) -> bool:
        return self.opening != "Unknown"

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["game_date"] = self.game_date.isoformat() if self.game_date else None
        result["moves_uci"] = list(self.moves_uci)
        result["actual_score"] = self.actual_score
        result["expected_score"] = self.expected_score
        return result


@dataclass(frozen=True, slots=True)
class AggregateRecord:
    aggregate_id: str
    level: str
    color: str
    eco: str
    opening: str
    variation: str
    subvariation: str
    time_control: str
    games: int
    wins: int
    draws: int
    losses: int
    points: float
    raw_score_percentage: float
    loss_percentage: float
    smoothed_score_percentage: float
    baseline_score_percentage: float
    baseline_source: str
    average_user_rating: float | None
    average_opponent_rating: float | None
    average_rating_difference: float | None
    earliest_game_date: str | None
    latest_game_date: str | None
    rating_adjusted_games: int
    expected_points: float
    rating_adjusted_actual_points: float
    actual_minus_expected_points: float
    average_expected_score_percentage: float | None
    actual_score_minus_expected_score: float | None
    study_priority_score: float
    priority_rating_underperformance: float
    priority_loss_volume: float
    priority_smoothed_underperformance: float
    priority_raw_rating_deficit: float
    priority_raw_smoothed_deficit: float
    is_classified: bool
    game_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["game_ids"] = list(self.game_ids)
        return result


@dataclass(frozen=True, slots=True)
class Baseline:
    color: str
    score: float | None
    percentage: float | None
    source: str
    color_games: int
    source_games: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class InputSummary:
    files_scanned: int = 0
    files_failed: int = 0
    games_parsed: int = 0
    matched_games: int = 0
    matched_before_filters: int = 0
    unmatched_games: int = 0
    ambiguous_games: int = 0
    malformed_games: int = 0
    duplicate_games: int = 0
    unknown_results: int = 0
    filtered_games: int = 0
    unknown_classifications: int = 0

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SourceFileManifest:
    path: str
    size_bytes: int
    modified_utc: str
    sha256: str

    @classmethod
    def from_path(cls, path: Path, sha256: str) -> "SourceFileManifest":
        stat = path.stat()
        return cls(
            path=str(path.resolve()),
            size_bytes=stat.st_size,
            modified_utc=datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat().replace("+00:00", "Z"),
            sha256=sha256,
        )
