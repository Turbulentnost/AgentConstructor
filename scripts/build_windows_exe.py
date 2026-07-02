"""Сборка Windows exe через PyInstaller."""

from __future__ import annotations

import shutil
import subprocess
import sys
from importlib.util import find_spec
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = PROJECT_ROOT / "AgentConstructor.spec"
DIST_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = PROJECT_ROOT / "build"


def main() -> int:
    """Запустить PyInstaller по spec-файлу проекта."""
    if shutil.which("pyinstaller") is None and find_spec("PyInstaller") is None:
        print(
            "PyInstaller не найден. Установите его командой: "
            f"{sys.executable} -m pip install pyinstaller",
            file=sys.stderr,
        )
        return 1

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        str(SPEC_PATH),
    ]
    print("Запуск сборки:", " ".join(command))
    completed = subprocess.run(command, cwd=PROJECT_ROOT, check=False)
    if completed.returncode != 0:
        return completed.returncode

    exe_path = DIST_DIR / "AgentConstructor" / "AgentConstructor.exe"
    if not exe_path.exists():
        print(f"Сборка завершилась, но exe не найден: {exe_path}", file=sys.stderr)
        return 2

    print(f"Готово: {exe_path}")
    print("Для LLM-ключей положите .env рядом с exe или задайте переменные окружения.")
    print(f"Временная директория сборки: {BUILD_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
