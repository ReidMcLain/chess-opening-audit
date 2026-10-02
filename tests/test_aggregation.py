from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from chess_audit.aggregation import aggregate_games, with_priority_components
from chess_audit.metrics import calculate_baselines
from chess_audit.models import Baseline


def _find(aggregates, level, color, **fields):
    matches = [
        item
        for item in aggregates
        if item.level == level
        and item.color == color
        and all(getattr(item, key) == value for key, value in fields.items())
    ]
    assert len(matches) == 1
    return matches[0]


def test_aggregation_builds_every_color_aware_hierarchy(game_factory):
    records = [
        game_factory(
            record_id="w-najdorf",
            user_color="white",
            user_result="win",
            eco="B90",
            opening="Sicilian Defense",
            variation="Najdorf Variation",
            subvariation="English Attack",
            time_control="600",
        ),
        game_factory(
            record_id="w-dragon",
            user_color="white",
            user_result="loss",
            eco="B77",
            opening="Sicilian Defense",
            variation="Dragon Variation",
            subvariation="Yugoslav Attack",
            time_control="600+5",
        ),
        game_factory(
            record_id="b-french",
            user_color="black",
            user_result="draw",
            eco="C11",
            opening="French Defense",
            variation="Classical Variation",
            subvariation="Steinitz Variation",
            time_control="600",
        ),
        game_factory(
            record_id="unknown-result",
            user_color="white",
            user_result="unknown",
            opening="English Opening",
            eco="A10",
        ),
    ]
    baselines = calculate_baselines(records, prior_games=0)

    aggregates = aggregate_games(records, baselines, prior_games=0)

    assert {item.level for item in aggregates} == {
        "color",
        "opening",
        "variation",
        "subvariation",
        "eco",
        "time_control",
    }
    white = _find(aggregates, "color", "white")
    assert (white.games, white.wins, white.draws, white.losses) == (2, 1, 0, 1)
    assert set(white.game_ids) == {"w-najdorf", "w-dragon"}
    assert white.opening == white.variation == white.subvariation == ""

    sicilian = _find(aggregates, "opening", "white", opening="Sicilian Defense")
    assert sicilian.games == 2
    assert sicilian.eco == "B77; B90"
    assert sicilian.variation == ""
    assert sicilian.subvariation == ""
    assert _find(aggregates, "variation", "white", variation="Najdorf Variation").games == 1
    assert _find(aggregates, "subvariation", "white", subvariation="Yugoslav Attack").games == 1
    assert _find(aggregates, "eco", "black", eco="C11").games == 1
    assert _find(aggregates, "time_control", "white", time_control="600+5").games == 1
    assert not any(item.opening == "English Opening" for item in aggregates)


def test_empty_variation_and_subvariation_do_not_create_narrow_groups(game_factory):
    record = game_factory(variation="", subvariation="")
    baselines = calculate_baselines([record], prior_games=0)

    aggregates = aggregate_games([record], baselines, prior_games=0)

    assert any(item.level == "opening" for item in aggregates)
    assert not any(item.level == "variation" for item in aggregates)
    assert not any(item.level == "subvariation" for item in aggregates)


def test_raw_and_rating_adjusted_metrics_have_the_correct_denominators(game_factory):
    records = [
        game_factory(
            record_id="win",
            user_result="win",
            user_rating=1600,
            opponent_rating=1600,
            game_date=date(2025, 1, 10),
        ),
        game_factory(
            record_id="draw",
            user_result="draw",
            user_rating=1500,
            opponent_rating=1600,
            game_date=date(2025, 2, 10),
        ),
        game_factory(
            record_id="loss-no-ratings",
            user_result="loss",
            user_rating=None,
            opponent_rating=None,
            game_date=date(2025, 3, 10),
        ),
    ]
    baselines = calculate_baselines(records, prior_games=0)

    aggregate = _find(aggregate_games(records, baselines, prior_games=0), "opening", "white")

    expected = 0.5 + 1.0 / (1.0 + 10.0 ** (100.0 / 400.0))
    assert aggregate.games == 3
    assert (aggregate.wins, aggregate.draws, aggregate.losses) == (1, 1, 1)
    assert aggregate.points == pytest.approx(1.5)
    assert aggregate.raw_score_percentage == pytest.approx(50.0)
    assert aggregate.loss_percentage == pytest.approx(100.0 / 3.0)
    assert aggregate.rating_adjusted_games == 2
    assert aggregate.expected_points == pytest.approx(expected)
    assert aggregate.rating_adjusted_actual_points == pytest.approx(1.5)
    assert aggregate.actual_minus_expected_points == pytest.approx(1.5 - expected)
    assert aggregate.average_expected_score_percentage == pytest.approx(expected / 2.0 * 100.0)
    assert aggregate.actual_score_minus_expected_score == pytest.approx((1.5 - expected) / 2.0 * 100.0)
    assert aggregate.average_user_rating == pytest.approx(1550.0)
    assert aggregate.average_opponent_rating == pytest.approx(1600.0)
    assert aggregate.average_rating_difference == pytest.approx(-50.0)
    assert aggregate.earliest_game_date == "2025-01-10"
    assert aggregate.latest_game_date == "2025-03-10"


def test_bayesian_smoothing_uses_color_baseline_and_configured_prior(game_factory):
    records = [
        game_factory(user_result="win"),
        game_factory(user_result="loss"),
    ]
    baseline = Baseline("white", 0.75, 75.0, "color", 20, 20)

    aggregate = _find(
        aggregate_games(records, {"white": baseline}, prior_games=8),
        "opening",
        "white",
    )

    assert aggregate.raw_score_percentage == pytest.approx(50.0)
    assert aggregate.smoothed_score_percentage == pytest.approx((1.0 + 8 * 0.75) / 10 * 100.0)
    assert aggregate.baseline_score_percentage == 75.0
    assert aggregate.baseline_source == "color"


def test_zero_prior_leaves_raw_score_unsmoothed(game_factory):
    records = [game_factory(user_result="win"), game_factory(user_result="loss")]
    baseline = Baseline("white", 0.9, 90.0, "color", 10, 10)

    aggregate = _find(
        aggregate_games(records, {"white": baseline}, prior_games=0),
        "opening",
        "white",
    )

    assert aggregate.smoothed_score_percentage == pytest.approx(aggregate.raw_score_percentage)


def test_positive_rating_adjusted_performance_has_zero_weakness(game_factory):
    # A win at equal ratings scores 0.5 more than expected and must not become a
    # weakness merely because another component in the same scope has a maximum.
    winning_record = game_factory(user_result="win", user_rating=1500, opponent_rating=1500)
    baseline = Baseline("white", 0.5, 50.0, "color", 20, 20)
    aggregate = _find(
        aggregate_games([winning_record], {"white": baseline}, prior_games=8),
        "opening",
        "white",
    )

    assert aggregate.actual_minus_expected_points == pytest.approx(0.5)
    assert aggregate.priority_raw_rating_deficit == 0.0
    prioritized = with_priority_components([aggregate], minimum_games=1)[0]
    assert prioritized.priority_rating_underperformance == 0.0


def test_priority_components_are_normalized_within_color_and_level(aggregate_factory):
    white_worst = aggregate_factory(
        aggregate_id="white-worst",
        level="opening",
        color="white",
        games=10,
        losses=4,
        priority_raw_rating_deficit=4.0,
        priority_raw_smoothed_deficit=20.0,
    )
    white_half = aggregate_factory(
        aggregate_id="white-half",
        level="opening",
        color="white",
        games=10,
        losses=2,
        priority_raw_rating_deficit=2.0,
        priority_raw_smoothed_deficit=10.0,
    )
    black_independent = aggregate_factory(
        aggregate_id="black",
        level="opening",
        color="black",
        games=5,
        losses=1,
        priority_raw_rating_deficit=0.25,
        priority_raw_smoothed_deficit=2.0,
    )
    variation_independent = aggregate_factory(
        aggregate_id="variation",
        level="variation",
        color="white",
        games=5,
        losses=1,
        priority_raw_rating_deficit=0.1,
        priority_raw_smoothed_deficit=1.0,
    )
    ineligible = aggregate_factory(
        aggregate_id="below-minimum",
        level="opening",
        color="white",
        games=4,
        losses=4,
        priority_raw_rating_deficit=100.0,
        priority_raw_smoothed_deficit=100.0,
    )

    prioritized = {
        item.aggregate_id: item
        for item in with_priority_components(
            [white_worst, white_half, black_independent, variation_independent, ineligible],
            minimum_games=5,
        )
    }

    assert prioritized["white-worst"].study_priority_score == pytest.approx(100.0)
    assert prioritized["white-half"].priority_rating_underperformance == pytest.approx(0.5)
    assert prioritized["white-half"].priority_loss_volume == pytest.approx(0.5)
    assert prioritized["white-half"].priority_smoothed_underperformance == pytest.approx(0.5)
    assert prioritized["white-half"].study_priority_score == pytest.approx(50.0)
    assert prioritized["black"].study_priority_score == pytest.approx(100.0)
    assert prioritized["variation"].study_priority_score == pytest.approx(100.0)
    assert prioritized["below-minimum"].study_priority_score == 0.0


def test_zero_component_maximum_stays_zero(aggregate_factory):
    first = aggregate_factory(
        priority_raw_rating_deficit=0.0,
        priority_raw_smoothed_deficit=0.0,
        losses=1,
    )
    second = replace(
        aggregate_factory(
            priority_raw_rating_deficit=0.0,
            priority_raw_smoothed_deficit=0.0,
            losses=2,
        ),
        color="white",
        level="opening",
    )

    prioritized = with_priority_components([first, second], minimum_games=1)

    assert all(item.priority_rating_underperformance == 0.0 for item in prioritized)
    assert all(item.priority_smoothed_underperformance == 0.0 for item in prioritized)
