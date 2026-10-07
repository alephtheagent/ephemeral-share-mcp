# ephemeral-share-mcp

Fast ephemeral web file sharing MCP server with sleek dark cyber UI, live countdown timer, and dynamic multi-file TTL.

---

## Features
- **Ephemeral & Self-destructing**: Serves files over HTTP on a configurable port (`7997` default) with strict time-to-live.
- **Dynamic Multi-file Lifecycle**: Adding new files while the server is alive preserves independent TTLs. The server gracefully terminates once the last file expires.
- **Minimal Cyber OLED UI**: Responsive mobile-first dark interface (#000000) with client-side JS countdown, clean headers, and concise labels (`DOWNLOAD`, `EXPIRY: MM:SS`, `SIZE`).
- **Streaming Transfer**: Chunked async streaming to handle large firmware images, archives, and audio without loading files into memory.

## Tools
- `share_file(file_path, duration_minutes=30, message=None, port=7997)`: Ephemerally share a single file.
- `share_files(file_paths, duration_minutes=30, message=None, port=7997)`: Ephemerally share a batch of files.
- `list_shared_files()`: Inspect active shares and their remaining TTL.
- `stop_share(file_id=None)`: Revoke a specific file or stop all shares immediately.
