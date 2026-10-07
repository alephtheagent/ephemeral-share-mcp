# Ephemeral Share MCP (`ephemeral-share-mcp`)

Architecture and implementation plan for a standalone FastMCP server that serves files ephemerally over a sleek, ultra-minimalist web UI.

---

## 1. Core Requirements & Behavior

1. **Ephemeral File Serving**:
   - Tool `share_file(file_path, duration_minutes=30, message=None, port=7997)`
   - Tool `share_files(file_paths, duration_minutes=30, message=None, port=7997)`
   - Tool `list_shared_files()`
   - Tool `stop_share(file_id=None)` (stops specific file or shuts down server if none specified)

2. **Server Lifecycle & Dynamic Port Binding**:
   - Default port: `7997` (configurable per request or env `EPHEMERAL_SHARE_PORT`).
   - If the HTTP server is already running on the port, calling `share_file` adds the new file dynamically with its own independent Time-To-Live (TTL).
   - The web server remains alive as long as at least one shared file is active (`max(expires_at)` across all active files).
   - Once the last file's TTL expires, the HTTP server shuts down automatically and frees the port.

## 3. Web UI Design
- Dark OLED aesthetic (`#000000` / `#0a0a0a`), monospace accents, neon green/amber telemetry highlights.
- Fully responsive mobile & desktop layout.
- **Copy & Labels**: STRICTLY minimal, concise, telegram-style. No wordy/fluffy descriptions.
  - Use `EXPIRY` or `EXPIRES IN` (NOT "Self destruction time / The files will delete automatically").
  - Use `DOWNLOAD` (NOT "Download file to device").
  - Use `SIZE` (NOT "Total file size on disk").
  - Headers: clean and crisp (e.g. `EPHEMERAL SHARE // [ID]`).
- Shows:
  - Custom message / note if provided (e.g. "Firmware binaries v0.2.2 for ESP32-S3").
  - File table / cards: filename, human-readable size, MIME badge, direct download button.
  - Live countdown timer updating client-side every second via JS.
  - Once expired, page displays a clean `LINK EXPIRED // 404` notice.

4. **HTTP Server Stack**:
   - Built with `aiohttp` or `fastapi/uvicorn` (pure async within the FastMCP process).
   - Runs in a background asyncio task inside the MCP server process.
   - Streaming file downloads with chunking (handles large ISOs, tars, audio without loading into RAM).
   - Direct download endpoint: `/download/{file_id}/{filename}`.

5. **Package & Test Structure**:
   - Standard Python project (`pyproject.toml`, `src/ephemeral_share_mcp/`).
   - CLI entrypoint (`python -m ephemeral_share_mcp`).
   - Full pytest test suite verifying:
     - File registration and expiry tracking.
     - Web UI rendering and HTTP download stream.
     - Auto-shutdown when all TTLs expire.
