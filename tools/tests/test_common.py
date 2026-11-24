# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Unit tests for tools.common (logging, verified downloads, metrics)."""

import hashlib
import http.server
import json
import threading

import pytest

from tools.common import jsonlog, metrics, netfetch


# ---------------------------------------------------------------- jsonlog

def test_log_record_has_required_fields(tmp_path):
    log = jsonlog.JsonlLogger(tmp_path / "logs" / "run.jsonl", phase="phase0", run_id="r1")
    log.log("step-a", result="ok", duration_ms=12, extra="x")
    (record,) = jsonlog.read_records(log.path)
    for key in ("ts", "level", "run_id", "phase", "step", "duration_ms", "result"):
        assert key in record
    assert record["run_id"] == "r1" and record["phase"] == "phase0"
    assert record["step"] == "step-a" and record["duration_ms"] == 12
    assert record["extra"] == "x"


@pytest.mark.parametrize("kwargs", [
    {"level": "LOUD"}, {"result": "maybe"}, {"step": ""}, {"run_id": "collides"},
])
def test_log_rejects_bad_input(tmp_path, kwargs):
    log = jsonlog.JsonlLogger(tmp_path / "run.jsonl", phase="p")
    step = kwargs.pop("step", "s")
    with pytest.raises(ValueError):
        log.log(step, **kwargs)


def test_logger_rejects_bad_run_id_and_phase(tmp_path):
    with pytest.raises(ValueError):
        jsonlog.JsonlLogger(tmp_path / "a.jsonl", phase="p", run_id="../evil")
    with pytest.raises(ValueError):
        jsonlog.JsonlLogger(tmp_path / "a.jsonl", phase="")


def test_timed_records_failure_and_reraises(tmp_path):
    log = jsonlog.JsonlLogger(tmp_path / "run.jsonl", phase="p")
    with log.timed("good") as ctx:
        ctx["items"] = 3
    with pytest.raises(RuntimeError):
        with log.timed("bad"):
            raise RuntimeError("boom")
    good, bad = jsonlog.read_records(log.path)
    assert good["result"] == "ok" and good["items"] == 3
    assert bad["result"] == "fail" and bad["level"] == "ERROR" and "boom" in bad["error"]


def test_timed_result_override_and_unserialisable_values(tmp_path):
    log = jsonlog.JsonlLogger(tmp_path / "run.jsonl", phase="p")
    with log.timed("skipped") as ctx:
        ctx["result"] = "skip"
    log.log("odd", value={1, 2})  # a set is not JSON; must not raise
    first, second = jsonlog.read_records(log.path)
    assert first["result"] == "skip"
    assert isinstance(second["value"], str)


def test_read_records_rejects_malformed(tmp_path):
    path = tmp_path / "x.jsonl"
    path.write_text('{"ts": 1}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="missing fields"):
        jsonlog.read_records(path)
    path.write_text("not json\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not JSON"):
        jsonlog.read_records(path)


def test_default_log_dir_honours_environment(tmp_path, monkeypatch):
    monkeypatch.delenv("SUITE_LOG_DIR", raising=False)
    assert jsonlog.default_log_dir(tmp_path) == tmp_path / "logs"
    monkeypatch.setenv("SUITE_LOG_DIR", str(tmp_path / "elsewhere"))
    assert jsonlog.default_log_dir(tmp_path) == tmp_path / "elsewhere"


# ---------------------------------------------------------------- netfetch

class _Handler(http.server.BaseHTTPRequestHandler):
    payload = b"hello world" * 100
    failures_left = 0
    hits = 0

    def do_GET(self):  # noqa: N802 - http.server API
        cls = type(self)
        cls.hits += 1
        if self.path == "/missing":
            self.send_error(404)
            return
        if self.path == "/flaky" and cls.failures_left > 0:
            cls.failures_left -= 1
            self.send_error(503)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(cls.payload)))
        self.end_headers()
        self.wfile.write(cls.payload)

    def log_message(self, *args):
        pass


@pytest.fixture()
def server():
    _Handler.failures_left = 0
    _Handler.hits = 0
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


GOOD = hashlib.sha256(_Handler.payload).hexdigest()


def test_fetch_downloads_then_uses_cache(server, tmp_path):
    dest = tmp_path / "sub" / "file.bin"
    first = netfetch.fetch_verified(server + "/ok", dest, GOOD, allow_http=True)
    assert first.status == "downloaded" and dest.read_bytes() == _Handler.payload
    hits = _Handler.hits
    second = netfetch.fetch_verified(server + "/ok", dest, GOOD, allow_http=True)
    assert second.status == "cached" and _Handler.hits == hits  # no network on re-run


def test_fetch_checksum_mismatch_leaves_nothing_and_is_not_retried(server, tmp_path):
    dest = tmp_path / "file.bin"
    sleeps = []
    with pytest.raises(netfetch.ChecksumMismatch) as info:
        netfetch.fetch_verified(server + "/ok", dest, "0" * 64, allow_http=True,
                                sleep=sleeps.append)
    assert info.value.actual == GOOD
    assert not dest.exists() and not dest.with_name("file.bin.part").exists()
    assert sleeps == [] and _Handler.hits == 1


def test_fetch_replaces_wrong_existing_file(server, tmp_path):
    dest = tmp_path / "file.bin"
    dest.write_bytes(b"tampered")
    result = netfetch.fetch_verified(server + "/ok", dest, GOOD, allow_http=True)
    assert result.status == "downloaded" and dest.read_bytes() == _Handler.payload


def test_fetch_retries_server_errors_with_backoff(server, tmp_path):
    _Handler.failures_left = 2
    sleeps = []
    result = netfetch.fetch_verified(server + "/flaky", tmp_path / "f", GOOD, retries=3,
                                     backoff_base=1.0, allow_http=True, sleep=sleeps.append)
    assert result.attempts == 3 and sleeps == [1.0, 2.0]


def test_fetch_gives_up_after_bounded_retries(server, tmp_path):
    _Handler.failures_left = 99
    sleeps = []
    with pytest.raises(netfetch.FetchError):
        netfetch.fetch_verified(server + "/flaky", tmp_path / "f", GOOD, retries=2,
                                backoff_base=0.5, allow_http=True, sleep=sleeps.append)
    assert sleeps == [0.5, 1.0] and _Handler.hits == 3


def test_fetch_does_not_retry_not_found(server, tmp_path):
    sleeps = []
    with pytest.raises(netfetch.FetchError, match="404"):
        netfetch.fetch_verified(server + "/missing", tmp_path / "f", GOOD, allow_http=True,
                                sleep=sleeps.append)
    assert sleeps == [] and _Handler.hits == 1


@pytest.mark.parametrize("url", ["http://example.org/x", "ftp://example.org/x", "file:///etc/passwd",
                                 "https://", "not a url"])
def test_fetch_rejects_non_https_urls(url, tmp_path):
    with pytest.raises(ValueError):
        netfetch.fetch_verified(url, tmp_path / "f", GOOD)


def test_validators():
    assert netfetch.validate_sha256(" " + GOOD.upper() + " ") == GOOD
    with pytest.raises(ValueError):
        netfetch.validate_sha256("abc")
    assert netfetch.backoff_delays(4, base=2, cap=10) == [2, 4, 8, 10]
    with pytest.raises(ValueError):
        netfetch.backoff_delays(-1)


# ---------------------------------------------------------------- metrics

def test_update_metrics_replaces_only_its_section(tmp_path):
    path = tmp_path / "reports" / "build-metrics.json"
    metrics.update_metrics(path, "fidelity_baseline", {"pass_rate": 0.5})
    metrics.update_metrics(path, "ledger", {"allow": 3})
    metrics.update_metrics(path, "fidelity_baseline", {"pass_rate": 0.75})
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["sections"]["fidelity_baseline"]["pass_rate"] == 0.75
    assert data["sections"]["ledger"]["allow"] == 3
    assert "updated_at" in data["sections"]["ledger"]


def test_update_metrics_validates(tmp_path):
    with pytest.raises(ValueError):
        metrics.update_metrics(tmp_path / "m.json", "Bad Name", {})
    with pytest.raises(ValueError):
        metrics.update_metrics(tmp_path / "m.json", "ok", ["not", "a", "dict"])
    (tmp_path / "broken.json").write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError):
        metrics.read_metrics(tmp_path / "broken.json")
