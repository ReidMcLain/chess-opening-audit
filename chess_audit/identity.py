from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from typing import Iterable, Literal, Mapping

from .models import Color, GameRecord, ParsedGame, UserResult


IdentityStatus = Literal["white", "black", "unmatched", "ambiguous"]
CHESS_COM_URL_RE = re.compile(
    r"https?://(?:www\.)?chess\.com/(?:game/(?:live|daily)/|live/game/|daily/game/)(\d+)(?:[^\s\"]*)?",
    re.IGNORECASE,
)


def normalize_username(value: str) -> str:
    return value.strip().casefold()


def normalize_usernames(values: Iterable[str]) -> frozenset[str]:
    return frozenset(normalize_username(value) for value in values if normalize_username(value))


def header(headers: Mapping[str, str], *names: str) -> str:
    folded = {key.casefold(): str(value).strip() for key, value in headers.items()}
    for name in names:
        value = folded.get(name.casefold(), "")
        if value:
            return value
    return ""


def identify_player(headers: Mapping[str, str], usernames: frozenset[str]) -> IdentityStatus:
    white_match = normalize_username(header(headers, "White")) in usernames
    black_match = normalize_username(header(headers, "Black")) in usernames
    if white_match and black_match:
        return "ambiguous"
    if white_match:
        return "white"
    if black_match:
        return "black"
    return "unmatched"


def chess_com_url(headers: Mapping[str, str]) -> str:
    for name in ("Link", "GameURL", "URL", "Site"):
        value = header(headers, name)
        match = CHESS_COM_URL_RE.search(value)
        if match:
            return match.group(0).rstrip("/.,;)")
    for value in headers.values():
        match = CHESS_COM_URL_RE.search(str(value))
        if match:
            return match.group(0).rstrip("/.,;)")
    return ""


def stable_game_id(headers: Mapping[str, str], moves_uci: tuple[str, ...]) -> tuple[str, str]:
    link = chess_com_url(headers)
    if link:
        match = CHESS_COM_URL_RE.search(link)
        if match:
            return f"chesscom:{match.group(1)}", link

    payload = {
        "white": normalize_username(header(headers, "White")),
        "black": normalize_username(header(headers, "Black")),
        "utc_date": header(headers, "UTCDate", "Date"),
        "utc_time": header(headers, "UTCTime", "EndTime", "Time"),
        "result": header(headers, "Result"),
        "moves_uci": list(moves_uci),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}", ""


def parse_rating(value: str) -> int | None:
    value = value.strip()
    if not value or value in {"?", "-"}:
        return None
    try:
        rating = int(value)
    except ValueError:
        return None
    # Treat impossible values as missing rather than allowing malformed headers
    # to overflow Elo expectation calculations.
    return rating if 0 < rating <= 10_000 else None


def parse_game_date(headers: Mapping[str, str]) -> date | None:
    value = header(headers, "UTCDate", "Date")
    if not value or "?" in value:
        return None
    for pattern in ("%Y.%m.%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, pattern).date()
        except ValueError:
            continue
    return None


def parse_utc_datetime(headers: Mapping[str, str]) -> str | None:
    date_value = header(headers, "UTCDate")
    time_value = header(headers, "UTCTime")
    if not date_value or not time_value or "?" in date_value + time_value:
        return None
    normalized_time = time_value.rstrip("Z")
    for date_pattern in ("%Y.%m.%d", "%Y-%m-%d"):
        for time_pattern in ("%H:%M:%S", "%H:%M"):
            try:
                parsed = datetime.strptime(f"{date_value} {normalized_time}", f"{date_pattern} {time_pattern}")
                return parsed.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
            except ValueError:
                continue
    return None


def parse_rated(headers: Mapping[str, str]) -> bool | None:
    value = header(headers, "Rated", "IsRated").casefold()
    if value in {"true", "yes", "1", "rated"}:
        return True
    if value in {"false", "no", "0", "unrated"}:
        return False
    return None


def normalize_result(pgn_result: str, user_color: Color) -> UserResult:
    result = pgn_result.strip()
    if result == "1/2-1/2":
        return "draw"
    if result == "1-0":
        return "win" if user_color == "white" else "loss"
    if result == "0-1":
        return "win" if user_color == "black" else "loss"
    return "unknown"


def build_game_record(parsed: ParsedGame, user_color: Color, occurrence: int = 1) -> GameRecord:
    headers = parsed.headers
    white_rating = parse_rating(header(headers, "WhiteElo", "WhiteRating"))
    black_rating = parse_rating(header(headers, "BlackElo", "BlackRating"))
    user_rating = white_rating if user_color == "white" else black_rating
    opponent_rating = black_rating if user_color == "white" else white_rating
    rating_difference = (
        user_rating - opponent_rating if user_rating is not None and opponent_rating is not None else None
    )
    game_id, link = stable_game_id(headers, parsed.moves_uci)
    record_id = game_id if occurrence == 1 else f"{game_id}#occurrence-{occurrence}"
    pgn_result = header(headers, "Result") or "*"
    classification = parsed.classification
    return GameRecord(
        record_id=record_id,
        source_file=str(parsed.source_file.resolve()),
        game_index=parsed.game_index,
        stable_game_id=game_id,
        identity_source="chesscom_id" if game_id.startswith("chesscom:") else "move_hash",
        chess_com_url=link,
        event=header(headers, "Event"),
        site=header(headers, "Site"),
        utc_datetime=parse_utc_datetime(headers),
        game_date=parse_game_date(headers),
        white_username=header(headers, "White"),
        black_username=header(headers, "Black"),
        white_rating=white_rating,
        black_rating=black_rating,
        user_color=user_color,
        user_rating=user_rating,
        opponent_rating=opponent_rating,
        rating_difference=rating_difference,
        pgn_result=pgn_result,
        user_result=normalize_result(pgn_result, user_color),
        time_control=header(headers, "TimeControl"),
        termination=header(headers, "Termination"),
        rated=parse_rated(headers),
        eco=classification.eco,
        opening=classification.opening,
        variation=classification.variation,
        subvariation=classification.subvariation,
        deepest_classified_ply=classification.deepest_ply,
        opening_dataset_version=classification.dataset_version,
        classification_source=classification.source,
        moves_uci=parsed.moves_uci,
    )
