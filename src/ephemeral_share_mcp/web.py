import os
import aiohttp
from aiohttp import web
from typing import Optional
from .manager import manager, SharedFile

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
      max-width: 480px;
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
      margin-bottom: 12px;
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

    setInterval(updateTimers, 1000);
    updateTimers();
  </script>
</body>
</html>
"""

async def index_handler(request: web.Request) -> web.Response:
    files = await manager.get_active_files()
    if not files:
        html = HTML_TEMPLATE.replace("<!--MSG_PLACEHOLDER-->", "")
        html = html.replace("<!--FILES_PLACEHOLDER-->", "<div class='empty-state'>NO ACTIVE SHARES // EXPIRED</div>")
        return web.Response(text=html, content_type="text/html")

    msg_html = ""
    # Use first file's message if any
    for f in files:
        if f.message:
            msg_html = f"<div class='msg-box'>{f.message}</div>"
            break

    cards = []
    for f in files:
        card = f"""
        <div class="file-card">
          <div class="file-name">{f.filename}</div>
          <div class="file-meta">
            <span>SIZE: {f.formatted_size}</span>
            <span>EXPIRY: <span class="expiry" data-expires="{int(f.expires_at)}">{f.remaining_seconds // 60:02d}:{f.remaining_seconds % 60:02d}</span></span>
          </div>
          <a class="btn-download" href="/download/{f.file_id}/{f.filename}">DOWNLOAD</a>
        </div>
        """
        cards.append(card)

    html = HTML_TEMPLATE.replace("<!--MSG_PLACEHOLDER-->", msg_html)
    html = html.replace("<!--FILES_PLACEHOLDER-->", "".join(cards))
    return web.Response(text=html, content_type="text/html")

async def download_handler(request: web.Request) -> web.StreamResponse:
    file_id = request.match_info.get("file_id")
    shared_file = await manager.get_file(file_id)

    if not shared_file:
        return web.Response(status=404, text="Link expired or file not found")

    if not os.path.exists(shared_file.file_path):
        return web.Response(status=404, text="Underlying file removed")

    resp = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "application/octet-stream",
            "Content-Disposition": f'attachment; filename="{shared_file.filename}"',
            "Content-Length": str(shared_file.size_bytes),
        }
    )
    await resp.prepare(request)

    # Chunked streaming to prevent high RAM usage
    chunk_size = 64 * 1024
    with open(shared_file.file_path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            await resp.write(chunk)

    await resp.write_eof()
    return resp

def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", index_handler)
    app.router.add_get("/download/{file_id}/{filename}", download_handler)
    return app

async def start_web_server(port: int = 7997) -> web.AppRunner:
    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    manager.set_server_runner(runner, port)
    return runner
