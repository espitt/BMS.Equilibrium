"""Plays a startup sound on Windows at full system volume, then puts the volume back.

Uses only the standard library: winsound for playback (WAV files) and the Windows Core Audio
API through ctypes for the volume, so nothing extra has to be bundled.
"""

from __future__ import annotations

import ctypes
import sys
import uuid
import wave
from pathlib import Path

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication

_CLSCTX_ALL = 23
_E_RENDER = 0  # Output devices.
_E_CONSOLE = 1  # The default device for general sounds.


class _GUID(ctypes.Structure):
    _fields_ = [("data", ctypes.c_ubyte * 16)]


def _guid(text: str) -> _GUID:
    guid = _GUID()
    ctypes.memmove(guid.data, uuid.UUID(text).bytes_le, 16)
    return guid


_CLSID_MMDEVICE_ENUMERATOR = _guid("BCDE0395-E52F-467C-8E3D-C4579291692E")
_IID_IMMDEVICE_ENUMERATOR = _guid("A95664D2-9614-4F35-A746-DE8DB63617E6")
_IID_IAUDIO_ENDPOINT_VOLUME = _guid("5CDF2C82-841E-4546-9722-0CF74078229A")


def _call(obj: ctypes.c_void_p, index: int, *args, argtypes=(), restype=ctypes.HRESULT):
    """Call method number ``index`` of a COM object. A failed HRESULT raises OSError."""
    vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
    prototype = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
    return prototype(vtable[index])(obj, *args)


def _release(obj: ctypes.c_void_p) -> None:
    if obj:
        _call(obj, 2, restype=ctypes.c_ulong)


class SystemVolume:
    """Master volume and mute of the default speakers (IAudioEndpointVolume)."""

    def __init__(self) -> None:
        ole32 = ctypes.oledll.ole32
        try:
            ole32.CoInitialize(None)
        except OSError:
            pass  # Qt has already set COM up for this thread, which is all that is needed.
        enumerator = ctypes.c_void_p()
        ole32.CoCreateInstance(
            ctypes.byref(_CLSID_MMDEVICE_ENUMERATOR),
            None,
            _CLSCTX_ALL,
            ctypes.byref(_IID_IMMDEVICE_ENUMERATOR),
            ctypes.byref(enumerator),
        )
        device = ctypes.c_void_p()
        try:  # IMMDeviceEnumerator::GetDefaultAudioEndpoint
            _call(enumerator, 4, _E_RENDER, _E_CONSOLE, ctypes.byref(device),
                  argtypes=(ctypes.c_int, ctypes.c_int, ctypes.c_void_p))
        finally:
            _release(enumerator)
        self._volume = ctypes.c_void_p()
        try:  # IMMDevice::Activate
            _call(device, 3, ctypes.byref(_IID_IAUDIO_ENDPOINT_VOLUME), _CLSCTX_ALL, None,
                  ctypes.byref(self._volume),
                  argtypes=(ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p))
        finally:
            _release(device)

    def get(self) -> tuple[float, bool]:
        """The current level (0.0 to 1.0) and whether the speakers are muted."""
        level, muted = ctypes.c_float(), ctypes.c_int()
        _call(self._volume, 9, ctypes.byref(level), argtypes=(ctypes.c_void_p,))
        _call(self._volume, 15, ctypes.byref(muted), argtypes=(ctypes.c_void_p,))
        return level.value, bool(muted.value)

    def set(self, level: float, muted: bool) -> None:
        _call(self._volume, 7, level, None, argtypes=(ctypes.c_float, ctypes.c_void_p))
        _call(self._volume, 14, int(muted), None, argtypes=(ctypes.c_int, ctypes.c_void_p))

    def close(self) -> None:
        _release(self._volume)
        self._volume = ctypes.c_void_p()


def _duration_ms(path: Path) -> int:
    with wave.open(str(path), "rb") as audio:
        return round(audio.getnframes() * 1000 / audio.getframerate())


class StartupSound(QObject):
    """Turns the speakers up to 100%, plays the sound, and restores the volume afterwards.

    The volume is put back when the sound ends or the app quits, unless the user changed it
    while the sound was playing. Any failure is ignored: a sound must never stop the app opening.
    """

    def __init__(self, path: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.path = path
        self.playing = False
        self.volume: SystemVolume | None = None
        self.saved: tuple[float, bool] | None = None

    def play(self) -> None:
        if sys.platform != "win32" or self.playing:
            return
        import winsound

        try:
            duration = _duration_ms(self.path)
        except (OSError, wave.Error, ZeroDivisionError):
            return
        try:
            self.volume = SystemVolume()
            self.saved = self.volume.get()
            self.volume.set(1.0, False)
        except Exception:  # No speakers, or the audio service is unavailable: play anyway.
            self._forget_volume()
        try:
            winsound.PlaySound(
                str(self.path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT
            )
        except RuntimeError:
            self._restore_volume()
            return
        self.playing = True
        QTimer.singleShot(duration + 500, self, self.stop)
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.stop)

    def stop(self) -> None:
        if not self.playing:
            return
        self.playing = False
        import winsound

        winsound.PlaySound(None, 0)
        self._restore_volume()

    def _restore_volume(self) -> None:
        if self.volume is not None and self.saved is not None:
            try:
                level, muted = self.volume.get()
                if abs(level - 1.0) < 0.01 and not muted:  # Leave it if the user has changed it.
                    self.volume.set(*self.saved)
            except Exception:
                pass
        self._forget_volume()

    def _forget_volume(self) -> None:
        if self.volume is not None:
            try:
                self.volume.close()
            except Exception:
                pass
        self.volume = None
        self.saved = None
