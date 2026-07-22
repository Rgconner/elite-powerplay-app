"""Sound action — play a short beep on the host machine.

The implementation picks the right tool at runtime:

* On Linux with PulseAudio / ALSA: prefer ``paplay``, fall back to ``play``,
  fall back to a terminal bell character.
* On Windows: ``winsound.Beep``.
* On macOS: ``afplay`` with a built-in system sound, or ``osascript``.
* Anywhere: the terminal bell ``\\a`` as a last resort.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import time
from typing import Any, Dict

from ..models import SoundAction

log = logging.getLogger(__name__)


def _play_linux(wav: str, freq: int, duration_ms: int) -> bool:
    if wav and shutil.which("paplay"):
        try:
            subprocess.run(["paplay", wav], check=False, timeout=5)
            return True
        except (OSError, subprocess.SubprocessError) as e:
            log.debug("paplay failed: %s", e)
    if wav and shutil.which("aplay"):
        try:
            subprocess.run(["aplay", wav], check=False, timeout=5)
            return True
        except (OSError, subprocess.SubprocessError) as e:
            log.debug("aplay failed: %s", e)
    if shutil.which("speaker-test"):
        try:
            subprocess.run(
                ["speaker-test", "-t", "sine", "-f", str(freq), "-l", "1"],
                check=False, timeout=5,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return True
        except (OSError, subprocess.SubprocessError) as e:
            log.debug("speaker-test failed: %s", e)
    return False


def _play_macos(wav: str) -> bool:
    if wav and shutil.which("afplay"):
        try:
            subprocess.run(["afplay", wav], check=False, timeout=5)
            return True
        except (OSError, subprocess.SubprocessError) as e:
            log.debug("afplay failed: %s", e)
    return False


def _play_windows(freq: int, duration_ms: int) -> bool:
    if sys.platform.startswith("win"):
        try:
            import winsound  # type: ignore
            winsound.Beep(int(freq), int(duration_ms))
            return True
        except (ImportError, RuntimeError) as e:
            log.debug("winsound.Beep failed: %s", e)
    return False


class SoundActionHandler:
    """Play a beep / wav file."""

    def __call__(self, action: SoundAction, context: Dict[str, Any]) -> None:
        wav = action.wav or ""
        freq = int(action.frequency_hz or 1000)
        duration_ms = int(action.duration_ms or 300)
        played = False
        if sys.platform.startswith("win"):
            played = _play_windows(freq, duration_ms)
        elif sys.platform == "darwin":
            played = _play_macos(wav)
        else:
            played = _play_linux(wav, freq, duration_ms)
        if not played:
            # Last-resort terminal bell.
            try:
                sys.stderr.write("\a")
                sys.stderr.flush()
            except Exception:  # noqa: BLE001
                pass
        log.info("sound_action: wav=%r freq=%d dur=%dms played=%s context=%s",
                 wav, freq, duration_ms, played,
                 {k: v for k, v in context.items() if k in ("alert_id", "job_id")})


__all__ = ["SoundActionHandler"]
