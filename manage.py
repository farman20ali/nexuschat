#!/usr/bin/env python3
"""Project management automation tool for NexusChat.

Usage:
    python manage.py build --pypi       # Build source distribution and wheel
    python manage.py publish --pypi     # Publish dist/* to PyPI using twine
    python manage.py publish --pypi --test # Publish to TestPyPI
    python manage.py build --client     # Build cross-platform standalone executable & zip
    python manage.py clean              # Clean all build artifacts and caches
    python manage.py run <command>      # Shortcut to run client, server, setup-db, or admin
"""
import argparse
import os
import platform
import shutil
import subprocess
import sys
import zipfile
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def log(msg):
    print(f"[*] {msg}")


def log_success(msg):
    print(f"[OK] {msg}")


def log_error(msg):
    print(f"[ERROR] {msg}", file=sys.stderr)


def clean_artifacts():
    log("Cleaning build artifacts and temporary files...")
    patterns_to_remove = [
        ROOT / "build",
        ROOT / "dist",
        ROOT / "*.spec",
    ]

    for p in patterns_to_remove:
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
            log(f"Removed directory: {p}")
        elif p.is_file():
            p.unlink(missing_ok=True)
            log(f"Removed file: {p}")

    # Remove egg-info directories and spec files
    for item in ROOT.glob("*.egg-info"):
        if item.is_dir():
            shutil.rmtree(item, ignore_errors=True)
            log(f"Removed: {item}")

    for item in ROOT.glob("*.spec"):
        if item.is_file():
            item.unlink(missing_ok=True)
            log(f"Removed: {item}")

    # Remove __pycache__ folders
    for item in ROOT.rglob("__pycache__"):
        if item.is_dir():
            shutil.rmtree(item, ignore_errors=True)

    log_success("Workspace cleaned successfully.")


def build_pypi():
    log("Building PyPI distribution package (sdist + wheel)...")
    dist_dir = ROOT / "dist"
    dist_dir.mkdir(exist_ok=True)

    # Ensure build package is installed
    cmd = [sys.executable, "-m", "build", "--sdist", "--wheel", "--outdir", str(dist_dir)]
    try:
        subprocess.check_call(cmd, cwd=ROOT)
    except (subprocess.CalledProcessError, FileNotFoundError):
        log("Standard 'build' module not found, attempting setuptools fallback...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "build"], cwd=ROOT)
            subprocess.check_call(cmd, cwd=ROOT)
        except Exception as exc:
            log_error(f"Failed to build PyPI distribution: {exc}")
            log("Install build with: pip install build")
            sys.exit(1)

    log("\nGenerated Distribution Files in 'dist/':")
    for f in dist_dir.glob("*"):
        if f.suffix in (".whl", ".gz"):
            size_kb = f.stat().st_size / 1024
            print(f"  - {f.name} ({size_kb:.1f} KB)")
    log_success("PyPI packages built successfully!")


def publish_pypi(test=False):
    dist_dir = ROOT / "dist"
    files = list(dist_dir.glob("*.whl")) + list(dist_dir.glob("*.tar.gz"))
    if not files:
        log_error("No distribution packages found in dist/. Run 'python manage.py build --pypi' first.")
        sys.exit(1)

    repo_url = "https://test.pypi.org/legacy/" if test else "https://upload.pypi.org/legacy/"
    target_name = "TestPyPI" if test else "Production PyPI"

    log(f"Publishing {len(files)} package(s) to {target_name} ({repo_url})...")

    cmd = [sys.executable, "-m", "twine", "upload", "--repository-url", repo_url] + [str(f) for f in files]
    try:
        subprocess.check_call(cmd, cwd=ROOT)
        log_success(f"Successfully published to {target_name}!")
    except FileNotFoundError:
        log_error("'twine' is not installed. Install with: pip install twine")
        sys.exit(1)
    except subprocess.CalledProcessError as exc:
        log_error(f"Upload failed: {exc}")
        sys.exit(1)


def build_client_binary():
    system = platform.system()
    binary_name = "NexusChat.exe" if system == "Windows" else "NexusChat"
    log(f"Building standalone desktop client binary for {system}...")

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--onedir",
        "--name",
        "NexusChat",
        "--paths",
        str(ROOT),
        "--collect-submodules",
        "client",
        "--collect-submodules",
        "shared",
        str(ROOT / "client" / "__main__.py"),
    ]

    try:
        subprocess.check_call(cmd, cwd=ROOT)
    except FileNotFoundError:
        log_error("'pyinstaller' is not installed. Install with: pip install pyinstaller")
        sys.exit(1)
    except subprocess.CalledProcessError as exc:
        log_error(f"PyInstaller build failed: {exc}")
        sys.exit(1)

    out_folder = ROOT / "dist" / "NexusChat"
    binary_path = out_folder / binary_name

    if not binary_path.exists():
        log_error(f"Expected binary not found at: {binary_path}")
        sys.exit(1)

    log_success(f"Binary generated at: {binary_path}")

    # Compress into a portable distribution archive
    if system == "Windows":
        archive_path = ROOT / "dist" / "NexusChat-windows.zip"
        log(f"Creating portable zip archive: {archive_path.name}...")
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for file in out_folder.rglob("*"):
                if file.is_file():
                    zipf.write(file, arcname=file.relative_to(ROOT / "dist"))
        log_success(f"Created release package: {archive_path} ({archive_path.stat().st_size / (1024*1024):.1f} MB)")
    else:
        archive_path = ROOT / "dist" / f"NexusChat-{system.lower()}.tar.gz"
        log(f"Creating portable tarball: {archive_path.name}...")
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(out_folder, arcname="NexusChat")
        log_success(f"Created release package: {archive_path} ({archive_path.stat().st_size / (1024*1024):.1f} MB)")


def main():
    parser = argparse.ArgumentParser(
        prog="manage.py",
        description="NexusChat Automation and Release Management Tool",
    )
    subparsers = parser.add_subparsers(dest="action", help="Action to execute")

    # Build subcommand
    build_p = subparsers.add_parser("build", help="Build packages or binaries")
    build_p.add_argument("--pypi", action="store_true", help="Build PyPI source distribution and wheel")
    build_p.add_argument("--client", "--bin", dest="client", action="store_true", help="Build standalone client executable")

    # Publish subcommand
    pub_p = subparsers.add_parser("publish", help="Publish package to PyPI")
    pub_p.add_argument("--pypi", action="store_true", required=True, help="Publish to PyPI")
    pub_p.add_argument("--test", action="store_true", help="Publish to TestPyPI instead of production")

    # Clean subcommand
    subparsers.add_parser("clean", help="Remove all build artifacts and caches")

    # Run subcommand
    run_p = subparsers.add_parser("run", help="Run application component")
    run_p.add_argument("target", choices=["client", "server", "setup-db", "admin"], help="Component to run")
    run_p.add_argument("extra", nargs=argparse.REMAINDER, help="Additional arguments")

    if len(sys.argv) == 1:
        parser.print_help()
        return

    args = parser.parse_args()

    try:
        if args.action == "build":
            if args.pypi:
                build_pypi()
            elif args.client:
                build_client_binary()
            else:
                log("Specify what to build: --pypi or --client")
                build_p.print_help()
        elif args.action == "publish":
            if args.pypi:
                publish_pypi(test=args.test)
        elif args.action == "clean":
            clean_artifacts()
        elif args.action == "run":
            from nexuschat.cli import main as cli_main
            sys.argv = [sys.argv[0], args.target] + args.extra
            cli_main()
    except (KeyboardInterrupt, SystemExit):
        sys.exit(0)


if __name__ == "__main__":
    main()
