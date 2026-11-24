# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Static HTML summary of a fidelity run.

Self-contained (no scripts, no external resources) so it can be opened
offline.  Every value is HTML-escaped: font names, reasons and paths
originate from untrusted corpus files.
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any, Dict, Iterable, List

_STYLE = """
:root { color-scheme: light dark; }
body { font: 14px/1.45 system-ui, sans-serif; margin: 24px; }
h1 { font-size: 20px; } h2 { font-size: 16px; margin-top: 28px; }
table { border-collapse: collapse; margin: 8px 0 16px; }
th, td { border: 1px solid #8884; padding: 4px 8px; text-align: left; vertical-align: top; }
th { background: #8882; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
.pass { color: #1a7f37; font-weight: 600; }
.partial { color: #9a6700; font-weight: 600; }
.fail { color: #cf222e; font-weight: 600; }
code { font-size: 12px; }
.small { font-size: 12px; opacity: .8; }
"""


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _rate(value: Any) -> str:
    return "n/a" if value is None else f"{float(value) * 100:.1f}%"


def _group_table(title: str, groups: Dict[str, Dict[str, Any]]) -> List[str]:
    lines = [f"<h2>{_e(title)}</h2>", "<table>",
             "<tr><th>Group</th><th>Total</th><th>Pass</th><th>Partial</th>"
             "<th>Fail</th><th>Pass rate</th></tr>"]
    for name, item in groups.items():
        lines.append(
            f"<tr><td>{_e(name)}</td><td class='num'>{_e(item['total'])}</td>"
            f"<td class='num'>{_e(item['pass'])}</td><td class='num'>{_e(item['partial'])}</td>"
            f"<td class='num'>{_e(item['fail'])}</td>"
            f"<td class='num'>{_e(_rate(item.get('pass_rate')))}</td></tr>")
    lines.append("</table>")
    return lines


def _diff_text(diffs: Dict[str, Any]) -> str:
    return "; ".join(f"{key}: {old!r} → {new!r}" for key, (old, new) in diffs.items())


def render(report: Dict[str, Any]) -> str:
    summary = report["summary"]
    lines: List[str] = [
        "<!doctype html>", "<html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        f"<title>Fidelity report – {_e(report.get('label', ''))}</title>",
        f"<style>{_STYLE}</style></head><body>",
        f"<h1>Fidelity report – {_e(report.get('label', ''))}</h1>",
        "<p class='small'>"
        f"Run {_e(report['run_id'])} · generated {_e(report['generated_at'])} · "
        f"engine <code>{_e(report['engine']['version'])}</code> · "
        f"corpus {_e(report['corpus']['files'])} files · "
        f"manifest sha256 <code>{_e(report['corpus']['manifest_sha256'][:16])}…</code></p>",
        "<table><tr><th>Total</th><th>Pass</th><th>Partial</th><th>Fail</th>"
        "<th>Pass rate</th></tr>",
        f"<tr><td class='num'>{_e(summary['total'])}</td>"
        f"<td class='num pass'>{_e(summary['pass'])}</td>"
        f"<td class='num partial'>{_e(summary['partial'])}</td>"
        f"<td class='num fail'>{_e(summary['fail'])}</td>"
        f"<td class='num'>{_e(_rate(summary.get('pass_rate')))}</td></tr></table>",
    ]
    lines += _group_table("By application", summary.get("by_app", {}))
    lines += _group_table("By format", summary.get("by_format", {}))
    lines += _group_table("By feature tag", summary.get("by_feature", {}))

    lines += ["<h2>Reasons</h2>", "<table><tr><th>Reason</th><th>Files</th></tr>"]
    for reason, count in summary.get("reasons", {}).items():
        lines.append(f"<tr><td><code>{_e(reason)}</code></td><td class='num'>{_e(count)}</td></tr>")
    lines.append("</table>")

    lines += ["<h2>Files</h2>", "<table>",
              "<tr><th>Id</th><th>Format</th><th>Status</th><th>Units</th><th>PDF pages</th>"
              "<th>Reasons</th><th>Critical differences (before → after)</th>"
              "<th>Import filter</th><th>ms</th></tr>"]
    for row in report["files"]:
        status = row["status"]
        units = f"{row.get('units_before')} → {row.get('units_after')}"
        lines.append(
            f"<tr><td><code>{_e(row['id'])}</code><br><span class='small'>{_e(row['path'])}"
            f"</span></td><td>{_e(row['format'])}</td>"
            f"<td class='{_e(status)}'>{_e(status)}</td><td class='num'>{_e(units)}</td>"
            f"<td class='num'>{_e(row.get('pdf_pages'))}</td>"
            f"<td>{_e(', '.join(row.get('reasons', [])))}</td>"
            f"<td>{_e(_diff_text(row.get('critical_diffs') or {}))}</td>"
            f"<td>{_e(row.get('import_filter', ''))}</td>"
            f"<td class='num'>{_e(row.get('duration_ms', 0))}</td></tr>")
    lines += ["</table>", "</body></html>"]
    return "\n".join(lines) + "\n"


def write_html(report: Dict[str, Any], path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(report), encoding="utf-8")


def fonts_used(rows: Iterable[Dict[str, Any]]) -> Dict[str, List[str]]:
    """Map font name -> ids of corpus files that reference it."""
    table: Dict[str, List[str]] = {}
    for row in rows:
        for font in row.get("fonts", []):
            table.setdefault(font, []).append(row["id"])
    return {font: sorted(ids) for font, ids in sorted(table.items())}
