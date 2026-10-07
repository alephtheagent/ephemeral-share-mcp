import os
import time
import uuid
import asyncio
from typing import Dict, List, Optional
from dataclasses import dataclass

@dataclass
class SharedFile:
    file_id: str
    file_path: str
    filename: str
    size_bytes: int
    created_at: float
    expires_at: float
    message: Optional[str] = None

    @property
    def is_expired(self) -> bool:
        return time.time() >= self.expires_at

    @property
    def remaining_seconds(self) -> int:
        rem = int(self.expires_at - time.time())
        return max(0, rem)

    @property
    def formatted_size(self) -> str:
        size = float(self.size_bytes)
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024.0 or unit == 'TB':
                return f"{size:.1f} {unit}" if unit != 'B' else f"{int(size)} B"
            size /= 1024.0
        return f"{size:.1f} B"

    def to_dict(self) -> dict:
        return {
            "file_id": self.file_id,
            "filename": self.filename,
            "size": self.formatted_size,
            "size_bytes": self.size_bytes,
            "expires_in_seconds": self.remaining_seconds,
            "message": self.message,
            "download_url": f"/download/{self.file_id}/{self.filename}"
        }

class ShareManager:
    def __init__(self):
        self._files: Dict[str, SharedFile] = {}
        self._lock = asyncio.Lock()
        self._server_runner = None
        self._cleanup_task: Optional[asyncio.Task] = None
        self.port: int = 7997

    async def register_file(self, file_path: str, duration_minutes: int = 30, message: Optional[str] = None) -> SharedFile:
        abs_path = os.path.abspath(file_path)
        if not os.path.exists(abs_path) or not os.path.isfile(abs_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        file_id = uuid.uuid4().hex[:8]
        filename = os.path.basename(abs_path)
        size_bytes = os.path.getsize(abs_path)
        now = time.time()
        expires_at = now + (max(1, duration_minutes) * 60)

        shared = SharedFile(
            file_id=file_id,
            file_path=abs_path,
            filename=filename,
            size_bytes=size_bytes,
            created_at=now,
            expires_at=expires_at,
            message=message
        )

        async with self._lock:
            self._files[file_id] = shared
            self._ensure_cleanup_task()

        return shared

    async def get_file(self, file_id: str) -> Optional[SharedFile]:
        async with self._lock:
            item = self._files.get(file_id)
            if item and not item.is_expired:
                return item
            if item and item.is_expired:
                del self._files[file_id]
            return None

    async def get_active_files(self) -> List[SharedFile]:
        async with self._lock:
            now = time.time()
            active = []
            expired_keys = []
            for fid, f in self._files.items():
                if f.expires_at > now:
                    active.append(f)
                else:
                    expired_keys.append(fid)
            for k in expired_keys:
                del self._files[k]
            return active

    async def remove_file(self, file_id: str) -> bool:
        async with self._lock:
            if file_id in self._files:
                del self._files[file_id]
                return True
            return False

    async def clear_all(self):
        async with self._lock:
            self._files.clear()

    def set_server_runner(self, runner, port: int):
        self._server_runner = runner
        self.port = port
        self._ensure_cleanup_task()

    def _ensure_cleanup_task(self):
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def _cleanup_loop(self):
        while True:
            await asyncio.sleep(5)
            active = await self.get_active_files()
            if not active and self._server_runner:
                # All files expired -> shutdown web server
                try:
                    await self._server_runner.cleanup()
                except Exception:
                    pass
                self._server_runner = None
                break

manager = ShareManager()
