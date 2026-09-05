#!/usr/bin/env python3
"""Project management automation tool for NexusChat.

Usage:
    python manage.py --version                  # Show current project version
    python manage.py version                    # Check version sync across files
    python manage.py version --set 1.0.1        # Set version across all files
    python manage.py version --bump patch       # Bump patch version (1.0.0 -> 1.0.1)
    python manage.py setup                      # Install dependencies & setup editable package
    python manage.py setup --dev                # Also install build/publishing/test tools
    python manage.py build --pypi              # Pre-flight check & build PyPI dist (sdist + wheel)
    python manage.py build --client            # Pre-flight check & build standalone client executable
    python manage.py publish --pypi            # Publish dist/* to PyPI using twine
    python manage.py publish --pypi --test       # Publish to TestPyPI
    python manage.py clean                     # Clean all build artifacts and caches
    python manage.py run <command>             # Run client, server, setup-db, or admin
"""
import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Tracked version files and their regex search/replace templates
VERSION_FILES = {
    "pyproject.toml": (
        ROOT / "pyproject.toml",
        r'version\s*=\s*"([^"]+)"',
        'version = "{version}"',
    ),
    "nexuschat/__init__.py": (
        ROOT / "nexuschat" / "__init__.py",
        r'__version__\s*=\s*"([^"]+)"',
        '__version__ = "{version}"',
    ),
    "shared/constants.py": (
        ROOT / "shared" / "constants.py",
        r'VERSION\s*=\s*"([^"]+)"',
        'VERSION = "{version}"',
    ),
}


def log(msg):
    print(f"[*] {msg}")


def log_success(msg):
    print(f"[OK] {msg}")


def log_error(msg):
    print(f"[ERROR] {msg}", file=sys.stderr)


# =============================================================================
# Version Management & Synchronization
# =============================================================================

def get_version_info():
    """Return dictionary of {file_key: version_str} across tracked files."""
    versions = {}
    for key, (path, pattern, _) in VERSION_FILES.items():
        if not path.is_file():
            versions[key] = None
            continue
        content = path.read_text(encoding="utf-8")
        match = re.search(pattern, content)
        versions[key] = match.group(1) if match else None
    return versions


def check_version_sync(silent=False):
    """Check if version strings across all files match. Returns (in_sync, primary_version)."""
    versions = get_version_info()
    if not silent:
        log("Checking project version sync across files...")
    
    valid_versions = [v for v in versions.values() if v is not None]
    all_same = len(set(valid_versions)) == 1 and len(valid_versions) > 0
    primary_version = versions.get("pyproject.toml") or versions.get("nexuschat/__init__.py") or "unknown"

    if not silent:
        for key, ver in versions.items():
            status = f"v{ver}" if ver else "NOT FOUND"
            print(f"  - {key:<25}: {status}")

    if all_same:
        if not silent:
            log_success(f"All version files are in sync! Current version: v{primary_version}")
        return True, primary_version
    else:
        if not silent:
            log_error("Version mismatch detected across project files!")
        return False, primary_version


def set_version(new_version):
    """Set project version across all tracked files."""
    clean_ver = new_version.lstrip("v").strip()
    if not re.match(r"^\d+\.\d+\.\d+(?:-[a-zA-Z0-9.]+)?$", clean_ver):
        log_error(f"Invalid version format: '{new_version}'. Use SemVer format (e.g. 1.0.1 or 1.1.0).")
        sys.exit(1)

    log(f"Updating project version to v{clean_ver} across all files...")
    for key, (path, pattern, replacement_fmt) in VERSION_FILES.items():
        if not path.is_file():
            log_error(f"File not found: {key}")
            continue
        content = path.read_text(encoding="utf-8")
        if re.search(pattern, content):
            new_content = re.sub(pattern, replacement_fmt.format(version=clean_ver), content)
            path.write_text(new_content, encoding="utf-8")
            log_success(f"Updated {key:<25} -> v{clean_ver}")
        else:
            log_error(f"Could not find version pattern in {key}")

    # Also update README.md if version package strings exist
    readme_path = ROOT / "README.md"
    if readme_path.is_file():
        r_content = readme_path.read_text(encoding="utf-8")
        r_new_content = re.sub(r'nexuschat-\d+\.\d+\.\d+', f'nexuschat-{clean_ver}', r_content)
        if r_new_content != r_content:
            readme_path.write_text(r_new_content, encoding="utf-8")
            log_success(f"Updated README.md package references -> v{clean_ver}")

    # Ensure release notes file exists in docs/release_notes/
    ensure_release_notes(clean_ver)

    log_success(f"Project successfully updated to v{clean_ver}!")


def ensure_release_notes(version):
    """Ensure release notes file exists in docs/release_notes/ for given version."""
    clean_ver = version.lstrip("v").strip()
    notes_dir = ROOT / "docs" / "release_notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    notes_file = notes_dir / f"RELEASE_NOTES_V{clean_ver}.md"

    if not notes_file.exists():
        template_file = notes_dir / "TEMPLATE.md"
        if template_file.exists():
            content = template_file.read_text(encoding="utf-8").replace("{VERSION}", clean_ver)
        else:
            content = f"# NexusChat v{clean_ver} Release Notes\n\n- Release v{clean_ver}.\n"
        notes_file.write_text(content, encoding="utf-8")
        log_success(f"Created release notes template: docs/release_notes/RELEASE_NOTES_V{clean_ver}.md")
    else:
        log(f"Release notes verified: docs/release_notes/RELEASE_NOTES_V{clean_ver}.md")



def bump_version(level):
    """Bump version by level ('major', 'minor', 'patch')."""
    versions = get_version_info()
    curr = versions.get("pyproject.toml") or "1.0.0"
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)(?:-.*)?$", curr)
    if not m:
        log_error(f"Cannot parse current version '{curr}' for bumping.")
        sys.exit(1)

    major, minor, patch = map(int, m.groups())
    if level == "major":
        major += 1
        minor = 0
        patch = 0
    elif level == "minor":
        minor += 1
        patch = 0
    elif level == "patch":
        patch += 1

    new_ver = f"{major}.{minor}.{patch}"
    set_version(new_ver)


# =============================================================================
# Environment & Setup Management
# =============================================================================

def setup_environment(dev=False):
    """Check Python environment, install requirements, dev tools, and editable package."""
    log("Configuring and setting up NexusChat environment...")

    # 1. Check Python version
    if sys.version_info < (3, 8):
        log_error(f"Python 3.8+ required. Current version: {sys.version}")
        sys.exit(1)
    log_success(f"Python version check passed: {sys.version.split()[0]}")

    # 2. Check requirements.txt
    req_file = ROOT / "requirements.txt"
    if not req_file.is_file():
        log_error("requirements.txt not found in project root!")
        sys.exit(1)

    # 3. Install runtime dependencies
    log("Installing runtime dependencies from requirements.txt...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", str(req_file)], cwd=ROOT)
        log_success("Runtime dependencies installed successfully.")
    except subprocess.CalledProcessError as exc:
        log_error(f"Failed to install runtime dependencies: {exc}")
        sys.exit(1)

    # 4. Install dev tools if requested
    if dev:
        log("Installing development & build tools (build, twine, pyinstaller, pytest)...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "build", "twine", "pyinstaller", "pytest"], cwd=ROOT)
            log_success("Development tools installed successfully.")
        except subprocess.CalledProcessError as exc:
            log_error(f"Failed to install development tools: {exc}")

    # 5. Install package in editable mode
    log("Installing nexuschat package in editable mode ('pip install -e .')...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-e", "."], cwd=ROOT)
        log_success("Package installed in editable mode!")
    except subprocess.CalledProcessError as exc:
        log_error(f"Failed editable installation: {exc}")
        sys.exit(1)

    # 6. Import verification
    log("Verifying setup and module imports...")
    try:
        import nexuschat
        if sys.platform == "win32" and sys.version_info >= (3, 8) and hasattr(os, "add_dll_directory"):
            for p in os.environ.get("PATH", "").split(os.pathsep):
                if p and os.path.isdir(p) and ("postgre" in p.lower() or "pgsql" in p.lower() or "pg" in p.lower()):
                    try:
                        os.add_dll_directory(p)
                    except (OSError, ValueError):
                        pass
        import psycopg2
        import bcrypt
        log_success(f"All module imports verified! (nexuschat v{nexuschat.__version__})")
    except Exception as exc:
        log_error(f"Verification failed during import check: {exc}")
        sys.exit(1)


    log_success("Setup complete! Start server: 'nexuschat server' | Start client: 'nexuschat client'")


# =============================================================================
# Packaging & Release Automation
# =============================================================================

def verify_packaging_integrity():
    """Run pre-flight checks for files, version sync, and packaging setup."""
    log("Performing pre-flight packaging integrity check...")

    required_paths = [
        ROOT / "pyproject.toml",
        ROOT / "requirements.txt",
        ROOT / "README.md",
        ROOT / "nexuschat" / "__init__.py",
        ROOT / "nexuschat" / "cli.py",
        ROOT / "client" / "app.py",
        ROOT / "server" / "chat_server.py",
        ROOT / "shared" / "constants.py",
    ]

    missing = [str(p.relative_to(ROOT)) for p in required_paths if not p.exists()]
    if missing:
        log_error(f"Packaging failed! Missing essential project files: {missing}")
        sys.exit(1)

    in_sync, primary_ver = check_version_sync(silent=True)
    if not in_sync:
        log_error("Packaging cancelled due to version mismatch across project files!")
        log("Run 'python manage.py version' to inspect or 'python manage.py version --set <version>' to fix.")
        sys.exit(1)

    log_success(f"Packaging integrity check passed! Ready to build v{primary_ver}.")


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

    for item in ROOT.glob("*.egg-info"):
        if item.is_dir():
            shutil.rmtree(item, ignore_errors=True)
            log(f"Removed: {item}")

    for item in ROOT.glob("*.spec"):
        if item.is_file():
            item.unlink(missing_ok=True)
            log(f"Removed: {item}")

    for item in ROOT.rglob("__pycache__"):
        if item.is_dir():
            shutil.rmtree(item, ignore_errors=True)

    log_success("Workspace cleaned successfully.")


def build_pypi():
    verify_packaging_integrity()
    log("Building PyPI distribution package (sdist + wheel)...")
    dist_dir = ROOT / "dist"
    dist_dir.mkdir(exist_ok=True)

    cmd = [sys.executable, "-m", "build", "--sdist", "--wheel", "--outdir", str(dist_dir)]
    try:
        subprocess.check_call(cmd, cwd=ROOT)
    except (subprocess.CalledProcessError, FileNotFoundError):
        log("Standard 'build' module not found, attempting auto-install...")
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
    verify_packaging_integrity()
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
        description="NexusChat Automation, Setup, Versioning, and Release Management Tool",
    )
    parser.add_argument("--version", action="store_true", help="Print NexusChat project version and exit")

    subparsers = parser.add_subparsers(dest="action", help="Action to execute")

    # Version subcommand
    ver_p = subparsers.add_parser("version", help="Inspect, synchronize, or bump project version")
    ver_p.add_argument("--set", dest="set_ver", metavar="VERSION", help="Set exact project version across all files (e.g. 1.0.1)")
    ver_p.add_argument("--bump", choices=["major", "minor", "patch"], help="Bump version level according to SemVer")
    ver_p.add_argument("--check", action="store_true", help="Check version sync status and exit with non-zero on mismatch")

    # Setup subcommand
    setup_p = subparsers.add_parser("setup", aliases=["install"], help="Configure dependencies and install package in editable mode")
    setup_p.add_argument("--dev", action="store_true", help="Also install development and build tools (build, twine, pyinstaller, pytest)")

    # Build subcommand
    build_p = subparsers.add_parser("build", help="Build packages or standalone binaries")
    build_p.add_argument("--pypi", action="store_true", help="Build PyPI source distribution and wheel")
    build_p.add_argument("--client", "--bin", dest="client", action="store_true", help="Build standalone client executable")
    build_p.add_argument("--check", action="store_true", help="Run packaging integrity pre-flight checks without building")

    # Publish subcommand
    pub_p = subparsers.add_parser("publish", help="Publish package to PyPI")
    pub_p.add_argument("--pypi", action="store_true", required=True, help="Publish to PyPI")
    pub_p.add_argument("--test", action="store_true", help="Publish to TestPyPI instead of production")

    # Clean subcommand
    subparsers.add_parser("clean", help="Remove all build artifacts and caches")

    # Release Notes subcommand
    rn_p = subparsers.add_parser("release-notes", help="Ensure or generate release notes template in docs/release_notes/")
    rn_p.add_argument("--ver", help="Specify version string (default: current project version)")

    # Run subcommand
    run_p = subparsers.add_parser("run", help="Run application component")
    run_p.add_argument("target", choices=["client", "server", "setup-db", "admin"], help="Component to run")
    run_p.add_argument("extra", nargs=argparse.REMAINDER, help="Additional arguments")

    if len(sys.argv) == 1:
        parser.print_help()
        return

    args = parser.parse_args()

    if args.version:
        _, primary_ver = check_version_sync(silent=True)
        print(f"NexusChat v{primary_ver}")
        return

    try:
        if args.action == "version":
            if args.set_ver:
                set_version(args.set_ver)
            elif args.bump:
                bump_version(args.bump)
            else:
                in_sync, _ = check_version_sync()
                if args.check and not in_sync:
                    sys.exit(1)
        elif args.action == "release-notes":
            ver = args.ver
            if not ver:
                _, ver = check_version_sync(silent=True)
            ensure_release_notes(ver)

        elif args.action in ("setup", "install"):
            setup_environment(dev=args.dev)
        elif args.action == "build":
            if args.check:
                verify_packaging_integrity()
            elif args.pypi:
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

