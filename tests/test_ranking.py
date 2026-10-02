from __future__ import annotations

from chess_audit.ranking import aggregate_label, build_rankings, ranking_records


def _ids(rankings, level, color, name):
    return rankings[level][color][name]


def test_minimum_games_applies_only_to_rate_and_priority_rankings(aggregate_factory):
    below_minimum = aggregate_factory(
        aggregate_id="small",
        opening="Small sample",
        games=4,
        wins=0,
        draws=0,
        losses=4,
        points=0.0,
        raw_score_percentage=0.0,
        loss_percentage=100.0,
        smoothed_score_percentage=30.0,
        study_priority_score=100.0,
    )
    eligible = aggregate_factory(
        aggregate_id="eligible",
        opening="Eligible",
        games=5,
        wins=2,
        draws=0,
        losses=3,
        points=2.0,
        raw_score_percentage=40.0,
        loss_percentage=60.0,
        smoothed_score_percentage=45.0,
        study_priority_score=80.0,
    )

    rankings = build_rankings([below_minimum, eligible], minimum_games=5)

    assert _ids(rankings, "opening", "white", "most_total_losses") == ["small", "eligible"]
    for name in (
        "highest_loss_percentage",
        "worst_raw_score",
        "worst_smoothed_score",
        "highest_study_priority",
        "best_performing",
    ):
        assert _ids(rankings, "opening", "white", name) == ["eligible"]


def test_rankings_keep_levels_and_colors_independent(aggregate_factory):
    white_opening = aggregate_factory(aggregate_id="white-opening", color="white", level="opening")
    black_opening = aggregate_factory(aggregate_id="black-opening", color="black", level="opening")
    white_variation = aggregate_factory(
        aggregate_id="white-variation",
        color="white",
        level="variation",
        variation="Named Variation",
    )
    white_subvariation = aggregate_factory(
        aggregate_id="white-subvariation",
        color="white",
        level="subvariation",
        variation="Named Variation",
        subvariation="Named Subvariation",
    )

    rankings = build_rankings(
        [white_opening, black_opening, white_variation, white_subvariation], minimum_games=1
    )

    assert _ids(rankings, "opening", "white", "most_total_losses") == ["white-opening"]
    assert _ids(rankings, "opening", "black", "most_total_losses") == ["black-opening"]
    assert _ids(rankings, "variation", "white", "most_total_losses") == ["white-variation"]
    assert _ids(rankings, "subvariation", "white", "most_total_losses") == ["white-subvariation"]


def test_unclassified_lines_are_labeled_and_excluded_from_performance_rankings(aggregate_factory):
    classified = aggregate_factory(aggregate_id="classified", opening="French Defense")
    unknown = aggregate_factory(
        aggregate_id="unknown",
        opening="Unknown",
        eco="",
        is_classified=False,
        games=20,
        losses=20,
        study_priority_score=100.0,
    )

    rankings = build_rankings([unknown, classified], minimum_games=1)

    assert _ids(rankings, "opening", "white", "unclassified") == ["unknown"]
    assert "unknown" not in _ids(rankings, "opening", "white", "most_total_losses")
    assert "unknown" not in _ids(rankings, "opening", "white", "highest_study_priority")
    assert aggregate_label(unknown) == "Unknown"


def test_rating_adjusted_deficit_excludes_zero_positive_and_missing_samples(aggregate_factory):
    negative = aggregate_factory(
        aggregate_id="negative",
        actual_minus_expected_points=-2.0,
        rating_adjusted_games=5,
    )
    zero = aggregate_factory(
        aggregate_id="zero",
        actual_minus_expected_points=0.0,
        rating_adjusted_games=5,
    )
    positive = aggregate_factory(
        aggregate_id="positive",
        actual_minus_expected_points=1.0,
        rating_adjusted_games=5,
    )
    no_ratings = aggregate_factory(
        aggregate_id="no-ratings",
        actual_minus_expected_points=-3.0,
        rating_adjusted_games=0,
    )

    rankings = build_rankings([zero, positive, negative, no_ratings], minimum_games=1)

    assert _ids(rankings, "opening", "white", "largest_rating_adjusted_deficit") == ["negative"]


def test_all_ranking_ties_use_stable_case_insensitive_labels(aggregate_factory):
    beta = aggregate_factory(
        aggregate_id="beta",
        opening="beta Opening",
        games=5,
        losses=2,
        raw_score_percentage=50.0,
        loss_percentage=40.0,
        smoothed_score_percentage=50.0,
        actual_minus_expected_points=-1.0,
        study_priority_score=50.0,
    )
    alpha = aggregate_factory(
        aggregate_id="alpha",
        opening="Alpha Opening",
        games=5,
        losses=2,
        raw_score_percentage=50.0,
        loss_percentage=40.0,
        smoothed_score_percentage=50.0,
        actual_minus_expected_points=-1.0,
        study_priority_score=50.0,
    )

    rankings = build_rankings([beta, alpha], minimum_games=1)

    for name in (
        "most_total_losses",
        "highest_loss_percentage",
        "worst_raw_score",
        "worst_smoothed_score",
        "largest_rating_adjusted_deficit",
        "highest_study_priority",
        "best_performing",
    ):
        assert _ids(rankings, "opening", "white", name) == ["alpha", "beta"]


def test_ranking_records_resolves_ids_and_ignores_missing_ids(aggregate_factory):
    item = aggregate_factory(aggregate_id="present")
    rankings = {
        "opening": {
            "white": {
                "custom": ["missing", "present"],
            }
        }
    }

    assert ranking_records(rankings, [item], "opening", "white", "custom") == [item]
    assert ranking_records(rankings, [item], "variation", "white", "custom") == []


def test_aggregate_label_uses_most_specific_hierarchy_and_fallbacks(aggregate_factory):
    hierarchy = aggregate_factory(
        opening="Sicilian Defense",
        variation="Najdorf Variation",
        subvariation="English Attack",
    )
    eco = aggregate_factory(opening="", variation="", subvariation="", eco="A00")
    time_control = aggregate_factory(
        opening="", variation="", subvariation="", eco="", time_control="600+5"
    )
    color = aggregate_factory(opening="", variation="", subvariation="", eco="", time_control="")

    assert aggregate_label(hierarchy) == "Sicilian Defense > Najdorf Variation > English Attack"
    assert aggregate_label(eco) == "A00"
    assert aggregate_label(time_control) == "600+5"
    assert aggregate_label(color) == "White"
