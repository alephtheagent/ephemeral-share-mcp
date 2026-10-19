import os
import html
import tempfile
import zipfile
from urllib.parse import quote
from typing import Optional, List, Dict, Any

from aiohttp import web
from .manager import manager, SharedFile

AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".opus"}
VIDEO_EXTENSIONS = {".mp4", ".webm", ".mkv", ".mov", ".ogv"}
TEXT_EXTENSIONS = {
    ".txt", ".md", ".py", ".c", ".h", ".cpp", ".hpp", ".cc", ".cxx",
    ".rs", ".go", ".js", ".jsx", ".ts", ".tsx", ".json", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".conf", ".csv", ".tsv", ".log", ".sh",
    ".bash", ".zsh", ".fish", ".env", ".xml", ".html", ".htm", ".css",
    ".scss", ".sass", ".less", ".sql", ".r", ".java", ".kt", ".kts",
    ".swift", ".php", ".rb", ".pl", ".lua", ".vim", ".dockerfile",
    ".makefile", ".cmake", ".diff", ".patch"
}
TEXT_BASENAMES = {
    "dockerfile", "makefile", "license", "readme", ".gitignore",
    ".env", ".bashrc", ".profile"
}

def is_audio_file(filename: str) -> bool:
    return os.path.splitext(filename.lower())[1] in AUDIO_EXTENSIONS

def is_video_file(filename: str) -> bool:
    return os.path.splitext(filename.lower())[1] in VIDEO_EXTENSIONS

def is_pdf_file(filename: str) -> bool:
    return filename.lower().endswith(".pdf")

def is_text_file(filename: str) -> bool:
    base = os.path.basename(filename).lower()
    if base in TEXT_BASENAMES:
        return True
    ext = os.path.splitext(base)[1]
    return ext in TEXT_EXTENSIONS

def get_text_preview(file_path: str, max_bytes: int = 65536, max_lines: int = 500) -> Optional[str]:
    try:
        with open(file_path, "rb") as f:
            raw_bytes = f.read(max_bytes)
        try:
            text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = raw_bytes.decode("latin-1")
            except Exception:
                return None
        lines = text.splitlines()
        truncated = False
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            truncated = True
        preview_text = "\n".join(lines)
        if truncated or (len(raw_bytes) >= max_bytes and os.path.getsize(file_path) > max_bytes):
            preview_text += "\n\n... [PREVIEW TRUNCATED // LIMIT REACHED] ..."
        return preview_text
    except Exception:
        return None

def render_archive_tree(file_id: str, items: List[Dict[str, Any]]) -> str:
    if not items:
        return '<div class="archive-row"><span class="item-name" style="color:var(--dim)">[EMPTY ARCHIVE]</span></div>'

    root: Dict[str, Any] = {"children": {}, "is_dir": True, "path": "", "name": "", "formatted_size": ""}
    for it in items:
        clean_p = it["path"].replace("\\", "/").strip("/")
        if not clean_p:
            continue
        parts = clean_p.split("/")
        curr = root
        accum = []
        for i, part in enumerate(parts):
            accum.append(part)
            curr_path = "/".join(accum)
            is_last = (i == len(parts) - 1)
            if part not in curr["children"]:
                curr["children"][part] = {
                    "name": part,
                    "path": curr_path,
                    "is_dir": it["is_dir"] if is_last else True,
                    "formatted_size": it.get("formatted_size", "DIR" if it["is_dir"] else "") if is_last else "DIR",
                    "children": {},
                }
            else:
                if is_last:
                    curr["children"][part]["is_dir"] = it["is_dir"]
                    curr["children"][part]["formatted_size"] = it.get("formatted_size", "")
            curr = curr["children"][part]

    def render_nodes(children_dict: Dict[str, Any]) -> str:
        sorted_nodes = sorted(
            children_dict.values(),
            key=lambda x: (not x["is_dir"], x["name"].lower())
        )
        html_out = []
        for node in sorted_nodes:
            name_esc = html.escape(node["name"])
            quoted_path = quote(node["path"])
            if node["is_dir"]:
                dl_url = f"/download/{file_id}/archive-dir/{quoted_path}"
                inner_html = render_nodes(node["children"])
                html_out.append(f"""
                <details class="archive-dir" open>
                  <summary class="archive-row dir-summary">
                    <div class="item-main">
                      <span class="dir-caret">▶</span>
                      <span class="item-name dir-name">{name_esc}/</span>
                    </div>
                    <div class="item-meta">
                      <span class="item-size">DIR</span>
                      <a class="btn-item-dl" onclick="event.stopPropagation();" href="{dl_url}">ZIP</a>
                    </div>
                  </summary>
                  <div class="archive-children">
                    {inner_html}
                  </div>
                </details>
                """)
            else:
                dl_url = f"/download/{file_id}/archive-file/{quoted_path}"
                html_out.append(f"""
                <div class="archive-row file-row">
                  <div class="item-main">
                    <span class="file-bullet">▪</span>
                    <a class="item-name file-name" href="{dl_url}" title="Download {name_esc}">{name_esc}</a>
                  </div>
                  <div class="item-meta">
                    <span class="item-size">{node['formatted_size']}</span>
                    <a class="btn-item-dl" href="{dl_url}">FILE</a>
                  </div>
                </div>
                """)
        return "".join(html_out)

    return render_nodes(root["children"])

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>EPHEMERAL SHARE</title>
  <style>
    :root {
      --bg: #000000;
      --card: #080808;
      --border: #1a1a1a;
      --fg: #e0e0e0;
      --dim: #666666;
      --accent: #00ff66;
      --warn: #ffaa00;
      --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "JetBrains Mono", monospace;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: var(--bg);
      color: var(--fg);
      font-family: var(--font);
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 16px;
      -webkit-font-smoothing: antialiased;
    }
    .container {
      width: 100%;
      max-width: 680px;
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 4px;
      padding: 20px;
    }
    .header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-bottom: 1px solid var(--border);
      padding-bottom: 12px;
      margin-bottom: 16px;
      font-size: 11px;
      letter-spacing: 1px;
      color: var(--dim);
    }
    .status-badge {
      color: var(--accent);
      font-weight: 600;
    }
    .msg-box {
      background: #0d0d0d;
      border-left: 2px solid var(--accent);
      padding: 10px 12px;
      font-size: 13px;
      margin-bottom: 16px;
      line-height: 1.4;
      word-break: break-word;
    }
    .file-card {
      border: 1px solid var(--border);
      padding: 14px;
      margin-bottom: 14px;
      background: #040404;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .file-name {
      font-size: 14px;
      font-weight: 600;
      word-break: break-all;
      color: #fff;
      text-decoration: none;
      transition: color 0.15s;
    }
    a.file-name:hover {
      color: var(--accent);
      text-decoration: underline;
    }
    .file-meta {
      display: flex;
      justify-content: space-between;
      font-size: 11px;
      color: var(--dim);
    }
    .expiry {
      color: var(--warn);
      font-weight: 600;
      font-family: monospace;
    }
    .btn-download {
      display: block;
      width: 100%;
      text-align: center;
      background: #ffffff;
      color: #000000;
      text-decoration: none;
      padding: 10px;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 1px;
      border-radius: 2px;
      transition: opacity 0.15s;
    }
    .btn-download:hover { opacity: 0.85; }
    .btn-download:active { opacity: 0.7; }
    .media-block {
      width: 100%;
      margin: 4px 0;
    }
    .cyber-audio {
      width: 100%;
      height: 38px;
      accent-color: var(--accent);
      border-radius: 2px;
      outline: none;
    }
    .cyber-video {
      width: 100%;
      max-height: 360px;
      background: #000;
      border: 1px solid var(--border);
      border-radius: 2px;
      display: block;
    }
    .cyber-pdf {
      width: 100%;
      height: 380px;
      background: #0c0c0c;
      border: 1px solid var(--border);
      border-radius: 2px;
      display: block;
    }
    .preview-box {
      border: 1px solid var(--border);
      background: #000000;
      border-radius: 2px;
      overflow: hidden;
    }
    .preview-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 6px 10px;
      background: #0d0d0d;
      border-bottom: 1px solid var(--border);
      font-size: 10px;
      letter-spacing: 1px;
      color: var(--dim);
    }
    .btn-toggle {
      background: #111111;
      border: 1px solid var(--border);
      color: var(--accent);
      font-family: var(--font);
      font-size: 9px;
      padding: 3px 8px;
      cursor: pointer;
      border-radius: 2px;
      letter-spacing: 0.5px;
    }
    .btn-toggle:hover {
      border-color: var(--accent);
    }
    .preview-code {
      padding: 10px;
      margin: 0;
      max-height: 280px;
      overflow: auto;
      font-family: "JetBrains Mono", Consolas, Monaco, monospace;
      font-size: 11px;
      line-height: 1.45;
      color: #38ef7d;
      white-space: pre-wrap;
      word-break: break-all;
    }
    .archive-box {
      border: 1px solid var(--border);
      background: #000000;
      border-radius: 2px;
      overflow: hidden;
    }
    .archive-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 6px 10px;
      background: #0d0d0d;
      border-bottom: 1px solid var(--border);
      font-size: 10px;
      letter-spacing: 1px;
      color: var(--dim);
    }
    .archive-list {
      max-height: 280px;
      overflow-y: auto;
    }
    .archive-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 6px 10px;
      border-bottom: 1px solid #111;
      font-size: 11px;
    }
    .archive-row:last-child {
      border-bottom: none;
    }
    .archive-row:hover {
      background: #0a0a0a;
    }
    .item-main {
      display: flex;
      align-items: center;
      gap: 6px;
      min-width: 0;
      flex: 1;
      margin-right: 12px;
    }
    .dir-caret {
      display: inline-block;
      font-size: 8px;
      color: var(--accent);
      transition: transform 0.15s ease;
      width: 12px;
      text-align: center;
      flex-shrink: 0;
      user-select: none;
    }
    details.archive-dir[open] > summary .dir-caret {
      transform: rotate(90deg);
    }
    .file-bullet {
      display: inline-block;
      font-size: 8px;
      color: var(--dim);
      width: 12px;
      text-align: center;
      flex-shrink: 0;
      user-select: none;
    }
    details.archive-dir > summary {
      list-style: none;
      cursor: pointer;
      user-select: none;
    }
    details.archive-dir > summary::-webkit-details-marker {
      display: none;
    }
    details.archive-dir > summary::marker {
      display: none;
      content: "";
    }
    .archive-children {
      margin-left: 12px;
      padding-left: 4px;
      border-left: 1px dashed #222222;
    }
    .item-name {
      font-family: "JetBrains Mono", monospace;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .item-name.dir-name {
      color: var(--accent);
      font-weight: 600;
    }
    .item-name.file-name {
      color: #cccccc;
      text-decoration: none;
      transition: color 0.15s;
    }
    .item-name.file-name:hover {
      color: var(--accent);
      text-decoration: underline;
    }
    .item-meta {
      display: flex;
      align-items: center;
      gap: 10px;
      flex-shrink: 0;
    }
    .item-size {
      font-size: 10px;
      color: var(--dim);
      font-family: monospace;
    }
    .btn-item-dl {
      background: #111111;
      border: 1px solid var(--border);
      color: var(--accent);
      text-decoration: none;
      font-size: 9px;
      font-weight: 700;
      padding: 3px 8px;
      border-radius: 2px;
      letter-spacing: 0.5px;
      transition: all 0.15s;
    }
    .btn-item-dl:hover {
      background: var(--accent);
      color: #000000;
    }
    .empty-state {
      text-align: center;
      padding: 30px 10px;
      color: var(--dim);
      font-size: 12px;
      letter-spacing: 1px;
    }
    .footer {
      margin-top: 16px;
      text-align: center;
      font-size: 10px;
      color: #333333;
      letter-spacing: 1px;
    }
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <span>EPHEMERAL SHARE // GATEWAY</span>
      <span class="status-badge" id="lbl-status">ONLINE</span>
    </div>

    <!--MSG_PLACEHOLDER-->

    <div id="file-list">
      <!--FILES_PLACEHOLDER-->
    </div>

    <div class="footer">
      ALEPH // AUTONOMOUS RUNTIME
    </div>
  </div>

  <script>
    function updateTimers() {
      const nodes = document.querySelectorAll('[data-expires]');
      let activeCount = 0;
      const now = Math.floor(Date.now() / 1000);

      nodes.forEach(el => {
        const exp = parseInt(el.getAttribute('data-expires'));
        const diff = exp - now;
        if (diff <= 0) {
          el.innerText = 'EXPIRED';
          const card = el.closest('.file-card');
          if (card) {
            const btn = card.querySelector('.btn-download');
            if (btn) {
              btn.style.display = 'none';
              const notice = document.createElement('div');
              notice.style.fontSize = '11px';
              notice.style.color = '#ff3333';
              notice.style.textAlign = 'center';
              notice.style.padding = '8px 0';
              notice.innerText = 'EXPIRED // 404';
              btn.parentNode.replaceChild(notice, btn);
            }
          }
        } else {
          activeCount++;
          const m = Math.floor(diff / 60);
          const s = diff % 60;
          el.innerText = (m < 10 ? '0' : '') + m + ':' + (s < 10 ? '0' : '') + s;
        }
      });

      if (nodes.length > 0 && activeCount === 0) {
        document.getElementById('lbl-status').innerText = 'EXPIRED';
        document.getElementById('lbl-status').style.color = '#ff3333';
      }
    }

    function togglePreview(id) {
      const pre = document.getElementById('pre-' + id);
      const btn = document.getElementById('btn-toggle-' + id);
      if (!pre || !btn) return;
      if (pre.style.display === 'none') {
        pre.style.display = 'block';
        btn.innerText = 'COLLAPSE';
      } else {
        pre.style.display = 'none';
        btn.innerText = 'EXPAND';
      }
    }

    function toggleArchiveDirs(id) {
      const box = document.getElementById('archive-box-' + id);
      const btn = document.getElementById('btn-dirs-' + id);
      if (!box || !btn) return;
      const dirs = box.querySelectorAll('details.archive-dir');
      const shouldOpen = btn.innerText === 'EXPAND ALL';
      dirs.forEach(d => {
        d.open = shouldOpen;
      });
      btn.innerText = shouldOpen ? 'COLLAPSE ALL' : 'EXPAND ALL';
    }

    setInterval(updateTimers, 1000);
    updateTimers();
  </script>
</body>
</html>
"""

async def index_handler(request: web.Request) -> web.Response:
    files = await manager.get_active_files()
    if not files:
        html_page = HTML_TEMPLATE.replace("<!--MSG_PLACEHOLDER-->", "")
        html_page = html_page.replace("<!--FILES_PLACEHOLDER-->", "<div class='empty-state'>NO ACTIVE SHARES // EXPIRED</div>")
        return web.Response(text=html_page, content_type="text/html")

    msg_html = ""
    for f in files:
        if f.message:
            msg_html = f"<div class='msg-box'>{html.escape(f.message)}</div>"
            break

    cards = []
    for f in files:
        preview_block = ""
        lower_name = f.filename.lower()

        if f.is_archive and f.archive_items is not None:
            has_dirs = any(it.get("is_dir") for it in f.archive_items)
            toggle_btn = (
                f'<button type="button" class="btn-toggle" onclick="toggleArchiveDirs(\'{f.file_id}\')" id="btn-dirs-{f.file_id}">COLLAPSE ALL</button>'
                if has_dirs else ""
            )
            tree_html = render_archive_tree(f.file_id, f.archive_items)
            preview_block = f"""
            <div class="archive-box" id="archive-box-{f.file_id}">
              <div class="archive-header">
                <span>ARCHIVE CONTENTS // {len(f.archive_items)} ITEMS</span>
                {toggle_btn}
              </div>
              <div class="archive-list">
                {tree_html}
              </div>
            </div>
            """
        elif is_audio_file(lower_name):
            preview_block = f"""
            <div class="media-block">
              <audio controls preload="metadata" class="cyber-audio" src="/stream/{f.file_id}/{quote(f.filename)}"></audio>
            </div>
            """
        elif is_video_file(lower_name):
            preview_block = f"""
            <div class="media-block">
              <video controls preload="metadata" class="cyber-video" src="/stream/{f.file_id}/{quote(f.filename)}"></video>
            </div>
            """
        elif is_pdf_file(lower_name):
            preview_block = f"""
            <div class="media-block">
              <iframe class="cyber-pdf" src="/stream/{f.file_id}/{quote(f.filename)}"></iframe>
            </div>
            """
        elif is_text_file(lower_name):
            content = get_text_preview(f.file_path)
            if content is not None:
                escaped = html.escape(content)
                preview_block = f"""
                <div class="preview-box">
                  <div class="preview-header">
                    <span>CODE // TEXT PREVIEW</span>
                    <button type="button" class="btn-toggle" onclick="togglePreview('{f.file_id}')" id="btn-toggle-{f.file_id}">COLLAPSE</button>
                  </div>
                  <pre id="pre-{f.file_id}" class="preview-code"><code>{escaped}</code></pre>
                </div>
                """

        card = f"""
        <div class="file-card">
          <a class="file-name" href="/download/{f.file_id}/{quote(f.filename)}" title="Download {html.escape(f.filename)}">{html.escape(f.filename)}</a>
          <div class="file-meta">
            <span>SIZE: {f.formatted_size}</span>
            <span>EXPIRY: <span class="expiry" data-expires="{int(f.expires_at)}">{f.remaining_seconds // 60:02d}:{f.remaining_seconds % 60:02d}</span></span>
          </div>
          {preview_block}
          <a class="btn-download" href="/download/{f.file_id}/{quote(f.filename)}">DOWNLOAD</a>
        </div>
        """
        cards.append(card)

    html_page = HTML_TEMPLATE.replace("<!--MSG_PLACEHOLDER-->", msg_html)
    html_page = html_page.replace("<!--FILES_PLACEHOLDER-->", "".join(cards))
    return web.Response(text=html_page, content_type="text/html")

async def download_handler(request: web.Request) -> web.StreamResponse:
    file_id = request.match_info.get("file_id")
    if not file_id:
        return web.Response(status=404, text="Link expired or file not found")
    shared_file = await manager.get_file(file_id)

    if not shared_file:
        return web.Response(status=404, text="Link expired or file not found")

    if not os.path.exists(shared_file.file_path):
        return web.Response(status=404, text="Underlying file removed")

    return web.FileResponse(
        shared_file.file_path,
        headers={
            "Content-Disposition": f'attachment; filename="{shared_file.filename}"'
        }
    )

async def stream_handler(request: web.Request) -> web.StreamResponse:
    file_id = request.match_info.get("file_id")
    if not file_id:
        return web.Response(status=404, text="Link expired or file not found")
    shared_file = await manager.get_file(file_id)

    if not shared_file:
        return web.Response(status=404, text="Link expired or file not found")

    if not os.path.exists(shared_file.file_path):
        return web.Response(status=404, text="Underlying file removed")

    return web.FileResponse(
        shared_file.file_path,
        headers={
            "Content-Disposition": f'inline; filename="{shared_file.filename}"'
        }
    )

async def archive_file_download_handler(request: web.Request) -> web.StreamResponse:
    file_id = request.match_info.get("file_id")
    if not file_id:
        return web.Response(status=404, text="Link expired or file not found")
    subpath = request.match_info.get("subpath", "").lstrip("/\\")
    shared_file = await manager.get_file(file_id)

    if not shared_file:
        return web.Response(status=404, text="Link expired or file not found")

    if not shared_file.is_archive or not shared_file.temp_dir:
        return web.Response(status=404, text="Not an active archive share")

    base_dir = os.path.realpath(shared_file.temp_dir)
    target_path = os.path.realpath(os.path.join(base_dir, subpath))

    try:
        common = os.path.commonpath([base_dir, target_path])
        if common != base_dir:
            return web.Response(status=403, text="Forbidden path traversal")
    except ValueError:
        return web.Response(status=403, text="Forbidden path traversal")

    if not os.path.exists(target_path) or not os.path.isfile(target_path):
        return web.Response(status=404, text="File not found in archive")

    item_filename = os.path.basename(target_path)
    return web.FileResponse(
        target_path,
        headers={
            "Content-Disposition": f'attachment; filename="{item_filename}"'
        }
    )

async def archive_dir_download_handler(request: web.Request) -> web.StreamResponse:
    file_id = request.match_info.get("file_id")
    if not file_id:
        return web.Response(status=404, text="Link expired or file not found")
    subpath = request.match_info.get("subpath", "")
    if subpath:
        subpath = subpath.lstrip("/\\")
    shared_file = await manager.get_file(file_id)

    if not shared_file:
        return web.Response(status=404, text="Link expired or file not found")

    if not shared_file.is_archive or not shared_file.temp_dir:
        return web.Response(status=404, text="Not an active archive share")

    base_dir = os.path.realpath(shared_file.temp_dir)
    target_path = os.path.realpath(os.path.join(base_dir, subpath)) if subpath else base_dir

    try:
        common = os.path.commonpath([base_dir, target_path])
        if common != base_dir:
            return web.Response(status=403, text="Forbidden path traversal")
    except ValueError:
        return web.Response(status=403, text="Forbidden path traversal")

    if not os.path.exists(target_path) or not os.path.isdir(target_path):
        return web.Response(status=404, text="Directory not found in archive")

    if subpath:
        dir_name = os.path.basename(target_path) or "archive"
    else:
        dir_name = os.path.splitext(shared_file.filename)[0] or "archive"

    zip_filename = f"{dir_name}.zip"

    tmp_zip = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    tmp_zip.close()
    try:
        with zipfile.ZipFile(tmp_zip.name, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(target_path):
                for file in files:
                    full_p = os.path.join(root, file)
                    rel_p = os.path.relpath(full_p, target_path)
                    zf.write(full_p, arcname=rel_p)

        file_size = os.path.getsize(tmp_zip.name)
        resp = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "application/zip",
                "Content-Disposition": f'attachment; filename="{zip_filename}"',
                "Content-Length": str(file_size),
            }
        )
        await resp.prepare(request)
        with open(tmp_zip.name, "rb") as f:
            while chunk := f.read(64 * 1024):
                await resp.write(chunk)
        await resp.write_eof()
        return resp
    finally:
        if os.path.exists(tmp_zip.name):
            try:
                os.unlink(tmp_zip.name)
            except OSError:
                pass

def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", index_handler)
    app.router.add_get("/download/{file_id}/{filename}", download_handler)
    app.router.add_get("/stream/{file_id}/{filename}", stream_handler)
    app.router.add_get("/download/{file_id}/archive-file/{subpath:.*}", archive_file_download_handler)
    app.router.add_get("/download/{file_id}/archive-dir/{subpath:.*}", archive_dir_download_handler)
    app.router.add_get("/download/{file_id}/archive-dir", archive_dir_download_handler)
    return app

async def start_web_server(port: int = 7997) -> web.AppRunner:
    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    manager.set_server_runner(runner, port)
    return runner
