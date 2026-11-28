"""Serves the animated now-playing page (display/index.html), its settings page, and tells pages what to show.

One Display per room. A TV opens /?room=<Sonos room name>; its page polls /state?room=... .
Everything adjustable lives in settings.json (see LOOK and DEFAULTS) and is edited at /settings.
A room uses the top-level settings unless "overrides" has its own value for that room.
The file is re-read as it is needed, so changes apply without a restart.

Preview without Sonos: python display.py cover1.jpg cover2.jpg ...   (cycles through the files)
"""
import hashlib
import hmac
import json
import os
import random
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
TRANSITIONS = ["develop", "inmat", "ink", "sleeve", "fade"]
FIELDS = ["title", "artist", "album"]
CAPTION = FIELDS + ["source", "liked"]     # the last two come from Spotify: the playlist, and a heart on liked songs
LYRICS = ["off", "backdrop", "margin", "line", "typewriter"]
CLOCKS = ["classic", "modern", "analog", "words"]
WAVES = ["off", "ripples", "grooves", "emboss", "rays", "strings"]
PORT = int(os.environ.get("PORT", "8765"))
SETTINGS = os.path.join(HERE, "settings.json")

LOOK = {                    # every one of these can be overridden per room
    "transition": "rotate", # "rotate" (each in turn), "shuffle", or one of TRANSITIONS
    "seconds": 7,           # length of a cover transition
    "caption": True,        # text under the cover
    "align": "center",      # "left" or "center"
    "fields": FIELDS,       # what the caption shows: any of CAPTION
    "upnext": "off",        # the next song, from Spotify: "off", "end" (the last 20 seconds) or "always"
    "station": "logo",      # on radio, the station in a corner: "off", "name", or "logo" (its logo and name)
    "size": "medium",       # caption: "small", "medium", "large"
    "mute": 0.5,            # 0 = the cover as it is, 1 = a very faded print
    "mat": "paper",         # "paper", "white", "charcoal", or "cover" (tinted by the cover)
    "cover": 0.62,          # cover edge as a share of screen height
    "inches": 75,           # the TV's size, corner to corner: set per room
    "same_size": False,     # True: everything is as big in real inches on this TV as on a 75-inch one
    "wake": False,          # True: music wakes this room's Samsung Frame when it is asleep (never when it is being watched)
    "grain": True,
    "brightness": 1,
    "night": {"on": False, "from": "21:00", "to": "07:00", "brightness": 0.3},
    "shift": False,         # move the picture a few pixels now and then (burn-in)
    "grace": 60,            # seconds of silence before a screen is given back
    "idle": "black",        # with no music: "black", "last" (keep the cover up) or "clock"
    "clock": "classic",     # the clock's face: one of CLOCKS
    "quiet": {"on": False, "from": "22:00", "to": "07:00"},   # never show anything in these hours
    "lyrics": "off",        # how the song's words are shown: one of LYRICS
    "waves": "off",         # sound waves coming off the cover while music plays: one of WAVES
    "wave_level": 0.6,      # how strong they are, 0.1 - 1
    "wave_color": "edges",  # "edges": each wave takes the colours along the cover's sides; "ink": one colour
}
DEFAULTS = {
    **LOOK,
    "rooms": {},            # Sonos room name -> its art TV: "192.168.1.50" (TCL with BetterFrame),
                            # "samsung:192.168.1.60" (Samsung Frame), or None
    "overrides": {},        # Sonos room name -> {some LOOK settings}
    "hears": {},            # room name -> other rooms whose music it shows when it has none of its own:
                            # {"Living Room": ["Kitchen"]} puts the kitchen's music on the living room TV
    "ignore": [],           # sources that never take a screen: "linein", "radio"
    "pin": "",              # digits; when set, changing settings needs it
    "weather": {"on": False, "place": "", "unit": "F"},   # shown with the clock, and in a corner of a kept cover
    "spotify": {"client_id": ""},   # of your app at developer.spotify.com; see spotify.py
    "by_ear": ["Turntable"],        # Control4 sources with no song of their own, named by listening: see recognise.py
}
REFERENCE = 75      # inches: the TV size the look settings are judged on when "same_size" is on
PAGE = ["caption", "align", "fields", "size", "mute", "mat", "cover", "grain", "shift", "idle", "lyrics", "clock", "waves", "wave_level", "wave_color", "upnext", "station"]   # what a TV page needs

number = lambda v, lo, hi: type(v) in (int, float) and lo <= v <= hi
clock = lambda v: isinstance(v, str) and re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v)
window = lambda v, more=(): (isinstance(v, dict) and set(v) == {"on", "from", "to", *more}
                             and isinstance(v["on"], bool) and clock(v["from"]) and clock(v["to"]))
subset = lambda v, allowed: isinstance(v, list) and all(x in allowed for x in v)
VALID = {
    "transition": lambda v: v in TRANSITIONS + ["rotate", "shuffle"],
    "seconds": lambda v: number(v, 1, 30),
    "caption": lambda v: isinstance(v, bool),
    "align": lambda v: v in ("left", "center"),
    "fields": lambda v: subset(v, CAPTION),
    "upnext": lambda v: v in ("off", "end", "always"),
    "station": lambda v: v in ("off", "name", "logo"),
    "size": lambda v: v in ("small", "medium", "large"),
    "mute": lambda v: number(v, 0, 1),
    "mat": lambda v: v in ("paper", "white", "charcoal", "cover"),
    "cover": lambda v: number(v, 0.3, 0.8),
    "inches": lambda v: number(v, 20, 150),
    "same_size": lambda v: isinstance(v, bool),
    "wake": lambda v: isinstance(v, bool),
    "grain": lambda v: isinstance(v, bool),
    "brightness": lambda v: number(v, 0.05, 1),
    "night": lambda v: window(v, ("brightness",)) and number(v["brightness"], 0.05, 1),
    "shift": lambda v: isinstance(v, bool),
    "grace": lambda v: number(v, 0, 3600),
    "idle": lambda v: v in ("black", "last", "clock"),
    "clock": lambda v: v in CLOCKS,
    "weather": lambda v: (isinstance(v, dict) and set(v) == {"on", "place", "unit"} and isinstance(v["on"], bool)
                          and isinstance(v["place"], str) and len(v["place"]) <= 80 and v["unit"] in ("F", "C")),
    "quiet": window,
    "lyrics": lambda v: v in LYRICS,
    "waves": lambda v: v in WAVES,
    "wave_level": lambda v: number(v, 0.1, 1),
    "wave_color": lambda v: v in ("edges", "ink"),
    "rooms": lambda v: isinstance(v, dict) and all(
        isinstance(name, str) and 0 < len(name) <= 64
        and (tv is None or isinstance(tv, str) and re.fullmatch(r"(samsung:)?[A-Za-z0-9.-]{1,253}(:\d{1,5})?", tv))
        for name, tv in v.items()),
    "overrides": lambda v: isinstance(v, dict) and all(
        isinstance(name, str) and isinstance(o, dict) and all(k in LOOK and VALID[k](x) for k, x in o.items())
        for name, o in v.items()),
    "ignore": lambda v: subset(v, ("linein", "radio")),
    "by_ear": lambda v: isinstance(v, list) and all(isinstance(x, str) and 0 < len(x) <= 64 for x in v),
    "hears": lambda v: isinstance(v, dict) and all(
        isinstance(name, str) and isinstance(others, list) and all(isinstance(o, str) and 0 < len(o) <= 64 for o in others)
        for name, others in v.items()),
    "spotify": lambda v: (isinstance(v, dict) and set(v) == {"client_id"} and isinstance(v["client_id"], str)
                          and re.fullmatch(r"[0-9A-Za-z]{0,64}", v["client_id"])),
    "pin": lambda v: isinstance(v, str) and re.fullmatch(r"\d{0,12}", v),
}


def settings(path=SETTINGS):
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    return {**DEFAULTS, **(data if isinstance(data, dict) else {})}


def save(changes, path=SETTINGS):
    """Merge changes (from the settings page) into the file. ValueError if any of it is not a valid setting."""
    if not isinstance(changes, dict) or not all(k in VALID and VALID[k](v) for k, v in changes.items()):
        raise ValueError("not a valid setting")
    with open(path + ".tmp", "w") as f:
        json.dump({**settings(path), **changes}, f, indent=2)
    os.replace(path + ".tmp", path)


def room_settings(conf, room):
    return {**conf, **conf["overrides"].get(room, {})}


def within(hours, now=None):
    """Is the clock inside an {"on", "from", "to"} window? Windows may run past midnight."""
    t, a, b = time.strftime("%H:%M", time.localtime(now)), hours["from"], hours["to"]
    return hours["on"] and (a <= t < b if a < b else t >= a or t < b)


def look(conf, now=None):
    """What a TV page needs out of a room's settings, night dimming applied.
    scale: how much bigger or smaller than usual to draw, so that sizes match in real inches across TVs."""
    night = conf["night"]
    return dict({k: conf[k] for k in PAGE}, brightness=night["brightness"] if within(night, now) else conf["brightness"],
                scale=round(REFERENCE / conf["inches"], 3) if conf["same_size"] else 1)


class Display:
    def __init__(self, fetch, settings=SETTINGS, room=None):
        self.fetch = fetch          # cover URL -> image bytes
        self.settings = settings
        self.room = room
        self.url = None             # cover URL currently shown
        self.info = None            # its caption: {"title", "artist", "album"}
        self.covers = {}            # name -> bytes; only what the page may still ask for, newest last
        self.state = {"art": None}
        self.turn = 0
        self.last = None
        self.plays, self.demo = 0, None   # "play it now" from the settings page
        self.lyrics = None          # [[seconds, line], ...] of the song playing, when wanted and found
        self.position = None        # (seconds into the song, time.time() it was read), while playing
        self.tv_seen = 0            # when the JamFrame TV app last asked for this room
        self.tempo = None           # beats a minute of the song playing, when wanted and found
        self.duration = None        # its length in seconds
        self.extra = {}             # next, liked, source (from Spotify, when it is playing this song); station (on radio)

    def pick(self):
        s = room_settings(settings(self.settings), self.room)
        t = s["transition"]
        if t == "shuffle":
            t = random.choice([x for x in TRANSITIONS if x != self.last])
        elif t not in TRANSITIONS:      # "rotate", or a typo
            t = TRANSITIONS[self.turn % len(TRANSITIONS)]
            self.turn += 1
        self.last = t
        seconds = s["seconds"]
        return {"transition": t, "seconds": seconds if isinstance(seconds, (int, float)) and seconds > 0 else 7}

    def play(self, transition=None):
        """Have the page run a transition now, from the previous cover to the current one."""
        self.demo = dict(self.pick(), **({"transition": transition} if transition in TRANSITIONS else {}))
        self.plays += 1

    def update(self, url, info=None):
        """url: cover of the music playing now, or None. info: its title, artist and album."""
        if (url, info) == (self.url, self.info):
            return
        if not url:
            self.state = {"art": None}
        else:
            if url != self.url:     # a new song on the same album keeps the cover: no transition
                name = hashlib.sha1(url.encode()).hexdigest()[:10]
                self.covers.pop(name, None)
                self.covers[name] = self.fetch(url)
                for old in list(self.covers)[:-3]:
                    del self.covers[old]
                self.state = dict(self.pick(), art="cover/" + name)
            self.state = {**self.state, "title": "", "artist": "", "album": "", **(info or {})}
        self.url, self.info = url, info

    def page_state(self):
        names = list(self.covers)
        at = self.position and self.position[0] + time.time() - self.position[1]
        return {**self.state, "play": self.plays, "demo": self.demo,
                "from": "cover/" + names[-2] if len(names) > 1 else None,
                "lyrics": self.lyrics if self.url else None, "position": at if self.url else None,
                "bpm": self.tempo if self.url else None, "duration": self.duration if self.url else None,
                **{k: self.extra.get(k) if self.url else None for k in ("next", "liked", "source", "station")}}


def serve(displays, port=PORT, speakers=(), path=SETTINGS, status=None, weather=None, spotify=None, control4=None):
    """displays: room name -> Display. With no ?room= the first room answers.
    speakers: names of the Sonos rooms found, offered on the settings page.
    status: () -> what each room is doing, for the settings page.
    weather: () -> the weather now, or None; see watch.find_weather.
    spotify: a spotify.Spotify, for signing in and the controls on the settings page.
    control4: a control4.Control4, for signing in from the settings page."""

    def page(name):
        with open(os.path.join(HERE, "display", name), "rb") as f:
            return f.read(), "text/html; charset=utf-8"

    as_json = lambda obj: (json.dumps(obj).encode(), "application/json")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            url = urlparse(self.path)
            room = parse_qs(url.query).get("room", [None])[0]
            name = url.path[7:] if url.path.startswith("/cover/") else None
            cover = next((d.covers[name] for d in list(displays.values()) if name in d.covers), None)
            conf = settings(path)
            client, back = conf["spotify"]["client_id"], "http://127.0.0.1:%d/spotify/callback" % self.server.server_port
            if spotify and url.path in ("/spotify/login", "/spotify/callback"):
                try:
                    if url.path == "/spotify/login":
                        if not client:
                            raise ValueError("no Client ID saved yet")
                        to = spotify.login_url(client, back)
                    else:
                        query = parse_qs(url.query)
                        spotify.finish(client, back, query.get("code", [""])[0], query.get("state", [""])[0])
                        to = "/settings"
                except ValueError as e:
                    return self.send_error(400, str(e))
                self.send_response(302)
                self.send_header("Location", to)
                self.end_headers()
                return
            if url.path == "/":
                body, kind = page("index.html")
            elif url.path == "/settings":
                body, kind = page("settings.html")
            elif url.path == "/settings.json":      # never hands out the PIN itself
                body, kind = as_json({**{k: v for k, v in conf.items() if k != "pin"}, "pin_set": bool(conf["pin"]),
                                      "transitions": TRANSITIONS, "speakers": sorted(speakers)})
            elif url.path == "/status":
                body, kind = as_json(status() if status else {})
            elif url.path == "/state":
                room = room or next(iter(list(displays)), None)
                d = displays.get(room)
                if d and parse_qs(url.query).get("screen") == ["tv"]:
                    d.tv_seen = time.time()
                body, kind = as_json({**(d.page_state() if d else {"art": None}), "look": look(room_settings(conf, room)),
                                      "weather": weather() if weather else None})
            elif url.path == "/spotify/status":
                body, kind = as_json(dict(spotify.status() if spotify else {"connected": False}, configured=bool(client), redirect=back))
            elif url.path == "/control4/status":
                body, kind = as_json(control4.status() if control4 else {"connected": False})
            elif url.path == "/weather":
                body, kind = as_json(weather() if weather else None)
            elif cover:
                body, kind = cover, "image/jpeg"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Cache-Control", "no-store" if kind != "image/jpeg" else "max-age=3600")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            # JSON only: a web page elsewhere cannot send that here without a preflight we never answer
            if self.path not in ("/settings.json", "/play", "/spotify", "/control4") or self.headers.get("Content-Type") != "application/json":
                return self.send_error(404)
            pin = settings(path)["pin"]
            if pin and not hmac.compare_digest(pin.encode(), (self.headers.get("X-Pin") or "").encode()):
                return self.send_error(403)
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
                if self.path == "/play":
                    displays[body["room"]].play(body.get("transition"))
                elif self.path == "/control4":
                    if not control4:
                        raise ValueError("no Control4 link")
                    if body["action"] == "disconnect":
                        control4.disconnect()
                    else:
                        address = str(body["address"])
                        if not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", address):
                            raise ValueError("not an address")
                        control4.sign_in(str(body["username"]), str(body["password"]), address)
                elif self.path == "/spotify":
                    if not spotify:
                        raise ValueError("no Spotify link")
                    if body["action"] == "disconnect":
                        spotify.disconnect()
                    elif not spotify.control(settings(path)["spotify"]["client_id"], body["action"]):
                        return self.send_error(502, spotify.error or "Spotify did not take it")
                else:
                    save(body, path)
            except (ValueError, KeyError, TypeError) as e:
                return self.send_error(400, str(e))
            self.send_response(204)
            self.end_headers()

    server = ThreadingHTTPServer(("", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


if __name__ == "__main__":
    files = sys.argv[1:] or sys.exit(__doc__)
    display = Display(lambda path: open(path, "rb").read())
    serve({"demo": display})
    print("open http://localhost:%d" % PORT, flush=True)
    every = float(os.environ.get("EVERY", "12"))
    while True:
        for f in files:
            display.update(f)
            time.sleep(every)
