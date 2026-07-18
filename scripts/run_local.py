"""
Convenience launcher to run backend (FastAPI) and frontend (Next.js) together.

Usage:
    python scripts/run_local.py

This script:
1) Loads .env so API keys are available.
2) Starts uvicorn on port 8000 and Next.js on port 3000.
3) Gracefully stops both on Ctrl+C.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import zipfile
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent


def _restore_packaged_index() -> None:
    """Restore the versioned index for first-run local development."""

    index_database = PROJECT_ROOT / "data" / "indexes" / "chroma" / "chroma.sqlite3"
    if index_database.is_file():
        return

    archive = PROJECT_ROOT / "chroma_index.zip"
    if not archive.is_file():
        raise FileNotFoundError(
            "No local Chroma index was found. Build one with "
            "`python scripts/build_index.py --all --fresh`."
        )

    destination = (PROJECT_ROOT / "data" / "indexes").resolve()
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            target = (destination / member.filename).resolve()
            if not target.is_relative_to(destination):
                raise ValueError(f"Unsafe path in packaged index: {member.filename}")
        bundle.extractall(destination)

    if not index_database.is_file():
        raise RuntimeError("The packaged index does not contain chroma/chroma.sqlite3.")


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    _restore_packaged_index()

    backend_cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "backend.app.main:app",
        "--reload",
        "--port",
        "8000",
    ]

    npm_executable = "npm.cmd" if os.name == "nt" else "npm"
    frontend_cmd = [npm_executable, "--prefix", "frontend", "run", "dev"]

    print("Starting backend:", " ".join(backend_cmd))
    backend = subprocess.Popen(backend_cmd, cwd=PROJECT_ROOT)
    time.sleep(1.5)  # small gap to avoid interleaved logs on startup

    print("Starting frontend:", " ".join(frontend_cmd))
    frontend = subprocess.Popen(frontend_cmd, cwd=PROJECT_ROOT)

    try:
        # Wait until one process exits
        while True:
            backend_code = backend.poll()
            frontend_code = frontend.poll()
            if backend_code is not None:
                print(f"Backend exited with code {backend_code}")
                break
            if frontend_code is not None:
                print(f"Frontend exited with code {frontend_code}")
                break
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\nStopping processes...")
    finally:
        for proc in (backend, frontend):
            if proc.poll() is None:
                proc.terminate()
        for proc in (backend, frontend):
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    main()
