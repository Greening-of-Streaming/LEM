# PyInstaller spec for the LEM desktop app.
#
# macOS:   venv/bin/pyinstaller packaging/lem.spec --noconfirm  -> dist/LEM.app
# Windows: same spec on a Windows machine/runner                -> dist/LEM/LEM.exe
#
# The bundle is unsigned; signing/notarization is applied to the finished
# .app once the Apple Developer (GREENING OF STREAMING) account is active.

import os
import re
import subprocess
import sys

SRC = os.path.join(SPECPATH, "..", "src")

# Single source of truth for the version: src/lem/__init__.py.
with open(os.path.join(SRC, "lem", "__init__.py")) as f:
    VERSION = re.search(r'^__version__ = "([^"]+)"', f.read(), re.M).group(1)

# Stamp the commit into the bundle so the app can show which build it is.
try:
    COMMIT = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=SPECPATH,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
except (OSError, subprocess.CalledProcessError):
    COMMIT = ""
BUILD_INFO = os.path.join(workpath, "build.txt")
os.makedirs(workpath, exist_ok=True)
with open(BUILD_INFO, "w") as f:
    f.write(COMMIT)

a = Analysis(
    [os.path.join(SPECPATH, "entry.py")],
    pathex=[SRC],
    binaries=[],
    datas=[
        (os.path.join(SRC, "lem", "gui", "assets"), "lem_assets"),
        (BUILD_INFO, "lem_assets"),
    ],
    # tapo (Rust extension) and the device modules are imported lazily via the
    # DEVICE_TYPES registry, so PyInstaller's static analysis misses them.
    hiddenimports=[
        "tapo",
        "aiohttp",
        "lem.devices.tapo",
        "lem.devices.shelly",
        "lem.devices.fake",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LEM",
    debug=False,
    strip=False,
    upx=False,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="LEM",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="LEM.app",
        icon=os.path.join(SPECPATH, "gos.icns"),
        bundle_identifier="org.greeningofstreaming.lem",
        info_plist={
            "NSHighResolutionCapable": True,
            "CFBundleShortVersionString": VERSION,
            "NSHumanReadableCopyright": "Greening of Streaming",
            # Without this, macOS silently blocks all LAN connections (no
            # prompt), and scans/measurements find nothing.
            "NSLocalNetworkUsageDescription":
                "LEM talks to smart plugs on your local network to "
                "discover them and measure their power consumption.",
        },
    )
