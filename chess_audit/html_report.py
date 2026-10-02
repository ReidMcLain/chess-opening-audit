from __future__ import annotations

import html
import json
from collections.abc import Iterable

from .models import AggregateRecord, GameRecord
from .pipeline import AuditResult
from .ranking import REPORT_LEVELS, aggregate_label, ranking_records


def _h(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f}%"


def _num(value: float | None, digits: int = 1) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def _embedded_json(value: object) -> str:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _aggregate_rows(items: Iterable[AggregateRecord], details: bool = True) -> str:
    rows: list[str] = []
    for item in items:
        unclassified = ' class="unclassified"' if not item.is_classified else ""
        detail = (
            f'<button class="details" data-aggregate="{_h(item.aggregate_id)}">Games</button>' if details else ""
        )
        rows.append(
            f"<tr{unclassified}>"
            f"<td>{_h(item.color.title())}</td><td>{_h(item.eco)}</td>"
            f"<td>{_h(item.opening or '—')}</td><td>{_h(item.variation or '—')}</td>"
            f"<td>{_h(item.subvariation or '—')}</td><td data-sort='{item.games}'>{item.games}</td>"
            f"<td>{item.wins}-{item.draws}-{item.losses}</td>"
            f"<td data-sort='{item.raw_score_percentage}'>{_pct(item.raw_score_percentage)}</td>"
            f"<td data-sort='{item.loss_percentage}'>{_pct(item.loss_percentage)}</td>"
            f"<td data-sort='{item.smoothed_score_percentage}'>{_pct(item.smoothed_score_percentage)}</td>"
            f"<td data-sort='{item.actual_minus_expected_points}'>{item.actual_minus_expected_points:+.2f}</td>"
            f"<td data-sort='{item.study_priority_score}'>{item.study_priority_score:.1f}</td>"
            f"<td>{item.priority_rating_underperformance:.3f} / "
            f"{item.priority_loss_volume:.3f} / {item.priority_smoothed_underperformance:.3f}</td>"
            f"<td>{detail}</td></tr>"
        )
    return "".join(rows) or '<tr><td colspan="14" class="empty">No eligible records</td></tr>'


def _table(identifier: str, title: str, items: Iterable[AggregateRecord]) -> str:
    return f"""
<section id="{_h(identifier)}">
  <h2>{_h(title)}</h2>
  <label class="filter">Filter <input type="search" data-filter="{_h(identifier)}" placeholder="type to filter"></label>
  <div class="table-wrap"><table id="{_h(identifier)}-table" class="sortable">
    <thead><tr><th>Color</th><th>ECO</th><th>Opening</th><th>Variation</th><th>Subvariation</th>
    <th>Games</th><th>W-D-L</th><th>Raw</th><th>Loss</th><th>Smoothed</th><th>Act−Exp pts</th>
    <th>Priority</th><th>Components R/L/B</th><th>Drill-down</th></tr></thead>
    <tbody>{_aggregate_rows(items)}</tbody>
  </table></div>
</section>"""


def _ranking_section(
    result: AuditResult, ranking_name: str, heading: str, level: str = "opening", limit: int = 10
) -> str:
    blocks: list[str] = []
    for color in ("white", "black"):
        items = ranking_records(result.rankings, list(result.aggregates), level, color, ranking_name)[:limit]
        blocks.append(
            f"<div class='ranking'><h3>{_h(color.title())}</h3><table><thead><tr>"
            "<th>Line</th><th>Games</th><th>Losses</th><th>Raw</th><th>Smoothed</th>"
            "<th>Act−Exp pts</th><th>Priority</th></tr></thead><tbody>"
            + "".join(
                f"<tr><td>{_h(aggregate_label(item))}</td><td>{item.games}</td><td>{item.losses}</td>"
                f"<td>{_pct(item.raw_score_percentage)}</td><td>{_pct(item.smoothed_score_percentage)}</td>"
                f"<td>{item.actual_minus_expected_points:+.2f}</td><td>{item.study_priority_score:.1f}</td></tr>"
                for item in items
            )
            + ("" if items else "<tr><td colspan='7' class='empty'>No eligible records</td></tr>")
            + "</tbody></table></div>"
        )
    return f"<section><h2>{_h(heading)} — {_h(level.title())} level</h2><div class='ranking-grid'>{''.join(blocks)}</div></section>"


def _overall_cards(result: AuditResult) -> str:
    color_items = {item.color: item for item in result.aggregates if item.level == "color"}
    cards: list[str] = []
    for color in ("white", "black"):
        item = color_items.get(color)
        baseline = result.baselines[color]
        if item is None:
            cards.append(f"<article class='card'><h3>{color.title()}</h3><p>No scored games</p></article>")
            continue
        if item.actual_minus_expected_points < -1e-12:
            performance_label = "underperformance"
        elif item.actual_minus_expected_points > 1e-12:
            performance_label = "overperformance"
        else:
            performance_label = "on expectation"
        cards.append(
            f"<article class='card'><h3>{color.title()}</h3>"
            f"<strong>{item.wins}-{item.draws}-{item.losses}</strong>"
            f"<p>{_pct(item.raw_score_percentage)} raw score · {_pct(item.loss_percentage)} losses</p>"
            f"<p>Expected {_pct(item.average_expected_score_percentage)} · actual − expected "
            f"{item.actual_minus_expected_points:+.2f} points ({performance_label})</p>"
            f"<p class='muted'>Bayesian baseline {_pct(baseline.percentage)} ({_h(baseline.source)})</p></article>"
        )
    return "".join(cards)


def render_html(result: AuditResult) -> str:
    player = result.config.usernames[0]
    title = f"Opening Audit: {player} — {result.summary.matched_games} matched games"
    weakness_order = lambda item: (-item.study_priority_score, -item.losses, item.smoothed_score_percentage)
    opening_items = sorted((item for item in result.aggregates if item.level == "opening"), key=weakness_order)
    variation_items = sorted((item for item in result.aggregates if item.level == "variation"), key=weakness_order)
    subvariation_items = sorted(
        (item for item in result.aggregates if item.level == "subvariation"), key=weakness_order
    )
    unknown_games = [game for game in result.games if not game.is_classified]
    time_controls = sorted({game.time_control for game in result.games if game.time_control})
    game_data = {game.record_id: game.to_dict() for game in result.games}
    aggregate_map = {item.aggregate_id: list(item.game_ids) for item in result.aggregates}
    warnings_html = "".join(f"<li>{_h(warning)}</li>" for warning in result.warnings) or "<li>None</li>"
    unknown_rows = "".join(
        f"<tr><td>{_h(game.game_date)}</td><td>{_h(game.user_color)}</td><td>{_h(game.user_result)}</td>"
        f"<td>{_h(game.white_username)} – {_h(game.black_username)}</td>"
        f"<td>{_h(game.source_file)} #{game.game_index}</td></tr>" for game in unknown_games
    ) or "<tr><td colspan='5' class='empty'>All analyzed games received a dataset classification.</td></tr>"

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_h(title)}</title>
<style>
:root{{--bg:#f5f7fb;--panel:#fff;--ink:#172033;--muted:#667085;--line:#d9deea;--accent:#2457c5;--warn:#fff4d6}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 Segoe UI,Arial,sans-serif}}
header,main{{max-width:1500px;margin:auto;padding:24px}} header{{padding-bottom:8px}} h1{{margin:.2rem 0}} h2{{margin-top:0}}
section{{background:var(--panel);border:1px solid var(--line);border-radius:10px;margin:18px 0;padding:20px;box-shadow:0 2px 7px #1a2b4a0b}}
.meta,.muted{{color:var(--muted)}} .cards,.ranking-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px}}
.card,.ranking{{border:1px solid var(--line);border-radius:8px;padding:14px}} .card strong{{font-size:24px}} .quality{{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px}}
.quality div{{background:#f7f9fc;padding:10px;border-radius:6px}} .quality strong{{display:block;font-size:20px}} .table-wrap{{overflow:auto}}
table{{border-collapse:collapse;width:100%;font-size:13px}} th,td{{border-bottom:1px solid var(--line);padding:8px;text-align:left;vertical-align:top;white-space:nowrap}}
th{{background:#f1f4f9;cursor:pointer;position:sticky;top:0}} tr.unclassified td{{background:var(--warn)}} .empty{{color:var(--muted);text-align:center}}
.filter{{display:block;margin:-5px 0 12px;color:var(--muted)}} input{{padding:7px 10px;border:1px solid var(--line);border-radius:6px;min-width:260px}}
button.details{{border:1px solid var(--accent);background:white;color:var(--accent);border-radius:5px;padding:4px 8px;cursor:pointer}}
.detail-row td{{background:#fafbfe;white-space:normal}} a{{color:var(--accent)}} code{{white-space:normal}} footer{{padding:15px 0;color:var(--muted)}}
</style></head><body>
<header><h1>{_h(title)}</h1><p class="meta">Run {_h(result.run_timestamp_utc)} · Dataset {_h(result.dataset_metadata.get('version'))}</p></header>
<main>
<section id="executive"><h2>Executive summary</h2><div class="cards">{_overall_cards(result)}</div>
<p>Time controls encountered: <strong>{_h(', '.join(time_controls) or 'none supplied')}</strong>.</p>
<p>The composite priority is a study aid, not a verdict. Review its loss volume, rating deficit, Bayesian adjustment, sample size, and underlying games together.</p></section>
<section id="import-quality"><h2>Import-quality summary</h2><div class="quality">
{''.join(f'<div><strong>{value}</strong>{_h(label)}</div>' for label, value in [
('Files scanned', result.summary.files_scanned), ('Games parsed', result.summary.games_parsed),
('Matched/analyzed', result.summary.matched_games), ('Unmatched', result.summary.unmatched_games),
('Ambiguous', result.summary.ambiguous_games), ('Malformed', result.summary.malformed_games),
('Duplicates', result.summary.duplicate_games), ('Unknown results', result.summary.unknown_results),
('Unknown openings', result.summary.unknown_classifications)])}
</div></section>
{''.join(_ranking_section(result, 'most_total_losses', 'Most total losses', level) for level in REPORT_LEVELS)}
{''.join(_ranking_section(result, 'largest_rating_adjusted_deficit', 'Largest rating-adjusted deficits', level) for level in REPORT_LEVELS)}
{''.join(_ranking_section(result, 'highest_study_priority', 'Highest study priorities', level) for level in REPORT_LEVELS)}
{_table('opening-level', 'Opening-level performance and weaknesses', opening_items)}
{_table('variation-level', 'Variation-level performance and weaknesses', variation_items)}
{_table('subvariation-level', 'Subvariation-level performance and weaknesses', subvariation_items)}
{''.join(_ranking_section(result, 'best_performing', 'Best-performing lines for comparison', level) for level in REPORT_LEVELS)}
<section id="unknown"><h2>Unknown/unclassified games</h2><div class="table-wrap"><table><thead><tr><th>Date</th><th>Color</th><th>Result</th><th>Players</th><th>Source</th></tr></thead><tbody>{unknown_rows}</tbody></table></div></section>
<section id="warnings"><h2>Data-quality warnings</h2><ul>{warnings_html}</ul></section>
<section id="methodology"><h2>Methodology</h2>
<p>Games are streamed from the selected files, matched against the supplied aliases after trimming and case-folding, and deduplicated by Chess.com ID/URL when available or by a deterministic player/date/result/main-line-move hash. Unmatched, ambiguous, malformed, and duplicate records do not affect performance statistics.</p>
<p>Opening names come from the pinned CC0 Lichess dataset. The classifier replays legal UCI moves and retains the deepest exact move-prefix or unique normalized four-field-FEN match; literal PGN opening headers are only a fallback. It never derives names from ECO codes or URLs.</p>
<p>Raw score is (wins + 0.5 × draws) / scored games. Rating expectation is 1 / (1 + 10<sup>−rating difference / 400</sup>). Missing ratings stay in raw W-D-L but not adjusted metrics. Negative actual-minus-expected points mean underperformance.</p>
<p>Smoothed score uses a {_h(result.config.prior_games)}-game equivalent prior and the color baseline. If that color has fewer than the prior game count, the overall score is used and recorded as a fallback. Priority is normalized separately for each level and color: 45% non-positive rating underperformance, 35% loss volume, and 20% Bayesian underperformance. Tables never mix White and Black or broad and narrow levels.</p>
</section><footer>Generated locally by Chess Opening Audit. No network services were used during analysis.</footer>
</main>
<script>const GAMES={_embedded_json(game_data)};const AGGREGATES={_embedded_json(aggregate_map)};
function cellText(value){{const td=document.createElement('td');td.textContent=value??'—';return td}}
function detailRow(button){{const id=button.dataset.aggregate;const current=button.closest('tr').nextElementSibling;if(current&&current.classList.contains('detail-row')){{current.remove();return}}
 const tr=document.createElement('tr');tr.className='detail-row';const td=document.createElement('td');td.colSpan=14;const table=document.createElement('table');
 const head=document.createElement('tr');['Date','Color','Result','User','Opponent','Ratings','Opening','Source','Link'].forEach(x=>{{const th=document.createElement('th');th.textContent=x;head.appendChild(th)}});table.appendChild(head);
 (AGGREGATES[id]||[]).forEach(gameId=>{{const g=GAMES[gameId];if(!g)return;const row=document.createElement('tr');const user=g.user_color==='white'?g.white_username:g.black_username;const opp=g.user_color==='white'?g.black_username:g.white_username;
 [g.game_date,g.user_color,g.user_result,user,opp,(g.user_rating??'—')+' / '+(g.opponent_rating??'—'),[g.opening,g.variation,g.subvariation].filter(Boolean).join(' > '),g.source_file+' #'+g.game_index].forEach(x=>row.appendChild(cellText(x)));
 const link=cellText('—');if(g.chess_com_url){{const a=document.createElement('a');a.href=g.chess_com_url;a.target='_blank';a.rel='noopener';a.textContent='Chess.com';link.textContent='';link.appendChild(a)}}row.appendChild(link);table.appendChild(row)}});td.appendChild(table);tr.appendChild(td);button.closest('tr').after(tr)}}
document.querySelectorAll('button.details').forEach(b=>b.addEventListener('click',()=>detailRow(b)));
document.querySelectorAll('[data-filter]').forEach(input=>input.addEventListener('input',()=>{{const q=input.value.toLocaleLowerCase();document.querySelectorAll('#'+input.dataset.filter+'-table tbody tr:not(.detail-row)').forEach(row=>row.hidden=!row.textContent.toLocaleLowerCase().includes(q))}}));
document.querySelectorAll('table.sortable th').forEach((th,index)=>th.addEventListener('click',()=>{{const table=th.closest('table'),body=table.tBodies[0],rows=[...body.rows].filter(r=>!r.classList.contains('detail-row'));const asc=th.dataset.asc!=='true';table.querySelectorAll('.detail-row').forEach(r=>r.remove());rows.sort((a,b)=>{{const ac=a.cells[index],bc=b.cells[index],av=ac.dataset.sort??ac.textContent,bv=bc.dataset.sort??bc.textContent,an=Number(av),bn=Number(bv);const cmp=!Number.isNaN(an)&&!Number.isNaN(bn)?an-bn:av.localeCompare(bv,undefined,{{numeric:true}});return asc?cmp:-cmp}});rows.forEach(r=>body.appendChild(r));th.dataset.asc=String(asc)}}));
</script></body></html>"""
