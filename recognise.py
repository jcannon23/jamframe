"""Name a song from a few seconds of its sound, with Shazam.

For music that arrives with no name: a record on a turntable. The sound is turned into a fingerprint on this
computer; the fingerprint, not the sound, is sent to Shazam, through the open-source shazamio library. This is
not a service Shazam offers to other programs, so it may stop working without notice.

Usage: python recognise.py clip.flac
"""
import asyncio
import os
import shutil
import subprocess
import sys
import tempfile


def recognise(audio, kind="flac"):
    """audio: a sound file's bytes. Returns {"title", "artist", "album", "art", "offset"} or None.
    offset: how many seconds into the song the clip began."""
    try:
        import certifi
        os.environ.setdefault("SSL_CERT_FILE", certifi.where())     # this Python has no root certificates of its own
        import warnings
        warnings.filterwarnings("ignore", message="Couldn't find ffmpeg")     # pydub's; we convert the sound ourselves
        from shazamio import Shazam
    except ImportError:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        src, wav = os.path.join(tmp, "clip." + kind), os.path.join(tmp, "clip.wav")
        with open(src, "wb") as f:
            f.write(audio)
        if shutil.which("afconvert"):       # macOS
            cmd = ["afconvert", "-f", "WAVE", "-d", "LEI16@44100", "-c", "2", src, wav]
        elif shutil.which("ffmpeg"):
            cmd = ["ffmpeg", "-loglevel", "error", "-i", src, "-ac", "2", "-ar", "44100", wav]
        else:
            return None
        try:
            if subprocess.run(cmd, capture_output=True, timeout=30).returncode:
                return None
            found = asyncio.run(Shazam().recognize(wav))
        except Exception:                   # the network, Shazam changing its mind, a clip it cannot read
            return None
    track = found.get("track")
    if not track or not found.get("matches"):
        return None
    album = next((m.get("text") for s in track.get("sections", []) for m in s.get("metadata", [])
                  if m.get("title") == "Album"), "")
    art = (track.get("images") or {}).get("coverarthq") or (track.get("images") or {}).get("coverart")
    return {"title": track.get("title", ""), "artist": track.get("subtitle", ""), "album": album or "",
            "art": art and art.replace("400x400cc", "1000x1000cc"),     # the same picture, sharper
            "offset": found["matches"][0].get("offset") or 0}


if __name__ == "__main__":
    print(recognise(open(sys.argv[1], "rb").read(), sys.argv[1].rsplit(".", 1)[-1]) if len(sys.argv) > 1 else __doc__)
