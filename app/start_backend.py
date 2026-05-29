"""Robust backend launcher.

Works no matter where you call it from. Sets PYTHONPATH, switches cwd into
`app/backend/`, then boots uvicorn with `main:app`.

Usage (any of these):
    python app/start_backend.py
    python app\start_backend.py
    cd app && python start_backend.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> None:
    here = Path(__file__).resolve()
    app_dir = here.parent
    backend_dir = app_dir / "backend"
    root_dir = app_dir.parent

    if not (backend_dir / "main.py").exists():
        sys.stderr.write(
            f"[start_backend] Không thấy {backend_dir / 'main.py'}. "
            "Cấu trúc thư mục sai?\n"
        )
        sys.exit(1)

    # Make project Python modules importable.
    # NOTE: do NOT add `cognitive_trading/` to sys.path — its `config.py` would
    # shadow root `config.py`. Import cognitive_trading via package name instead.
    extra_paths = [
        str(root_dir),
        str(root_dir / "vnstock"),
        str(root_dir / "tracking_news"),
        str(backend_dir),
    ]
    existing_pp = os.environ.get("PYTHONPATH", "")
    merged = os.pathsep.join(
        [p for p in extra_paths if p] + ([existing_pp] if existing_pp else [])
    )
    os.environ["PYTHONPATH"] = merged
    for p in extra_paths:
        if p not in sys.path:
            sys.path.insert(0, p)

    # Ensure UTF-8 stdout/stderr on Windows.
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

    os.chdir(backend_dir)

    host = os.environ.get("BACKEND_HOST", "127.0.0.1")
    port = int(os.environ.get("BACKEND_PORT", "8000"))
    reload = os.environ.get("BACKEND_RELOAD", "1") not in ("0", "false", "False")

    try:
        import uvicorn
    except ImportError:
        sys.stderr.write(
            "[start_backend] uvicorn chưa cài. Chạy: "
            "pip install -r app/backend/requirements.txt\n"
        )
        sys.exit(1)

    print(
        f"[start_backend] cwd={backend_dir}  host={host}  port={port}  reload={reload}",
        flush=True,
    )
    uvicorn.run("main:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    main()
