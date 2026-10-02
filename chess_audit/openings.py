from __future__ import annotations

import csv
import hashlib
import io
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Protocol

import chess
import chess.pgn

from .identity import header
from .models import OpeningClassification


def position_key(board: chess.Board) -> str:
    """Return the transposition key: placement, turn, castling, legal en-passant."""
    return " ".join(board.fen(en_passant="legal").split()[:4])


def split_opening_name(name: str) -> tuple[str, str, str]:
    """Map the dataset's documented family: variation, subvariation convention."""
    family, separator, detail = name.partition(":")
    opening = family.strip() or "Unknown"
    if not separator:
        return opening, "", ""
    parts = [part.strip() for part in detail.split(",") if part.strip()]
    variation = parts[0] if parts else ""
    subvariation = ", ".join(parts[1:]) if len(parts) > 1 else ""
    return opening, variation, subvariation


class OpeningClassifier(Protocol):
    dataset_version: str

    def classify(self, moves_uci: Iterable[str], headers: Mapping[str, str]) -> OpeningClassification:
        ...


@dataclass(frozen=True, slots=True)
class _DatasetEntry:
    eco: str
    name: str
    moves: tuple[str, ...]
    final_position_key: str

    def classification(self, ply: int, version: str, source: str) -> OpeningClassification:
        opening, variation, subvariation = split_opening_name(self.name)
        return OpeningClassification(
            eco=self.eco,
            opening=opening,
            variation=variation,
            subvariation=subvariation,
            deepest_ply=ply,
            dataset_version=version,
            source=source,
        )


class BundledOpeningClassifier:
    """Classify against replaceable TSV data using exact lines and unique positions."""

    def __init__(self, data_directory: Path) -> None:
        self.data_directory = data_directory
        metadata_path = data_directory / "metadata.json"
        if not metadata_path.is_file():
            raise ValueError(f"Opening dataset metadata is missing: {metadata_path}")
        try:
            self.metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Cannot read opening dataset metadata: {exc}") from exc
        self.dataset_version = str(self.metadata.get("version", "unknown"))
        files = self.metadata.get("files") or ["a.tsv", "b.tsv", "c.tsv", "d.tsv", "e.tsv"]
        if files == ["openings.tsv"] and self.metadata.get("runtime_sha256"):
            runtime_path = data_directory / "openings.tsv"
            if not runtime_path.is_file():
                raise ValueError(f"Opening dataset file is missing: {runtime_path}")
            actual_hash = hashlib.sha256(runtime_path.read_bytes()).hexdigest()
            if actual_hash != self.metadata["runtime_sha256"]:
                raise ValueError("Opening dataset checksum does not match metadata")
        self._prefixes: dict[tuple[str, ...], tuple[_DatasetEntry, ...]] = {}
        self._positions: dict[str, tuple[_DatasetEntry, ...]] = {}
        self._load([data_directory / str(name) for name in files])
        expected_count = self.metadata.get("entry_count")
        if expected_count is not None and self.entry_count != int(expected_count):
            raise ValueError(
                f"Opening dataset entry count mismatch: expected {expected_count}, loaded {self.entry_count}"
            )

    @property
    def entry_count(self) -> int:
        return sum(len(entries) for entries in self._prefixes.values())

    def _load(self, paths: Iterable[Path]) -> None:
        prefixes: dict[tuple[str, ...], list[_DatasetEntry]] = defaultdict(list)
        positions: dict[str, list[_DatasetEntry]] = defaultdict(list)
        for path in paths:
            if not path.is_file():
                raise ValueError(f"Opening dataset file is missing: {path}")
            try:
                stream = path.open("r", encoding="utf-8-sig", newline="")
            except OSError as exc:
                raise ValueError(f"Cannot open opening dataset {path}: {exc}") from exc
            with stream:
                reader = csv.DictReader(stream, delimiter="\t")
                required = {"eco", "name"}
                if not reader.fieldnames or not required.issubset(reader.fieldnames):
                    raise ValueError(f"Opening dataset has invalid columns: {path}")
                for line_number, row in enumerate(reader, 2):
                    try:
                        moves, final_key = self._moves_and_position(row)
                    except ValueError as exc:
                        raise ValueError(f"Invalid opening row {path.name}:{line_number}: {exc}") from exc
                    if not moves:
                        continue
                    entry = _DatasetEntry(
                        eco=(row.get("eco") or "").strip(),
                        name=(row.get("name") or "").strip(),
                        moves=moves,
                        final_position_key=final_key,
                    )
                    if not entry.name:
                        continue
                    prefixes[moves].append(entry)
                    positions[final_key].append(entry)
        if not prefixes:
            raise ValueError("Opening dataset contains no usable entries")
        self._prefixes = {key: tuple(value) for key, value in prefixes.items()}
        self._positions = {key: tuple(value) for key, value in positions.items()}

    @staticmethod
    def _moves_and_position(row: Mapping[str, str]) -> tuple[tuple[str, ...], str]:
        uci = (row.get("uci") or "").strip()
        if uci:
            moves = tuple(uci.split())
            board = chess.Board()
            for text in moves:
                try:
                    move = chess.Move.from_uci(text)
                except ValueError as exc:
                    raise ValueError(f"invalid UCI move {text!r}") from exc
                if move not in board.legal_moves:
                    raise ValueError(f"illegal UCI move {text!r}")
                board.push(move)
            return moves, position_key(board)

        pgn = (row.get("pgn") or "").strip()
        game = chess.pgn.read_game(io.StringIO(pgn)) if pgn else None
        if game is None or game.errors:
            raise ValueError("missing or malformed PGN line")
        board = game.board()
        moves_list: list[str] = []
        for move in game.mainline_moves():
            if move not in board.legal_moves:
                raise ValueError(f"illegal PGN move {move.uci()!r}")
            moves_list.append(move.uci())
            board.push(move)
        return tuple(moves_list), position_key(board)

    @staticmethod
    def _unique_entry(entries: tuple[_DatasetEntry, ...] | None) -> _DatasetEntry | None:
        if not entries:
            return None
        distinct = {(entry.eco, entry.name) for entry in entries}
        if len(distinct) != 1:
            return None
        return min(entries, key=lambda entry: (entry.eco, entry.name, entry.moves))

    def classify(self, moves_uci: Iterable[str], headers: Mapping[str, str]) -> OpeningClassification:
        board = chess.Board()
        prefix: list[str] = []
        best: OpeningClassification | None = None
        for ply, text in enumerate(moves_uci, 1):
            try:
                move = chess.Move.from_uci(text)
            except ValueError:
                break
            if move not in board.legal_moves:
                break
            prefix.append(move.uci())
            board.push(move)

            exact = self._unique_entry(self._prefixes.get(tuple(prefix)))
            if exact is not None:
                best = exact.classification(ply, self.dataset_version, "dataset_prefix")
                continue
            transposed = self._unique_entry(self._positions.get(position_key(board)))
            if transposed is not None:
                best = transposed.classification(ply, self.dataset_version, "dataset_position")

        if best is not None:
            return best
        return self._header_fallback(headers)

    def _header_fallback(self, headers: Mapping[str, str]) -> OpeningClassification:
        opening = header(headers, "Opening")
        variation = header(headers, "Variation")
        subvariation = header(headers, "SubVariation", "Subvariation")
        eco = header(headers, "ECO")
        if opening:
            return OpeningClassification(
                eco=eco,
                opening=opening,
                variation=variation,
                subvariation=subvariation,
                deepest_ply=0,
                dataset_version=self.dataset_version,
                source="pgn_headers",
            )
        return OpeningClassification(
            eco=eco,
            opening="Unknown",
            variation="",
            subvariation="",
            deepest_ply=0,
            dataset_version=self.dataset_version,
            source="unknown",
        )
