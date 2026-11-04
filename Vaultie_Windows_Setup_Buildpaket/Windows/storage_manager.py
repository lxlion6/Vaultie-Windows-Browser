"""Safe local-storage budget checks for Vaultie on Windows.

Only Vaultie's own LocalAppData folder is inspected. Downloads and personal
settings are never deleted silently. Browser temporary folders may be cleaned
when they are not in use. The upper bound is enforced for *new* downloads.
"""
import os
import shutil
from pathlib import Path

GIB = 1_000_000_000
CLEAN_AT = 3_800_000_000
HARD_LIMIT = 5_000_000_000
TEMP_NAMES = ("cache", "Cache", "Code Cache", "GPUCache", "DawnCache",
              "GrShaderCache")
PRESERVE = frozenset(("Downloads", "settings.json", "bookmarks.json",
                      "filterliste.txt"))


def _inside(root: Path, path: Path):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def folder_bytes(root):
    """Count regular files; never traverse symlinks or leave root."""
    root = Path(root).resolve()
    if not root.exists():
        return 0
    total = 0
    for base, dirs, files in os.walk(root, topdown=True, followlinks=False):
        base_path = Path(base)
        dirs[:] = [d for d in dirs
                   if not (base_path / d).is_symlink()
                   and _inside(root, (base_path / d).resolve())]
        for filename in files:
            path = base_path / filename
            if path.is_symlink():
                continue
            try:
                if _inside(root, path.resolve()) and path.is_file():
                    total += path.stat().st_size
            except OSError:
                continue
    return total


def clean_temporary(root):
    """Delete only known temporary cache directories, never user files."""
    root = Path(root).resolve()
    removed = 0
    if not root.is_dir():
        return removed
    for directory in root.iterdir():
        if directory.is_symlink() or not directory.is_dir():
            continue
        if directory.name in PRESERVE:
            continue
        # Restrict cleanup to known cache names, including nested Chromium caches.
        for base, dirs, _ in os.walk(directory, topdown=True, followlinks=False):
            base_path = Path(base)
            for name in list(dirs):
                candidate = base_path / name
                if candidate.is_symlink():
                    dirs.remove(name)
                    continue
                if name in TEMP_NAMES and _inside(root, candidate.resolve()):
                    before = folder_bytes(candidate)
                    try:
                        shutil.rmtree(candidate)
                        removed += before
                        dirs.remove(name)
                    except OSError:
                        pass
    for name in TEMP_NAMES:
        candidate = root / name
        if candidate.is_symlink() or not candidate.is_dir():
            continue
        before = folder_bytes(candidate)
        try:
            shutil.rmtree(candidate)
            removed += before
        except OSError:
            pass
    return removed


class StorageBudget:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def size(self):
        return folder_bytes(self.root)

    def check(self, force=False):
        before = self.size()
        cleaned = clean_temporary(self.root) if force or before >= CLEAN_AT else 0
        after = self.size() if cleaned or force else before
        return before, after, cleaned

    def can_download(self, expected_size):
        _, size, _ = self.check()
        if expected_size is None or expected_size < 0:
            return size < HARD_LIMIT
        return size + expected_size <= HARD_LIMIT
