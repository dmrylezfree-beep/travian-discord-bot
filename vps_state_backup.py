#!/usr/bin/env python3
"""Create an atomic, local VPS backup of Travian bot state.

Staging only: this script does not modify live bot data or upload to GitHub.
Use a separate, restricted backup destination outside the repository.
"""
import argparse
import json
import os
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT = Path("/var/backups/travian-bots")
ALLOWED = ("data/defence", "data/attacks", "data/snapshots")
SKIP_NAMES = {".env", ".git", "__pycache__", "node_modules", ".venv"}
SKIP_SUFFIXES = {".key", ".pem", ".p12", ".sqlite-journal", ".sqlite-wal", ".sqlite-shm"}


def safe_files(root):
    for folder in ALLOWED:
        base = root / folder
        if not base.is_dir() or base.is_symlink():
            continue
        for path in base.rglob("*"):
            if path.is_symlink() or not path.is_file():
                continue
            rel = path.relative_to(root)
            if any(part in SKIP_NAMES or part.startswith(".") for part in rel.parts):
                continue
            if path.suffix.lower() in SKIP_SUFFIXES:
                continue
            if not path.resolve().is_relative_to(root.resolve()):
                continue
            yield path, rel


def create_backup(destination=DEFAULT_OUTPUT):
    destination = Path(destination).expanduser().resolve()
    if destination == ROOT or ROOT in destination.parents:
        raise ValueError("Backup destination must be outside the repository")
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(destination, 0o700)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    final = destination / f"travian-state-{stamp}-{os.getpid()}.tar.gz"
    fd, temp_name = tempfile.mkstemp(prefix=".travian-", suffix=".tmp", dir=destination)
    os.close(fd)
    temp = Path(temp_name)
    files = list(safe_files(ROOT))
    try:
        with tarfile.open(temp, "w:gz") as archive:
            for path, rel in files:
                archive.add(path, arcname=str(rel), recursive=False)
        os.chmod(temp, 0o600)
        os.replace(temp, final)
    finally:
        temp.unlink(missing_ok=True)
    return {"backup": str(final), "files": len(files), "created_utc": stamp}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(json.dumps(create_backup(args.destination), ensure_ascii=False))
