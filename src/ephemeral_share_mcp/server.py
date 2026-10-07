import os
import asyncio
from typing import List, Optional, Dict, Any
from fastmcp import FastMCP
from .manager import manager
from .web import start_web_server

mcp = FastMCP("ephemeral-share-mcp")

_server_started = False
_server_lock = asyncio.Lock()

async def _ensure_server_running(port: int = 7997):
    global _server_started
    async with _server_lock:
        if not _server_started or manager._server_runner is None:
            await start_web_server(port)
            _server_started = True

@mcp.tool()
async def share_file(
    file_path: str,
    duration_minutes: int = 30,
    message: Optional[str] = None,
    port: int = 7997
) -> Dict[str, Any]:
    """Share a local file ephemerally with a web download link and countdown timer.

    Args:
        file_path: Absolute or relative path to the file.
        duration_minutes: Time-to-live in minutes (default: 30).
        message: Optional brief note/message to display on the page.
        port: HTTP server port (default: 7997).

    Returns:
        Dict with file details, expiry info, and the direct web URL.
    """
    shared = await manager.register_file(file_path, duration_minutes, message)
    await _ensure_server_running(port)

    # Derive public or localhost host URL
    url = f"http://127.0.0.1:{port}/"

    return {
        "status": "active",
        "url": url,
        "download_url": f"http://127.0.0.1:{port}/download/{shared.file_id}/{shared.filename}",
        "file_id": shared.file_id,
        "filename": shared.filename,
        "size": shared.formatted_size,
        "expires_in_minutes": duration_minutes,
        "message": message
    }

@mcp.tool()
async def share_files(
    file_paths: List[str],
    duration_minutes: int = 30,
    message: Optional[str] = None,
    port: int = 7997
) -> Dict[str, Any]:
    """Share multiple files ephemerally on the web page.

    Args:
        file_paths: List of file paths to share.
        duration_minutes: TTL in minutes for each file.
        message: Optional note/message to display on the page.
        port: HTTP port (default: 7997).

    Returns:
        Dict with list of shared files and the web URL.
    """
    shared_list = []
    for fp in file_paths:
        shared = await manager.register_file(fp, duration_minutes, message)
        shared_list.append(shared.to_dict())

    await _ensure_server_running(port)

    return {
        "status": "active",
        "url": f"http://127.0.0.1:{port}/",
        "total_files": len(shared_list),
        "files": shared_list,
        "expires_in_minutes": duration_minutes,
        "message": message
    }

@mcp.tool()
async def list_shared_files() -> Dict[str, Any]:
    """List all currently active shared files, their TTL, and download links."""
    active = await manager.get_active_files()
    server_running = manager._server_runner is not None and len(active) > 0
    return {
        "server_running": server_running,
        "port": manager.port,
        "url": f"http://127.0.0.1:{manager.port}/" if server_running else None,
        "active_files_count": len(active),
        "files": [f.to_dict() for f in active]
    }

@mcp.tool()
async def stop_share(file_id: Optional[str] = None) -> Dict[str, Any]:
    """Stop sharing a specific file, or shut down the entire ephemeral share server.

    Args:
        file_id: Optional specific file_id to revoke. If omitted, stops all shares and shuts down server.
    """
    global _server_started
    if file_id:
        removed = await manager.remove_file(file_id)
        active = await manager.get_active_files()
        if not active and manager._server_runner:
            await manager._server_runner.cleanup()
            manager._server_runner = None
            _server_started = False
        return {"success": removed, "file_id": file_id, "remaining_active": len(active)}

    # Stop all
    await manager.clear_all()
    if manager._server_runner:
        await manager._server_runner.cleanup()
        manager._server_runner = None
        _server_started = False

    return {"success": True, "message": "All shares stopped and server shut down"}

def main():
    mcp.run()

if __name__ == "__main__":
    main()
