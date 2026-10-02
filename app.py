"""A small Streamlit report for Chess.com opening performance."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import chess.pgn
import pandas as pd
import requests
import streamlit as st


USER_AGENT = "ChessOpeningPerformance/1.0 (personal Streamlit analysis app)"
REQUEST_TIMEOUT_SECONDS = 30
OLD_LINES_PATH = Path(__file__).with_name("old_lines.json")

# Add or edit rules here.  Rules use exact SAN prefixes, in the order shown.
OPENING_RULES: list[dict[str, list[str] | str]] = [
    {"name": "Italian Game", "moves": ["e4", "e5", "Nf3", "Nc6", "Bc4"]},
    {"name": "Philidor Defense", "moves": ["e4", "e5", "Nf3", "d6"]},
    {"name": "Petrov Defense", "moves": ["e4", "e5", "Nf3", "Nf6"]},
    {"name": "Busch-Gass Gambit", "moves": ["e4", "e5", "Nf3", "Bc5"]},
    {"name": "Elephant Gambit", "moves": ["e4", "e5", "Nf3", "d5"]},
    {"name": "McConnell Defense", "moves": ["e4", "e5", "Nf3", "Qf6"]},
    {"name": "Latvian Gambit", "moves": ["e4", "e5", "Nf3", "f5"]},
    {"name": "Damiano Defense", "moves": ["e4", "e5", "Nf3", "f6"]},
    {"name": "Gunderam Gambit", "moves": ["e4", "e5", "Nf3", "c6"]},
    {"name": "Gunderam Defense", "moves": ["e4", "e5", "Nf3", "Qe7"]},
    {"name": "Old Sicilian", "moves": ["e4", "c5", "Nf3", "Nc6"]},
    {"name": "Modern Sicilian", "moves": ["e4", "c5", "Nf3", "d6"]},
    {"name": "French Sicilian", "moves": ["e4", "c5", "Nf3", "e6"]},
    {"name": "Hyper Accelerated Dragon Sicilian", "moves": ["e4", "c5", "Nf3", "g6"]},
    {"name": "O'Kelly Sicilian", "moves": ["e4", "c5", "Nf3", "a6"]},
    {"name": "d5 French", "moves": ["e4", "e6", "d4", "d5"]},
    {"name": "b6 French", "moves": ["e4", "e6", "d4", "b6"]},
    {"name": "c5 French", "moves": ["e4", "e6", "d4", "c5"]},
    {"name": "c6 French", "moves": ["e4", "e6", "d4", "c6"]},
    {"name": "Ne7 French", "moves": ["e4", "e6", "d4", "Ne7"]},
    {"name": "d6 French", "moves": ["e4", "e6", "d4", "d6"]},
    {"name": "Nc6 French", "moves": ["e4", "e6", "d4", "Nc6"]},
    {"name": "g6 French", "moves": ["e4", "e6", "d4", "g6"]},
    {"name": "Be7 French", "moves": ["e4", "e6", "d4", "Be7"]},
    {"name": "Mediterranean Defense", "moves": ["e4", "e6", "d4", "Nf6"]},
    {"name": "Qxd5 Scandinavian", "moves": ["e4", "d5", "exd5", "Qxd5"]},
    {"name": "Nf6 Scandinavian", "moves": ["e4", "d5", "exd5", "Nf6"]},
    {"name": "e6 Scandinavian", "moves": ["e4", "d5", "exd5", "e6"]},
    {"name": "e5 Scandinavian", "moves": ["e4", "d5", "exd5", "e5"]},
    {"name": "Blackburne-Kloosterboer Gambit", "moves": ["e4", "d5", "exd5", "c6"]},
    {"name": "dxe4 2NA Caro-Kann", "moves": ["e4", "c6", "Nf3", "d5", "Nc3", "dxe4"]},
    {"name": "Bg4 2NA Caro-Kann", "moves": ["e4", "c6", "Nf3", "d5", "Nc3", "Bg4"]},
    {"name": "d4 2NA Caro-Kann", "moves": ["e4", "c6", "Nf3", "d5", "Nc3", "d4"]},
    {"name": "Nf6 2NA Caro-Kann", "moves": ["e4", "c6", "Nf3", "d5", "Nc3", "Nf6"]},
    {"name": "e6 2NA Caro-Kann", "moves": ["e4", "c6", "Nf3", "d5", "Nc3", "e6"]},
    {"name": "Modern", "moves": ["e4", "g6"]},
    {"name": "St. George Defense", "moves": ["e4", "a6"]},
    {"name": "Owen's Defense", "moves": ["e4", "b6"]},
    {"name": "Pirc Defense", "moves": ["e4", "d6"]},
    {"name": "Nimzowitsch Defense", "moves": ["e4", "Nc6"]},
    {"name": "Alekhine Defense", "moves": ["e4", "Nf6"]},
    {"name": "Duras Gambit", "moves": ["e4", "f5"]},
    {"name": "Barnes Defense", "moves": ["e4", "f6"]},
    {"name": "Borg Defense", "moves": ["e4", "g5"]},
    # Black Sicilian repertoire, split by White's second or third move.
    {"name": "Open Sicilian", "moves": ["e4", "c5", "Nf3", "Nc6", "d4"], "colors": ["Black"]},
    {"name": "Bc4 Old Sicilian", "moves": ["e4", "c5", "Nf3", "Nc6", "Bc4"], "colors": ["Black"]},
    {"name": "Alapin Sicilian", "moves": ["e4", "c5", "Nf3", "Nc6", "c3"], "colors": ["Black"]},
    {"name": "Rossolimo", "moves": ["e4", "c5", "Nf3", "Nc6", "Bb5"], "colors": ["Black"]},
    {"name": "Nc3 Old Sicilian", "moves": ["e4", "c5", "Nf3", "Nc6", "Nc3"], "colors": ["Black"]},
    {"name": "Closed Sicilian", "moves": ["e4", "c5", "Nc3"], "colors": ["Black"]},
    {"name": "Bowdler Attack", "moves": ["e4", "c5", "Bc4"], "colors": ["Black"]},
    {"name": "Smith-Morra Gambit", "moves": ["e4", "c5", "d4"], "colors": ["Black"]},
    {"name": "Alapin", "moves": ["e4", "c5", "c3"], "colors": ["Black"]},
    {"name": "McDonnell Attack", "moves": ["e4", "c5", "f4"], "colors": ["Black"]},
    {"name": "d3 Sicilian", "moves": ["e4", "c5", "d3"], "colors": ["Black"]},
    {"name": "Staunton-Cochrane", "moves": ["e4", "c5", "c4"], "colors": ["Black"]},
    {"name": "Mengarini", "moves": ["e4", "c5", "a3"], "colors": ["Black"]},
    # Black Indian repertoire, split by White's second move.
    {"name": "Normal Indian", "moves": ["d4", "Nf6", "c4"], "colors": ["Black"]},
    {"name": "Accelerated London", "moves": ["d4", "Nf6", "Bf4"], "colors": ["Black"]},
    {"name": "Knights Indian", "moves": ["d4", "Nf6", "Nf3"], "colors": ["Black"]},
    {"name": "e3 Indian", "moves": ["d4", "Nf6", "e3"], "colors": ["Black"]},
    {"name": "Trompowsky", "moves": ["d4", "Nf6", "Bg5"], "colors": ["Black"]},
    {"name": "Nc3 Indian", "moves": ["d4", "Nf6", "Nc3"], "colors": ["Black"]},
    # Remaining opponent-first-move buckets used only when analyzing as Black.
    {"name": "Réti Opening", "moves": ["Nf3"], "colors": ["Black"]},
    {"name": "Van 't Kruijs Opening", "moves": ["e3"], "colors": ["Black"]},
    {"name": "English Opening", "moves": ["c4"], "colors": ["Black"]},
    {"name": "Nimzo-Larsen Attack", "moves": ["b3"], "colors": ["Black"]},
    {"name": "King's Fianchetto Opening", "moves": ["g3"], "colors": ["Black"]},
    {"name": "Bird Opening", "moves": ["f4"], "colors": ["Black"]},
    {"name": "Mieses Opening", "moves": ["d3"], "colors": ["Black"]},
    {"name": "Polish Opening", "moves": ["b4"], "colors": ["Black"]},
    {"name": "Grob Opening", "moves": ["g4"], "colors": ["Black"]},
    {"name": "Saragossa Opening", "moves": ["c3"], "colors": ["Black"]},
    {"name": "Van Geet Opening", "moves": ["Nc3"], "colors": ["Black"]},
    {"name": "Anderssen Opening", "moves": ["a3"], "colors": ["Black"]},
]


@st.cache_data(show_spinner=False, ttl=60 * 60)
def fetch_archives(username: str) -> list[str]:
    """Return the user's Chess.com monthly archive URLs."""
    response = requests.get(
        f"https://api.chess.com/pub/player/{username}/games/archives",
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json().get("archives", [])


@st.cache_data(show_spinner=False, ttl=60 * 60)
def fetch_games(username: str) -> list[dict[str, Any]]:
    """Fetch monthly archives serially; Streamlit caches the resulting game list."""
    games: list[dict[str, Any]] = []
    for archive_url in fetch_archives(username):
        response = requests.get(
            archive_url,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        games.extend(response.json().get("games", []))
    return games


def parse_moves_from_pgn(pgn: str) -> list[str]:
    """Read only the legal PGN main line and return its SAN move sequence."""
    game = chess.pgn.read_game(io.StringIO(pgn))
    if game is None:
        return []
    board = game.board()
    moves: list[str] = []
    for move in game.mainline_moves():
        moves.append(board.san(move))
        board.push(move)
    return moves


def starts_with_moves(moves: list[str], pattern: list[str]) -> bool:
    """Return whether a SAN sequence starts with an exact rule prefix."""
    return len(moves) >= len(pattern) and moves[: len(pattern)] == pattern


def rules_for_color(color: str | None = None) -> list[dict[str, Any]]:
    """Return the rule set for one side of the player's repertoire.

    The original custom taxonomy is a White repertoire. Rules carrying an
    explicit ``colors`` field (such as the opponent-first-move buckets) can
    opt into another side instead. Passing no color remains useful for generic
    standalone helper calls and returns every rule.
    """
    return [
        rule for rule in OPENING_RULES
        if color is None or color in rule.get("colors", ["White"])
    ]


def selected_result(game: dict[str, Any], color: str) -> str:
    player = game[color.lower()]
    opponent = game["black" if color == "White" else "white"]
    if player.get("result") == "win":
        return "win"
    if opponent.get("result") == "win":
        return "loss"
    return "draw"


def is_rated_standard_game(game: dict[str, Any]) -> bool:
    """Chess.com's normal chess variant is represented by ``rules == 'chess'``.

    ``time_class`` is a speed category (blitz, rapid, bullet, or daily), not a
    standard-vs-variant field.  Therefore it must not be compared with the
    string ``'standard'``.
    """
    return game.get("rated") is True and game.get("rules") == "chess"


def classify_opening_stats(games: list[dict[str, Any]], color: str | None = None) -> tuple[pd.DataFrame, set[str]]:
    """Make one stats row per rule and return the URLs covered by any rule."""
    rows: list[dict[str, Any]] = []
    covered_urls: set[str] = set()
    for rule in rules_for_color(color):
        matched = [game for game in games if starts_with_moves(game["moves"], rule["moves"])]
        covered_urls.update(game["url"] for game in matched)
        wins = sum(game["outcome"] == "win" for game in matched)
        losses = sum(game["outcome"] == "loss" for game in matched)
        draws = sum(game["outcome"] == "draw" for game in matched)
        game_count = len(matched)
        rows.append({
            "Opening": rule["name"], "Games": game_count, "Wins": wins,
            "Losses": losses, "Draws": draws, "W-L-D": f"{wins}-{losses}-{draws}",
            "Score %": (wins + 0.5 * draws) / game_count * 100 if game_count else None,
            "% of All Games for Selected Color": game_count / len(games) * 100 if games else 0.0,
        })
    report = pd.DataFrame(rows)
    report = report.sort_values(["Score %", "Opening"], na_position="last").reset_index(drop=True)
    report.insert(0, "Rank", range(1, len(report) + 1))
    return report, covered_urls


def compute_coverage(games: list[dict[str, Any]], covered_urls: set[str]) -> dict[str, int | float]:
    """Calculate coverage from unique game URLs, even when rules overlap."""
    all_urls = {game["url"] for game in games}
    covered = len(all_urls & covered_urls)
    total = len(all_urls)
    return {"total": total, "covered": covered, "coverage_pct": covered / total * 100 if total else 0.0,
            "uncovered": total - covered}


def compute_coverage_by_move(games: list[dict[str, Any]], max_move: int = 10, color: str | None = None) -> pd.DataFrame:
    """Measure how far unique games remain inside the custom opening-rule tree.

    A full move contains White's and Black's ply. A game is covered through
    move N only when its first 2*N SAN moves match the corresponding prefix of
    at least one rule that is itself that long.
    """
    unique_games = {game["url"]: game for game in games}.values()
    unique_games = list(unique_games)
    total_games = len(unique_games)
    rows: list[dict[str, int | float]] = []
    for move_number in range(1, max_move + 1):
        required_plies = move_number * 2
        covered = sum(
            any(
                len(rule["moves"]) >= required_plies
                and game["moves"][:required_plies] == rule["moves"][:required_plies]
                for rule in rules_for_color(color)
            )
            for game in unique_games
        )
        rows.append({
            "Move": move_number,
            "Covered Games": covered,
            "Total Games": total_games,
            "Coverage %": covered / total_games * 100 if total_games else 0.0,
        })
    return pd.DataFrame(rows)


def first_uncovered_line(moves: list[str], color: str | None = None) -> str:
    """Show the opening context through the first move outside every rule tree.

    For example, a game beginning ``e4 e6 e5`` is shown as that full sequence,
    not merely ``e6``.  This makes it clear that the game is an uncovered French
    branch rather than an entirely different first-move response.
    """
    for length in range(1, len(moves) + 1):
        prefix = moves[:length]
        if not any(
            len(rule["moves"]) >= length and rule["moves"][:length] == prefix
            for rule in rules_for_color(color)
        ):
            return " ".join(prefix)
    return " ".join(moves) if moves else "(no moves)"


def load_old_lines() -> dict[str, dict[str, list[str]]]:
    """Load locally saved exclusions; a database is intentionally unnecessary."""
    if not OLD_LINES_PATH.exists():
        return {}
    try:
        data = json.loads(OLD_LINES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_old_lines(old_lines: dict[str, dict[str, list[str]]]) -> None:
    """Persist old-line exclusions beside the app for use after a restart."""
    OLD_LINES_PATH.write_text(json.dumps(old_lines, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def old_lines_for_player(old_lines: dict[str, dict[str, list[str]]], username: str, color: str) -> set[str]:
    return set(old_lines.get(username.casefold(), {}).get(color, []))


def set_old_lines_for_player(
    old_lines: dict[str, dict[str, list[str]]], username: str, color: str, lines: set[str]
) -> None:
    player_lines = old_lines.setdefault(username.casefold(), {})
    player_lines[color] = sorted(lines)


def compute_uncovered_groups(games: list[dict[str, Any]], covered_urls: set[str], color: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Group unmatched games by their contextual first unclassified line."""
    uncovered = [game for game in games if game["url"] not in covered_urls]
    move_index = 1 if color == "White" else 0
    detail_rows = []
    for game in uncovered:
        opponent_first_move = game["moves"][move_index] if len(game["moves"]) > move_index else "(no move)"
        detail_rows.append({
            "Uncovered opening line": first_uncovered_line(game["moves"], color),
            "Opponent first move": opponent_first_move,
            "Opponent": game["opponent"], "Result": game["outcome"],
            "URL": game["url"], "Moves": " ".join(game["moves"]),
        })
    detail_columns = ["Uncovered opening line", "Opponent first move", "Opponent", "Result", "URL", "Moves"]
    details = pd.DataFrame(detail_rows, columns=detail_columns)
    if details.empty:
        return pd.DataFrame(columns=["Uncovered opening line", "Games", "% of All White Games"]), details
    groups = details.groupby("Uncovered opening line", as_index=False).size().rename(columns={"size": "Games"})
    label = "% of All White Games" if color == "White" else "% of All Black Games"
    groups[label] = groups["Games"] / len(games) * 100 if games else 0.0
    return groups.sort_values(["Games", "Uncovered opening line"], ascending=[False, True]).reset_index(drop=True), details


def prepare_games(raw_games: list[dict[str, Any]], username: str, color: str) -> list[dict[str, Any]]:
    """Keep only the selected player's rated standard games and parse their PGNs."""
    selected: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for game in raw_games:
        if not is_rated_standard_game(game):
            continue
        side = game.get(color.lower(), {})
        if side.get("username", "").casefold() != username.casefold():
            continue
        url = game.get("url")
        if not url or url in seen_urls:
            continue
        try:
            moves = parse_moves_from_pgn(game.get("pgn", ""))
        except Exception:
            continue
        seen_urls.add(url)
        opponent_side = game.get("black" if color == "White" else "white", {})
        selected.append({"url": url, "moves": moves, "outcome": selected_result(game, color),
                         "opponent": opponent_side.get("username", "Unknown")})
    return selected


def main() -> None:
    st.set_page_config(page_title="Chess.com Opening Performance", layout="wide")
    st.title("Chess.com Opening Performance")
    username = st.text_input("Chess.com username", value="ReidMate").strip()
    color = st.selectbox("Color", ["White", "Black"])
    refresh = st.button("Fetch / Refresh Games", type="primary")

    if "games" not in st.session_state:
        st.session_state.games = None
    if "archive_months" not in st.session_state:
        st.session_state.archive_months = None
    if "loaded_username" not in st.session_state:
        st.session_state.loaded_username = None
    if "old_lines" not in st.session_state:
        st.session_state.old_lines = load_old_lines()

    with st.expander("Opening Rules"):
        st.dataframe(pd.DataFrame([{
            "Opening": r["name"],
            "SAN move sequence": " ".join(r["moves"]),
            "Applies as": ", ".join(r.get("colors", ["White"])),
        } for r in OPENING_RULES]), hide_index=True, width="stretch")

    if not username:
        st.info("Enter a Chess.com username, then fetch games.")
        return
    if refresh:
        fetch_archives.clear()
        fetch_games.clear()
        try:
            with st.spinner("Fetching public Chess.com archives (one month at a time)..."):
                archive_months = fetch_archives(username)
                raw_games = fetch_games(username)
            st.session_state.games = raw_games
            st.session_state.archive_months = len(archive_months)
            st.session_state.loaded_username = username
        except Exception as exc:
            st.error(f"Could not fetch Chess.com games: {exc}")
            return

    if st.session_state.games is None or st.session_state.loaded_username != username:
        st.info("Click Fetch / Refresh Games to load Chess.com games.")
        return

    raw_games: list[dict[str, Any]] = st.session_state.games
    rated_games = [game for game in raw_games if game.get("rated") is True]
    rated_standard_games = [game for game in rated_games if game.get("rules") == "chess"]
    white_raw_games = [
        game for game in rated_standard_games
        if game.get("white", {}).get("username", "").casefold() == username.casefold()
    ]
    black_raw_games = [
        game for game in rated_standard_games
        if game.get("black", {}).get("username", "").casefold() == username.casefold()
    ]

    parsed_white_samples: list[list[str]] = []
    for game in white_raw_games[:5]:
        try:
            parsed_white_samples.append(parse_moves_from_pgn(game.get("pgn", "")))
        except Exception as exc:
            parsed_white_samples.append([f"PGN parse error: {exc}"])

    with st.expander("Temporary pipeline diagnostics", expanded=True):
        diagnostics = st.columns(3)
        diagnostics[0].metric("Archive months returned", st.session_state.archive_months)
        diagnostics[1].metric("Total raw games downloaded", len(raw_games))
        diagnostics[2].metric("Rated games", len(rated_games))
        diagnostics[0].metric("Rated standard-chess games", len(rated_standard_games))
        diagnostics[1].metric(f"Rated standard: {username} as White", len(white_raw_games))
        diagnostics[2].metric(f"Rated standard: {username} as Black", len(black_raw_games))
        st.caption("First 5 parsed main-line SAN move arrays from White games")
        st.code("\n".join(str(moves) for moves in parsed_white_samples) or "No White games found.", language="python")

    all_games = prepare_games(raw_games, username, color)
    _, all_covered_urls = classify_opening_stats(all_games, color)
    saved_old_lines = old_lines_for_player(st.session_state.old_lines, username, color)
    old_line_games = [
        game for game in all_games
        if game["url"] not in all_covered_urls and first_uncovered_line(game["moves"], color) in saved_old_lines
    ]
    old_line_urls = {game["url"] for game in old_line_games}
    games = [game for game in all_games if game["url"] not in old_line_urls]
    report, covered_urls = classify_opening_stats(games, color)
    coverage = compute_coverage(games, covered_urls)

    filter_key_suffix = f"{username.casefold()}_{color.casefold()}"
    hide_zero_key = f"hide_zero_{filter_key_suffix}"
    min_games_key = f"min_games_{filter_key_suffix}"
    if st.button("Reset report filters", key=f"reset_filters_{filter_key_suffix}"):
        st.session_state[hide_zero_key] = False
        st.session_state[min_games_key] = 0
        st.rerun()
    controls = st.columns(2)
    with controls[0]:
        hide_zero = st.checkbox("Hide opening rows with 0 games", key=hide_zero_key)
    with controls[1]:
        min_games = st.number_input("Minimum games", min_value=0, value=0, step=1, key=min_games_key)
    displayed = report if not hide_zero else report[report["Games"] > 0]
    displayed = displayed[displayed["Games"] >= min_games]
    displayed = displayed.copy()
    displayed["Score %"] = displayed["Score %"].map(lambda x: "" if pd.isna(x) else f"{x:.1f}")
    displayed["% of All Games for Selected Color"] = displayed["% of All Games for Selected Color"].map(lambda x: f"{x:.1f}")

    st.subheader(f"Opening performance as {color}")
    if displayed.empty:
        st.warning("No opening rows match the current report filters. Use Reset report filters to show all rules for this color.")
    else:
        st.dataframe(displayed, hide_index=True, width="stretch")
    st.download_button("Download opening report CSV", report.to_csv(index=False).encode("utf-8"), "opening_report.csv", "text/csv")

    metrics = st.columns(4)
    metrics[0].metric(f"Active rated standard games as {color}", coverage["total"])
    metrics[1].metric("Covered games", coverage["covered"])
    metrics[2].metric("Coverage %", f"{coverage['coverage_pct']:.1f}%")
    metrics[3].metric("Uncovered games", coverage["uncovered"])

    st.subheader("Coverage by Move")
    st.caption("Coverage through each full move (both White and Black moves) using the current active games and exact rule tree. No games are refetched for this table.")
    coverage_by_move = compute_coverage_by_move(games, color=color)
    coverage_by_move_display = coverage_by_move.copy()
    coverage_by_move_display["Coverage %"] = coverage_by_move_display["Coverage %"].map(lambda value: f"{value:.1f}")
    st.dataframe(coverage_by_move_display, hide_index=True, width="stretch")

    groups, uncovered_details = compute_uncovered_groups(games, covered_urls, color)
    st.subheader("Uncovered Games by First Unclassified Opening Decision")
    st.caption("Each line keeps the opening moves through the first move not covered by any custom rule. For example, `e4 e6 e5` identifies an uncovered French branch rather than just `e6`.")
    st.caption("Check **Old line** for an opening you no longer play, then save. It will be excluded from active coverage and this review on future reruns.")
    editable_groups = groups.copy()
    editable_groups.insert(0, "Old line", False)
    edited_groups = st.data_editor(
        editable_groups,
        hide_index=True,
        width="stretch",
        disabled=[column for column in editable_groups.columns if column != "Old line"],
        column_config={"Old line": st.column_config.CheckboxColumn("Old line", help="Exclude this historical line from active analysis.")},
        key=f"old_line_editor_{username.casefold()}_{color}",
    )
    if st.button("Save selected old lines"):
        newly_old = set(edited_groups.loc[edited_groups["Old line"], "Uncovered opening line"])
        if newly_old:
            set_old_lines_for_player(st.session_state.old_lines, username, color, saved_old_lines | newly_old)
            try:
                save_old_lines(st.session_state.old_lines)
            except OSError as exc:
                st.error(f"Could not save old lines: {exc}")
            else:
                st.success(f"Saved {len(newly_old)} old line(s).")
                st.rerun()
        else:
            st.info("Check one or more old lines before saving.")

    if saved_old_lines:
        with st.expander(f"Saved old lines ({len(saved_old_lines)})"):
            st.caption(f"{len(old_line_games)} historical game(s) are currently excluded from active analysis as {color}.")
            saved_lines_editor = pd.DataFrame({"Restore line": False, "Saved old line": sorted(saved_old_lines)})
            edited_saved_lines = st.data_editor(
                saved_lines_editor,
                hide_index=True,
                width="stretch",
                disabled=["Saved old line"],
                column_config={"Restore line": st.column_config.CheckboxColumn("Restore line", help="Include this line in active analysis again.")},
                key=f"restore_old_line_editor_{username.casefold()}_{color}",
            )
            if st.button("Restore selected lines"):
                restored = set(edited_saved_lines.loc[edited_saved_lines["Restore line"], "Saved old line"])
                if restored:
                    set_old_lines_for_player(st.session_state.old_lines, username, color, saved_old_lines - restored)
                    try:
                        save_old_lines(st.session_state.old_lines)
                    except OSError as exc:
                        st.error(f"Could not save restored lines: {exc}")
                    else:
                        st.success(f"Restored {len(restored)} line(s) to active analysis.")
                        st.rerun()
                else:
                    st.info("Check one or more lines to restore.")
    st.download_button("Download uncovered games CSV", uncovered_details.to_csv(index=False).encode("utf-8"), "uncovered_games.csv", "text/csv")


if __name__ == "__main__":
    main()
