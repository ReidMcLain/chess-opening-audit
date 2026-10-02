"""Build the offline runtime opening table from a pinned Lichess snapshot.

This maintenance command is not used during normal audits. Download a.tsv through
e.tsv from the exact UPSTREAM_COMMIT into --source, then run this script.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path

import chess
import chess.pgn


UPSTREAM_COMMIT = "292fd0468068f58bb244f7fe1c3e573e493c3c53"
SOURCE_HASHES = {
    "a.tsv": "41722fa3d44f294357326fe2ca1b956d9e56490b30efcfa68db61114c9df7e10",
    "b.tsv": "28d5c2dfc3329d70e85be2a149d001a59e47c2176c9d2c6594eb3be88128a3fc",
    "c.tsv": "e90f063b3a04f5fbb24425682b13f574141a266a1ba877974cdd9c6595a3d942",
    "d.tsv": "58cad40b886bd499717eabcce281d4bfcf00eeadbdc00552f42042cf4aac50d2",
    "e.tsv": "f1f8494f488f660e284f23527d5acfbeccdbbc3acc76e74f05d125f39d2f8a74",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(source: Path, output: Path) -> None:
    rows: list[dict[str, str | int]] = []
    positions: set[str] = set()
    for filename, expected_hash in SOURCE_HASHES.items():
        path = source / filename
        actual_hash = digest(path)
        if actual_hash != expected_hash:
            raise ValueError(f"Hash mismatch for {filename}: {actual_hash}")
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream, delimiter="\t"):
                game = chess.pgn.read_game(io.StringIO(row["pgn"]))
                if game is None or game.errors:
                    raise ValueError(f"Malformed dataset PGN: {filename} {row}")
                board = game.board()
                moves: list[str] = []
                for move in game.mainline_moves():
                    if move not in board.legal_moves:
                        raise ValueError(f"Illegal dataset move: {filename} {row}")
                    moves.append(move.uci())
                    board.push(move)
                epd = " ".join(board.fen(en_passant="legal").split()[:4])
                if epd in positions:
                    raise ValueError(f"Duplicate final opening position: {filename} {epd}")
                positions.add(epd)
                rows.append(
                    {
                        "eco": row["eco"],
                        "name": row["name"],
                        "pgn": row["pgn"],
                        "uci": " ".join(moves),
                        "epd": epd,
                        "canonical_ply": len(moves),
                    }
                )
    rows.sort(key=lambda row: (str(row["eco"]), str(row["name"]), str(row["uci"])))
    output.mkdir(parents=True, exist_ok=True)
    runtime_path = output / "openings.tsv"
    with runtime_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=("eco", "name", "pgn", "uci", "epd", "canonical_ply"),
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)
    metadata = {
        "schema_version": "1.0",
        "version": f"lichess-chess-openings@git-{UPSTREAM_COMMIT}",
        "upstream": "https://github.com/lichess-org/chess-openings",
        "upstream_commit": UPSTREAM_COMMIT,
        "upstream_commit_date": "2026-07-12",
        "license": "CC0-1.0",
        "files": ["openings.tsv"],
        "entry_count": len(rows),
        "eco_code_count": len({str(row["eco"]) for row in rows}),
        "maximum_canonical_ply": max(int(row["canonical_ply"]) for row in rows),
        "runtime_sha256": digest(runtime_path),
        "source_sha256": SOURCE_HASHES,
        "generated_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "generator": "tools/build_opening_dataset.py",
        "python_chess_version": chess.__version__,
    }
    (output / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"Wrote {len(rows)} positions to {runtime_path}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("data"))
    arguments = parser.parse_args()
    build(arguments.source, arguments.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

