"""Offline integrity tests. All option rows here are synthetic, not vendor data."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import stat
import zipfile
from pathlib import Path

import pandas as pd
import pytest

SPEC = importlib.util.spec_from_file_location("research_fetch", Path(__file__).parents[1] / "fetch_data.py")
fetcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fetcher)


class FakeResponse:
    def __init__(self, body, status=200, headers=None):
        self.body = body
        self.status_code = status
        self.headers = headers or {"Content-Length": str(len(body)), "ETag": '"version1"'}
        self.url = "https://example.test/input"

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size):
        yield self.body


def test_download_hash_verified_cache_and_tamper(tmp_path, monkeypatch):
    monkeypatch.setattr(fetcher.requests, "get", lambda *a, **k: FakeResponse(b"real source bytes"))
    target = tmp_path / "source.csv"
    meta = fetcher.fetch("https://example.test/input", target)
    assert meta["sha256"] == hashlib.sha256(b"real source bytes").hexdigest()
    monkeypatch.setattr(fetcher.requests, "get", lambda *a, **k: pytest.fail("Cache should not use network"))
    assert fetcher.fetch("https://example.test/input", target) == meta
    target.write_bytes(b"changed")
    with pytest.raises(ValueError, match="hash mismatch"):
        fetcher.fetch("https://example.test/input", target)


def test_unverified_cache_rejected(tmp_path):
    target = tmp_path / "source.csv"
    target.write_bytes(b"untrusted")
    with pytest.raises(ValueError, match="no source metadata"):
        fetcher.fetch("https://example.test/input", target)


def test_conditional_resume_preserves_original_prefix(tmp_path, monkeypatch):
    target = tmp_path / "source.csv"
    target.with_suffix(".csv.part").write_bytes(b"abc")
    target.with_suffix(".csv.part.json").write_text(json.dumps({
        "url": "https://example.test/input", "etag": '"version1"'}))

    def get(url, **kwargs):
        assert kwargs["headers"]["Range"] == "bytes=3-"
        assert kwargs["headers"]["If-Range"] == '"version1"'
        return FakeResponse(b"def", 206, {"Content-Range": "bytes 3-5/6", "ETag": '"version1"'})

    monkeypatch.setattr(fetcher.requests, "get", get)
    result = fetcher.fetch("https://example.test/input", target)
    assert target.read_bytes() == b"abcdef"
    assert result["sha256"] == hashlib.sha256(b"abcdef").hexdigest()
    assert not target.with_suffix(".csv.part").exists()


def test_range_with_wrong_start_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(fetcher.requests, "get", lambda *a, **k:
                        FakeResponse(b"x", 206, {"Content-Range": "bytes 1-1/2"}))
    with pytest.raises(ValueError, match="Content-Range"):
        fetcher.fetch("https://example.test/input", tmp_path / "source.csv")


def test_truncated_response_never_becomes_completed(tmp_path, monkeypatch):
    monkeypatch.setattr(fetcher.requests, "get", lambda *a, **k:
                        FakeResponse(b"x", headers={"Content-Length": "9"}))
    target = tmp_path / "source.csv"
    with pytest.raises(ValueError, match="Truncated"):
        fetcher.fetch("https://example.test/input", target)
    assert not target.exists()


@pytest.mark.parametrize("name", ["../escape.csv", "/absolute.csv", "C:/escape.csv", "a\\escape.csv", "a/./x.csv"])
def test_zip_rejects_path_escape(name):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        member = zipfile.ZipInfo("placeholder")
        member.filename = name  # Bypass Windows constructor's slash normalization.
        archive.writestr(member, b"x")
    with zipfile.ZipFile(stream) as archive, pytest.raises(ValueError, match="Unsafe ZIP"):
        fetcher.validate_zip_members(archive)


def test_zip_rejects_symlink_and_case_collision():
    for kind in ["symlink", "collision"]:
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            if kind == "symlink":
                member = zipfile.ZipInfo("link")
                member.create_system = 3
                member.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(member, "target")
            else:
                archive.writestr("A.csv", "x")
                archive.writestr("a.csv", "y")
        with zipfile.ZipFile(stream) as archive, pytest.raises(ValueError):
            fetcher.validate_zip_members(archive)


def test_publisher_hash_is_independently_checked(tmp_path):
    source = tmp_path / "day.csv"
    source.write_bytes(b"synthetic data")
    entry = {"name": source.name, "bytes": source.stat().st_size,
             "sha256": hashlib.sha256(b"other contents").hexdigest()}
    with pytest.raises(ValueError, match="byte/hash mismatch"):
        fetcher.check_publisher_file(source, entry)


@pytest.mark.parametrize("value", [None, "2022-6-01", "2022-02-30", "2023-01-01"])
def test_date_validation_rejects_missing_malformed_and_outside(value):
    with pytest.raises(ValueError):
        fetcher.validate_dates(pd.Series([value]), "2022-01-01", "2022-12-31")


def make_option_fixture(path):
    row = dict.fromkeys(fetcher.OPTION_COLUMNS, "")
    row.update(contract="SPXW220801C04000000", underlying="SPXW", expiration="2022-08-01",
               type="call", strike="4000", style="E", quote_date="2022-07-01",
               bid="5", ask="6", underlying_close="3900", settlement_time="PM", iv_flag="0")
    pd.DataFrame([row], columns=fetcher.OPTION_COLUMNS).to_csv(path, index=False)
    return row


def test_options_missing_values_preserved_and_contract_metadata_checked(tmp_path):
    path = tmp_path / "day.csv"
    row = make_option_fixture(path)
    audit = fetcher.audit_options_day(path, "2022-07-01")
    assert audit["quote_time_missing"] == 1
    assert audit["spxw_two_sided_uncrossed_rows"] == 1
    row["strike"] = "4001"
    pd.DataFrame([row], columns=fetcher.OPTION_COLUMNS).to_csv(path, index=False)
    with pytest.raises(ValueError, match="Contract symbol disagrees"):
        fetcher.audit_options_day(path, "2022-07-01")


def test_options_schema_rejects_missing_columns(tmp_path):
    path = tmp_path / "day.csv"
    row = make_option_fixture(path)
    del row["bid"]
    pd.DataFrame([row]).to_csv(path, index=False)
    with pytest.raises(ValueError, match="34-column"):
        fetcher.audit_options_day(path, "2022-07-01")


def test_fx_and_rates_missing_columns_fail_before_output(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("date,value\n2022-07-01,1\n")
    for processor in [fetcher.process_fx, fetcher.process_rates]:
        with pytest.raises(ValueError, match="Missing required columns"):
            processor(path, tmp_path / "should_not_exist.csv")
    assert not (tmp_path / "should_not_exist.csv").exists()
