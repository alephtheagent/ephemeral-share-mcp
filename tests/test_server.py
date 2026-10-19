import io
import os
import time
import zipfile
import tarfile
import pytest
from aiohttp.test_utils import TestServer, TestClient
from ephemeral_share_mcp.manager import ShareManager, SharedFile, manager, extract_archive
from ephemeral_share_mcp.web import create_app

@pytest.fixture(autouse=True)
async def cleanup_global_manager():
    await manager.clear_all()
    yield
    await manager.clear_all()

@pytest.fixture
def temp_file(tmp_path):
    f = tmp_path / "test_firmware.bin"
    f.write_bytes(b"\x00\x01\x02\x03\x04" * 1024)  # 5KB
    return str(f)

@pytest.fixture
def audio_file(tmp_path):
    f = tmp_path / "track.mp3"
    f.write_bytes(b"MP3DATA" * 500)  # 3500 bytes
    return str(f)

@pytest.fixture
def video_file(tmp_path):
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"MP4DATA" * 600)  # 4200 bytes
    return str(f)

@pytest.fixture
def code_file(tmp_path):
    f = tmp_path / "script.py"
    f.write_text("def hello():\n    print('EPHEMERAL_SHARE_ACTIVE')\n", encoding="utf-8")
    return str(f)

@pytest.fixture
def pdf_file(tmp_path):
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"%PDF-1.4 sample pdf content")
    return str(f)

@pytest.fixture
def sample_zip(tmp_path):
    zip_path = tmp_path / "bundle.zip"
    with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("docs/readme.txt", "This is documentation.")
        zf.writestr("src/main.py", "print('hello from archive')")
        zf.writestr("src/utils/math.py", "def add(a, b): return a + b")
        zf.writestr("license.txt", "MIT License")
    return str(zip_path)

@pytest.fixture
def sample_tar_gz(tmp_path):
    tar_path = tmp_path / "archive.tar.gz"
    with tarfile.open(str(tar_path), "w:gz") as tf:
        data = b"hello from tar.gz"
        ti = tarfile.TarInfo(name="sub/content.txt")
        ti.size = len(data)
        tf.addfile(ti, io.BytesIO(data))
    return str(tar_path)

@pytest.mark.asyncio
async def test_manager_registration_and_ttl(temp_file):
    mgr = ShareManager()
    shared = await mgr.register_file(temp_file, duration_minutes=1, message="Test build")
    assert shared.filename == "test_firmware.bin"
    assert shared.size_bytes == 5120
    assert not shared.is_expired
    assert shared.remaining_seconds > 0

    active = await mgr.get_active_files()
    assert len(active) == 1
    assert active[0].file_id == shared.file_id
    await mgr.clear_all()

@pytest.mark.asyncio
async def test_manager_expiry(temp_file):
    mgr = ShareManager()
    shared = await mgr.register_file(temp_file, duration_minutes=1)
    shared.expires_at = time.time() - 10
    assert shared.is_expired

    active = await mgr.get_active_files()
    assert len(active) == 0
    await mgr.clear_all()

@pytest.mark.asyncio
async def test_web_routes_and_download(temp_file):
    shared = await manager.register_file(temp_file, duration_minutes=10, message="Test v0.2.2")

    app = create_app()
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()

    try:
        # 1. Test Index Page
        resp = await client.get("/")
        assert resp.status == 200
        text = await resp.text()
        assert "test_firmware.bin" in text
        assert "Test v0.2.2" in text
        assert "DOWNLOAD" in text
        assert "EXPIRY:" in text

        # 2. Test Download
        dl_resp = await client.get(f"/download/{shared.file_id}/{shared.filename}")
        assert dl_resp.status == 200
        content = await dl_resp.read()
        assert len(content) == 5120
        assert content == b"\x00\x01\x02\x03\x04" * 1024

        # 3. Test Invalid Download
        bad_resp = await client.get("/download/fakeid/fake.bin")
        assert bad_resp.status == 404
    finally:
        await client.close()

@pytest.mark.asyncio
async def test_audio_stream_and_range_requests(audio_file):
    shared = await manager.register_file(audio_file, duration_minutes=15)
    app = create_app()
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()

    try:
        # Check audio tag in UI
        resp = await client.get("/")
        assert resp.status == 200
        text = await resp.text()
        assert "<audio controls" in text
        assert f"/stream/{shared.file_id}/{shared.filename}" in text

        # Stream full
        s_resp = await client.get(f"/stream/{shared.file_id}/{shared.filename}")
        assert s_resp.status == 200
        assert "audio/" in s_resp.headers.get("Content-Type", "")
        full_data = await s_resp.read()
        assert len(full_data) == 3500

        # Stream with Range header
        range_resp = await client.get(
            f"/stream/{shared.file_id}/{shared.filename}",
            headers={"Range": "bytes=100-199"}
        )
        assert range_resp.status == 206
        assert range_resp.headers.get("Content-Range") == "bytes 100-199/3500"
        part = await range_resp.read()
        assert len(part) == 100
        assert part == full_data[100:200]
    finally:
        await client.close()

@pytest.mark.asyncio
async def test_video_stream_and_range_requests(video_file):
    shared = await manager.register_file(video_file, duration_minutes=15)
    app = create_app()
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()

    try:
        # Check video tag in UI
        resp = await client.get("/")
        assert resp.status == 200
        text = await resp.text()
        assert "<video controls" in text
        assert f"/stream/{shared.file_id}/{shared.filename}" in text

        # Stream with Range header
        range_resp = await client.get(
            f"/stream/{shared.file_id}/{shared.filename}",
            headers={"Range": "bytes=0-499"}
        )
        assert range_resp.status == 206
        assert range_resp.headers.get("Content-Range") == "bytes 0-499/4200"
        part = await range_resp.read()
        assert len(part) == 500
    finally:
        await client.close()

@pytest.mark.asyncio
async def test_text_and_pdf_preview(code_file, pdf_file):
    shared_code = await manager.register_file(code_file, duration_minutes=10)
    shared_pdf = await manager.register_file(pdf_file, duration_minutes=10)

    app = create_app()
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()

    try:
        resp = await client.get("/")
        assert resp.status == 200
        html = await resp.text()

        # Text/code preview block
        assert f"pre-{shared_code.file_id}" in html
        assert "EPHEMERAL_SHARE_ACTIVE" in html
        assert "COLLAPSE" in html

        # PDF embed iframe
        assert f"/stream/{shared_pdf.file_id}/{shared_pdf.filename}" in html
        assert "cyber-pdf" in html
    finally:
        await client.close()

@pytest.mark.asyncio
async def test_archive_unpack_and_tree(sample_zip):
    shared = await manager.register_file(sample_zip, duration_minutes=15)
    assert shared.is_archive is True
    assert shared.temp_dir is not None
    assert os.path.isdir(shared.temp_dir)
    assert os.path.basename(shared.temp_dir).startswith(f"ephem_archive_{shared.file_id}_")

    assert shared.archive_items is not None
    paths = [it["path"] for it in shared.archive_items]
    assert "license.txt" in paths
    assert "src/main.py" in paths
    assert "docs/readme.txt" in paths
    assert any(it["path"] == "src" and it["is_dir"] for it in shared.archive_items)

    app = create_app()
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()

    try:
        resp = await client.get("/")
        assert resp.status == 200
        text = await resp.text()
        assert "ARCHIVE CONTENTS" in text
        assert "src/main.py" in text
        assert "docs/readme.txt" in text
    finally:
        await client.close()

@pytest.mark.asyncio
async def test_archive_subfile_and_subdir_download(sample_zip):
    shared = await manager.register_file(sample_zip, duration_minutes=15)
    app = create_app()
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()

    try:
        # 1. Download subfile
        f_resp = await client.get(f"/download/{shared.file_id}/archive-file/src/main.py")
        assert f_resp.status == 200
        assert f_resp.headers.get("Content-Disposition") == 'attachment; filename="main.py"'
        content = await f_resp.text()
        assert "print('hello from archive')" in content

        # 2. Download subdirectory as zip on the fly
        d_resp = await client.get(f"/download/{shared.file_id}/archive-dir/src")
        assert d_resp.status == 200
        assert d_resp.headers.get("Content-Type") == "application/zip"
        assert d_resp.headers.get("Content-Disposition") == 'attachment; filename="src.zip"'

        zip_bytes = await d_resp.read()
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            namelist = zf.namelist()
            assert "main.py" in namelist
            assert "utils/math.py" in namelist
            assert zf.read("main.py") == b"print('hello from archive')"

        # 3. Path traversal protection on archive-file
        bad_f = await client.get(f"/download/{shared.file_id}/archive-file/..%2F..%2Fetc/passwd")
        assert bad_f.status == 403

        # 4. Path traversal protection on archive-dir
        bad_d = await client.get(f"/download/{shared.file_id}/archive-dir/..%2F..%2Fetc")
        assert bad_d.status == 403

        # 5. Non-existent file in archive
        missing = await client.get(f"/download/{shared.file_id}/archive-file/src/nonexistent.py")
        assert missing.status == 404
    finally:
        await client.close()

@pytest.mark.asyncio
async def test_tar_gz_extraction(sample_tar_gz):
    shared = await manager.register_file(sample_tar_gz, duration_minutes=15)
    assert shared.is_archive is True
    assert shared.temp_dir is not None
    assert os.path.isdir(shared.temp_dir)

    assert shared.archive_items is not None
    paths = [it["path"] for it in shared.archive_items]
    assert "sub/content.txt" in paths

    app = create_app()
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()

    try:
        f_resp = await client.get(f"/download/{shared.file_id}/archive-file/sub/content.txt")
        assert f_resp.status == 200
        content = await f_resp.read()
        assert content == b"hello from tar.gz"
    finally:
        await client.close()

@pytest.mark.asyncio
async def test_zip_slip_prevention(tmp_path):
    bad_zip = tmp_path / "malicious.zip"
    with zipfile.ZipFile(str(bad_zip), "w") as zf:
        zf.writestr("../../slip.txt", "malicious payload")

    mgr = ShareManager()
    with pytest.raises(ValueError, match="Zip slip|Directory traversal"):
        await mgr.register_file(str(bad_zip))

    # Ensure no leftover temp directories for this failed registration
    assert not os.path.exists(tmp_path / "slip.txt")
    await mgr.clear_all()

@pytest.mark.asyncio
async def test_temp_dir_cleanup_on_expiration_and_removal(sample_zip):
    mgr = ShareManager()
    # 1. Removal test
    shared1 = await mgr.register_file(sample_zip, duration_minutes=10)
    td1 = shared1.temp_dir
    assert td1 is not None and os.path.isdir(td1)

    removed = await mgr.remove_file(shared1.file_id)
    assert removed is True
    assert not os.path.exists(td1)

    # 2. Expiration test via get_active_files
    shared2 = await mgr.register_file(sample_zip, duration_minutes=10)
    td2 = shared2.temp_dir
    assert td2 is not None and os.path.isdir(td2)

    shared2.expires_at = time.time() - 5
    active = await mgr.get_active_files()
    assert len(active) == 0
    assert not os.path.exists(td2)

    # 3. Expiration test via get_file
    shared3 = await mgr.register_file(sample_zip, duration_minutes=10)
    td3 = shared3.temp_dir
    assert td3 is not None and os.path.isdir(td3)

    shared3.expires_at = time.time() - 5
    res = await mgr.get_file(shared3.file_id)
    assert res is None
    assert not os.path.exists(td3)

    # 4. clear_all test
    shared4 = await mgr.register_file(sample_zip, duration_minutes=10)
    td4 = shared4.temp_dir
    assert td4 is not None and os.path.isdir(td4)
    await mgr.clear_all()
    assert not os.path.exists(td4)

@pytest.mark.asyncio
async def test_tar_slip_prevention(tmp_path):
    bad_tar = tmp_path / "malicious.tar.gz"
    with tarfile.open(str(bad_tar), "w:gz") as tf:
        data = b"evil"
        ti = tarfile.TarInfo(name="../../evil.txt")
        ti.size = len(data)
        tf.addfile(ti, io.BytesIO(data))

    mgr = ShareManager()
    with pytest.raises(ValueError, match="Tar slip|Directory traversal"):
        await mgr.register_file(str(bad_tar))

    assert not os.path.exists(tmp_path / "evil.txt")
    await mgr.clear_all()

@pytest.mark.asyncio
async def test_text_preview_truncation(tmp_path):
    from ephemeral_share_mcp.web import get_text_preview
    long_file = tmp_path / "large.txt"
    # Write 600 lines
    long_file.write_text("\n".join(f"line {i}" for i in range(600)))
    preview = get_text_preview(str(long_file), max_lines=500)
    assert preview is not None
    assert "line 499" in preview
    assert "line 550" not in preview
    assert "PREVIEW TRUNCATED" in preview

@pytest.mark.asyncio
async def test_mcp_tools(sample_zip, temp_file):
    from ephemeral_share_mcp.server import share_file, list_shared_files, stop_share
    # 1. Share archive via MCP tool
    res = await share_file(sample_zip, duration_minutes=5)
    assert res["status"] == "active"
    assert res["is_archive"] is True
    assert "archive_items" in res
    fid = res["file_id"]

    # 2. List shared files
    listing = await list_shared_files()
    assert listing["active_files_count"] >= 1
    assert any(f["file_id"] == fid and f["is_archive"] for f in listing["files"])

    # 3. Stop specific share
    stop_res = await stop_share(fid)
    assert stop_res["success"] is True

    # 4. Stop all shares
    await share_file(temp_file, duration_minutes=5)
    stop_all = await stop_share()
    assert stop_all["success"] is True

