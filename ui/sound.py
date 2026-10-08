"""Optional, subtle sound effects.

* Off by default; the preference (on/off and volume) is saved with the profile.
* The tones are generated here in Python (sine waves with soft fades), so no third-party
  audio files or licences are involved.
* Each event has a unique id and plays at most once: the hidden <audio autoplay> element is
  rendered only on the run right after the event and then removed, so Streamlit reruns never
  replay it.
* Browsers may block autoplay. A blocked sound fails silently inside the browser and never
  affects the quiz; every sound event also has visible feedback on screen.
"""
from __future__ import annotations

import io
import math
import struct
import wave
from functools import lru_cache

import streamlit as st

RATE = 22_050
# (frequency Hz, duration s) sequences — short and gentle, no countdowns or loops.
PATTERNS = {
    "correct": ((659.25, 0.09), (880.00, 0.14)),
    "incorrect": ((293.66, 0.12), (246.94, 0.18)),
    "complete": ((523.25, 0.10), (659.25, 0.10), (783.99, 0.22)),
    "preview": ((659.25, 0.09), (880.00, 0.14)),
}


@lru_cache(maxsize=64)
def tone(kind: str, volume: int) -> bytes:
    """A mono 16-bit WAV for `kind` at `volume` (0–100), capped at 35% of full scale."""
    amplitude = 0.35 * max(0, min(volume, 100)) / 100 * 32767
    frames = bytearray()
    for freq, seconds in PATTERNS[kind]:
        n = int(RATE * seconds)
        fade = max(1, int(RATE * 0.012))
        for i in range(n):
            envelope = min(1.0, i / fade, (n - i) / fade)
            frames += struct.pack("<h", int(amplitude * envelope * math.sin(2 * math.pi * freq * i / RATE)))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(bytes(frames))
    return buffer.getvalue()


def enabled() -> bool:
    return bool(st.session_state.get("sound_enabled", False)) and st.session_state.get("sound_volume", 0) > 0


def play_event(event: dict | None) -> bool:
    """Play a quiz feedback event once. Returns True if an audio element was rendered."""
    if not event or not enabled():
        return False
    played = st.session_state.setdefault("sounds_played", [])
    if event["id"] in played:
        return False
    played.append(event["id"])
    del played[:-50]
    _render(event["kind"], st.session_state.get("sound_volume", 40))
    return True


def play_preview(token: int, volume: int) -> bool:
    """Play the preview for a specific button press (token) once, at the chosen volume."""
    if not token or not volume or st.session_state.get("sound_preview_played") == token:
        return False
    st.session_state.sound_preview_played = token
    _render("preview", volume)
    return True


def _render(kind: str, volume: int) -> None:
    with st.container(key=f"sound_player_{kind}"):  # hidden by CSS; the audio still plays
        st.audio(tone(kind, volume), format="audio/wav", autoplay=True)
