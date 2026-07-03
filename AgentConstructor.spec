# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec для desktop exe конструктора ИИ-агентов."""

block_cipher = None

hiddenimports = [
    "sqlalchemy.dialects.sqlite",
    "pythoncom",
    "pywintypes",
    "win32com",
    "win32com.client",
    "win32timezone",
    "agent_desktop_constructor.workers.com_worker_process",
    "agent_desktop_constructor.workers.outlook_com_worker",
    "agent_desktop_constructor.workers.outlook_com_actions",
]

datas = [
    (
        "agent_desktop_constructor/tools/default_tools_catalog.json",
        "agent_desktop_constructor/tools",
    ),
    ("data/settings.json", "data"),
]

# .env с LLM-ключами вшивается в бандл, чтобы Claude/OpenAI работали на других
# ПК без ручной настройки. ВНИМАНИЕ: ключи попадают внутрь exe — распространяйте
# сборку только на доверенные машины. Файл опционален (сборка не падает без него).
import os as _os

if _os.path.exists(".env"):
    datas.append((".env", "."))

a = Analysis(
    ["agent_desktop_constructor/app/ui/desktop_entry.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AgentConstructor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="AgentConstructor",
)
