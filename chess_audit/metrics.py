from __future__ import annotations

from collections.abc import Iterable

from .models import Baseline, GameRecord


def expected_score(rating_difference: float) -> float:
    return 1.0 / (1.0 + 10.0 ** (-rating_difference / 400.0))


def calculate_baselines(records: Iterable[GameRecord], prior_games: float) -> dict[str, Baseline]:
    scored = [record for record in records if record.actual_score is not None]
    overall_games = len(scored)
    overall_points = sum(record.actual_score or 0.0 for record in scored)
    overall_score = overall_points / overall_games if overall_games else None
    baselines: dict[str, Baseline] = {}
    for color in ("white", "black"):
        color_records = [record for record in scored if record.user_color == color]
        color_games = len(color_records)
        color_points = sum(record.actual_score or 0.0 for record in color_records)
        useful = color_games > 0 and (prior_games == 0 or color_games >= prior_games)
        if useful:
            score = color_points / color_games
            source = "color"
            source_games = color_games
        else:
            score = overall_score
            source = "overall_fallback" if overall_score is not None else "unavailable"
            source_games = overall_games
        baselines[color] = Baseline(
            color=color,
            score=score,
            percentage=score * 100.0 if score is not None else None,
            source=source,
            color_games=color_games,
            source_games=source_games,
        )
    return baselines

