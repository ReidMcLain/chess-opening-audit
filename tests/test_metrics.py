from __future__ import annotations

import pytest

from chess_audit.metrics import calculate_baselines, expected_score


@pytest.mark.parametrize(
    ("rating_difference", "expected"),
    [
        (0, 0.5),
        (400, 10.0 / 11.0),
        (-400, 1.0 / 11.0),
        (800, 100.0 / 101.0),
    ],
)
def test_expected_score_uses_elo_formula(rating_difference, expected):
    assert expected_score(rating_difference) == pytest.approx(expected)


def test_expected_scores_are_symmetric():
    for difference in (1, 75, 250, 600):
        assert expected_score(difference) + expected_score(-difference) == pytest.approx(1.0)


def test_game_expected_score_is_unavailable_without_both_ratings(game_factory):
    missing_user = game_factory(user_rating=None, opponent_rating=1500, rating_difference=None)
    missing_opponent = game_factory(user_rating=1500, opponent_rating=None, rating_difference=None)

    assert missing_user.expected_score is None
    assert missing_opponent.expected_score is None


def test_baselines_are_calculated_separately_by_color(game_factory):
    records = [
        game_factory(user_color="white", user_result="win"),
        game_factory(user_color="white", user_result="loss"),
        game_factory(user_color="black", user_result="win"),
        game_factory(user_color="black", user_result="draw"),
    ]

    baselines = calculate_baselines(records, prior_games=2)

    assert baselines["white"].score == pytest.approx(0.5)
    assert baselines["white"].percentage == pytest.approx(50.0)
    assert baselines["white"].source == "color"
    assert baselines["white"].color_games == 2
    assert baselines["black"].score == pytest.approx(0.75)
    assert baselines["black"].percentage == pytest.approx(75.0)
    assert baselines["black"].source == "color"
    assert baselines["black"].color_games == 2


def test_small_color_samples_fall_back_to_overall_score(game_factory):
    records = [
        game_factory(user_color="white", user_result="win"),
        game_factory(user_color="white", user_result="draw"),
        game_factory(user_color="black", user_result="loss"),
        game_factory(user_color="black", user_result="unknown"),
    ]

    baselines = calculate_baselines(records, prior_games=3)

    # The unknown result is not a scored game: the overall baseline is 1.5 / 3.
    for color in ("white", "black"):
        assert baselines[color].score == pytest.approx(0.5)
        assert baselines[color].source == "overall_fallback"
        assert baselines[color].source_games == 3
    assert baselines["white"].color_games == 2
    assert baselines["black"].color_games == 1


def test_zero_prior_uses_any_available_color_sample(game_factory):
    records = [game_factory(user_color="white", user_result="win")]

    baselines = calculate_baselines(records, prior_games=0)

    assert baselines["white"].score == 1.0
    assert baselines["white"].source == "color"
    assert baselines["black"].score == 1.0
    assert baselines["black"].source == "overall_fallback"
    assert baselines["black"].color_games == 0


def test_baselines_are_unavailable_when_no_game_has_a_known_result(game_factory):
    baselines = calculate_baselines(
        [game_factory(user_result="unknown"), game_factory(user_color="black", user_result="unknown")],
        prior_games=8,
    )

    for color in ("white", "black"):
        assert baselines[color].score is None
        assert baselines[color].percentage is None
        assert baselines[color].source == "unavailable"
        assert baselines[color].source_games == 0
