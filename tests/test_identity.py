from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from chess_audit.identity import (
    build_game_record,
    chess_com_url,
    header,
    identify_player,
    normalize_result,
    normalize_username,
    normalize_usernames,
    parse_game_date,
    parse_rated,
    parse_rating,
    parse_utc_datetime,
    stable_game_id,
)
from chess_audit.models import OpeningClassification, ParsedGame


class UsernameIdentityTests(unittest.TestCase):
    def test_username_normalization_is_trimmed_and_case_insensitive(self) -> None:
        self.assertEqual("reidmate", normalize_username("  ReIdMaTe  "))
        self.assertEqual(
            frozenset({"reidmate", "oldaccount"}),
            normalize_usernames([" ReidMate ", "OLDACCOUNT", "", "   ", "reidmate"]),
        )

    def test_header_lookup_is_case_insensitive_and_trimmed(self) -> None:
        headers = {"white": "  ReidMate ", "BLACK": " Opponent "}
        self.assertEqual("ReidMate", header(headers, "White"))
        self.assertEqual("Opponent", header(headers, "Black"))
        self.assertEqual("", header(headers, "Missing"))

    def test_identifies_white_black_unmatched_and_ambiguous_aliases(self) -> None:
        aliases = normalize_usernames(["ReidMate", "OldAccount"])
        cases = (
            ({"White": " reidmate ", "Black": "Opponent"}, "white"),
            ({"White": "Opponent", "Black": "OLDACCOUNT"}, "black"),
            ({"White": "Someone", "Black": "Opponent"}, "unmatched"),
            ({"White": "ReidMate", "Black": "oldaccount"}, "ambiguous"),
        )
        for headers, expected in cases:
            with self.subTest(headers=headers):
                self.assertEqual(expected, identify_player(headers, aliases))


class ResultAndHeaderParsingTests(unittest.TestCase):
    def test_all_result_types_are_normalized_from_player_perspective(self) -> None:
        cases = (
            ("1-0", "white", "win"),
            ("1-0", "black", "loss"),
            ("0-1", "white", "loss"),
            ("0-1", "black", "win"),
            ("1/2-1/2", "white", "draw"),
            ("1/2-1/2", "black", "draw"),
            ("*", "white", "unknown"),
            ("abandoned", "black", "unknown"),
        )
        for result, color, expected in cases:
            with self.subTest(result=result, color=color):
                self.assertEqual(expected, normalize_result(result, color))

    def test_ratings_accept_only_positive_integers(self) -> None:
        self.assertEqual(1725, parse_rating(" 1725 "))
        for value in ("", "?", "-", "0", "-4", "1700?", "not-a-rating"):
            with self.subTest(value=value):
                self.assertIsNone(parse_rating(value))

    def test_dates_utc_datetimes_and_rated_values(self) -> None:
        headers = {"UTCDate": "2026.07.14", "UTCTime": "23:45:10Z"}
        self.assertEqual(date(2026, 7, 14), parse_game_date(headers))
        self.assertEqual("2026-07-14T23:45:10Z", parse_utc_datetime(headers))
        self.assertEqual(date(2025, 1, 2), parse_game_date({"Date": "2025-01-02"}))
        self.assertIsNone(parse_game_date({"Date": "2025.??.02"}))
        self.assertIsNone(parse_utc_datetime({"UTCDate": "2026.07.14"}))
        for value in ("true", "YES", "1", "rated"):
            self.assertIs(parse_rated({"Rated": value}), True)
        for value in ("false", "No", "0", "unrated"):
            self.assertIs(parse_rated({"IsRated": value}), False)
        self.assertIsNone(parse_rated({"Rated": "maybe"}))


class StableIdentityTests(unittest.TestCase):
    def test_chess_com_game_url_is_preferred_for_stable_identity(self) -> None:
        headers = {
            "Link": "https://www.chess.com/game/live/123456789?username=ReidMate",
            "White": "ReidMate",
            "Black": "Opponent",
            "Result": "1-0",
        }
        game_id, link = stable_game_id(headers, ("e2e4", "e7e5"))
        self.assertEqual("chesscom:123456789", game_id)
        self.assertEqual(headers["Link"], link)
        self.assertEqual(headers["Link"], chess_com_url(headers))

        changed_id, _ = stable_game_id(
            {**headers, "White": "Different", "Result": "0-1"},
            ("d2d4",),
        )
        self.assertEqual(game_id, changed_id)

    def test_chess_com_url_can_be_found_in_site_or_an_unusual_header(self) -> None:
        self.assertEqual(
            "https://chess.com/daily/game/98765",
            chess_com_url({"Site": "https://chess.com/daily/game/98765"}),
        )
        self.assertEqual(
            "https://www.chess.com/live/game/24680",
            chess_com_url({"ArchiveLink": "See https://www.chess.com/live/game/24680."}),
        )

    def test_move_hash_is_deterministic_and_uses_normalized_identity_fields(self) -> None:
        headers_a = {
            "White": " ReidMate ",
            "Black": " OPPONENT ",
            "UTCDate": "2026.07.14",
            "UTCTime": "12:34:56",
            "Result": "1-0",
        }
        headers_b = {
            "result": "1-0",
            "utctime": "12:34:56",
            "utcdate": "2026.07.14",
            "black": "opponent",
            "white": "reidmate",
        }
        moves = ("e2e4", "e7e5", "g1f3")
        first, first_link = stable_game_id(headers_a, moves)
        second, second_link = stable_game_id(headers_b, moves)
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("sha256:"))
        self.assertEqual("", first_link)
        self.assertEqual("", second_link)

        changed_moves, _ = stable_game_id(headers_a, moves + ("b8c6",))
        changed_time, _ = stable_game_id({**headers_a, "UTCTime": "12:34:57"}, moves)
        self.assertNotEqual(first, changed_moves)
        self.assertNotEqual(first, changed_time)

    def test_build_game_record_populates_black_perspective_and_windows_space_path(self) -> None:
        classification = OpeningClassification(
            eco="C20",
            opening="King's Pawn Game",
            variation="",
            subvariation="",
            deepest_ply=2,
            dataset_version="synthetic-test-v1",
            source="dataset_prefix",
        )
        headers = {
            "Event": "Live Chess",
            "Site": "Chess.com",
            "Link": "https://www.chess.com/game/live/112233",
            "UTCDate": "2026.07.14",
            "UTCTime": "19:08:07",
            "White": "Opponent",
            "Black": "ReidMate",
            "WhiteElo": "1810",
            "BlackElo": "1710",
            "Result": "1-0",
            "TimeControl": "600",
            "Termination": "Opponent won by resignation",
            "Rated": "false",
        }
        with tempfile.TemporaryDirectory(prefix="opening audit path with spaces ") as directory:
            source = Path(directory) / "game archive with spaces.pgn"
            parsed = ParsedGame(source, 7, headers, ("e2e4", "e7e5"), classification)
            record = build_game_record(parsed, "black", occurrence=2)

        self.assertEqual(str(source.resolve()), record.source_file)
        self.assertEqual(7, record.game_index)
        self.assertEqual("chesscom:112233#occurrence-2", record.record_id)
        self.assertEqual("chesscom:112233", record.stable_game_id)
        self.assertEqual("chesscom_id", record.identity_source)
        self.assertEqual("black", record.user_color)
        self.assertEqual(1710, record.user_rating)
        self.assertEqual(1810, record.opponent_rating)
        self.assertEqual(-100, record.rating_difference)
        self.assertEqual("loss", record.user_result)
        self.assertEqual(date(2026, 7, 14), record.game_date)
        self.assertEqual("2026-07-14T19:08:07Z", record.utc_datetime)
        self.assertIs(record.rated, False)
        self.assertEqual("King's Pawn Game", record.opening)
        self.assertEqual(2, record.deepest_classified_ply)

    def test_build_game_record_keeps_missing_ratings(self) -> None:
        classification = OpeningClassification("", "Unknown", "", "", 0, "test", "unknown")
        parsed = ParsedGame(
            Path("missing rating.pgn"),
            1,
            {"White": "ReidMate", "Black": "Opponent", "Result": "0-1"},
            (),
            classification,
        )
        record = build_game_record(parsed, "white")
        self.assertIsNone(record.white_rating)
        self.assertIsNone(record.user_rating)
        self.assertIsNone(record.opponent_rating)
        self.assertIsNone(record.rating_difference)
        self.assertIsNone(record.expected_score)
        self.assertEqual(0.0, record.actual_score)


if __name__ == "__main__":
    unittest.main()
