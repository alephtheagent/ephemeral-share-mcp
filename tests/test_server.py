import os
import time
import pytest
import aiohttp
from aiohttp import web
from ephemeral_share_mcp.manager import ShareManager, SharedFile
from ephemeral_share_mcp.web import create_app

@pytest.fixture
def temp_file(tmp_path):
    f = tmp_path / "test_firmware.bin"
    f.write_bytes(b"\x00\x01\x02\x03\x04" * 1024)  # 5KB
    return str(f)

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

@pytest.mark.asyncio
async def test_manager_expiry(temp_file):
    mgr = ShareManager()
    shared = await mgr.register_file(temp_file, duration_minutes=1)
    # Manually expire
    shared.expires_at = time.time() - 10
    assert shared.is_expired

    active = await mgr.get_active_files()
    assert len(active) == 0

@pytest.mark.asyncio
async def test_web_routes_and_download(temp_file):
    from ephemeral_share_mcp.manager import manager
    from aiohttp.test_utils import TestServer, TestClient
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
        bad_resp = await client.get(f"/download/fakeid/fake.bin")
        assert bad_resp.status == 404
    finally:
        await client.close()
