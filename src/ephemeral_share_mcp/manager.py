import os
import time
import uuid
import asyncio
import shutil
import tempfile
import zipfile
import tarfile
import stat
import atexit
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

def format_size(size_bytes: int) -> str:
    size = float(size_bytes)
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0 or unit == 'TB':
            return f"{size:.1f} {unit}" if unit != 'B' else f"{int(size)} B"
        size /= 1024.0
    return f"{size:.1f} B"

ARCHIVE_EXTENSIONS = (
    ".zip",
    ".tar",
    ".tar.gz",
    ".tgz",
    ".tar.bz2",
    ".tbz2",
    ".tar.xz",
    ".txz",
)

def is_archive_file(filename: str) -> bool:
    lower = filename.lower()
    return any(lower.endswith(ext) for ext in ARCHIVE_EXTENSIONS)

def extract_archive(file_path: str, dest_dir: str) -> List[Dict[str, Any]]:
    abs_file = os.path.abspath(file_path)
    abs_dest = os.path.abspath(dest_dir)
    dest_real = os.path.realpath(abs_dest)

    if zipfile.is_zipfile(abs_file) or abs_file.lower().endswith(".zip"):
        with zipfile.ZipFile(abs_file, "r") as zf:
            for member in zf.infolist():
                clean_name = os.path.normpath(member.filename.replace("\\", "/").lstrip("/"))
                if clean_name in (".", ""):
                    continue
                if clean_name.startswith("..") or "/../" in clean_name:
                    raise ValueError(f"Directory traversal detected in archive: {member.filename}")

                target_path = os.path.realpath(os.path.join(dest_real, clean_name))
                if not (target_path == dest_real or target_path.startswith(dest_real + os.sep)):
                    raise ValueError(f"Zip slip detected: {member.filename}")
                mode = member.external_attr >> 16
                if stat.S_ISLNK(mode):
                    # Skip symlinks to prevent symlink-based traversal
                    continue

                if member.is_dir():
                    os.makedirs(target_path, exist_ok=True)
                else:
                    os.makedirs(os.path.dirname(target_path), exist_ok=True)
                    with zf.open(member) as src, open(target_path, "wb") as dst:
                        shutil.copyfileobj(src, dst)

    elif tarfile.is_tarfile(abs_file) or any(abs_file.lower().endswith(ext) for ext in ARCHIVE_EXTENSIONS):
        with tarfile.open(abs_file, "r:*") as tf:
            for member in tf.getmembers():
                if member.issym() or member.islnk():
                    # Skip symlinks/hardlinks
                    continue
                clean_name = os.path.normpath(member.name.replace("\\", "/").lstrip("/"))
                if clean_name in (".", ""):
                    continue
                if clean_name.startswith("..") or "/../" in clean_name:
                    raise ValueError(f"Directory traversal detected in archive: {member.name}")

                target_path = os.path.realpath(os.path.join(dest_real, clean_name))
                if not (target_path == dest_real or target_path.startswith(dest_real + os.sep)):
                    raise ValueError(f"Tar slip detected: {member.name}")
                if member.isdir():
                    os.makedirs(target_path, exist_ok=True)
                elif member.isreg():
                    os.makedirs(os.path.dirname(target_path), exist_ok=True)
                    f_obj = tf.extractfile(member)
                    if f_obj is not None:
                        with f_obj as src, open(target_path, "wb") as dst:
                            shutil.copyfileobj(src, dst)
    else:
        raise ValueError(f"Unsupported archive format: {file_path}")

    # Collect list of items
    items: List[Dict[str, Any]] = []
    for root, dirs, files in os.walk(dest_real):
        dirs.sort()
        files.sort()
        for d in dirs:
            full_p = os.path.join(root, d)
            rel_p = os.path.relpath(full_p, dest_real).replace("\\", "/")
            items.append({
                "path": rel_p,
                "size_bytes": 0,
                "formatted_size": "DIR",
                "is_dir": True,
            })
        for f in files:
            full_p = os.path.join(root, f)
            rel_p = os.path.relpath(full_p, dest_real).replace("\\", "/")
            sz = os.path.getsize(full_p)
            items.append({
                "path": rel_p,
                "size_bytes": sz,
                "formatted_size": format_size(sz),
                "is_dir": False,
            })

    items.sort(key=lambda x: (not x["is_dir"], x["path"].lower()))
    return items

@dataclass
class SharedFile:
    file_id: str
    file_path: str
    filename: str
    size_bytes: int
    created_at: float
    expires_at: float
    message: Optional[str] = None
    is_archive: bool = False
    temp_dir: Optional[str] = None
    archive_items: Optional[List[Dict[str, Any]]] = None

    @property
    def is_expired(self) -> bool:
        return time.time() >= self.expires_at

    @property
    def remaining_seconds(self) -> int:
        rem = int(self.expires_at - time.time())
        return max(0, rem)

    @property
    def formatted_size(self) -> str:
        return format_size(self.size_bytes)

    def cleanup(self):
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        self.temp_dir = None

    def __del__(self):
        self.cleanup()

    def to_dict(self) -> dict:
        d = {
            "file_id": self.file_id,
            "filename": self.filename,
            "size": self.formatted_size,
            "size_bytes": self.size_bytes,
            "expires_in_seconds": self.remaining_seconds,
            "message": self.message,
            "download_url": f"/download/{self.file_id}/{self.filename}",
            "is_archive": self.is_archive,
        }
        if self.is_archive and self.archive_items is not None:
            d["archive_items"] = self.archive_items
        return d

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

        if is_archive_file(filename):
            temp_dir = tempfile.mkdtemp(prefix=f"ephem_archive_{file_id}_")
            try:
                items = extract_archive(abs_path, temp_dir)
                shared.is_archive = True
                shared.temp_dir = temp_dir
                shared.archive_items = items
            except Exception:
                shutil.rmtree(temp_dir, ignore_errors=True)
                raise

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
                item.cleanup()
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
                self._files[k].cleanup()
                del self._files[k]
            return active

    async def remove_file(self, file_id: str) -> bool:
        async with self._lock:
            if file_id in self._files:
                f = self._files.pop(file_id)
                f.cleanup()
                return True
            return False

    async def clear_all(self):
        async with self._lock:
            for f in self._files.values():
                f.cleanup()
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

def _exit_cleanup():
    for f in list(manager._files.values()):
        f.cleanup()

atexit.register(_exit_cleanup)
