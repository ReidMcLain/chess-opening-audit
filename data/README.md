# Bundled opening data

Chess Opening Audit uses the curated
[`lichess-org/chess-openings`](https://github.com/lichess-org/chess-openings)
dataset. The bundled snapshot is pinned to immutable Git commit
`292fd0468068f58bb244f7fe1c3e573e493c3c53` from 2026-07-12 and is released
under the CC0-1.0 public-domain dedication.

`openings.tsv` is generated from upstream `a.tsv` through `e.tsv`; it retains
the literal ECO, full opening name, canonical PGN, UCI sequence, normalized
four-field FEN/EPD position, and canonical ply. `metadata.json` records the
source and generated hashes and is copied into every audit report.

To update deliberately:

1. Select an immutable upstream tag or commit and review its changes.
2. Update the commit and expected source hashes in
   `tools/build_opening_dataset.py`.
3. Download `a.tsv` through `e.tsv` from URLs containing that exact commit.
4. Run `python tools/build_opening_dataset.py --source <download-folder>`.
5. Copy the matching upstream `COPYING.txt` if it changed.
6. Run the full tests and inspect classification diffs before committing data.

The normal audit command never downloads or updates opening information.

