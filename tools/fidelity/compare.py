# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Turn one probe result into a verdict: ``pass`` / ``partial`` / ``fail``.

Rules (version 4; docs/fidelity-method.md has the history of versions
1 to 3, which were replaced after trial runs and an independent review
showed false alarms and missed losses; the recorded baseline uses
version 4):

``fail``     the document did not open, the PDF export failed, the
             round-trip save failed, the saved copy did not reopen, the
             engine crashed, or the probe timed out.
``partial``  everything ran, but the page/slide count changed, a
             *critical* model metric changed, a critical kind of package
             part disappeared completely, user content counted in the
             package (comments, notes, formulas, header text ...) was
             lost, an amount of content (words, characters, shapes ...)
             shrank by more than 5 %, a slide transition effect named in
             the file is gone after saving, or the PDF page count does not
             match the document or could not be read.
``pass``     none of the above.

Non-critical differences are kept as information and never change the
verdict.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

WRITER_CRITICAL = (
    "page_count", "tables", "images", "embedded_objects", "footnotes", "endnotes",
    "comments", "redlines", "indexes", "basic.modules", "page_styles.with_header",
    "page_styles.with_footer", "page_styles.multi_column",
)
IMPRESS_CRITICAL = (
    "slide_count", "master_count", "hidden_slides", "slides_with_transition", "transitions",
    "animation_effects", "notes_slides", "comments", "tables", "images", "media",
    "ole_objects", "custom_shows", "basic.modules",
)
CRITICAL_BY_KIND = {
    "writer": WRITER_CRITICAL, "writer-web": WRITER_CRITICAL, "writer-global": WRITER_CRITICAL,
    "impress": IMPRESS_CRITICAL, "draw": IMPRESS_CRITICAL,
}
FAIL_STEPS = (
    ("engine_start", "engine-start-failed"),
    ("open", "open-failed"),
    ("measure", "measure-failed"),
    ("pdf_export", "pdf-export-failed"),
    ("roundtrip_save", "roundtrip-save-failed"),
    ("reopen", "reopen-failed"),
    ("remeasure", "remeasure-failed"),
)
STATUSES = ("pass", "partial", "fail")
CRITERIA_VERSION = 4
#: Amounts of content.  A drop of more than SHRINK_TOLERANCE (and at least one
#: unit) between the first and the second reading is a loss, whatever the kind.
SHRINK_KEYS = {
    "writer": ("word_count", "character_count", "paragraphs", "text_frames", "draw_shapes",
               "hyperlink_portions", "list_paragraphs", "bookmarks", "sections"),
    "impress": ("text_chars", "notes_chars", "shapes", "paragraphs", "hyperlink_portions",
                "animation_nodes"),
}
SHRINK_KEYS["writer-web"] = SHRINK_KEYS["writer-global"] = SHRINK_KEYS["writer"]
SHRINK_KEYS["draw"] = SHRINK_KEYS["impress"]
SHRINK_TOLERANCE = 0.05


def shrunk(before: Dict[str, Any], after: Dict[str, Any], kind: str) -> List[str]:
    """Content metrics that dropped by more than the tolerance."""
    lost = []
    for key in SHRINK_KEYS.get(kind, ()):
        old, new = before.get(key), after.get(key)
        if not isinstance(old, (int, float)) or not isinstance(new, (int, float)) or old <= 0:
            continue
        if new < old and (old - new) >= max(1.0, old * SHRINK_TOLERANCE):
            lost.append(key)
    return lost


def flatten(metrics: Dict[str, Any], prefix: str = "") -> Dict[str, Any]:
    """Flatten one level of nested dicts: ``{"a": {"b": 1}}`` -> ``{"a.b": 1}``.

    Dicts that are open-ended maps (index kinds, field kinds, shape types)
    stay whole so that a new key shows up as a change of the map.
    """
    flat: Dict[str, Any] = {}
    open_maps = ("indexes", "fields", "redlines_by_type", "shapes_by_type")
    for key, value in metrics.items():
        name = prefix + key
        if isinstance(value, dict) and key not in open_maps:
            flat.update(flatten(value, name + "."))
        else:
            flat[name] = value
    return flat


def metric_diffs(before: Dict[str, Any], after: Dict[str, Any],
                 critical: Tuple[str, ...]) -> Tuple[Dict[str, list], Dict[str, list]]:
    """Return ``(critical_diffs, info_diffs)`` as ``{key: [before, after]}``."""
    flat_before, flat_after = flatten(before), flatten(after)
    critical_diffs: Dict[str, list] = {}
    info_diffs: Dict[str, list] = {}
    for key in sorted(set(flat_before) | set(flat_after)):
        old, new = flat_before.get(key), flat_after.get(key)
        if old == new:
            continue
        (critical_diffs if key in critical else info_diffs)[key] = [old, new]
    return critical_diffs, info_diffs


def expected_pdf_pages(before: Dict[str, Any]) -> Optional[int]:
    """Pages a default PDF export should have for the measured document.

    Hidden slides are not exported by default, so they are subtracted.
    """
    count = before.get("unit_count")
    if count is None:
        return None
    if before.get("kind") in ("impress", "draw"):
        hidden = before.get("metrics", {}).get("hidden_slides") or 0
        return max(0, int(count) - int(hidden))
    return int(count)


def classify(worker: Optional[Dict[str, Any]], package_diff: Optional[Dict[str, Any]],
             pdf_pages: Optional[int], pdf_valid: Optional[bool],
             timed_out: bool = False, worker_exit: Optional[int] = None) -> Dict[str, Any]:
    """Compute the verdict for one document."""
    reasons: List[str] = []
    info: List[str] = []
    critical_diffs: Dict[str, list] = {}
    info_diffs: Dict[str, list] = {}

    if timed_out:
        reasons.append("timeout")
    if worker is None:
        if not timed_out:
            reasons.append("no-result" if worker_exit in (None, 0)
                           else f"worker-exit-{worker_exit}")
        return _verdict("fail", reasons, info, critical_diffs, info_diffs)
    if "fatal" in worker:
        reasons.append("probe-error")

    steps = worker.get("steps", {})
    for step, code in FAIL_STEPS:
        entry = steps.get(step)
        if entry is not None and not entry.get("ok"):
            reasons.append(code)
            break  # later steps cannot have run meaningfully
    engine = worker.get("engine", {})
    if steps.get("engine_start", {}).get("ok") and engine.get("alive_at_end") is False:
        reasons.append("engine-crashed")
    if reasons:
        return _verdict("fail", reasons, info, critical_diffs, info_diffs)

    before, after = worker.get("before"), worker.get("after")
    if not before or not after:
        return _verdict("fail", ["incomplete-result"], info, critical_diffs, info_diffs)
    if pdf_valid is False:
        return _verdict("fail", ["pdf-invalid"], info, critical_diffs, info_diffs)

    partial: List[str] = []
    if before.get("kind") != after.get("kind"):
        partial.append("document-kind-changed")
    if before.get("unit_count") != after.get("unit_count"):
        partial.append("unit-count-changed")
    critical_keys = CRITICAL_BY_KIND.get(before.get("kind", ""), ())
    critical_diffs, info_diffs = metric_diffs(
        before.get("metrics", {}), after.get("metrics", {}), critical_keys)
    partial.extend(f"critical-metric-changed:{key}" for key in critical_diffs)
    partial.extend(f"content-shrank:{key}" for key in shrunk(
        before.get("metrics", {}), after.get("metrics", {}), before.get("kind", "")))

    expected = expected_pdf_pages(before)
    if pdf_pages is None:
        partial.append("pdf-page-count-unknown")   # the page criterion could not be checked
    elif expected is not None and pdf_pages != expected:
        partial.append("pdf-page-mismatch")

    if package_diff:
        partial.extend(f"part-kind-lost:{kind}"
                       for kind in package_diff.get("critical_part_kinds_lost", []))
        partial.extend(f"content-lost:{key}" for key in package_diff.get("content_lost", []))
        partial.extend(f"transition-lost:{name}"
                       for name in package_diff.get("transitions_lost", []))
        for kind in package_diff.get("part_kinds_lost", []):
            if kind not in package_diff.get("critical_part_kinds_lost", []):
                info.append(f"part-kind-lost:{kind}")
        if package_diff.get("transitions_changed"):
            info.append("package-transitions-changed")
        if package_diff.get("family_changed"):
            partial.append("package-family-changed")
    if worker.get("import_filter") != worker.get("reopen_filter"):
        info.append("reopen-filter-differs")

    status = "partial" if partial else "pass"
    return _verdict(status, partial, info, critical_diffs, info_diffs)


def _verdict(status: str, reasons: List[str], info: List[str],
             critical_diffs: Dict[str, list], info_diffs: Dict[str, list]) -> Dict[str, Any]:
    return {"status": status, "reasons": reasons, "info": info,
            "critical_diffs": critical_diffs, "info_diffs": info_diffs}


def summarise(files: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate verdicts overall, per format and per feature tag."""
    def bucket() -> Dict[str, int]:
        return {"total": 0, "pass": 0, "partial": 0, "fail": 0}

    def rate(item: Dict[str, int]) -> Optional[float]:
        return round(item["pass"] / item["total"], 4) if item["total"] else None

    overall = bucket()
    by_format: Dict[str, Dict[str, int]] = {}
    by_feature: Dict[str, Dict[str, int]] = {}
    by_app: Dict[str, Dict[str, int]] = {}
    reasons: Dict[str, int] = {}
    for item in files:
        status = item["status"]
        groups = [overall, by_format.setdefault(item["format"], bucket()),
                  by_app.setdefault(item["app"], bucket())]
        groups.extend(by_feature.setdefault(tag, bucket()) for tag in item.get("features", []))
        for group in groups:
            group["total"] += 1
            group[status] += 1
        for reason in item.get("reasons", []):
            reasons[reason] = reasons.get(reason, 0) + 1
    result: Dict[str, Any] = dict(overall)
    result["pass_rate"] = rate(overall)
    result["by_format"] = {k: {**v, "pass_rate": rate(v)} for k, v in sorted(by_format.items())}
    result["by_app"] = {k: {**v, "pass_rate": rate(v)} for k, v in sorted(by_app.items())}
    result["by_feature"] = {k: {**v, "pass_rate": rate(v)} for k, v in sorted(by_feature.items())}
    result["reasons"] = dict(sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0])))
    return result
