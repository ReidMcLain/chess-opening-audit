from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from .aggregation import aggregate_games, with_priority_components
from .config import RunConfig
from .identity import build_game_record, identify_player, normalize_usernames, stable_game_id
from .metrics import calculate_baselines
from .models import (
    AggregateRecord,
    Baseline,
    GameRecord,
    InputSummary,
    OpeningClassification,
    ParsedGame,
    SourceFileManifest,
)
from .openings import BundledOpeningClassifier, OpeningClassifier
from .pgn_reader import discover_pgn_files, iter_pgn_file, sha256_file
from .ranking import build_rankings


SCHEMA_VERSION = "1.0"


@dataclass(frozen=True, slots=True)
class AuditResult:
    run_timestamp_utc: str
    config: RunConfig
    dataset_metadata: dict[str, Any]
    source_files: tuple[SourceFileManifest, ...]
    summary: InputSummary
    baselines: dict[str, Baseline]
    games: tuple[GameRecord, ...]
    aggregates: tuple[AggregateRecord, ...]
    rankings: dict[str, dict[str, dict[str, list[str]]]]
    warnings: tuple[str, ...]


def _game_sort_key(record: GameRecord) -> tuple[date, str, str, int, str]:
    return (
        record.game_date or date.min,
        record.utc_datetime or "",
        record.source_file.casefold(),
        record.game_index,
        record.record_id,
    )


def run_audit(config: RunConfig, classifier: OpeningClassifier | None = None) -> AuditResult:
    config.validate()
    usernames = normalize_usernames(config.usernames)
    if not usernames:
        raise ValueError("Supply at least one non-empty --username.")
    if classifier is None:
        classifier = BundledOpeningClassifier(config.dataset_directory.expanduser().resolve())

    files, discovery_warnings = discover_pgn_files(
        config.explicit_files,
        config.folder,
        config.recursive,
        excluded_roots=(config.output_base,),
    )
    if not files:
        raise ValueError("No readable .pgn input files were found.")

    summary = InputSummary(files_scanned=len(files))
    warnings = list(discovery_warnings)
    manifests: list[SourceFileManifest] = []
    candidates: list[GameRecord] = []
    seen: dict[str, tuple[str, str, str, tuple[str, ...]]] = {}
    occurrence_counts: dict[str, int] = {}
    missing_date_filtered = 0

    for source_file in files:
        try:
            digest = sha256_file(source_file)
            manifests.append(SourceFileManifest.from_path(source_file, digest))
            items = iter_pgn_file(source_file)
            parsed_before_file = summary.games_parsed
            for item in items:
                summary.games_parsed += 1
                if item.malformed:
                    summary.malformed_games += 1
                    details = "; ".join(item.errors[:3]) or "unknown parse error"
                    warnings.append(f"Malformed game excluded: {source_file} game {item.game_index}: {details}")
                    continue

                identity = identify_player(item.headers, usernames)
                if identity == "unmatched":
                    summary.unmatched_games += 1
                    continue
                if identity == "ambiguous":
                    summary.ambiguous_games += 1
                    warnings.append(
                        f"Ambiguous player aliases excluded: {source_file} game {item.game_index}"
                    )
                    continue
                summary.matched_before_filters += 1

                game_id, _link = stable_game_id(item.headers, item.moves_uci)
                signature = (
                    item.headers.get("White", "").strip().casefold(),
                    item.headers.get("Black", "").strip().casefold(),
                    item.headers.get("Result", "").strip(),
                    item.moves_uci,
                )
                if game_id in seen:
                    summary.duplicate_games += 1
                    if seen[game_id] != signature:
                        warnings.append(
                            f"Conflicting records share stable ID {game_id}; deterministic first occurrence retained"
                        )
                    if config.deduplicate:
                        continue
                else:
                    seen[game_id] = signature

                occurrence_counts[game_id] = occurrence_counts.get(game_id, 0) + 1
                classification = classifier.classify(item.moves_uci, item.headers)
                parsed = ParsedGame(
                    source_file=source_file,
                    game_index=item.game_index,
                    headers=item.headers,
                    moves_uci=item.moves_uci,
                    classification=classification,
                )
                record = build_game_record(parsed, identity, occurrence_counts[game_id])

                if config.color != "both" and record.user_color != config.color:
                    summary.filtered_games += 1
                    continue
                if config.after or config.before:
                    if record.game_date is None:
                        missing_date_filtered += 1
                        summary.filtered_games += 1
                        continue
                    if config.after and record.game_date < config.after:
                        summary.filtered_games += 1
                        continue
                    if config.before and record.game_date > config.before:
                        summary.filtered_games += 1
                        continue
                candidates.append(record)
            if summary.games_parsed == parsed_before_file:
                summary.files_failed += 1
                warnings.append(f"No PGN games could be parsed from {source_file}")
        except (OSError, UnicodeError) as exc:
            summary.files_failed += 1
            warnings.append(f"Could not read {source_file}: {exc}")

    if missing_date_filtered:
        warnings.append(
            f"Excluded {missing_date_filtered} matched game(s) without usable dates because a date filter was active"
        )

    candidates.sort(key=_game_sort_key)
    if config.last_games is not None and len(candidates) > config.last_games:
        removed = len(candidates) - config.last_games
        candidates = candidates[-config.last_games :]
        summary.filtered_games += removed

    summary.matched_games = len(candidates)
    summary.unknown_results = sum(record.user_result == "unknown" for record in candidates)
    summary.unknown_classifications = sum(not record.is_classified for record in candidates)
    if summary.unknown_results:
        warnings.append(
            f"{summary.unknown_results} matched game(s) have unknown results and are excluded from performance aggregates"
        )
    if summary.unknown_classifications:
        warnings.append(f"{summary.unknown_classifications} analyzed game(s) could not be classified by opening")

    baselines = calculate_baselines(candidates, config.prior_games)
    aggregates = aggregate_games(candidates, baselines, config.prior_games)
    aggregates = with_priority_components(aggregates, config.minimum_games)
    rankings = build_rankings(aggregates, config.minimum_games)
    dataset_metadata = getattr(classifier, "metadata", {"version": classifier.dataset_version})
    return AuditResult(
        run_timestamp_utc=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        config=config,
        dataset_metadata=dict(dataset_metadata),
        source_files=tuple(manifests),
        summary=summary,
        baselines=baselines,
        games=tuple(candidates),
        aggregates=tuple(aggregates),
        rankings=rankings,
        warnings=tuple(warnings),
    )
