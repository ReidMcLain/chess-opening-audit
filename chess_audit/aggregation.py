from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import replace
from typing import Callable, Iterable

from .models import AggregateRecord, Baseline, GameRecord


GroupKey = tuple[str, ...]


def _average(values: Iterable[int | float | None]) -> float | None:
    present = [float(value) for value in values if value is not None]
    return sum(present) / len(present) if present else None


def _aggregate_id(level: str, key: GroupKey) -> str:
    payload = json.dumps([level, *key], ensure_ascii=False, separators=(",", ":"))
    return f"{level}-{hashlib.sha1(payload.encode('utf-8')).hexdigest()[:14]}"


def _make_aggregate(
    level: str,
    key: GroupKey,
    records: list[GameRecord],
    baseline: Baseline,
    prior_games: float,
) -> AggregateRecord:
    games = len(records)
    wins = sum(record.user_result == "win" for record in records)
    draws = sum(record.user_result == "draw" for record in records)
    losses = sum(record.user_result == "loss" for record in records)
    points = wins + draws * 0.5
    raw_score = points / games
    baseline_score = baseline.score if baseline.score is not None else raw_score
    smoothed = (points + prior_games * baseline_score) / (games + prior_games) if games + prior_games else raw_score
    adjusted = [record for record in records if record.expected_score is not None]
    expected_points = sum(record.expected_score or 0.0 for record in adjusted)
    adjusted_actual = sum(record.actual_score or 0.0 for record in adjusted)
    adjusted_games = len(adjusted)
    dates = sorted(record.game_date for record in records if record.game_date is not None)

    eco_values = sorted({record.eco for record in records if record.eco})
    opening_values = sorted({record.opening for record in records if record.opening})
    variation_values = sorted({record.variation for record in records if record.variation})
    subvariation_values = sorted({record.subvariation for record in records if record.subvariation})
    time_values = sorted({record.time_control for record in records if record.time_control})

    color = records[0].user_color
    opening = opening_values[0] if len(opening_values) == 1 else ""
    variation = variation_values[0] if len(variation_values) == 1 else ""
    subvariation = subvariation_values[0] if len(subvariation_values) == 1 else ""
    time_control = time_values[0] if len(time_values) == 1 else ""
    if level == "color":
        opening = variation = subvariation = ""
    elif level == "opening":
        variation = subvariation = ""
    elif level == "variation":
        subvariation = ""
    elif level == "eco":
        opening = variation = subvariation = ""
    elif level == "time_control":
        opening = variation = subvariation = ""

    return AggregateRecord(
        aggregate_id=_aggregate_id(level, key),
        level=level,
        color=color,
        eco="; ".join(eco_values),
        opening=opening,
        variation=variation,
        subvariation=subvariation,
        time_control=time_control,
        games=games,
        wins=wins,
        draws=draws,
        losses=losses,
        points=points,
        raw_score_percentage=raw_score * 100.0,
        loss_percentage=losses / games * 100.0,
        smoothed_score_percentage=smoothed * 100.0,
        baseline_score_percentage=baseline_score * 100.0,
        baseline_source=baseline.source,
        average_user_rating=_average(record.user_rating for record in records),
        average_opponent_rating=_average(record.opponent_rating for record in records),
        average_rating_difference=_average(record.rating_difference for record in records),
        earliest_game_date=dates[0].isoformat() if dates else None,
        latest_game_date=dates[-1].isoformat() if dates else None,
        rating_adjusted_games=adjusted_games,
        expected_points=expected_points,
        rating_adjusted_actual_points=adjusted_actual,
        actual_minus_expected_points=adjusted_actual - expected_points,
        average_expected_score_percentage=(expected_points / adjusted_games * 100.0) if adjusted_games else None,
        actual_score_minus_expected_score=((adjusted_actual - expected_points) / adjusted_games * 100.0)
        if adjusted_games
        else None,
        study_priority_score=0.0,
        priority_rating_underperformance=0.0,
        priority_loss_volume=0.0,
        priority_smoothed_underperformance=0.0,
        priority_raw_rating_deficit=max(0.0, expected_points - adjusted_actual),
        priority_raw_smoothed_deficit=max(0.0, baseline_score * 100.0 - smoothed * 100.0),
        is_classified=all(record.is_classified for record in records),
        game_ids=tuple(record.record_id for record in records),
    )


def aggregate_games(
    game_records: Iterable[GameRecord],
    baselines: dict[str, Baseline],
    prior_games: float,
) -> list[AggregateRecord]:
    """Build independent color-aware hierarchies from games with known outcomes."""
    records = [record for record in game_records if record.actual_score is not None]
    specifications: list[tuple[str, Callable[[GameRecord], GroupKey | None]]] = [
        ("color", lambda record: (record.user_color,)),
        ("opening", lambda record: (record.user_color, record.opening)),
        (
            "variation",
            lambda record: (record.user_color, record.opening, record.variation) if record.variation else None,
        ),
        (
            "subvariation",
            lambda record: (record.user_color, record.opening, record.variation, record.subvariation)
            if record.subvariation
            else None,
        ),
        ("eco", lambda record: (record.user_color, record.eco) if record.eco else None),
        (
            "time_control",
            lambda record: (record.user_color, record.time_control) if record.time_control else None,
        ),
    ]
    result: list[AggregateRecord] = []
    for level, key_function in specifications:
        grouped: dict[GroupKey, list[GameRecord]] = defaultdict(list)
        for record in records:
            key = key_function(record)
            if key is not None:
                grouped[key].append(record)
        for key in sorted(grouped, key=lambda values: tuple(value.casefold() for value in values)):
            group = grouped[key]
            result.append(_make_aggregate(level, key, group, baselines[group[0].user_color], prior_games))
    return result


def with_priority_components(
    aggregates: list[AggregateRecord], minimum_games: int
) -> list[AggregateRecord]:
    """Normalize the three priority inputs independently within level and color."""
    updated = list(aggregates)
    scopes = sorted({(item.level, item.color) for item in aggregates})
    for scope in scopes:
        indices = [
            index
            for index, item in enumerate(updated)
            if (item.level, item.color) == scope and item.games >= minimum_games
        ]
        if not indices:
            continue
        max_rating = max(updated[index].priority_raw_rating_deficit for index in indices)
        max_losses = max(updated[index].losses for index in indices)
        max_smoothed = max(updated[index].priority_raw_smoothed_deficit for index in indices)
        for index in indices:
            item = updated[index]
            rating_component = item.priority_raw_rating_deficit / max_rating if max_rating else 0.0
            loss_component = item.losses / max_losses if max_losses else 0.0
            smoothed_component = item.priority_raw_smoothed_deficit / max_smoothed if max_smoothed else 0.0
            priority = 100.0 * (
                0.45 * rating_component + 0.35 * loss_component + 0.20 * smoothed_component
            )
            updated[index] = replace(
                item,
                study_priority_score=priority,
                priority_rating_underperformance=rating_component,
                priority_loss_volume=loss_component,
                priority_smoothed_underperformance=smoothed_component,
            )
    return updated
