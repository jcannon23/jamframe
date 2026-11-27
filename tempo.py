"""A song's tempo, so the sound waves can keep its speed.

Deezer's catalogue (free, no account; it is sent the song and artist names) lists a tempo for some songs.
For the rest we work it out from Deezer's 30-second preview clip: how regularly the loudness jumps.
The result is the song's speed, not where its beats fall. Half or double the true figure can come out;
on screen that still moves in time.

Usage: python tempo.py "Artist" "Song"
"""
import array
import math
import os
import shutil
import subprocess
import sys
import tempfile
import wave

RATE, HOP = 22050, 128      # the clip is read at this rate; loudness is measured every HOP samples (172 a second)


def tempo_of(samples, rate=RATE):
    """Beats a minute of mono 16-bit samples, between 70 and 180, or None for silence."""
    frames = len(samples) // HOP
    loud = [math.log1p(sum(abs(v) for v in samples[i * HOP:(i + 1) * HOP])) for i in range(frames)]
    rise = [max(0.0, b - a) for a, b in zip(loud, loud[1:])]          # only jumps up: the starts of notes and hits
    mean = sum(rise) / max(1, len(rise))
    rise = [v - mean for v in rise]
    if not any(rise):
        return None
    per_second = rate / HOP
    span = int(per_second * 60 / 70) * 4 + 1
    match = [sum(x * y for x, y in zip(rise, rise[lag:])) / (len(rise) - lag) for lag in range(span + 1)]
    best, scores = None, {}
    for lag in range(int(per_second * 60 / 180), int(per_second * 60 / 70) + 1):
        bpm = 60 * per_second / lag
        comb = sum(match[lag * n] for n in (1, 2, 3, 4))      # a true beat also lines up 2, 3 and 4 beats on
        scores[lag] = comb * math.exp(-0.5 * (math.log2(bpm / 115) / 0.9) ** 2)   # most music sits near here
        if best is None or scores[lag] > scores[best]:
            best = lag
    a, b, c = scores.get(best - 1, scores[best]), scores[best], scores.get(best + 1, scores[best])
    shift = 0.5 * (a - c) / (a - 2 * b + c) if a - 2 * b + c else 0                # finer than one step
    return round(60 * per_second / (best + shift), 1)


def decode(mp3):
    """MP3 bytes -> mono samples, with whichever converter this computer has; None with neither."""
    with tempfile.TemporaryDirectory() as tmp:
        src, out = os.path.join(tmp, "clip.mp3"), os.path.join(tmp, "clip.wav")
        with open(src, "wb") as f:
            f.write(mp3)
        if shutil.which("afconvert"):        # macOS
            cmd = ["afconvert", "-f", "WAVE", "-d", "LEI16@%d" % RATE, "-c", "1", src, out]
        elif shutil.which("ffmpeg"):
            cmd = ["ffmpeg", "-loglevel", "error", "-i", src, "-ac", "1", "-ar", str(RATE), out]
        else:
            return None
        if subprocess.run(cmd, capture_output=True, timeout=30).returncode:
            return None
        with wave.open(out) as w:
            return array.array("h", w.readframes(w.getnframes()))


def search(artist, title):
    """Deezer's best match for a song (its search record), or None. Exact names first, then loosely."""
    import requests
    ask = lambda q: requests.get("https://api.deezer.com/search", timeout=6, params={"q": q, "limit": 1}).json().get("data")
    found = ask('artist:"%s" track:"%s"' % (artist, title)) or ask(("%s %s" % (artist, title)).strip())
    return found[0] if found else None


def find_tempo(artist, title):
    """Beats a minute for a song, or None when it cannot be found."""
    import requests
    try:
        found = search(artist, title)
        if not found:
            return None
        track = requests.get("https://api.deezer.com/track/%s" % found["id"], timeout=6).json()
        if track.get("bpm"):
            return float(track["bpm"])
        if not track.get("preview"):
            return None
        samples = decode(requests.get(track["preview"], timeout=10).content)
        return tempo_of(samples) if samples else None
    except (OSError, ValueError, KeyError, subprocess.SubprocessError, wave.Error, EOFError):
        return None


if __name__ == "__main__":
    print(find_tempo(*sys.argv[1:3]) if len(sys.argv) > 2 else __doc__)
