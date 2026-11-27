"""Show the album cover of whatever a Sonos room is playing in the TV's art mode.

Music starts -> the muted cover goes up in BetterFrame's art mode.
Music stops  -> the TV goes back to the picture (or the off state) it had before.

Rooms come from settings.json: Sonos room name -> address of that room's TV, or null for no TV yet.
    "rooms": {"Playroom": "192.168.1.50", "Game Room": null}
Each room is followed on its own; rooms grouped in Sonos show the same cover. Every room's animated
page (see display.py) is served at http://<this-computer>:8765/?room=<room name>.
Rooms and everything else adjustable are edited at http://<this-computer>:8765/settings, live.

Usage: python watch.py
"""
import hashlib
import re
import json
import os
import signal
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from display import Display, room_settings, within
from tempo import find_tempo
from treat import treat_bytes

POLL = 3        # jamframe: polling, not UPnP event subscriptions; switch if 3 s lag ever matters
PREFIX = "nowplaying-"
TV_AUDIO = "x-sonos-htastream:"   # the soundbar playing the TV's own sound
# jamframe: prefixes as I know them, not yet tried against a real line-in or station
SOURCES = {"linein": ("x-rincon-stream:",), "radio": ("x-sonosapi-stream:", "x-rincon-mp3radio:")}


GRACE = 60


class Tv:
    """The slice of BetterFrame's REST API that we use."""

    def __init__(self, address):
        self.base = "http://" + (address if ":" in address else address + ":8080")

    def call(self, method, path, body=None):
        if isinstance(body, dict):
            body = json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=body, method=method)
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read() or b"null")


class Watcher:
    def __init__(self, tv, fetch=None):
        self.tv = tv
        self.fetch = fetch or download
        self.before = None   # the TV's state when we took over; None = not showing anything
        self.shown = None    # picture name we put on the TV
        self.art = None      # cover URL behind self.shown
        self.quiet_since = None
        self.grace = GRACE   # seconds of silence before the TV is restored

    def cleanup(self, keep=None):
        """Delete covers we uploaded, including ones a crashed run left behind."""
        for p in self.tv.call("GET", "/api/pictures"):
            if p["name"].startswith(PREFIX) and p["name"] != keep:
                self.tv.call("DELETE", "/api/pictures/" + urllib.parse.quote(p["name"]))

    def step(self, art, now=None):
        """art: cover URL of the music playing right now, or None."""
        now = time.time() if now is None else now
        if art:
            self.quiet_since = None
            if art != self.art:
                self.show(art)
        elif self.before:
            self.quiet_since = self.quiet_since or now
            if now - self.quiet_since >= self.grace:
                self.restore()

    def show(self, art):
        state = self.tv.call("GET", "/api/state")
        if self.before and state["mode"] != "art":
            self.release()            # someone switched to TV mid-album: let go
        if state["mode"] == "tv":
            return                    # never take the screen from someone watching TV
        if not self.before:
            self.before = {
                "mode": state["mode"],
                "picture": state.get("selected_picture"),
                "rotate": self.tv.call("GET", "/api/settings").get("rotate", True),
            }
            # or the slideshow would rotate away from the cover, and shuffle it in later
            self.tv.call("POST", "/api/settings", {"rotate": False})
        name = PREFIX + hashlib.sha1(art.encode()).hexdigest()[:10] + ".jpg"
        self.tv.call("PUT", "/api/pictures/" + name, treat_bytes(self.fetch(art)))
        self.tv.call("POST", "/api/art?picture=" + name)
        self.shown, self.art = name, art
        self.cleanup(keep=name)
        print("showing", art, flush=True)

    def restore(self):
        """Music is over: put the TV back the way it was."""
        before, shown = self.before, self.shown
        state = self.tv.call("GET", "/api/state")
        if state["mode"] == "art" and state.get("picture") == shown:
            if before["picture"]:
                self.tv.call("POST", "/api/picture?name=" + urllib.parse.quote(before["picture"]))
            if before["mode"] == "off":
                self.tv.call("POST", "/api/off")
        self.release()
        print("restored", flush=True)

    def release(self):
        if self.before:
            self.tv.call("POST", "/api/settings", {"rotate": self.before["rotate"]})
        self.before = self.shown = self.art = self.quiet_since = None
        self.cleanup()


def download(url):
    """Cover bytes. requests (installed with soco) brings its own root certificates; this Python's urllib has none."""
    import requests
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    return r.content


def seconds(clock):
    """ "0:03:25" -> 205; None for anything else (radio reports NOT_IMPLEMENTED)."""
    try:
        h, m, s = (int(x) for x in clock.split(":"))
        return h * 3600 + m * 60 + s
    except (AttributeError, ValueError):
        return None


def parse_lyrics(found, duration):
    """An lrclib.net record -> [[seconds, line], ...], or None.
    Timed lyrics are used as they are. Untimed ones are spread evenly over the song: close enough to follow."""
    timed = re.findall(r"\[(\d+):(\d+(?:\.\d+)?)\] ?(.*)", found.get("syncedLyrics") or "")
    if timed:
        return [[int(m) * 60 + float(s), text.strip()] for m, s, text in timed]
    plain = [line.strip() for line in (found.get("plainLyrics") or "").splitlines() if line.strip()]
    if not plain or not duration:
        return None
    start, end = duration * 0.08, duration * 0.95
    return [[round(start + (end - start) * i / len(plain), 1), line] for i, line in enumerate(plain)]


def find_lyrics(info, duration):
    """Look the song up at lrclib.net (free, no account). Only the song, artist and album names are sent."""
    import requests
    try:
        r = requests.get("https://lrclib.net/api/get", timeout=6, headers={"User-Agent": "JamFrame"},
                         params={"track_name": info["title"], "artist_name": info["artist"], "album_name": info["album"]})
        return parse_lyrics(r.json(), duration) if r.ok else None
    except (OSError, ValueError):
        return None


SKIES = [((0,), "clear", "Clear"), ((1, 2), "partly", "Partly cloudy"), ((3,), "cloud", "Cloudy"),
         ((45, 48), "fog", "Fog"), ((51, 53, 55, 56, 57), "rain", "Drizzle"), ((61, 63, 65, 66, 67, 80, 81, 82), "rain", "Rain"),
         ((71, 73, 75, 77, 85, 86), "snow", "Snow"), ((95, 96, 99), "storm", "Thunderstorm")]   # WMO weather codes
_weather = {"for": None, "at": 0, "now": None}


def find_weather(wanted):
    """The weather for settings' {"on", "place", "unit"}, from open-meteo.com (free, no account; it is sent the
    place name, then its coordinates). Asked at most every 15 minutes. None when off, {"error": ...} when it fails."""
    if not wanted["on"] or not wanted["place"].strip():
        return None
    key = (wanted["place"], wanted["unit"])
    if _weather["for"] == key and time.time() - _weather["at"] < 900:
        return _weather["now"]
    import requests
    try:
        name, _, region = (part.strip() for part in wanted["place"].partition(","))
        places = requests.get("https://geocoding-api.open-meteo.com/v1/search", timeout=6,
                              params={"name": name, "count": 10}).json().get("results") or []
        if not places:
            now = {"error": "No place called “%s” found." % wanted["place"]}
        else:
            match = lambda p: region.lower() in (p.get("admin1", "") + " " + p.get("country", "") + " " + p.get("country_code", "")).lower()
            place = next((p for p in places if region and match(p)), places[0])
            w = requests.get("https://api.open-meteo.com/v1/forecast", timeout=6, params={
                "latitude": place["latitude"], "longitude": place["longitude"], "current": "temperature_2m,weather_code,is_day",
                "daily": "temperature_2m_max,temperature_2m_min", "forecast_days": 1, "timezone": "auto",
                "temperature_unit": "fahrenheit" if wanted["unit"] == "F" else "celsius"}).json()
            sky = next((s for s in SKIES if w["current"]["weather_code"] in s[0]), SKIES[2])
            now = {"temp": round(w["current"]["temperature_2m"]), "sky": sky[1], "text": sky[2],
                   "night": not w["current"]["is_day"], "high": round(w["daily"]["temperature_2m_max"][0]),
                   "low": round(w["daily"]["temperature_2m_min"][0]),
                   "place": ", ".join(x for x in (place["name"], place.get("admin1")) if x)}
    except (OSError, ValueError, KeyError, IndexError):
        if _weather["for"] == key and _weather["now"]:
            return _weather["now"]       # a failed refresh: the last reading is better than none
        now = {"error": "The weather service is not answering."}
    _weather.update({"for": key, "at": time.time(), "now": now})
    return now


def now_playing(room, ignore=()):
    """(cover URL, {title, artist, album}, seconds in, length) if the room is playing music with a cover, else None.
    ignore: names from SOURCES that do not count as music."""
    player = room.group.coordinator if room.group else room
    if player.get_current_transport_info()["current_transport_state"] != "PLAYING":
        return None
    track = player.get_current_track_info()
    skip = (TV_AUDIO,) + tuple(p for name in ignore for p in SOURCES.get(name, ()))
    if track.get("uri", "").startswith(skip) or not track.get("album_art"):
        return None
    info = {k: track.get(k) or "" for k in ("title", "artist", "album")}
    return track["album_art"], info, seconds(track.get("position")), seconds(track.get("duration"))


class Room:
    """One Sonos room: its animated page, and its TV's BetterFrame if it has one."""

    def __init__(self, name, tv_address, fetch):
        self.name, self.tv = name, tv_address
        self.speaker = None      # found later: a speaker may be off, or not bought yet
        self.display = Display(fetch, room=name)
        self.watcher = Watcher(Tv(tv_address), fetch) if tv_address else None
        self.held, self.heard = (None, None), 0   # the page keeps the cover through pauses shorter than the grace too
        self.clean = False
        self.error = None        # why the last round failed, for the settings page
        self.song = None         # the song self.display.lyrics was looked up for
        self.beat = None         # the song self.display.tempo was looked up for

    def tick(self, conf):
        """conf: all settings."""
        mine = room_settings(conf, self.name)
        if self.watcher and not self.clean:
            self.watcher.cleanup()
            self.clean = True
        playing = now_playing(self.speaker, conf["ignore"]) if self.speaker else None
        if within(mine["quiet"]):
            playing, self.heard = None, 0
        self.display.position = playing and playing[2] is not None and (playing[2], time.time()) or None
        if playing:
            self.held, self.heard = playing[:2], time.time()
            song = mine["lyrics"] != "off" and playing[1]
            if song != self.song:        # looked up once per song, found or not
                self.song = song
                self.display.lyrics = find_lyrics(song, playing[3]) if song and song["title"] else None
            beat = mine["waves"] != "off" and playing[1]
            if beat != self.beat:        # the tempo takes a second or two to work out: not in this loop
                self.beat, self.display.tempo = beat, None
                if beat and beat["title"]:
                    def look_up(display=self.display, wanted=beat):
                        found = find_tempo(wanted["artist"], wanted["title"])
                        if self.beat == wanted:
                            display.tempo = found
                    threading.Thread(target=look_up, daemon=True).start()
        self.display.update(*(self.held if time.time() - self.heard < mine["grace"] else (None, None)))
        if self.watcher:
            self.watcher.grace = mine["grace"]
            self.watcher.step(playing and playing[0])

    def status(self):
        return {"speaker": bool(self.speaker), "playing": self.display.info if self.display.url else None,
                "tv": self.tv, "error": self.error, "app": time.time() - self.display.tv_seen < 15}


if __name__ == "__main__":
    import soco

    from display import PORT, serve, settings

    rooms, displays, speakers = {}, {}, {}   # by Sonos room name; speakers are the ones found so far

    def let_go(room):
        if room.watcher and room.watcher.before:
            room.watcher.restore()

    weather = {}     # read by the pages; refreshed in the loop below so a slow answer never holds a page up
    serve(displays, speakers=speakers, status=lambda: {name: r.status() for name, r in list(rooms.items())},
          weather=lambda: weather.get("now"))
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))   # so `finally` runs under launchd too
    print("settings at http://localhost:%d/settings" % PORT, flush=True)
    looked = 0
    try:
        while True:
            conf = settings()        # re-read every round: the settings page changes it
            weather["now"] = find_weather(conf["weather"])
            for name in [n for n, r in rooms.items() if n not in conf["rooms"] or conf["rooms"][n] != r.tv]:
                room = rooms.pop(name)       # removed, or given a different TV
                del displays[name]
                try:
                    let_go(room)
                except OSError as e:
                    print("%s: could not restore its TV: %s" % (name, e), flush=True)
            for name, tv in conf["rooms"].items():
                if name not in rooms:
                    rooms[name] = Room(name, tv, download)
                    displays[name] = rooms[name].display
                    looked = 0
                    print("following:", name, flush=True)
            if (not speakers or any(not r.speaker for r in rooms.values())) and time.time() - looked > 60:
                looked = time.time()
                speakers.update({z.player_name: z for z in soco.discover(timeout=3) or []})
            for r in rooms.values():
                if not r.speaker and r.name in speakers:
                    r.speaker = speakers[r.name]
                    print("found speaker:", r.name, flush=True)
                try:
                    r.tick(conf)
                    r.error = None
                except (OSError, soco.exceptions.SoCoException) as e:
                    if str(e) != r.error:    # TV asleep, speaker rebooting, Wi-Fi blip: say it once, keep trying
                        print("%s: retrying after: %s" % (r.name, e), flush=True)
                    r.error = str(e)
            time.sleep(POLL)
    finally:
        for r in rooms.values():
            let_go(r)
