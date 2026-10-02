from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

import chess.pgn


TAG_LINE_RE = re.compile(r'^\s*\[[A-Za-z][A-Za-z0-9_]*\s+"')
TAG_BLOCK_LINE_RE = re.compile(r"(?m)^\s*\[[^\r\n]*\]\s*$")
BRACE_COMMENT_RE = re.compile(r"\{.*?\}", re.DOTALL)
SEMICOLON_COMMENT_RE = re.compile(r";[^\r\n]*")
ESCAPE_LINE_RE = re.compile(r"(?m)^\s*%[^\r\n]*$")
ALLOWED_MOVETEXT_GAP_RE = re.compile(r"(?:\d+\.{1,3}|\.{1,3}|e\.?p\.?|[\s+#=])*", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class PgnReadItem:
    source_file: Path
    game_index: int
    headers: dict[str, str]
    moves_uci: tuple[str, ...]
    malformed: bool
    errors: tuple[str, ...]


def _canonical(path: Path) -> Path:
    return path.expanduser().resolve()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def discover_pgn_files(
    explicit_files: Iterable[Path],
    folder: Path | None,
    recursive: bool,
    excluded_roots: Iterable[Path] = (),
) -> tuple[list[Path], list[str]]:
    """Return a deterministic canonical union without following directory links."""
    warnings: list[str] = []
    excluded = tuple(_canonical(path) for path in excluded_roots)
    candidates: list[Path] = []

    for supplied in explicit_files:
        path = _canonical(supplied)
        if not path.is_file():
            warnings.append(f"Input file does not exist or is not a file: {path}")
            continue
        if path.suffix.casefold() != ".pgn":
            warnings.append(f"Input file is not a .pgn file and was ignored: {path}")
            continue
        candidates.append(path)

    if folder is not None:
        root = _canonical(folder)
        if not root.is_dir():
            raise ValueError(f"Input folder does not exist or is not a directory: {root}")
        if recursive:
            for current, directories, filenames in os.walk(root, topdown=True, followlinks=False):
                current_path = Path(current).resolve()
                directories[:] = sorted(
                    (
                        name
                        for name in directories
                        if not Path(current, name).is_symlink()
                        and not any(_is_within(Path(current, name).resolve(), item) for item in excluded)
                        and not (Path(current, name) / "run_manifest.json").is_file()
                    ),
                    key=str.casefold,
                )
                for filename in sorted(filenames, key=str.casefold):
                    if Path(filename).suffix.casefold() == ".pgn":
                        path = current_path / filename
                        if not any(_is_within(path, item) for item in excluded):
                            candidates.append(path.resolve())
        else:
            for path in sorted(root.iterdir(), key=lambda item: item.name.casefold()):
                if path.is_file() and path.suffix.casefold() == ".pgn":
                    resolved = path.resolve()
                    if not any(_is_within(resolved, item) for item in excluded):
                        candidates.append(resolved)

    unique: dict[str, Path] = {}
    for path in candidates:
        unique.setdefault(os.path.normcase(str(path)), path)
    return sorted(unique.values(), key=lambda path: os.path.normcase(str(path))), warnings


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _recover_to_next_tag(stream, failed_offset: int) -> bool:
    """Seek to a later plausible PGN tag block after an exceptional parse."""
    try:
        saw_blank = False
        if stream.tell() <= failed_offset:
            skipped_line = stream.readline()
            if not skipped_line:
                return False
            saw_blank = not skipped_line.strip()
        while True:
            offset = stream.tell()
            line = stream.readline()
            if not line:
                return False
            if saw_blank and TAG_LINE_RE.match(line):
                stream.seek(offset)
                return True
            saw_blank = not line.strip()
    except (OSError, UnicodeError):
        return False


def _consumed_text(stream, start: int, end: int) -> str:
    """Read only the just-consumed game span, then restore the parser position."""
    if end <= start:
        return ""
    stream.seek(start)
    parts: list[str] = []
    while stream.tell() != end:
        line = stream.readline()
        if not line:
            break
        parts.append(line)
        if stream.tell() > end:
            break
    stream.seek(end)
    return "".join(parts)


def _unrecognized_movetext(raw_game: str) -> tuple[str, ...]:
    """Detect text python-chess's permissive token scanner would silently skip."""
    if raw_game.count("{") != raw_game.count("}"):
        return ("Unbalanced PGN brace comment",)
    cleaned = BRACE_COMMENT_RE.sub(" ", raw_game)
    cleaned = SEMICOLON_COMMENT_RE.sub(" ", cleaned)
    cleaned = TAG_BLOCK_LINE_RE.sub(" ", cleaned)
    cleaned = ESCAPE_LINE_RE.sub(" ", cleaned)
    gaps: list[str] = []
    cursor = 0
    for match in chess.pgn.MOVETEXT_REGEX.finditer(cleaned):
        gaps.append(cleaned[cursor : match.start()])
        cursor = match.end()
    gaps.append(cleaned[cursor:])
    unexpected = " ".join(gap.strip() for gap in gaps if gap.strip())
    if not unexpected or ALLOWED_MOVETEXT_GAP_RE.fullmatch(unexpected):
        return ()
    compact = " ".join(unexpected.split())
    return (f"Unrecognized PGN movetext: {compact[:120]}",)


def iter_pgn_file(path: Path) -> Iterator[PgnReadItem]:
    """Stream games, surfacing malformed records without mutating the source."""
    with path.open("r", encoding="utf-8-sig", errors="replace", newline=None) as stream:
        game_index = 0
        while True:
            offset = stream.tell()
            try:
                game = chess.pgn.read_game(stream)
            except Exception as exc:  # parser recovery must isolate a bad record
                game_index += 1
                yield PgnReadItem(
                    source_file=path,
                    game_index=game_index,
                    headers={},
                    moves_uci=(),
                    malformed=True,
                    errors=(f"{type(exc).__name__}: {exc}",),
                )
                if not _recover_to_next_tag(stream, offset):
                    return
                continue
            if game is None:
                return
            end_offset = stream.tell()
            game_index += 1
            errors = tuple(f"{type(error).__name__}: {error}" for error in game.errors)
            errors += _unrecognized_movetext(_consumed_text(stream, offset, end_offset))
            moves: list[str] = []
            board = game.board()
            for move in game.mainline_moves():
                if move not in board.legal_moves:
                    errors += (f"Illegal main-line move: {move.uci()}",)
                    break
                moves.append(move.uci())
                board.push(move)
            yield PgnReadItem(
                source_file=path,
                game_index=game_index,
                headers={str(key): str(value) for key, value in game.headers.items()},
                moves_uci=tuple(moves),
                malformed=bool(errors),
                errors=errors,
            )
