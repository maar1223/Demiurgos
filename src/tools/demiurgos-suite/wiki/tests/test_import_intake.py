# -*- coding: utf-8 -*-
"""World importer slice 1 — RED tests (auth/path safety, bounds, zip bomb,
malformed provider -> failed, streamed resumable intake)."""

import base64
import os
import sys
import zipfile
from pathlib import Path

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

_HERE = Path(__file__).resolve().parent
_WIKI = _HERE.parent
for _p in (str(_WIKI),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from import_models import (  # noqa: E402
    ImportJob,
    ImportJobState,
    MAX_FILE_BYTES,
    MAX_JOB_AGGREGATE_BYTES,
    Candidate,
    utcnow_iso,
)
import import_intake as intake  # noqa: E402
from import_intake import (  # noqa: E402
    BoundsError,
    BoundedSpool,
    MalformedProviderError,
    UnsafePathError,
    ZipBombError,
    check_file_bounds,
    reject_unsafe_path,
    validate_zip_manifest,
    inspect_zip,
    extract_zip_bounded,
    SpoolFile,
    ZipEntrySpec,
)
from import_store import ImportJobStore  # noqa: E402
from import_router import create_import_router, CreateJobRequest, StreamChunkRequest  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakePrincipal:
    def __init__(self, pid: str = "tester"):
        self.id = pid


def _app(tmp_path: Path, *, provider=None, owner_id="tester", store=None):
    """Standalone app with the import router, hermetic store/spool."""
    if store is None:
        store = ImportJobStore(":memory:")
    spool = tmp_path / "spool"
    (tmp_path / "mundos" / "world1").mkdir(parents=True, exist_ok=True)

    def require_principal(request):
        return _FakePrincipal(owner_id)

    app = FastAPI()
    app.include_router(
        create_import_router(
            require_principal=require_principal,
            mundos_dir=lambda: tmp_path / "mundos",
            spool_dir=lambda: spool,
            store=store,
            provider=provider,
        )
    )
    return app, store, spool


def _create_job(client: TestClient, files=None, kind="loose") -> dict:
    resp = client.post("/api/world1/imports",
                       json={"source_kind": kind, "files": files or []})
    assert resp.status_code == 201, resp.text
    return resp.json()["job"]


def _stream(client: TestClient, job_id: str, relative: str, data: bytes,
            offset: int = 0) -> int:
    resp = client.post(
        f"/api/world1/imports/{job_id}/stream",
        json=StreamChunkRequest(relative=relative, offset=offset,
                                data_b64=base64.b64encode(data).decode()).model_dump(),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["offset"]


def _candidate(job_id: str, world: str = "world1", ident: str = "A",
               data: bytes = b"---\ntype: personaje\nname: A\n---\nA") -> Candidate:
    return Candidate(
        candidate_id=ident,
        job_id=job_id,
        world=world,
        normalized_identity=ident,
        source_hash="sha256:" + ident,
        provenance=intake_import_provenance(ident),
        content_preview=data.decode(),
        size_bytes=len(data),
    )


def intake_import_provenance(ident: str):
    from import_models import Provenance
    return Provenance(source_path=f"lore/{ident}.md", source_kind="loose",
                      source_hash="sha256:" + ident, source_sequence=0)


class TestAuthPathSafety:
    def test_unauthenticated_create_returns_401(self, tmp_path, monkeypatch):
        app, _, _ = _app(tmp_path)
        # force a None principal (unauthenticated)
        app = FastAPI()
        app.include_router(
            create_import_router(
                require_principal=lambda request: None,
                mundos_dir=lambda: tmp_path / "mundos",
                spool_dir=lambda: tmp_path / "spool",
                store=ImportJobStore(":memory:"),
            )
        )
        resp = TestClient(app).post("/api/world1/imports", json={})
        assert resp.status_code == 401

    def test_forged_principal_not_owner_is_403(self, tmp_path):
        _, store, _ = _app(tmp_path, owner_id="real")
        store.create_job(ImportJob(
            job_id="j1", world="world1", owner_principal="real",
            created_at=utcnow_iso(), updated_at=utcnow_iso(),
        ))
        # A second principal (different owner) must be rejected on the SAME store.
        def require_principal(request):
            return _FakePrincipal("forged")

        app2 = FastAPI()
        app2.include_router(
            create_import_router(
                require_principal=require_principal,
                mundos_dir=lambda: tmp_path / "mundos",
                spool_dir=lambda: tmp_path / "spool",
                store=store,
            )
        )
        resp = TestClient(app2).get("/api/world1/imports/j1")
        assert resp.status_code == 403

    @pytest.mark.parametrize("bad", ["../etc/passwd", "lore/..", "/abs/path",
                                     "lore\\win", "lore/.papelera/x",
                                     "lore/_context/x"])
    def test_unsafe_paths_rejected(self, tmp_path, bad):
        app, _, _ = _app(tmp_path)
        resp = TestClient(app).post(
            "/api/world1/imports", json=CreateJobRequest(files=[bad]).model_dump()
        )
        assert resp.status_code == 400

    def test_system_folder_fails_closed(self, tmp_path):
        with pytest.raises(UnsafePathError):
            reject_unsafe_path("lore/.papelera/old.md")
        with pytest.raises(UnsafePathError):
            reject_unsafe_path("canon/relaciones/x.md")

    def test_symlink_escape_fails_closed(self, tmp_path):
        spool = BoundedSpool(tmp_path / "spool", "job1", "world1")
        spool.begin_file("lore/a.md", 10)
        outside = tmp_path / "outside.txt"
        outside.write_text("x")
        link = spool.job_dir / "lore" / "evil.md"
        try:
            os.symlink(outside, link)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks not available")
        with pytest.raises(UnsafePathError):
            spool.begin_file("lore/evil.md", 10)


class TestMalformedProvider:
    def test_malformed_provider_marks_job_failed(self, tmp_path):
        def bad_provider(job, files):
            raise MalformedProviderError("garbage")

        app, _, _ = _app(tmp_path, provider=bad_provider)
        client = TestClient(app)
        job = _create_job(client)
        _stream(client, job["job_id"], "lore/a.md", b"abc")
        resp = client.post(f"/api/world1/imports/{job['job_id']}/analyze")
        assert resp.status_code == 200
        assert resp.json()["job"]["state"] == "failed"

    def test_non_list_provider_marks_job_failed(self, tmp_path):
        app, _, _ = _app(tmp_path, provider=lambda job, files: "not-a-list")
        client = TestClient(app)
        job = _create_job(client)
        resp = client.post(f"/api/world1/imports/{job['job_id']}/analyze")
        assert resp.json()["job"]["state"] == "failed"

    def test_unavailable_provider_fails_closed(self, tmp_path):
        app, _, _ = _app(tmp_path, provider=None)
        client = TestClient(app)
        job = _create_job(client)
        resp = client.post(f"/api/world1/imports/{job['job_id']}/analyze")
        assert resp.json()["job"]["state"] == "failed"

    def test_failed_job_never_approvable(self, tmp_path):
        app, _, _ = _app(tmp_path, provider=None)
        client = TestClient(app)
        job = _create_job(client)
        client.post(f"/api/world1/imports/{job['job_id']}/analyze")
        resp = client.post(f"/api/world1/imports/{job['job_id']}/approve", json={})
        assert resp.status_code == 409  # failed is terminal, never approvable


class TestSizeBounds:
    def test_per_file_bound_enforced(self):
        with pytest.raises(BoundsError):
            check_file_bounds(MAX_FILE_BYTES + 1, 0)

    def test_aggregate_bound_enforced(self):
        with pytest.raises(BoundsError):
            check_file_bounds(1024, MAX_JOB_AGGREGATE_BYTES + 1)

    def test_spool_begin_rejects_oversized_file(self, tmp_path):
        spool = BoundedSpool(tmp_path / "spool", "j", "w")
        with pytest.raises(BoundsError):
            spool.begin_file("lore/huge.md", MAX_FILE_BYTES + 1)

    def test_zip_counts_compressed_and_uncompressed(self, tmp_path):
        archive = tmp_path / "world.zip"
        payload = b"x" * 4096
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("lore/a.md", payload, compress_type=zipfile.ZIP_DEFLATED)
        specs, total = inspect_zip(archive)
        assert total == len(payload)  # uncompressed accounting
        assert specs[0].uncompressed_size == len(payload)
        assert specs[0].compressed_size < len(payload)  # compressed is smaller

    def test_bounds_are_importer_specific_not_generic(self):
        # Importer cap is 500 MB/file; generic media cap stays 10 MB.
        assert MAX_FILE_BYTES > 10 * 1024 * 1024


class TestZipBomb:
    def test_entry_count(self):
        entries = [ZipEntrySpec(f"lore/{i}.md", 1, 1) for i in range(10_001)]
        with pytest.raises(ZipBombError):
            validate_zip_manifest(entries)

    def test_depth(self):
        with pytest.raises(ZipBombError):
            validate_zip_manifest(
                [ZipEntrySpec("/".join(["a"] * 17) + "/x.md", 1, 1)]
            )

    def test_entry_size(self):
        with pytest.raises(ZipBombError):
            validate_zip_manifest(
                [ZipEntrySpec("lore/big.md", 1, MAX_FILE_BYTES + 1)]
            )

    def test_ratio(self):
        # uncompressed >> compressed with a non-trivial compressed entry
        with pytest.raises(ZipBombError):
            validate_zip_manifest(
                [ZipEntrySpec("lore/bomb.md", 2048, 2048 * 201)]
            )

    def test_real_highly_compressed_zip_rejected(self, tmp_path):
        archive = tmp_path / "bomb.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("lore/bomb.md", b"\x00" * (4 * 1024 * 1024),
                        compress_type=zipfile.ZIP_DEFLATED)
        with pytest.raises(ZipBombError):
            inspect_zip(archive)


class TestResumableIntake:
    def test_stream_writes_durable_chunks_incrementally(self, tmp_path):
        spool = BoundedSpool(tmp_path / "spool", "j", "w")
        spool.begin_file("lore/a.md", 6)
        off1 = spool.write_chunk("lore/a.md", 0, b"ab")
        off2 = spool.write_chunk("lore/a.md", off1, b"cd")
        off3 = spool.write_chunk("lore/a.md", off2, b"ef")
        assert (off1, off2, off3) == (2, 4, 6)
        # no whole-job buffering: durable file holds exactly the streamed bytes
        target = spool.job_dir / "lore" / "a.md"
        assert target.read_bytes() == b"abcdef"

    def test_resume_requires_revalidation(self, tmp_path):
        spool = BoundedSpool(tmp_path / "spool", "j", "w")
        spool.begin_file("lore/a.md", 4)
        spool.write_chunk("lore/a.md", 0, b"abcd")
        # denied without lease
        with pytest.raises(PermissionError):
            spool.resume(ImportJobState.PENDING, leased=False)
        # denied when job is no longer in an intake state
        with pytest.raises(PermissionError):
            spool.resume(ImportJobState.ANALYZING, leased=True)
        # granted only after revalidation (state + lease)
        offsets = spool.resume(ImportJobState.INTAKING, leased=True)
        assert offsets == {"lore/a.md": 4}

    def test_router_resume_offsets(self, tmp_path):
        app, _, _ = _app(tmp_path)
        client = TestClient(app)
        job = _create_job(client)
        _stream(client, job["job_id"], "lore/a.md", b"ab")
        end = _stream(client, job["job_id"], "lore/a.md", b"cd", offset=2)
        assert end == 4


# ---------------------------------------------------------------------------
# Slice 1 — extract_zip_bounded (bounded ZIP expansion)
# ---------------------------------------------------------------------------

class TestExtractZipBounded:
    """RED tests for ``extract_zip_bounded``.

    The function must reuse the existing manifest defenses (entry count, depth,
    per-entry size, compression ratio, path safety) BEFORE writing anything,
    and must stream entries into the destination one-by-one (never the
    unbounded ``ZipFile.extractall``). All violations fail closed with no
    partial extraction.
    """

    def test_extract_rejects_oversized_entry_count(self, tmp_path):
        archive = tmp_path / "too_many.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            for i in range(10_001):
                zf.writestr(f"lore/{i}.md", "x")
        out = tmp_path / "out"
        with pytest.raises(ZipBombError):
            extract_zip_bounded(archive, out)
        # Fail closed: nothing was extracted (destination empty or absent).
        assert not out.exists() or not any(out.rglob("*"))

    def test_extract_rejects_compression_ratio_bomb(self, tmp_path):
        archive = tmp_path / "bomb.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            # 4 MB of nulls compresses to a tiny payload; ratio exceeds 200x.
            zf.writestr("lore/bomb.md", b"\x00" * (4 * 1024 * 1024),
                        compress_type=zipfile.ZIP_DEFLATED)
        out = tmp_path / "out"
        with pytest.raises(ZipBombError):
            extract_zip_bounded(archive, out)
        assert not out.exists() or not any(out.rglob("*"))

    def test_extract_rejects_traversal_path(self, tmp_path):
        archive = tmp_path / "evil.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("../etc/passwd", "pwn")
        out = tmp_path / "out"
        with pytest.raises(UnsafePathError):
            extract_zip_bounded(archive, out)
        assert not out.exists() or not any(out.rglob("*"))

    def test_extract_rejects_absolute_path(self, tmp_path):
        archive = tmp_path / "abs.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("/abs/path.md", "x")
        out = tmp_path / "out"
        with pytest.raises(UnsafePathError):
            extract_zip_bounded(archive, out)
        assert not out.exists() or not any(out.rglob("*"))

    def test_extract_rejects_oversized_entry(self, tmp_path):
        archive = tmp_path / "huge.zip"
        # Write an entry whose declared uncompressed size exceeds 500 MB.
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("lore/huge.md", b"x", compress_type=zipfile.ZIP_STORED)
            info = zf.infolist()[-1]
            info.file_size = MAX_FILE_BYTES + 1
        out = tmp_path / "out"
        with pytest.raises(ZipBombError):
            extract_zip_bounded(archive, out)
        assert not out.exists() or not any(out.rglob("*"))

    def test_extract_writes_files_when_safe(self, tmp_path):
        archive = tmp_path / "world.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("lore/a.md", b"# A\nbody")
            zf.writestr("personajes/b.md", b"# B\nbody")
        out = tmp_path / "out"
        result = extract_zip_bounded(archive, out)
        assert len(result) == 2
        assert isinstance(result[0], SpoolFile)
        assert all(isinstance(sf, SpoolFile) for sf in result)
        # Files are written under the destination and the entries are intact.
        rels = {sf.relative_path for sf in result}
        assert rels == {"lore/a.md", "personajes/b.md"}
        assert (out / "lore" / "a.md").read_bytes() == b"# A\nbody"
        assert (out / "personajes" / "b.md").read_bytes() == b"# B\nbody"

    def test_extract_returns_spool_files_with_sizes(self, tmp_path):
        archive = tmp_path / "sized.zip"
        payload = b"hello world" * 10  # 110 bytes
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("lore/x.md", payload)
        out = tmp_path / "out"
        result = extract_zip_bounded(archive, out)
        assert len(result) == 1
        sf = result[0]
        assert sf.size == len(payload)
        assert sf.relative_path == "lore/x.md"
        assert sf.path == (out / "lore" / "x.md").resolve()
        assert sf.path.is_file()

    def test_extract_streams_per_entry_not_whole_archive(self, tmp_path, monkeypatch):
        """The implementation must call ``read``/``open`` per entry, never
        the unbounded ``ZipFile.extractall``."""
        archive = tmp_path / "safe.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("lore/a.md", b"a")
        out = tmp_path / "out"
        # If the implementation tried to call ``extractall``, this attribute
        # access would still succeed; the test then fails when the patched
        # method is invoked (extractall is forbidden here).
        import zipfile as _zf
        called = {"extractall": 0}
        original = _zf.ZipFile.extractall
        def _guard(self, *args, **kwargs):
            called["extractall"] += 1
            raise AssertionError("extractall must not be used in bounded extraction")
        monkeypatch.setattr(_zf.ZipFile, "extractall", _guard)
        extract_zip_bounded(archive, out)
        assert called["extractall"] == 0
        monkeypatch.setattr(_zf.ZipFile, "extractall", original)
