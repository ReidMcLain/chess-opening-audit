from __future__ import annotations

from typing import Any

from .models import AggregateRecord


REPORT_LEVELS = ("opening", "variation", "subvariation")


def aggregate_label(item: AggregateRecord) -> str:
    parts = [item.opening, item.variation, item.subvariation]
    label = " > ".join(part for part in parts if part)
    if not label:
        label = item.eco or item.time_control or item.color.title()
    return label


def _stable(item: AggregateRecord) -> tuple[str, str, str, str]:
    return (item.opening.casefold(), item.variation.casefold(), item.subvariation.casefold(), item.eco)


def build_rankings(
    aggregates: list[AggregateRecord], minimum_games: int
) -> dict[str, dict[str, dict[str, list[str]]]]:
    result: dict[str, dict[str, dict[str, list[str]]]] = {}
    for level in REPORT_LEVELS:
        result[level] = {}
        for color in ("white", "black"):
            all_items = [item for item in aggregates if item.level == level and item.color == color]
            classified = [item for item in all_items if item.is_classified]
            eligible = [item for item in classified if item.games >= minimum_games]
            unclassified = [item for item in all_items if not item.is_classified]
            rankings = {
                "most_total_losses": sorted(
                    classified, key=lambda item: (-item.losses, -item.games, _stable(item))
                ),
                "highest_loss_percentage": sorted(
                    eligible, key=lambda item: (-item.loss_percentage, -item.games, _stable(item))
                ),
                "worst_raw_score": sorted(
                    eligible, key=lambda item: (item.raw_score_percentage, -item.games, _stable(item))
                ),
                "worst_smoothed_score": sorted(
                    eligible, key=lambda item: (item.smoothed_score_percentage, -item.games, _stable(item))
                ),
                "largest_rating_adjusted_deficit": sorted(
                    (
                        item
                        for item in classified
                        if item.rating_adjusted_games and item.actual_minus_expected_points < 0
                    ),
                    key=lambda item: (item.actual_minus_expected_points, -item.rating_adjusted_games, _stable(item)),
                ),
                "highest_study_priority": sorted(
                    eligible,
                    key=lambda item: (
                        -item.study_priority_score,
                        -item.losses,
                        item.smoothed_score_percentage,
                        -item.games,
                        _stable(item),
                    ),
                ),
                "best_performing": sorted(
                    eligible,
                    key=lambda item: (
                        -item.smoothed_score_percentage,
                        -item.raw_score_percentage,
                        -item.games,
                        _stable(item),
                    ),
                ),
                "unclassified": sorted(
                    unclassified,
                    key=lambda item: (-item.study_priority_score, -item.losses, _stable(item)),
                ),
            }
            result[level][color] = {
                name: [item.aggregate_id for item in items] for name, items in rankings.items()
            }
    return result


def ranking_records(
    rankings: dict[str, dict[str, dict[str, list[str]]]],
    aggregates: list[AggregateRecord],
    level: str,
    color: str,
    name: str,
) -> list[AggregateRecord]:
    by_id = {item.aggregate_id: item for item in aggregates}
    return [by_id[item_id] for item_id in rankings.get(level, {}).get(color, {}).get(name, []) if item_id in by_id]

