# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Per-document fidelity probe.  Runs under the office engine's OWN Python.

This file is executed by ``tools/fidelity/run_fidelity.py`` as::

    <engine>/program/python uno_worker.py --request <request.json>

It must therefore only use the standard library and the engine's ``uno``
module, and must not import anything else from this repository.

For one input document it:

1. starts a private, headless engine process (own user profile, macros
   never executed, links never updated);
2. opens the document and records the import filter the engine chose;
3. measures the document model (page/slide count and structure);
4. exports it to PDF;
5. saves it again *with the same filter it was loaded with* (round trip);
6. reopens the round-tripped file and measures again;
7. writes everything to the result JSON and shuts the engine down.

Format knowledge used here is limited to the engine's public UNO API
(api.libreoffice.org) and filter names read from
``filter/source/config/fragments/filters/*.xcu`` in the pinned tree.

The engine is driven through its documented API only.  Exit code is 0
whenever a result file was written (document-level failures are data,
not tool failures); 2 for bad input; 3 when the engine could not be
started or the result could not be written.
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import traceback
import uuid

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_ENGINE = 3

PDF_FILTERS = {
    "com.sun.star.text.TextDocument": "writer_pdf_Export",
    "com.sun.star.presentation.PresentationDocument": "impress_pdf_Export",
    "com.sun.star.drawing.DrawingDocument": "draw_pdf_Export",
    "com.sun.star.sheet.SpreadsheetDocument": "calc_pdf_Export",
    "com.sun.star.text.WebDocument": "writer_web_pdf_Export",
    "com.sun.star.text.GlobalDocument": "writer_globaldocument_pdf_Export",
    "com.sun.star.formula.FormulaProperties": "math_pdf_Export",
}
DOC_KINDS = (
    ("com.sun.star.text.GlobalDocument", "writer-global"),
    ("com.sun.star.text.WebDocument", "writer-web"),
    ("com.sun.star.text.TextDocument", "writer"),
    ("com.sun.star.presentation.PresentationDocument", "impress"),
    ("com.sun.star.drawing.DrawingDocument", "draw"),
    ("com.sun.star.sheet.SpreadsheetDocument", "calc"),
    ("com.sun.star.formula.FormulaProperties", "math"),
)
MAX_PORTIONS = 20000     # bound on text portions walked per document
MAX_ANIM_NODES = 50000   # bound on animation nodes walked per document
CONNECT_TIMEOUT_S = 90


def _prop(name, value):
    import uno
    from com.sun.star.beans import PropertyValue
    item = PropertyValue()
    item.Name = name
    item.Value = value
    return item


def _safe(func, default=None):
    """Run a metric getter; a failing getter must not fail the document."""
    try:
        return func()
    except Exception:  # noqa: BLE001 - UNO raises many unrelated types
        return default


def _count(getter):
    """Count of the container returned by ``getter`` (called lazily)."""
    return _safe(lambda: int(getter().getCount()), None)


def _bump(table, key, amount=1):
    table[key] = table.get(key, 0) + amount


# --------------------------------------------------------------------------
# engine life cycle
# --------------------------------------------------------------------------

class Engine(object):
    """A private headless engine process reachable over a named pipe."""

    def __init__(self, soffice, profile_dir, log_path):
        self.soffice = soffice
        self.profile_dir = profile_dir
        self.log_path = log_path
        self.pipe = "fid" + uuid.uuid4().hex[:16]
        self.process = None
        self.context = None
        self.desktop = None

    def start(self):
        import uno
        profile_url = uno.systemPathToFileUrl(os.path.abspath(self.profile_dir))
        command = [
            self.soffice,
            "--headless", "--invisible", "--norestore", "--nologo", "--nodefault",
            "--nolockcheck", "--nofirststartwizard",
            "-env:UserInstallation=" + profile_url,
            "--accept=pipe,name=%s;urp;StarOffice.ComponentContext" % self.pipe,
        ]
        log = open(self.log_path, "ab")
        env = dict(os.environ)
        # No display, no session bus, no proxy-configured network access.
        for name in ("DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS",
                     "http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
                     "ftp_proxy", "FTP_PROXY", "all_proxy", "ALL_PROXY"):
            env.pop(name, None)
        env["SAL_USE_VCLPLUGIN"] = "svp"
        self.process = subprocess.Popen(command, stdout=log, stderr=log, env=env,
                                        stdin=subprocess.DEVNULL)
        log.close()
        local = uno.getComponentContext()
        resolver = local.ServiceManager.createInstanceWithContext(
            "com.sun.star.bridge.UnoUrlResolver", local)
        url = "uno:pipe,name=%s;urp;StarOffice.ComponentContext" % self.pipe
        deadline = time.time() + CONNECT_TIMEOUT_S
        last = None
        while time.time() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError("engine exited during start-up with code %s"
                                   % self.process.returncode)
            try:
                self.context = resolver.resolve(url)
                break
            except Exception as exc:  # noqa: BLE001
                last = exc
                time.sleep(0.25)
        if self.context is None:
            raise RuntimeError("could not connect to engine: %s" % last)
        self.desktop = self.context.ServiceManager.createInstanceWithContext(
            "com.sun.star.frame.Desktop", self.context)

    def alive(self):
        return self.process is not None and self.process.poll() is None

    def stop(self):
        if self.process is None:
            return None
        if self.alive() and self.desktop is not None:
            try:
                self.desktop.terminate()
            except Exception:  # noqa: BLE001 - the bridge dies while terminating
                pass
        try:
            self.process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self.process.send_signal(signal.SIGKILL)
            self.process.wait(timeout=10)
        return self.process.returncode


# --------------------------------------------------------------------------
# document model metrics
# --------------------------------------------------------------------------

def _doc_kind(doc):
    for service, kind in DOC_KINDS:
        if _safe(lambda s=service: doc.supportsService(s), False):
            return service, kind
    return "", "unknown"


def _basic_modules(doc):
    """Count Basic/VBA modules stored in the document (never executed)."""
    def read():
        libraries = doc.BasicLibraries
        total = 0
        names = []
        for name in libraries.getElementNames():
            if not libraries.isLibraryLoaded(name):
                libraries.loadLibrary(name)
            modules = libraries.getByName(name).getElementNames()
            total += len(modules)
            names.append(name)
        return {"libraries": sorted(names), "modules": total}
    return _safe(read, {"libraries": [], "modules": None})


def _walk_text_portions(text, fonts, counters, budget):
    """Walk paragraphs/portions of an XText; returns the remaining budget."""
    enum = _safe(lambda: text.createEnumeration())
    if enum is None:
        return budget
    while enum.hasMoreElements() and budget > 0:
        para = enum.nextElement()
        if _safe(lambda p=para: p.supportsService("com.sun.star.text.TextTable"), False):
            continue
        _bump(counters, "paragraphs")
        if _safe(lambda p=para: bool(p.NumberingIsNumber) and bool(p.NumberingStyleName), False):
            _bump(counters, "list_paragraphs")
        portions = _safe(lambda p=para: p.createEnumeration())
        if portions is None:
            continue
        while portions.hasMoreElements() and budget > 0:
            portion = portions.nextElement()
            budget -= 1
            kind = _safe(lambda p=portion: p.TextPortionType, "")
            if kind == "Text":
                font = _safe(lambda p=portion: p.CharFontName, "")
                if font:
                    fonts.add(font)
                if _safe(lambda p=portion: p.HyperLinkURL, ""):
                    _bump(counters, "hyperlink_portions")
            elif kind:
                _bump(counters, "portion_" + kind)
    return budget


def writer_metrics(doc):
    metrics = {}
    controller = _safe(lambda: doc.getCurrentController())
    metrics["page_count"] = _safe(lambda: int(controller.PageCount), None)
    metrics["tables"] = _count(doc.getTextTables)
    metrics["images"] = _count(doc.getGraphicObjects)
    metrics["embedded_objects"] = _count(doc.getEmbeddedObjects)
    metrics["text_frames"] = _count(doc.getTextFrames)
    metrics["draw_shapes"] = _safe(lambda: int(doc.getDrawPage().getCount()), None)
    metrics["sections"] = _count(doc.getTextSections)
    metrics["footnotes"] = _count(doc.getFootnotes)
    metrics["endnotes"] = _count(doc.getEndnotes)
    metrics["bookmarks"] = _count(doc.getBookmarks)
    metrics["word_count"] = _safe(lambda: int(doc.WordCount), None)
    metrics["character_count"] = _safe(lambda: int(doc.CharacterCount), None)

    def indexes():
        result = {}
        container = doc.getDocumentIndexes()
        for index in range(container.getCount()):
            name = container.getByIndex(index).getServiceName()
            _bump(result, name.rsplit(".", 1)[-1])
        return result
    metrics["indexes"] = _safe(indexes, None)

    def fields():
        result = {}
        enum = doc.getTextFields().createEnumeration()
        while enum.hasMoreElements():
            field = enum.nextElement()
            names = [n for n in field.getSupportedServiceNames()
                     if n.startswith("com.sun.star.text.textfield.")
                     or n.startswith("com.sun.star.text.TextField.")]
            label = names[0].rsplit(".", 1)[-1] if names else "Other"
            _bump(result, label)
        return result
    field_counts = _safe(fields, None)
    metrics["fields"] = field_counts
    metrics["comments"] = None if field_counts is None else field_counts.get("Annotation", 0)

    def redlines():
        result = {}
        enum = doc.getRedlines().createEnumeration()
        while enum.hasMoreElements():
            _bump(result, str(enum.nextElement().RedlineType))
        return result
    redline_counts = _safe(redlines, None)
    metrics["redlines_by_type"] = redline_counts
    metrics["redlines"] = None if redline_counts is None else sum(redline_counts.values())

    def page_styles():
        families = doc.getStyleFamilies().getByName("PageStyles")
        used = header = footer = columns = 0
        for index in range(families.getCount()):
            style = families.getByIndex(index)
            if not style.isInUse():
                continue
            used += 1
            header += 1 if style.HeaderIsOn else 0
            footer += 1 if style.FooterIsOn else 0
            cols = _safe(lambda s=style: s.TextColumns.getColumnCount(), 1)
            columns += 1 if cols and cols > 1 else 0
        return {"used": used, "with_header": header, "with_footer": footer,
                "multi_column": columns}
    metrics["page_styles"] = _safe(page_styles, None)

    def used_styles(family):
        families = doc.getStyleFamilies().getByName(family)
        return sorted(families.getByIndex(i).getName()
                      for i in range(families.getCount())
                      if families.getByIndex(i).isInUse())
    para_styles = _safe(lambda: used_styles("ParagraphStyles"), None)
    char_styles = _safe(lambda: used_styles("CharacterStyles"), None)
    metrics["paragraph_styles_used"] = None if para_styles is None else len(para_styles)
    metrics["character_styles_used"] = None if char_styles is None else len(char_styles)

    fonts = set()
    counters = {}
    budget = _walk_text_portions(doc.getText(), fonts, counters, MAX_PORTIONS)
    metrics["paragraphs"] = counters.get("paragraphs", 0)
    metrics["list_paragraphs"] = counters.get("list_paragraphs", 0)
    metrics["hyperlink_portions"] = counters.get("hyperlink_portions", 0)
    metrics["portion_walk_truncated"] = budget <= 0
    metrics["fonts"] = sorted(fonts)
    metrics["basic"] = _basic_modules(doc)
    return metrics


def _walk_anim(node, stats, budget):
    """Count animation nodes; an "effect" is a node carrying a preset-id."""
    if budget[0] <= 0:
        return
    budget[0] -= 1
    _bump(stats, "nodes")
    data = _safe(lambda: node.UserData, None) or ()
    for item in data:
        if item.Name == "preset-id" and item.Value:
            _bump(stats, "effects")
            stats.setdefault("presets", []).append(str(item.Value))
        elif item.Name == "preset-class":
            _bump(stats, "class_%s" % item.Value)
    enum = _safe(lambda: node.createEnumeration())
    if enum is None:
        return
    while enum.hasMoreElements():
        _walk_anim(enum.nextElement(), stats, budget)


def _shape_stats(shapes, by_type, fonts, counters, budget):
    for index in range(shapes.getCount()):
        shape = shapes.getByIndex(index)
        kind = _safe(lambda s=shape: s.getShapeType(), "unknown") or "unknown"
        _bump(by_type, kind.rsplit(".", 1)[-1])
        if kind == "com.sun.star.drawing.GroupShape":
            budget = _shape_stats(shape, by_type, fonts, counters, budget)
            continue
        if kind == "com.sun.star.drawing.OLE2Shape":
            clsid = _safe(lambda s=shape: s.CLSID, "")
            if clsid:
                counters.setdefault("ole_clsids", []).append(str(clsid).lower())
        if kind == "com.sun.star.drawing.TableShape":
            continue
        text = _safe(lambda s=shape: s.getText())
        if text is not None and budget > 0:
            string = _safe(lambda t=text: t.getString(), "") or ""
            counters["text_chars"] = counters.get("text_chars", 0) + len(string)
            budget = _walk_text_portions(text, fonts, counters, budget)
    return budget


def impress_metrics(doc):
    metrics = {}
    pages = doc.getDrawPages()
    count = pages.getCount()
    metrics["slide_count"] = count
    metrics["master_count"] = _count(doc.getMasterPages)
    metrics["custom_shows"] = _safe(
        lambda: len(doc.getCustomPresentations().getElementNames()), None)
    first = pages.getByIndex(0) if count else None
    metrics["slide_size"] = _safe(lambda: [int(first.Width), int(first.Height)], None)

    by_type = {}
    fonts = set()
    counters = {}
    budget = MAX_PORTIONS
    transitions = []
    anim = {"nodes": 0}
    anim_budget = [MAX_ANIM_NODES]
    hidden = notes_slides = notes_chars = comments = 0
    masters_used = set()
    layouts = []
    for index in range(count):
        page = pages.getByIndex(index)
        if not _safe(lambda p=page: bool(p.Visible), True):
            hidden += 1
        master = _safe(lambda p=page: p.getMasterPage().Name, "")
        if master:
            masters_used.add(master)
        layouts.append(_safe(lambda p=page: int(p.Layout), -1))
        transitions.append([
            _safe(lambda p=page: int(p.TransitionType), 0),
            _safe(lambda p=page: int(p.TransitionSubtype), 0),
            _safe(lambda p=page: bool(p.TransitionDirection), True),
            _safe(lambda p=page: int(p.Change), 0),
        ])
        budget = _shape_stats(page, by_type, fonts, counters, budget)
        node = _safe(lambda p=page: p.AnimationNode)
        if node is not None:
            _walk_anim(node, anim, anim_budget)
        notes = _safe(lambda p=page: p.getNotesPage())
        if notes is not None:
            chars = 0
            for shape_index in range(notes.getCount()):
                shape = notes.getByIndex(shape_index)
                if _safe(lambda s=shape: s.getShapeType(), "") == \
                        "com.sun.star.presentation.NotesShape":
                    chars += len(_safe(lambda s=shape: s.getString(), "") or "")
            if chars:
                notes_slides += 1
                notes_chars += chars

        def annotations(p=page):
            total = 0
            enum = p.createAnnotationEnumeration()
            while enum.hasMoreElements():
                enum.nextElement()
                total += 1
            return total
        comments += _safe(annotations, 0)

    metrics["hidden_slides"] = hidden
    metrics["masters_in_use"] = len(masters_used)
    metrics["layouts"] = layouts
    metrics["transitions"] = transitions
    metrics["slides_with_transition"] = sum(1 for t in transitions if t[0])
    metrics["animation_nodes"] = anim.get("nodes", 0)
    metrics["animation_effects"] = anim.get("effects", 0)
    metrics["animation_presets"] = sorted(anim.get("presets", []))
    metrics["animation_walk_truncated"] = anim_budget[0] <= 0
    metrics["notes_slides"] = notes_slides
    metrics["notes_chars"] = notes_chars
    metrics["comments"] = comments
    metrics["shapes_by_type"] = by_type
    metrics["shapes"] = sum(by_type.values())
    metrics["tables"] = by_type.get("TableShape", 0)
    metrics["images"] = by_type.get("GraphicObjectShape", 0)
    metrics["media"] = by_type.get("MediaShape", 0)
    metrics["ole_objects"] = by_type.get("OLE2Shape", 0)
    metrics["ole_clsids"] = sorted(counters.get("ole_clsids", []))
    metrics["text_chars"] = counters.get("text_chars", 0)
    metrics["paragraphs"] = counters.get("paragraphs", 0)
    metrics["hyperlink_portions"] = counters.get("hyperlink_portions", 0)
    metrics["portion_walk_truncated"] = budget <= 0
    metrics["fonts"] = sorted(fonts)

    def show_settings():
        show = doc.getPresentation()
        return {"endless": bool(show.IsEndless), "full_screen": bool(show.IsFullScreen),
                "automatic": bool(show.IsAutomatic), "pause": int(show.Pause)}
    metrics["show_settings"] = _safe(show_settings, None)
    metrics["basic"] = _basic_modules(doc)
    return metrics


def measure(doc):
    service, kind = _doc_kind(doc)
    if kind in ("writer", "writer-web", "writer-global"):
        metrics = writer_metrics(doc)
        pages = metrics.get("page_count")
    elif kind in ("impress", "draw"):
        metrics = impress_metrics(doc)
        pages = metrics.get("slide_count")
    else:
        metrics = {}
        pages = None
    return {"service": service, "kind": kind, "unit_count": pages, "metrics": metrics}


# --------------------------------------------------------------------------
# load / store
# --------------------------------------------------------------------------

def _load(engine, path, password):
    import uno
    props = [
        _prop("Hidden", True),
        _prop("MacroExecutionMode", 0),   # document::MacroExecMode::NEVER_EXECUTE
        _prop("UpdateDocMode", 0),        # document::UpdateDocMode::NO_UPDATE
    ]
    if password:
        props.append(_prop("Password", password))
    url = uno.systemPathToFileUrl(os.path.abspath(path))
    doc = engine.desktop.loadComponentFromURL(url, "_blank", 0, tuple(props))
    if doc is None:
        raise RuntimeError("engine returned no document (unsupported or unreadable file)")
    return doc


def _filter_name(doc):
    for item in doc.getArgs():
        if item.Name == "FilterName":
            return str(item.Value)
    return ""


def _store(doc, path, filter_name, password=None):
    import uno
    props = [_prop("FilterName", filter_name), _prop("Overwrite", True)]
    if password:
        props.append(_prop("Password", password))
    doc.storeToURL(uno.systemPathToFileUrl(os.path.abspath(path)), tuple(props))


def _close(doc):
    try:
        doc.close(True)
    except Exception:  # noqa: BLE001
        try:
            doc.dispose()
        except Exception:  # noqa: BLE001
            pass


def _step(result, name, func):
    """Run one step, record duration and outcome; return (ok, value)."""
    started = time.time()
    entry = {"ok": False, "duration_ms": 0}
    result["steps"][name] = entry
    try:
        value = func()
        entry["ok"] = True
        return True, value
    except Exception as exc:  # noqa: BLE001
        entry["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:500])
        entry["trace"] = traceback.format_exc()[-1500:]
        return False, None
    finally:
        entry["duration_ms"] = int((time.time() - started) * 1000)


def probe(request):
    source = request["input"]
    workdir = request["workdir"]
    extension = os.path.splitext(source)[1]
    result = {
        "input": source,
        "steps": {},
        "engine": {"soffice": request["soffice"]},
        "outputs": {},
    }
    os.makedirs(workdir, exist_ok=True)
    engine = Engine(request["soffice"], os.path.join(workdir, "profile"),
                    os.path.join(workdir, "engine.log"))
    ok, _ = _step(result, "engine_start", engine.start)
    if not ok:
        result["engine"]["exit_code"] = engine.stop()
        return result

    password = request.get("password") or None
    doc = None
    try:
        ok, doc = _step(result, "open", lambda: _load(engine, source, password))
        if ok:
            result["import_filter"] = _filter_name(doc)
            ok, before = _step(result, "measure", lambda: measure(doc))
            if ok:
                result["before"] = before
                pdf_filter = PDF_FILTERS.get(before["service"])
                pdf_path = os.path.join(workdir, "export.pdf")
                if pdf_filter:
                    ok_pdf, _ = _step(result, "pdf_export",
                                      lambda: _store(doc, pdf_path, pdf_filter))
                    if ok_pdf:
                        result["outputs"]["pdf"] = pdf_path
                else:
                    result["steps"]["pdf_export"] = {
                        "ok": False, "duration_ms": 0,
                        "error": "no PDF export filter known for " + before["service"]}
                roundtrip = os.path.join(workdir, "roundtrip" + extension)
                ok_rt, _ = _step(
                    result, "roundtrip_save",
                    lambda: _store(doc, roundtrip, result["import_filter"], password))
                if ok_rt:
                    result["outputs"]["roundtrip"] = roundtrip
            _close(doc)
            doc = None
            if "roundtrip" in result["outputs"] and engine.alive():
                ok, doc = _step(
                    result, "reopen",
                    lambda: _load(engine, result["outputs"]["roundtrip"], password))
                if ok:
                    result["reopen_filter"] = _filter_name(doc)
                    ok, after = _step(result, "remeasure", lambda: measure(doc))
                    if ok:
                        result["after"] = after
    finally:
        if doc is not None:
            _close(doc)
        result["engine"]["alive_at_end"] = engine.alive()
        result["engine"]["exit_code"] = engine.stop()
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="fidelity probe for one document")
    parser.add_argument("--request", required=True,
                        help="JSON file: input, workdir, result, soffice[, password]")
    args = parser.parse_args(argv)
    try:
        with open(args.request, "r", encoding="utf-8") as handle:
            request = json.load(handle)
        for key in ("input", "workdir", "result", "soffice"):
            if not isinstance(request.get(key), str) or not request[key]:
                raise ValueError("request field %r missing" % key)
        if not os.path.isfile(request["input"]):
            raise ValueError("input is not a file: %s" % request["input"])
        if not os.path.isfile(request["soffice"]):
            raise ValueError("soffice not found: %s" % request["soffice"])
    except (OSError, ValueError) as exc:
        sys.stderr.write("error: %s\n" % exc)
        return EXIT_USAGE

    started = time.time()
    try:
        result = probe(request)
    except Exception as exc:  # noqa: BLE001 - last resort, still write a result
        result = {"input": request["input"], "steps": {},
                  "fatal": "%s: %s" % (type(exc).__name__, exc),
                  "trace": traceback.format_exc()[-3000:]}
    result["duration_ms"] = int((time.time() - started) * 1000)
    try:
        tmp = request["result"] + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=1, sort_keys=True, default=repr)
        os.replace(tmp, request["result"])
    except OSError as exc:
        sys.stderr.write("error: cannot write result: %s\n" % exc)
        return EXIT_ENGINE
    if "fatal" in result or not result.get("steps", {}).get("engine_start", {}).get("ok"):
        return EXIT_ENGINE
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
