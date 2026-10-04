"""
Builds a clean cPanel upload zip.

The archive excludes local virtualenvs, caches, generated reports, logs, and
the private .env file. Create .env directly on the server from .env.example.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = PROJECT_ROOT / "dist"
PACKAGE_PATH = DIST_DIR / "amipi-monitor-cpanel.zip"

EXCLUDED_DIRS = {
    ".git",
    ".pytest_cache",
    "__pycache__",
    "venv",
    "dist",
}

EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
EXCLUDED_FILES = {".env", ".DS_Store"}
EXCLUDED_REPORT_SUFFIXES = {".html", ".json", ".csv", ".pdf"}


def should_include(path: Path) -> bool:
    rel = path.relative_to(PROJECT_ROOT)
    parts = set(rel.parts)

    if parts & EXCLUDED_DIRS:
        return False
    if path.name in EXCLUDED_FILES:
        return False
    if path.suffix in EXCLUDED_SUFFIXES:
        return False
    if rel.parts[0] == "logs" and path.name != ".gitkeep":
        return False
    if rel.parts[0] == "reports" and path.name != ".gitkeep" and path.suffix in EXCLUDED_REPORT_SUFFIXES:
        return False
    return True


def main() -> int:
    DIST_DIR.mkdir(exist_ok=True)
    if PACKAGE_PATH.exists():
        PACKAGE_PATH.unlink()

    with zipfile.ZipFile(PACKAGE_PATH, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(PROJECT_ROOT.rglob("*")):
            if path.is_file() and should_include(path):
                archive.write(path, path.relative_to(PROJECT_ROOT))

    print(f"Created {PACKAGE_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
