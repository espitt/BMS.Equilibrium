"""Operating-system integration: locations, shortcuts, registration and uninstall.

Everything is per-user, so no administrator password or UAC prompt is needed.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .core import APP_NAME, MARKER_NAME, InstallError, add_shortcuts_to_marker, read_marker

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"

UNINSTALLER_NAME = f"Uninstall {APP_NAME}.exe" if IS_WINDOWS else "uninstall"
_UNINSTALL_KEY = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_NAME}"
_NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW


def default_install_dir() -> Path:
    home = Path.home()
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or str(home / "AppData" / "Local")
        return Path(base) / "Programs" / APP_NAME
    if IS_MACOS:
        return home / "Applications" / f"{APP_NAME}.app"
    return _xdg_data_home() / APP_NAME


def supports_uninstaller() -> bool:
    """macOS apps are removed by dragging them to the Trash."""
    return not IS_MACOS


def app_executable(install_dir: Path) -> Path:
    if IS_WINDOWS:
        return install_dir / f"{APP_NAME}.exe"
    if IS_MACOS:
        return install_dir / "Contents" / "MacOS" / APP_NAME
    return install_dir / APP_NAME


def launch(install_dir: Path) -> None:
    """Start the app free of the frozen wizard's library paths, which would break it."""
    env = {**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"}
    if "LD_LIBRARY_PATH_ORIG" in env:
        env["LD_LIBRARY_PATH"] = env["LD_LIBRARY_PATH_ORIG"]
    else:
        env.pop("LD_LIBRARY_PATH", None)

    if IS_WINDOWS:
        import ctypes

        ctypes.windll.kernel32.SetDllDirectoryW(None)

    if IS_MACOS:
        subprocess.Popen(["open", str(install_dir)], env=env)
    else:
        subprocess.Popen([str(app_executable(install_dir))], cwd=install_dir, env=env)


def integrate(install_dir: Path, version: str, size: int, desktop_shortcut: bool) -> None:
    """Add the app to the OS menus. macOS needs nothing beyond ~/Applications."""
    if IS_WINDOWS:
        shortcuts = _windows_shortcuts(install_dir, desktop_shortcut)
        add_shortcuts_to_marker(install_dir, shortcuts)
        _windows_register(install_dir, version, size)
    elif not IS_MACOS:
        shortcuts = _linux_shortcuts(install_dir, desktop_shortcut)
        add_shortcuts_to_marker(install_dir, shortcuts)


def uninstall(install_dir: Path) -> None:
    """Remove an installation. The marker check protects unrelated folders."""
    if not (install_dir / MARKER_NAME).is_file():
        raise InstallError(f"{install_dir} is not an {APP_NAME} installation.")

    # Windows will not delete a running program, so this doubles as a safety
    # check: it fails before anything else has been removed.
    try:
        app_executable(install_dir).unlink(missing_ok=True)
    except PermissionError as error:
        raise InstallError(f"{APP_NAME} is running. Close it and try again.") from error

    for shortcut in read_marker(install_dir).get("shortcuts", []):
        Path(shortcut).unlink(missing_ok=True)

    if IS_WINDOWS:
        _windows_unregister()
    else:
        shutil.rmtree(install_dir)


def finish_uninstall(install_dir: Path) -> None:
    """Call as the very last action before the uninstaller exits.

    On Windows the uninstaller runs from inside the install folder and so cannot
    delete it. A hidden helper process does that a few seconds after this exits.
    """
    if IS_WINDOWS:
        subprocess.Popen(
            'cmd /d /c "ping -n 4 127.0.0.1 >nul & rmdir /s /q "%EQUILIBRIUM_DIR%""',
            cwd=tempfile.gettempdir(),
            env={**os.environ, "EQUILIBRIUM_DIR": str(install_dir)},
            creationflags=_NO_WINDOW,
        )


def _windows_shortcuts(install_dir: Path, desktop: bool) -> list[str]:
    folders = ["Programs"] + (["Desktop"] if desktop else [])
    # Paths travel through environment variables so that an apostrophe in a
    # folder name cannot break out of the PowerShell script.
    script = (
        "[Console]::OutputEncoding = [Text.Encoding]::UTF8;"
        "$shell = New-Object -ComObject WScript.Shell;"
        "foreach ($folder in $env:EQ_FOLDERS.Split(',')) {"
        "  $path = Join-Path ([Environment]::GetFolderPath($folder)) 'Equilibrium.lnk';"
        "  $link = $shell.CreateShortcut($path);"
        "  $link.TargetPath = $env:EQ_TARGET;"
        "  $link.WorkingDirectory = $env:EQ_DIR;"
        "  $link.Save();"
        "  [Console]::Out.WriteLine($path)"
        "}"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        env={
            **os.environ,
            "EQ_FOLDERS": ",".join(folders),
            "EQ_TARGET": str(app_executable(install_dir)),
            "EQ_DIR": str(install_dir),
        },
        stdin=subprocess.DEVNULL,
        capture_output=True,
        encoding="utf-8-sig",  # Keeps non-English folder names intact.
        creationflags=_NO_WINDOW,
    )
    if result.returncode != 0:
        raise InstallError("Could not create the Start Menu shortcut.")
    return result.stdout.splitlines()


def _windows_register(install_dir: Path, version: str, size: int) -> None:
    """Add the app to Settings > Apps > Installed apps."""
    import winreg

    uninstaller = install_dir / UNINSTALLER_NAME
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _UNINSTALL_KEY) as key:
        for name, value in {
            "DisplayName": APP_NAME,
            "DisplayVersion": version,
            "Publisher": APP_NAME,
            "InstallLocation": str(install_dir),
            "DisplayIcon": str(app_executable(install_dir)),
            "UninstallString": f'"{uninstaller}" --uninstall',
        }.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "EstimatedSize", 0, winreg.REG_DWORD, size // 1024)


def _windows_unregister() -> None:
    import winreg

    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, _UNINSTALL_KEY)
    except FileNotFoundError:
        pass


def _xdg_data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def _desktop_entry(install_dir: Path) -> str:
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={APP_NAME}\n"
        "Comment=Battery management\n"
        f"Exec={shlex.quote(str(app_executable(install_dir)))}\n"
        "Terminal=false\n"
        "Categories=Utility;\n"
    )


def _linux_shortcuts(install_dir: Path, desktop: bool) -> list[str]:
    folders = [_xdg_data_home() / "applications"]
    if desktop:
        folders.append(Path.home() / "Desktop")

    created = []
    for folder in folders:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "equilibrium.desktop"
        path.write_text(_desktop_entry(install_dir), encoding="utf-8")
        path.chmod(0o755)
        created.append(str(path))
    return created
