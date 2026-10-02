from __future__ import annotations

from datetime import date

import pytest

from chess_audit.models import AggregateRecord, GameRecord


@pytest.fixture
def game_factory():
    counter = 0

    def make_game(**overrides) -> GameRecord:
        nonlocal counter
        counter += 1
        user_rating = overrides.pop("user_rating", 1500)
        opponent_rating = overrides.pop("opponent_rating", 1500)
        rating_difference = overrides.pop("rating_difference", None)
        if rating_difference is None and user_rating is not None and opponent_rating is not None:
            rating_difference = user_rating - opponent_rating

        values = {
            "record_id": f"game-{counter}",
            "source_file": rf"C:\PGNs\game {counter}.pgn",
            "game_index": counter,
            "stable_game_id": f"stable-{counter}",
            "identity_source": "fallback_hash",
            "chess_com_url": "",
            "event": "Live Chess",
            "site": "Chess.com",
            "utc_datetime": "2026-01-01T12:00:00+00:00",
            "game_date": date(2026, 1, counter if counter <= 28 else 28),
            "white_username": "AuditedPlayer",
            "black_username": "Opponent",
            "white_rating": user_rating,
            "black_rating": opponent_rating,
            "user_color": "white",
            "user_rating": user_rating,
            "opponent_rating": opponent_rating,
            "rating_difference": rating_difference,
            "pgn_result": "1-0",
            "user_result": "win",
            "time_control": "600",
            "termination": "Normal",
            "rated": True,
            "eco": "B90",
            "opening": "Sicilian Defense",
            "variation": "Najdorf Variation",
            "subvariation": "English Attack",
            "deepest_classified_ply": 12,
            "opening_dataset_version": "test-v1",
            "classification_source": "dataset_position",
            "moves_uci": ("e2e4", "c7c5"),
        }
        values.update(overrides)
        return GameRecord(**values)

    return make_game


@pytest.fixture
def aggregate_factory():
    counter = 0

    def make_aggregate(**overrides) -> AggregateRecord:
        nonlocal counter
        counter += 1
        games = overrides.get("games", 5)
        losses = overrides.get("losses", 1)
        wins = overrides.get("wins", max(0, games - losses))
        draws = overrides.get("draws", max(0, games - wins - losses))
        points = overrides.get("points", wins + 0.5 * draws)
        raw_score = overrides.get("raw_score_percentage", points / games * 100.0)
        values = {
            "aggregate_id": f"aggregate-{counter}",
            "level": "opening",
            "color": "white",
            "eco": "B90",
            "opening": f"Opening {counter}",
            "variation": "",
            "subvariation": "",
            "time_control": "",
            "games": games,
            "wins": wins,
            "draws": draws,
            "losses": losses,
            "points": points,
            "raw_score_percentage": raw_score,
            "loss_percentage": losses / games * 100.0,
            "smoothed_score_percentage": raw_score,
            "baseline_score_percentage": 50.0,
            "baseline_source": "color",
            "average_user_rating": 1500.0,
            "average_opponent_rating": 1500.0,
            "average_rating_difference": 0.0,
            "earliest_game_date": "2026-01-01",
            "latest_game_date": "2026-01-31",
            "rating_adjusted_games": games,
            "expected_points": games * 0.5,
            "rating_adjusted_actual_points": points,
            "actual_minus_expected_points": points - games * 0.5,
            "average_expected_score_percentage": 50.0,
            "actual_score_minus_expected_score": (points / games - 0.5) * 100.0,
            "study_priority_score": 0.0,
            "priority_rating_underperformance": 0.0,
            "priority_loss_volume": 0.0,
            "priority_smoothed_underperformance": 0.0,
            "priority_raw_rating_deficit": max(0.0, games * 0.5 - points),
            "priority_raw_smoothed_deficit": max(0.0, 50.0 - raw_score),
            "is_classified": True,
            "game_ids": tuple(f"game-{index}" for index in range(games)),
        }
        values.update(overrides)
        return AggregateRecord(**values)

    return make_aggregate
