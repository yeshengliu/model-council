from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
MACOS_ROOT = ROOT / "macos"
SOURCES = MACOS_ROOT / "Sources" / "ModelCouncilApp"
BUILD_ROOT = MACOS_ROOT / "build"
PROJECT_ICON_ROOT = ROOT / "output" / "app-icon"
APP_ICON_PNG_NAME = "AppIcon-1024.png"
APP_ICON_ICNS_NAME = "AppIcon.icns"
PROJECT_ICON_PNG = PROJECT_ICON_ROOT / "model-council-art-icon-1024.png"
PROJECT_ICON_ICNS = PROJECT_ICON_ROOT / "model-council-art-icon.icns"
APP_NAME = "Model Council"


def run(cmd: list[str], cwd: Path | None = None) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, cwd=cwd or ROOT, check=True)


def write_info_plist(path: Path) -> None:
    path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key>
  <string>en</string>
  <key>CFBundleDisplayName</key>
  <string>Model Council</string>
  <key>CFBundleExecutable</key>
  <string>Model Council</string>
  <key>CFBundleIdentifier</key>
  <string>local.modelcouncil.desktop</string>
  <key>CFBundleIconFile</key>
  <string>AppIcon</string>
  <key>CFBundleInfoDictionaryVersion</key>
  <string>6.0</string>
  <key>CFBundleName</key>
  <string>Model Council</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>0.1.0</string>
  <key>CFBundleVersion</key>
  <string>1</string>
  <key>LSMinimumSystemVersion</key>
  <string>13.0</string>
  <key>NSHighResolutionCapable</key>
  <true/>
</dict>
</plist>
""",
        encoding="utf-8",
    )


def build_frontend() -> None:
    if not (FRONTEND / "node_modules").exists():
        run(["npm", "install"], cwd=FRONTEND)
    run(["npm", "run", "build"], cwd=FRONTEND)


def build_python_runtime(resources_dir: Path) -> None:
    python_dir = resources_dir / "python"
    if python_dir.exists():
        shutil.rmtree(python_dir)

    run(["python3", "-m", "venv", str(python_dir)])
    bundled_python = python_dir / "bin" / "python3"
    run([str(bundled_python), "-m", "pip", "install", "--upgrade", "pip"])
    run([str(bundled_python), "-m", "pip", "install", str(ROOT)])


def copy_frontend(resources_dir: Path) -> None:
    source = FRONTEND / "dist"
    target = resources_dir / "frontend-dist"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)


def build_macos_icon(resources_dir: Path) -> None:
    if not PROJECT_ICON_PNG.exists():
        raise RuntimeError(f"Missing app icon PNG: {PROJECT_ICON_PNG}")
    if not PROJECT_ICON_ICNS.exists():
        raise RuntimeError(f"Missing app icon ICNS: {PROJECT_ICON_ICNS}")
    shutil.copy2(PROJECT_ICON_PNG, resources_dir / APP_ICON_PNG_NAME)
    shutil.copy2(PROJECT_ICON_ICNS, resources_dir / APP_ICON_ICNS_NAME)


def compile_app_binary(macos_dir: Path) -> None:
    sources = sorted(str(path) for path in SOURCES.glob("*.swift"))
    if not sources:
        raise RuntimeError("No Swift sources found for macOS app.")
    run(
        [
            "xcrun",
            "swiftc",
            "-parse-as-library",
            "-O",
            "-o",
            str(macos_dir / APP_NAME),
            *sources,
            "-framework",
            "AppKit",
            "-framework",
            "SwiftUI",
            "-framework",
            "WebKit",
        ]
    )


def create_zip(app_dir: Path) -> None:
    zip_path = BUILD_ROOT / "Model-Council-macOS.zip"
    if zip_path.exists():
        zip_path.unlink()
    run(["ditto", "-c", "-k", "--keepParent", str(app_dir), str(zip_path)])


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the unsigned macOS Model Council app bundle.")
    parser.add_argument("--skip-zip", action="store_true", help="Do not create the distributable zip archive.")
    args = parser.parse_args()

    if sys.platform != "darwin":
        raise SystemExit("This build script must be run on macOS.")

    app_dir = BUILD_ROOT / f"{APP_NAME}.app"
    contents_dir = app_dir / "Contents"
    macos_dir = contents_dir / "MacOS"
    resources_dir = contents_dir / "Resources"

    if app_dir.exists():
        shutil.rmtree(app_dir)

    macos_dir.mkdir(parents=True, exist_ok=True)
    resources_dir.mkdir(parents=True, exist_ok=True)

    build_frontend()
    build_python_runtime(resources_dir)
    copy_frontend(resources_dir)
    build_macos_icon(resources_dir)
    compile_app_binary(macos_dir)
    write_info_plist(contents_dir / "Info.plist")

    if not args.skip_zip:
        create_zip(app_dir)

    print()
    print(f"Built app: {app_dir}")
    if not args.skip_zip:
        print(f"Built zip: {BUILD_ROOT / 'Model-Council-macOS.zip'}")


if __name__ == "__main__":
    main()
