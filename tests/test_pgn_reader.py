from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import chess.pgn

from chess_audit.pgn_reader import discover_pgn_files, iter_pgn_file, sha256_file


ONE_GAME = """[Event "Synthetic One"]
[Site "Local"]
[UTCDate "2026.07.14"]
[UTCTime "12:00:00"]
[White "ReidMate"]
[Black "Opponent"]
[Result "1-0"]

1. e4 e5 2. Nf3 Nc6 1-0
"""


SECOND_GAME = """[Event "Synthetic Two"]
[Site "Local"]
[UTCDate "2026.07.15"]
[UTCTime "13:00:00"]
[White "Opponent"]
[Black "ReidMate"]
[Result "1/2-1/2"]

1. d4 d5 2. c4 e6 1/2-1/2
"""


class PgnStreamingTests(unittest.TestCase):
    def test_unrecognized_movetext_is_reported_instead_of_silently_truncated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unknown-token.pgn"
            path.write_text(
                '[Event "Bad token"]\n[White "Hero"]\n[Black "Other"]\n[Result "*"]\n\n'
                "1. e4 e5 2. ThisIsNotAMove *\n",
                encoding="utf-8",
            )
            items = list(iter_pgn_file(path))

        self.assertEqual(1, len(items))
        self.assertTrue(items[0].malformed)
        self.assertTrue(any("Unrecognized PGN movetext" in error for error in items[0].errors))

    def test_streams_one_game_without_loading_an_archive_string(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "one.pgn"
            source.write_text(ONE_GAME, encoding="utf-8")
            items = list(iter_pgn_file(source))

        self.assertEqual(1, len(items))
        item = items[0]
        self.assertEqual(source, item.source_file)
        self.assertEqual(1, item.game_index)
        self.assertEqual("Synthetic One", item.headers["Event"])
        self.assertEqual(("e2e4", "e7e5", "g1f3", "b8c6"), item.moves_uci)
        self.assertFalse(item.malformed)
        self.assertEqual((), item.errors)

    def test_streams_multiple_games_in_source_order(self) -> None:
        with tempfile.TemporaryDirectory(prefix="PGN archive with spaces ") as directory:
            source = Path(directory) / "many games archive.pgn"
            source.write_text(ONE_GAME + "\n" + SECOND_GAME, encoding="utf-8")
            items = list(iter_pgn_file(source))

        self.assertEqual([1, 2], [item.game_index for item in items])
        self.assertEqual(["Synthetic One", "Synthetic Two"], [item.headers["Event"] for item in items])
        self.assertEqual(("d2d4", "d7d5", "c2c4", "e7e6"), items[1].moves_uci)

    def test_illegal_san_is_marked_malformed_and_later_game_survives(self) -> None:
        malformed = """[Event "Broken"]
[White "ReidMate"]
[Black "Opponent"]
[Result "0-1"]

1. e4 e5 2. Nf3 Nc6 3. e5 0-1
"""
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "broken then valid.pgn"
            original = (malformed + "\n" + SECOND_GAME).encode("utf-8")
            source.write_bytes(original)
            with self.assertLogs("chess.pgn", level="ERROR"):
                items = list(iter_pgn_file(source))
            after = source.read_bytes()

        self.assertEqual(original, after, "the reader must never alter source PGNs")
        self.assertEqual(2, len(items))
        self.assertTrue(items[0].malformed)
        self.assertTrue(any("IllegalMoveError" in error for error in items[0].errors))
        self.assertEqual(("e2e4", "e7e5", "g1f3", "b8c6"), items[0].moves_uci)
        self.assertFalse(items[1].malformed)
        self.assertEqual("Synthetic Two", items[1].headers["Event"])

    def test_exception_recovery_forces_progress_to_next_tag_block(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "exception recovery.pgn"
            source.write_text(ONE_GAME + "\n" + SECOND_GAME, encoding="utf-8")
            real_read_game = chess.pgn.read_game
            calls = 0

            def fail_once(stream):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise RuntimeError("synthetic parser failure")
                return real_read_game(stream)

            with patch("chess_audit.pgn_reader.chess.pgn.read_game", side_effect=fail_once):
                items = list(iter_pgn_file(source))

        self.assertEqual(2, len(items))
        self.assertEqual(1, items[0].game_index)
        self.assertTrue(items[0].malformed)
        self.assertEqual({}, items[0].headers)
        self.assertIn("RuntimeError: synthetic parser failure", items[0].errors[0])
        self.assertEqual(2, items[1].game_index)
        self.assertEqual("Synthetic Two", items[1].headers["Event"])

    def test_invalid_utf8_is_replaced_and_does_not_abort_reading(self) -> None:
        raw = ONE_GAME.replace("Synthetic One", "Synthetic Caf\N{LATIN SMALL LETTER E WITH ACUTE}").encode("utf-8")
        raw = raw.replace("Caf\N{LATIN SMALL LETTER E WITH ACUTE}".encode("utf-8"), b"Caf\xff")
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "encoding.pgn"
            source.write_bytes(raw)
            items = list(iter_pgn_file(source))

        self.assertEqual(1, len(items))
        self.assertEqual("Synthetic Caf\ufffd", items[0].headers["Event"])
        self.assertFalse(items[0].malformed)

    def test_sha256_file_reads_in_binary_blocks(self) -> None:
        payload = b"PGN\x00bytes\r\n" * 1000
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "hash.pgn"
            source.write_bytes(payload)
            actual = sha256_file(source)
        self.assertEqual(hashlib.sha256(payload).hexdigest(), actual)


class PgnDiscoveryTests(unittest.TestCase):
    @staticmethod
    def _touch(path: Path, contents: str = ONE_GAME) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
        return path.resolve()

    def test_nonrecursive_discovery_is_case_insensitive_and_deterministic(self) -> None:
        with tempfile.TemporaryDirectory(prefix="opening audit folder with spaces ") as directory:
            root = Path(directory)
            b_file = self._touch(root / "b.pgn")
            a_file = self._touch(root / "A.PGN")
            self._touch(root / "nested" / "c.pgn")
            (root / "notes.txt").write_text("not PGN", encoding="utf-8")

            files, warnings = discover_pgn_files((), root, recursive=False)

        expected = sorted((a_file, b_file), key=lambda item: os.path.normcase(str(item)))
        self.assertEqual(expected, files)
        self.assertEqual([], warnings)

    def test_recursive_discovery_ignores_output_and_prior_report_directories(self) -> None:
        with tempfile.TemporaryDirectory(prefix="recursive PGNs with spaces ") as directory:
            root = Path(directory)
            root_game = self._touch(root / "root.pgn")
            nested_game = self._touch(root / "nested folder" / "nested.PGN")

            output = root / "opening-audit-output"
            self._touch(output / "should never be scanned.pgn")

            prior_report = root / "prior report"
            self._touch(prior_report / "also ignored.pgn")
            (prior_report / "run_manifest.json").write_text("{}", encoding="utf-8")

            files, warnings = discover_pgn_files(
                (), root, recursive=True, excluded_roots=(output,)
            )

        expected = sorted((root_game, nested_game), key=lambda item: os.path.normcase(str(item)))
        self.assertEqual(expected, files)
        self.assertEqual([], warnings)

    def test_explicit_and_folder_inputs_form_a_canonical_union_with_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            included = self._touch(root / "included.pgn")
            extra = self._touch(root / "extra.PGN")
            non_pgn = root / "notes.txt"
            non_pgn.write_text("ignore", encoding="utf-8")
            missing = root / "missing.pgn"

            files, warnings = discover_pgn_files(
                (included, included, non_pgn, missing), root, recursive=False
            )

        expected = sorted((included, extra), key=lambda item: os.path.normcase(str(item)))
        self.assertEqual(expected, files)
        self.assertEqual(2, len(warnings))
        self.assertTrue(any("not a .pgn" in warning for warning in warnings))
        self.assertTrue(any("does not exist" in warning for warning in warnings))

    def test_missing_folder_is_a_clear_configuration_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "no such folder"
            with self.assertRaisesRegex(ValueError, "Input folder does not exist"):
                discover_pgn_files((), missing, recursive=True)


if __name__ == "__main__":
    unittest.main()
