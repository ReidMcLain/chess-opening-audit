from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

import chess

from chess_audit.openings import BundledOpeningClassifier, position_key, split_opening_name


FIXTURE_DATASET = Path(__file__).parent / "fixtures" / "openings"


def write_dataset(directory: Path, rows: list[dict[str, str]], *, version: str = "dynamic-v1") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    metadata = {
        "schema_version": "1.0",
        "version": version,
        "files": ["openings.tsv"],
        "entry_count": len(rows),
    }
    (directory / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    with (directory / "openings.tsv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("eco", "name", "pgn", "uci"), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    return directory


class OpeningDatasetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.classifier = BundledOpeningClassifier(FIXTURE_DATASET)

    def test_loads_versioned_synthetic_tsv_and_metadata(self) -> None:
        self.assertEqual("synthetic-test-v1", self.classifier.dataset_version)
        self.assertEqual(5, self.classifier.entry_count)
        self.assertEqual("CC0-1.0", self.classifier.metadata["license"])

    def test_missing_or_invalid_metadata_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "metadata is missing"):
                BundledOpeningClassifier(root)

            (root / "metadata.json").write_text("{not json", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Cannot read opening dataset metadata"):
                BundledOpeningClassifier(root)

    def test_missing_data_file_and_invalid_columns_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "metadata.json").write_text(
                json.dumps({"version": "bad", "files": ["missing.tsv"]}), encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "dataset file is missing"):
                BundledOpeningClassifier(root)

            (root / "metadata.json").write_text(
                json.dumps({"version": "bad", "files": ["invalid.tsv"]}), encoding="utf-8"
            )
            (root / "invalid.tsv").write_text("code\ttitle\nA00\tBad\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid columns"):
                BundledOpeningClassifier(root)

    def test_illegal_uci_and_malformed_pgn_rows_are_rejected_with_line_context(self) -> None:
        cases = (
            ({"eco": "A00", "name": "Bad UCI", "pgn": "", "uci": "e2e5"}, "illegal UCI move"),
            (
                {
                    "eco": "A00",
                    "name": "Bad PGN",
                    "pgn": "1. e4 e5 2. Nf3 Nc6 3. e5",
                    "uci": "",
                },
                "malformed PGN",
            ),
        )
        for row, message in cases:
            with self.subTest(row=row), tempfile.TemporaryDirectory() as directory:
                root = write_dataset(Path(directory), [row])
                if row["pgn"]:
                    with self.assertLogs("chess.pgn", level="ERROR"):
                        with self.assertRaisesRegex(ValueError, message):
                            BundledOpeningClassifier(root)
                else:
                    with self.assertRaisesRegex(ValueError, message):
                        BundledOpeningClassifier(root)


class OpeningClassificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.classifier = BundledOpeningClassifier(FIXTURE_DATASET)

    def test_deepest_exact_prefix_wins_and_preserves_dataset_names(self) -> None:
        classification = self.classifier.classify(
            ("e2e4", "e7e5", "g1f3", "b8c6", "b1c3", "g8f6"),
            {},
        )
        self.assertEqual("C46", classification.eco)
        self.assertEqual("Three Knights Opening", classification.opening)
        self.assertEqual("Steinitz Variation", classification.variation)
        self.assertEqual("Quiet Line", classification.subvariation)
        self.assertEqual(5, classification.deepest_ply)
        self.assertEqual("dataset_prefix", classification.source)
        self.assertEqual("synthetic-test-v1", classification.dataset_version)

    def test_position_index_classifies_a_transposed_move_order(self) -> None:
        canonical = ("g1f3", "d7d5", "g2g3", "g8f6", "f1g2")
        transposed = ("g2g3", "d7d5", "f1g2", "g8f6", "g1f3")

        canonical_result = self.classifier.classify(canonical, {})
        transposed_result = self.classifier.classify(transposed, {})

        self.assertEqual("dataset_prefix", canonical_result.source)
        self.assertEqual("dataset_position", transposed_result.source)
        self.assertEqual(canonical_result.eco, transposed_result.eco)
        self.assertEqual(canonical_result.opening, transposed_result.opening)
        self.assertEqual(canonical_result.variation, transposed_result.variation)
        self.assertEqual(canonical_result.subvariation, transposed_result.subvariation)
        self.assertEqual(5, transposed_result.deepest_ply)

    def test_conflicting_position_labels_are_not_chosen_arbitrarily(self) -> None:
        rows = [
            {
                "eco": "A07",
                "name": "First Label",
                "pgn": "",
                "uci": "g1f3 d7d5 g2g3 g8f6 f1g2",
            },
            {
                "eco": "A08",
                "name": "Second Label",
                "pgn": "",
                "uci": "g2g3 d7d5 f1g2 g8f6 g1f3",
            },
        ]
        third_move_order = ("g2g3", "g8f6", "g1f3", "d7d5", "f1g2")
        with tempfile.TemporaryDirectory() as directory:
            classifier = BundledOpeningClassifier(write_dataset(Path(directory), rows))
            result = classifier.classify(third_move_order, {})

        self.assertEqual("Unknown", result.opening)
        self.assertEqual("unknown", result.source)
        self.assertEqual(0, result.deepest_ply)

    def test_dataset_result_takes_precedence_over_conflicting_headers(self) -> None:
        classification = self.classifier.classify(
            ("e2e4", "e7e5"),
            {"ECO": "A00", "Opening": "Definitely Wrong", "Variation": "Wrong Line"},
        )
        self.assertEqual("C20", classification.eco)
        self.assertEqual("King's Pawn Game", classification.opening)
        self.assertEqual("dataset_prefix", classification.source)

    def test_explicit_pgn_headers_are_used_only_as_fallback(self) -> None:
        classification = self.classifier.classify(
            ("h2h3", "a7a6"),
            {
                "ECO": "A00",
                "Opening": "Clemenz Opening",
                "Variation": "Main Line",
                "SubVariation": "Synthetic Detail",
            },
        )
        self.assertEqual("A00", classification.eco)
        self.assertEqual("Clemenz Opening", classification.opening)
        self.assertEqual("Main Line", classification.variation)
        self.assertEqual("Synthetic Detail", classification.subvariation)
        self.assertEqual(0, classification.deepest_ply)
        self.assertEqual("pgn_headers", classification.source)

    def test_unknown_is_explicit_when_no_dataset_or_named_header_matches(self) -> None:
        classification = self.classifier.classify(("h2h3",), {"ECO": "A00"})
        self.assertEqual("A00", classification.eco)
        self.assertEqual("Unknown", classification.opening)
        self.assertEqual("", classification.variation)
        self.assertEqual("", classification.subvariation)
        self.assertEqual(0, classification.deepest_ply)
        self.assertEqual("unknown", classification.source)
        self.assertFalse(classification.is_classified)

    def test_pgn_column_is_supported_when_uci_column_is_empty(self) -> None:
        classification = self.classifier.classify(("d2d4", "d7d5"), {})
        self.assertEqual("D00", classification.eco)
        self.assertEqual("Queen's Pawn Game", classification.opening)
        self.assertEqual(2, classification.deepest_ply)

    def test_invalid_or_illegal_input_stops_at_last_reliable_match(self) -> None:
        classification = self.classifier.classify(("e2e4", "e7e5", "not-uci"), {})
        self.assertEqual("King's Pawn Game", classification.opening)
        self.assertEqual(2, classification.deepest_ply)


class OpeningHelpersTests(unittest.TestCase):
    def test_position_key_uses_exactly_first_four_relevant_fen_fields(self) -> None:
        board = chess.Board()
        board.push_uci("e2e4")
        key = position_key(board)
        self.assertEqual(4, len(key.split()))
        self.assertEqual("-", key.split()[3], "a non-capturable en-passant square is normalized away")

    def test_transposed_boards_share_a_position_key(self) -> None:
        first = chess.Board()
        for move in ("g1f3", "d7d5", "g2g3", "g8f6", "f1g2"):
            first.push_uci(move)
        second = chess.Board()
        for move in ("g2g3", "d7d5", "f1g2", "g8f6", "g1f3"):
            second.push_uci(move)
        self.assertEqual(position_key(first), position_key(second))

    def test_opening_name_split_does_not_invent_missing_levels(self) -> None:
        self.assertEqual(("Owen Defense", "", ""), split_opening_name("Owen Defense"))
        self.assertEqual(
            ("Three Knights Opening", "Steinitz Variation", "Quiet Line"),
            split_opening_name("Three Knights Opening: Steinitz Variation, Quiet Line"),
        )


if __name__ == "__main__":
    unittest.main()
