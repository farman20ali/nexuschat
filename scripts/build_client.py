"""Build a standalone folder bundle of the client (Cross-platform: Windows, Linux, macOS). Run from project root."""
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    system = platform.system()
    binary_name = "NexusChat.exe" if system == "Windows" else "NexusChat"

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

    print(f"Building NexusChat client bundle on {system}...")
    print(" ".join(cmd))
    subprocess.check_call(cmd, cwd=ROOT)

    out_folder = ROOT / "dist" / "NexusChat"
    binary_path = out_folder / binary_name

    print(f"\nBuild complete!")
    print(f"Bundle directory: {out_folder}")
    print(f"Executable:       {binary_path}")
    if system == "Windows":
        print("\nTip: Zip the entire 'dist/NexusChat/' folder and distribute it to Windows users.")
    else:
        print(f"\nTip: Create a tarball to distribute to {system} users:")
        print("     tar -czvf NexusChat-linux.tar.gz -C dist NexusChat")


if __name__ == "__main__":
    main()
