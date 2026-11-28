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
import html
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

from display import Display, look, room_settings, within
import tempo
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
        self.look = None     # how the still is made: display.look() of the TV's room
        self.made = None     # what the still on the TV was made with: see style()
        self.info = None     # the song's title, artist and album, for the still's caption

    def cleanup(self, keep=None):
        """Delete covers we uploaded, including ones a crashed run left behind."""
        for p in self.tv.call("GET", "/api/pictures"):
            if p["name"].startswith(PREFIX) and p["name"] != keep:
                self.tv.call("DELETE", "/api/pictures/" + urllib.parse.quote(p["name"]))

    def step(self, art, now=None, info=None):
        """art: cover URL of the music playing right now, or None. info: its title, artist and album."""
        now = time.time() if now is None else now
        self.info = info if art else None
        if art:
            self.quiet_since = None
            if art != self.art or self.style() != self.made:      # a new cover, or the same one restyled
                self.show(art)
        elif self.before:
            self.quiet_since = self.quiet_since or now
            if now - self.quiet_since >= self.grace:
                self.restore()

    def style(self):
        """Everything the still depends on: when any of it changes, the still is made again."""
        look, made = self.look or {}, {}
        for k in ("mute", "mat", "cover", "grain", "scale", "caption", "align", "fields", "size"):
            made[k] = look.get(k)
        if look.get("caption") and self.info:        # a captioned still is the song's, not just the album's
            made["words"] = {k: self.info.get(k, "") for k in ("title", "artist", "album") if k in (look.get("fields") or [])}
        return made

    def still(self, art, made):
        look = {k: v for k, v in made.items() if v is not None and k != "words"}
        return treat_bytes(self.fetch(art), look, made.get("words"))

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
        made = self.style()
        name = PREFIX + hashlib.sha1((art + json.dumps(made, sort_keys=True)).encode()).hexdigest()[:10] + ".jpg"
        self.tv.call("PUT", "/api/pictures/" + name, self.still(art, made))
        self.made = made
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


FRAMES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frame.json")


class FrameWatcher(Watcher):
    """The same job on a Samsung Frame, through its own art mode: the cover is uploaded as one of "My Photos",
    shown, and afterwards the picture that was up is put back and ours deleted. Nothing is installed on the TV.
    It only ever acts while the TV is showing art: a Frame that is being watched, or is off, is left alone."""

    def __init__(self, address, fetch=None, connect=None, memory=FRAMES):
        super().__init__(None, fetch)
        self.address, self.memory = address, memory
        self.connect = connect      # address -> an open samsungtvws SamsungTVArt (or a stand-in, in check.py)
        self.rest_until, self.why = 0, None

    def frame(self):
        """An open connection to the TV. After a failure, the next tries are refused for a while without
        knocking: a Frame that is off answers nothing, and waiting on it would hold up every other room."""
        if time.time() < self.rest_until:
            raise OSError(self.why)
        try:
            if self.connect:
                return self.connect(self.address)
            import urllib3
            from samsungtvws.art import SamsungTVArt
            urllib3.disable_warnings()      # the TV's own certificate is self-signed; there is nothing to check it against
            tv = SamsungTVArt(self.address, port=8002, timeout=8, name="JamFrame",
                              token_file=os.path.join(os.path.dirname(self.memory), "frame-token-" + self.address))
            tv.open()
            return tv
        except Exception as e:              # the library raises its own errors, the socket's, and plain ones
            self.rest_until, self.why = time.time() + 30, "Samsung Frame at %s: %s" % (self.address, e or type(e).__name__)
            raise OSError(self.why)

    def ours(self, keep=...):
        """The pictures we have uploaded to this TV and not yet deleted; with keep, set that list."""
        try:
            with open(self.memory) as f:
                known = json.load(f)
        except (OSError, ValueError):
            known = {}
        if keep is not ...:
            known[self.address] = keep
            with open(self.memory, "w") as f:
                json.dump(known, f)
        return known.get(self.address, [])

    def cleanup(self, keep=None):
        """Delete covers we uploaded, including ones a crashed run left behind."""
        stale = [i for i in self.ours() if i != keep]
        if stale:
            tv = self.frame()
            try:
                tv.delete_list(stale)
            except Exception as e:
                raise OSError("Samsung Frame: %s" % e)
            finally:
                tv.close()
        self.ours([keep] if keep else [])

    def show(self, art):
        tv = self.frame()
        try:
            if tv.get_artmode() != "on":        # someone is watching TV (or just switched to it mid-album)
                self.rest_until, self.why = time.time() + 15, None
                if self.before:
                    self.before = self.shown = self.art = self.made = self.quiet_since = None
                return
            if not self.before:
                self.before = {"picture": tv.get_current().get("content_id")}
            made = self.style()
            new = tv.upload(self.still(art, made), matte="none", portrait_matte="none", file_type="jpg")    # our mat is in the picture
            self.ours(self.ours() + [new])      # written down before it is shown, in case we stop right here
            tv.select_image(new, show=True)
            self.shown, self.art, self.made = new, art, made
        except OSError:
            raise
        except Exception as e:
            raise OSError("Samsung Frame: %s" % e)
        finally:
            tv.close()
        self.cleanup(keep=self.shown)
        print("showing", art, flush=True)

    def restore(self):
        """Music is over: put back the picture that was up."""
        tv = self.frame()
        try:
            showing = tv.get_artmode() == "on" and tv.get_current().get("content_id") == self.shown
            if showing and self.before["picture"]:
                tv.select_image(self.before["picture"], show=True)
        except Exception as e:
            raise OSError("Samsung Frame: %s" % e)
        finally:
            tv.close()
        self.release()
        print("restored", flush=True)

    def release(self):
        self.before = self.shown = self.art = self.made = self.quiet_since = None
        self.cleanup()


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


_covers = {}     # (artist, title, album) -> (cover URL or None, the album it is from, when asked)


def find_cover(artist, title, album="", sure=False):
    """A sharp cover for a song that arrived without one, or with a small one, as radio does: Deezer's, found
    by name (it is sent the song, artist and album names). None when it has no match; asked again after ten minutes.
    sure: only a cover from the album named. Songs sit on many records, and a live album's cover is the wrong one."""
    key = (artist, title, album)
    if key not in _covers or (not _covers[key][0] and time.time() - _covers[key][2] > 600):
        try:
            hit = tempo.search(artist, title, album) or {}
            _covers[key] = ((hit.get("album") or {}).get("cover_xl"), (hit.get("album") or {}).get("title", ""), time.time())
        except (OSError, ValueError):
            _covers[key] = (None, "", time.time())
    url, from_album = _covers[key][:2]
    plain = lambda text: re.sub(r"[^a-z0-9]", "", text.lower())
    same = album and from_album and (plain(album) in plain(from_album) or plain(from_album) in plain(album))
    return url if url and (same or not sure) else None


RADIO = ("x-sonosapi-hls:", "x-sonosapi-stream:", "x-sonosapi-radio:", "x-rincon-mp3radio:")   # SiriusXM is the first
_stations = {}   # stream URI -> (station name, its logo URL)
art_in = lambda didl: html.unescape((re.search(r"<upnp:albumArtURI>([^<]+)<", didl or "") or [None, ""])[1])


def station(player, uri):
    """(name, logo URL) of the radio station a player is tuned to, e.g. ("CH 25 - Classic Rewind", "https://...")."""
    if uri not in _stations:
        meta = player.avTransport.GetMediaInfo([("InstanceID", 0)]).get("CurrentURIMetaData") or ""
        name = html.unescape((re.search(r"<dc:title>([^<]+)<", meta) or [None, ""])[1])
        _stations[uri] = (name, art_in(meta))
    return _stations[uri]


def now_playing(room, ignore=()):
    """(cover URL, {title, artist, album}, seconds in, length, station) if the room is playing music, else None.
    Seconds in and length are None when the source does not say (AirPlay, radio); station is the radio
    station's (name, logo URL), None for anything else.
    ignore: names from SOURCES that do not count as music."""
    player = room.group.coordinator if room.group else room
    if player.get_current_transport_info()["current_transport_state"] != "PLAYING":
        return None
    track = player.get_current_track_info()
    skip = (TV_AUDIO,) + tuple(p for name in ignore for p in SOURCES.get(name, ()))
    if track.get("uri", "").startswith(skip):
        return None
    info = {k: track.get(k) or "" for k in ("title", "artist", "album")}
    on_air = station(player, track["uri"]) if track.get("uri", "").startswith(RADIO) else None
    # SiriusXM's app over AirPlay packs it differently: the album is the channel ("Ch 28 · The Spectrum"), the
    # artist is the show, and the song is "Artist - Song". Unpacked, lyrics and tempo can find the song too.
    channel = None if on_air else re.fullmatch(r"Ch\.? ?(\d+) ?[·\-–] ?(.+)", info["album"])
    if channel:
        on_air = ("CH %s - %s" % channel.groups(), "")          # no logo comes over AirPlay
        artist, dash, song = info["title"].partition(" - ")
        info = {"title": song, "artist": artist, "album": ""} if dash else dict(info, album="")
    # Best picture first: what Sonos has; a sharp cover found by name, if it is from the right album; the one
    # the station sent with the song (small, but right); any cover found by name; the station's logo, as during
    # talk and adverts.
    sent, named = art_in(track.get("metadata")), (info["artist"], info["title"], info["album"])
    art = (track.get("album_art") or (info["title"] and sent and find_cover(*named, sure=True)) or sent
           or (info["title"] and find_cover(*named)) or (on_air and on_air[1]))
    if not art:
        return None
    length, at = seconds(track.get("duration")), seconds(track.get("position"))
    # radio gives no length but does count from the start of each song; all zeros means the source says nothing
    return art, info, at if length or at else None, length or None, on_air


class Spinner:
    """Names the record a Control4 room is playing, by listening: a few seconds of the room's audio, taken off
    the network (c4audio) and put to Shazam (recognise). It listens when a record starts and again when the
    song should be over, not all the time. One song found carries a while: a quiet passage or a crackly groove
    is no reason to blank the screen."""
    hearing = threading.Lock()      # one listen at a time: an audio client has one pair of ports

    def __init__(self):
        self.found = None           # {"art", "info", "offset", "heard", "duration"} of the song last named
        self.again, self.misses, self.busy = 0, 0, False

    def tick(self, control4, room_id):
        """Called every round while the room plays something with no name. Returns what to show, or None."""
        if not self.busy and time.time() >= self.again:
            self.busy = True
            threading.Thread(target=self.listen, args=(control4, room_id), daemon=True).start()
        return self.found

    def listen(self, control4, room_id):
        import socket

        import c4audio
        from recognise import recognise
        try:
            where = control4.analogue_stream(room_id)
            if not where:               # nothing on the network: the room has it to itself, or the needle is up
                self.again = time.time() + 30
                return
            probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            probe.connect((where[0], 6000))     # no packet is sent: this only finds our address on that network
            me = probe.getsockname()[0]
            probe.close()
            with Spinner.hearing:
                began = time.time()
                sound = c4audio.listen(where[0], where[1], 9, me)
            song = sound and recognise(sound)
            if not song:
                self.misses += 1
                self.again = time.time() + 25
                if self.misses >= 6:    # some minutes of nothing we know: the side is over, or it is not music
                    self.found = None
                return
            hit = tempo.search(song["artist"], song["title"], song["album"]) or {}
            length = hit.get("duration") or None
            art = song["art"] or find_cover(song["artist"], song["title"], song["album"])
            self.misses = 0
            self.found = art and {"art": art, "info": {k: song[k] for k in ("title", "artist", "album")},
                                  "offset": max(0, song["offset"]), "heard": began, "duration": length}
            left = length - max(0, song["offset"]) - (time.time() - began) if length else 0
            self.again = time.time() + (max(20, min(left + 8, 600)) if length else 90)   # as this song should end
            print("heard:", song["title"], "by", song["artist"], flush=True)
        except OSError as e:
            self.again = time.time() + 60
            print("listening failed:", e, flush=True)
        finally:
            self.busy = False

    def stop(self):
        self.found, self.again, self.misses = None, 0, 0


spinners = {}    # Control4 room id -> its Spinner


class Room:
    """One Sonos room: its animated page, and its TV's BetterFrame if it has one."""

    def __init__(self, name, tv_address, fetch):
        self.name, self.tv = name, tv_address
        self.speaker = None      # found later: a speaker may be off, or not bought yet
        self.c4 = None           # or the Control4 room of this name, when there is no Sonos speaker called it
        self.ahead = None        # the next song, when the room's source says
        self.display = Display(fetch, room=name)
        self.watcher = (None if not tv_address
                        else FrameWatcher(tv_address[len("samsung:"):], fetch) if tv_address.startswith("samsung:")
                        else Watcher(Tv(tv_address), fetch))
        self.held, self.heard = (None, None), 0   # the page keeps the cover through pauses shorter than the grace too
        self.clean = False
        self.error = None        # why the last round failed, for the settings page
        self.song = None         # the song self.display.lyrics was looked up for
        self.beat = None         # the song self.display.tempo was looked up for
        self.began = (None, 0)   # (song, when we first saw it): our own clock for sources that give no position

    def listen(self, conf, control4, find=None):
        """What this room should show, as now_playing() gives it: its own music, from its Sonos speaker or its
        Control4 room; failing that, the music of the rooms it also hears (settings' "hears"), in order.
        find: room name -> (Sonos speaker or None, Control4 room id or None), for those other rooms."""
        sources = [(self.speaker, self.c4)] + [find(name) for name in conf["hears"].get(self.name, []) if find]
        for speaker, room_id in sources:
            self.ahead = None
            if speaker:
                playing = now_playing(speaker, conf["ignore"])
            else:
                found = control4.now_playing(room_id) if control4 and room_id is not None else None
                info = found and found["info"]
                art = found and (found["art"] or find_cover(info["artist"], info["title"], info["album"]))
                playing = art and (art, info, None, found["duration"], found["station"] and (found["station"], ""))
                self.ahead = playing and found["next"]
                named = control4.source(room_id) if control4 and room_id is not None and not found else None
                if named and named in conf["by_ear"]:           # a record: no name comes with it, so listen
                    spun = spinners.setdefault(room_id, Spinner()).tick(control4, room_id)
                    playing = spun and (spun["art"], spun["info"], spun["offset"] + time.time() - spun["heard"],
                                        spun["duration"], (named, ""))
                elif room_id in spinners:
                    spinners.pop(room_id).stop()
            if playing:
                return playing
        return None

    def tick(self, conf, spot=None, control4=None, find=None):
        """conf: all settings. spot: what the linked Spotify account is playing (spotify.Spotify.now), if anything.
        control4: the linked control4.Control4, if any. find: see listen()."""
        mine = room_settings(conf, self.name)
        if self.watcher and not self.clean:
            self.watcher.cleanup()
            self.clean = True
        playing = self.listen(conf, control4, find)
        if within(mine["quiet"]):
            playing, self.heard = None, 0
        if playing and playing[1] != self.began[0]:
            self.began = (playing[1], time.time())
        self.display.position = playing and ((playing[2], time.time()) if playing[2] is not None
                                             else (time.time() - self.began[1], time.time())) or None
        if playing:
            self.held, self.heard = playing[:2], time.time()
            song = mine["lyrics"] != "off" and playing[1]
            if song != self.song:        # looked up once per song, found or not
                self.song = song
                self.display.lyrics = find_lyrics(song, playing[3]) if song and song["title"] else None
            self.display.duration, self.display.extra = playing[3], {}
            if playing[4]:               # on radio: the station is where the song comes from
                self.display.extra = {"source": playing[4][0], "station": {"name": playing[4][0], "logo": playing[4][1]}}
            if self.ahead:               # Control4 knows the next song without Spotify's help
                self.display.extra["next"] = self.ahead
            if spot and spot["playing"] and spot["title"].strip().lower() == playing[1]["title"].strip().lower():
                # the same song: Spotify knows where it is to the millisecond, and what comes after
                self.display.position = (spot["progress"], spot["at"])
                self.display.duration = spot["duration"] or playing[3]
                self.display.extra = {k: spot[k] for k in ("next", "liked", "source")}
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
            self.watcher.grace, self.watcher.look = mine["grace"], look(mine)
            self.watcher.step(playing and playing[0], info=playing and playing[1])

    def status(self):
        return {"speaker": bool(self.speaker) or self.c4 is not None, "playing": self.display.info if self.display.url else None,
                "tv": self.tv, "error": self.error, "app": time.time() - self.display.tv_seen < 15}


if __name__ == "__main__":
    import soco

    from display import PORT, serve, settings

    rooms, displays, speakers = {}, {}, {}   # by Sonos room name; speakers are the ones found so far

    def let_go(room):
        if room.watcher and room.watcher.before:
            room.watcher.restore()

    weather = {}     # read by the pages; refreshed in the loop below so a slow answer never holds a page up
    from control4 import Control4
    from spotify import Spotify
    spot, c4 = Spotify(), Control4()
    c4_rooms = set()
    names = type("Names", (), {"__iter__": lambda self: iter(set(speakers) | c4_rooms)})()     # offered on the settings page
    serve(displays, speakers=names, status=lambda: {name: r.status() for name, r in list(rooms.items())},
          weather=lambda: weather.get("now"), spotify=spot, control4=c4)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))   # so `finally` runs under launchd too
    print("settings at http://localhost:%d/settings" % PORT, flush=True)
    looked = 0
    try:
        while True:
            conf = settings()        # re-read every round: the settings page changes it
            weather["now"] = find_weather(conf["weather"])
            if c4.connected:
                c4.poll()
            if conf["spotify"]["client_id"] and spot.connected:
                spot.poll(conf["spotify"]["client_id"])
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
            for r in rooms.values():         # a room with no Sonos speaker of its name may be a Control4 room
                r.c4 = None if r.speaker else c4.find(r.name)
            c4_rooms.clear(); c4_rooms.update(c4.status()["rooms"])
            if (not speakers or any(not r.speaker and r.c4 is None for r in rooms.values())) and time.time() - looked > 60:
                looked = time.time()
                speakers.update({z.player_name: z for z in soco.discover(timeout=3) or []})
            for r in rooms.values():
                if not r.speaker and r.name in speakers:
                    r.speaker = speakers[r.name]
                    print("found speaker:", r.name, flush=True)
                try:
                    r.tick(conf, spot.now, c4, lambda name: (speakers.get(name), c4.find(name)))
                    r.error = None
                except (OSError, soco.exceptions.SoCoException) as e:
                    if str(e) != r.error:    # TV asleep, speaker rebooting, Wi-Fi blip: say it once, keep trying
                        print("%s: retrying after: %s" % (r.name, e), flush=True)
                    r.error = str(e)
            time.sleep(POLL)
    finally:
        for r in rooms.values():
            let_go(r)
