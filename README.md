# Chess.com Opening Performance App

A small Streamlit app for fetching a Chess.com player's public archives and
ranking custom, exact-SAN opening rules by score. It only includes rated
standard games, parses the actual PGN main line, and uses unique game URLs for
coverage so overlapping rules cannot double-count a game.

## Run

Python 3.12 or newer is recommended.

```powershell
pip install -r requirements.txt
streamlit run app.py
```

Enter a username, choose White or Black, then select **Fetch / Refresh Games**.
The fetched archive data is cached for one hour; the button clears that cache
before re-fetching. Opening rules live near the top of `app.py` in
`OPENING_RULES` and can be extended with exact SAN prefixes.

In the uncovered-lines table, select **Old line** for a historical line that
you no longer play, then save it. The app records these per username and color
in a local `old_lines.json` file and excludes their unmatched games from active
coverage and the uncovered review. Saved entries remain visible in the **Saved
old lines** expander, where they can also be restored to active analysis.

The existing command-line audit documentation follows.

# Chess Opening Audit

Chess Opening Audit is a standalone, local command-line application for finding
color-specific opening weaknesses in PGN archives. It does not log in to a chess
site, call an API, use an engine, edit source PGNs, or retain a cumulative game
database. Every run is derived only from the files, aliases, filters, and settings
supplied for that invocation.

## Install

Python 3.11 or newer is required.

```powershell
cd C:\path\to\chess-opening-audit
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Run

Scan one folder (non-recursive by default):

```powershell
python opening_audit.py `
  --folder "$HOME\Downloads" `
  --username ReidMate `
  --output ".\opening-audit-output"
```

Analyze explicit files:

```powershell
python opening_audit.py game1.pgn game2.pgn --username ReidMate
python opening_audit.py archive.pgn --username ReidMate
```

Aliases belong to one audited player and can be repeated:

```powershell
python opening_audit.py --folder C:\Chess --username MainAccount --username OldAccount
```

Useful options:

```text
--recursive
--no-deduplicate
--color white|black|both
--minimum-games NUMBER       default 5
--prior-games NUMBER         default 8
--after YYYY-MM-DD           inclusive
--before YYYY-MM-DD          inclusive
--last-games NUMBER
--overwrite
```

Without `--overwrite`, `--output` is treated as a base directory and each run is
written to a new `run-YYYYMMDDTHHMMSSZ` subdirectory. With `--overwrite`, the five
named output files are replaced in the exact output directory; unrelated files
are not deleted.

Input files are processed in canonical deterministic order. Folder and explicit
inputs form a de-duplicated union. `--recursive` does not follow directory links,
and the selected output tree plus prior report directories are pruned. PGNs are
opened read-only and parsed one game at a time.

## Player identity and game identity

Aliases are trimmed and compared case-insensitively. A game is included only when
exactly one side matches. Neither-side matches are `unmatched`; both-side matches
are `ambiguous`. Both counts remain visible in every report.

Deduplication prefers a numeric Chess.com ID from a validated game URL. Otherwise
it hashes normalized White and Black names, UTC date/time when present (falling
back to exported Date/EndTime), result, and the legal main-line UCI sequence.
`--no-deduplicate` retains repeated occurrences but still reports them.

Unknown results remain in the per-game data and quality totals but are excluded
from performance aggregates, so they are never treated as losses.

## Opening data and classification

The offline dataset is the Lichess organization's curated
[`chess-openings`](https://github.com/lichess-org/chess-openings) collection,
pinned to immutable commit
`292fd0468068f58bb244f7fe1c3e573e493c3c53` (2026-07-12). It contains 3,803
unique named positions spanning all 500 ECO codes and is dedicated to the public
domain under CC0-1.0. See `data/README.md`, `data/metadata.json`, and the bundled
license. This is a broad curated taxonomy, not a claim of infallible opening
knowledge.

The classifier replays legal main-line moves and records the deepest exact UCI
prefix or unique normalized position match. Position keys contain piece placement,
side to move, castling rights, and a legally relevant en-passant square—the first
four FEN fields—so known transpositions can classify without identical move order.
Literal `ECO`, `Opening`, `Variation`, and `SubVariation` PGN headers are used only
when no dataset position is found. No name is inferred from an ECO code or URL.
Unresolved games are labeled `Unknown`.

The dataset is replaceable without changing the analyzer or reports. Its explicit,
hash-verified update procedure is documented in `data/README.md`; normal audit
runs never access the network.

## Calculations

Statistics are independent at these levels and are always separated by color:

- color
- opening
- opening + variation
- opening + variation + subvariation
- ECO
- raw time-control header

Raw points are `wins + 0.5 × draws`; raw score is points divided by scored games.
For games with both ratings:

```text
expected = 1 / (1 + 10 ** (-(user_rating - opponent_rating) / 400))
rating deficit = actual points - expected points
```

Negative deficit means underperformance. Missing ratings remain in raw W-D-L but
not in adjusted calculations.

Bayesian score uses the color baseline and an eight-game prior by default:

```text
(actual_points + prior_games × color_baseline) / (games + prior_games)
```

If that color has fewer scored games than the configured prior, the overall
filtered score is used and the fallback is recorded. A zero prior reproduces raw
score.

Study priority is normalized separately within each report level and color among
groups meeting `--minimum-games`:

```text
45% max(0, expected − actual) rating weakness
35% total-loss volume
20% max(0, baseline − smoothed score) Bayesian weakness
```

Each component is divided by that component's maximum in the comparable scope.
Positive rating performance contributes zero weakness. The three normalized
components and their raw deficits are exported beside the composite score.

## Outputs and stable schemas

Every run creates:

- `opening_audit.html` — self-contained sortable/filterable report with local
  JavaScript and aggregate-to-game drill-down.
- `opening_aggregates.csv` — all independent aggregation levels.
- `analyzed_games.csv` — one row per matched retained occurrence.
- `opening_audit.json` — schema version, metadata, settings, quality counts,
  baselines, game records, aggregate records, rankings, and warnings.
- `run_manifest.json` — tool/dataset versions, aliases, exact canonical inputs,
  sizes, modification timestamps, SHA-256 hashes, settings, counts, warnings, and
  generated filenames.

JSON and manifest schema version is `1.0`. CSV column order is defined by
`AGGREGATE_CSV_FIELDS` and `GAME_CSV_FIELDS` in `chess_audit/exporters.py` and is
covered by tests. Percent fields use a 0–100 scale. Missing values are empty in
CSV and `null` in JSON; NaN is never emitted. Text cells that could trigger a
spreadsheet formula are neutralized.

## Tests

```powershell
python -m pip install -e ".[dev]"
python -m pytest -v
```

The synthetic suite covers parsing, discovery, recovery, aliases, perspective,
deduplication, classifications and transpositions, metrics, hierarchy aggregation,
rankings, exports, local HTML, manifests, and CLI errors without touching personal
PGNs.
