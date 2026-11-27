"""Runs the watcher against a fake BetterFrame. Usage: python check.py"""
import io
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from PIL import Image

import watch

tv = {"mode": "off", "picture": None, "selected": "owl.jpg", "rotate": True, "pictures": {"owl.jpg": b"x"}}


class FakeTv(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, obj, code=200):
        self.send_response(code)
        self.end_headers()
        self.wfile.write(json.dumps(obj).encode())

    def do_GET(self):
        if self.path == "/api/state":
            self.reply({"mode": tv["mode"], "picture": tv["picture"], "selected_picture": tv["selected"]})
        elif self.path == "/api/settings":
            self.reply({"rotate": tv["rotate"]})
        elif self.path == "/api/pictures":
            self.reply([{"name": n} for n in tv["pictures"]])

    def do_PUT(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        tv["pictures"][self.path.rsplit("/", 1)[1]] = body
        self.reply({})

    def do_DELETE(self):
        del tv["pictures"][self.path.rsplit("/", 1)[1]]
        self.reply({})

    def do_POST(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if u.path == "/api/settings":
            tv["rotate"] = json.loads(body)["rotate"]
        elif u.path == "/api/art":
            if q["picture"] not in tv["pictures"]:
                return self.reply({}, 404)
            tv["mode"], tv["picture"] = "art", q["picture"]
        elif u.path == "/api/picture":
            tv["selected"] = q["name"]
            if tv["mode"] == "art":
                tv["picture"] = q["name"]
        elif u.path == "/api/off":
            tv["mode"], tv["picture"] = "off", None
        self.reply({})


server = HTTPServer(("127.0.0.1", 0), FakeTv)
threading.Thread(target=server.serve_forever, daemon=True).start()

cover = io.BytesIO()
Image.new("RGB", (640, 640), (200, 40, 40)).save(cover, "JPEG")
w = watch.Watcher(watch.Tv("127.0.0.1:%d" % server.server_port), fetch=lambda url: cover.getvalue())
ours = lambda: [n for n in tv["pictures"] if n.startswith(watch.PREFIX)]

# music starts while the TV is off: cover goes up as art, slideshow rotation paused
w.step("http://a/1", now=0)
assert tv["mode"] == "art" and tv["picture"] == ours()[0] and tv["rotate"] is False, tv["mode"]
assert Image.open(io.BytesIO(tv["pictures"][ours()[0]])).size == (3840, 2160)

# next album: new cover shown, old upload deleted
first = ours()[0]
w.step("http://a/2", now=10)
assert len(ours()) == 1 and ours()[0] != first and tv["picture"] == ours()[0]

# a pause shorter than the grace period changes nothing
w.step(None, now=20)
w.step(None, now=20 + watch.GRACE - 1)
assert tv["mode"] == "art" and ours()

# silence past the grace period: TV off again, old picture selected, rotation back, upload gone
w.step(None, now=20 + watch.GRACE)
assert tv["mode"] == "off" and tv["selected"] == "owl.jpg" and tv["rotate"] is True and not ours(), tv

# someone is watching TV: music never takes the screen
tv["mode"] = "tv"
w.step("http://a/3", now=200)
assert tv["mode"] == "tv" and not ours() and tv["rotate"] is True

# TV was showing art: when the music ends the old picture comes back and art stays on
tv["mode"], tv["picture"] = "art", "owl.jpg"
w.step("http://a/3", now=300)
assert tv["picture"] == ours()[0]
w.step(None, now=310)
w.step(None, now=310 + watch.GRACE)
assert tv["mode"] == "art" and tv["picture"] == "owl.jpg" and not ours()

print("ok")

# the animated page: each new cover gets the next transition; settings.json can pin one
import os, tempfile
from display import Display, TRANSITIONS
path = os.path.join(tempfile.mkdtemp(), "settings.json")
d = Display(lambda url: b"jpeg", settings=path)
seen = []
for i in range(len(TRANSITIONS) + 1):
    d.update("http://a/%d" % i)
    seen.append(d.state["transition"])
assert seen == TRANSITIONS + TRANSITIONS[:1] and d.state["seconds"] == 7 and len(d.covers) == 3, seen
open(path, "w").write('{"transition": "ink", "seconds": 4}')
d.update("http://a/x")
assert (d.state["transition"], d.state["seconds"]) == ("ink", 4)
# a new song on the same album: caption changes, cover and transition stay
d.update("http://a/x", {"title": "One", "artist": "A", "album": "B"})
d.update("http://a/x", {"title": "Two", "artist": "A", "album": "B"})
assert (d.state["transition"], d.state["title"], d.state["album"]) == ("ink", "Two", "B")
d.update(None)
assert d.state == {"art": None}

# lyrics: timed ones as they are; untimed ones spread over the song; the page gets them with the position
d.update("http://a/y", {"title": "One", "artist": "A", "album": "B"})
d.lyrics = watch.parse_lyrics({"syncedLyrics": "[00:12.50] first\n[01:02.00]\n[01:05.10] second"}, 200)
assert d.lyrics == [[12.5, "first"], [62.0, ""], [65.1, "second"]]
spread = watch.parse_lyrics({"syncedLyrics": None, "plainLyrics": "a\n\nb\nc"}, 100)
assert [l[1] for l in spread] == ["a", "b", "c"] and spread[0][0] == 8.0 and spread[-1][0] < 95
assert watch.parse_lyrics({}, 100) is None and watch.seconds("0:03:25") == 205 and watch.seconds("NOT_IMPLEMENTED") is None
d.position = (30, __import__("time").time() - 2)
st = d.page_state()
assert st["lyrics"] == d.lyrics and 31.9 < st["position"] < 32.5
d.update(None)
assert d.page_state()["lyrics"] is None and d.page_state()["position"] is None
print("display ok")

# several rooms: each TV's page gets its own room's cover
import urllib.request
from display import serve
a, b = Display(lambda url: b"A", settings=path), Display(lambda url: b"B", settings=path)
srv = serve({"Playroom": a, "Game Room": b}, port=0, path=path)
get = lambda p: urllib.request.urlopen("http://127.0.0.1:%d%s" % (srv.server_port, p)).read()
a.update("http://a/1")
sa, sb = json.loads(get("/state?room=Playroom")), json.loads(get("/state?room=Game%20Room"))
assert sa["art"] and sb["art"] is None and get("/" + sa["art"]) == b"A"
assert json.loads(get("/state?room=Nowhere"))["art"] is None and json.loads(get("/state")) == sa
print("rooms ok")

# the settings page: valid changes are saved and reach the TV page, anything else is refused
def post(body, kind="application/json"):
    req = urllib.request.Request("http://127.0.0.1:%d/settings.json" % srv.server_port, json.dumps(body).encode(),
                                 {"Content-Type": kind})
    try:
        return urllib.request.urlopen(req).status
    except urllib.error.HTTPError as e:
        return e.code
assert post({"brightness": 0.5, "rooms": {"Den": None, "Loft": "10.0.0.9:8080"}}) == 204
now = json.loads(get("/settings.json"))
assert now["brightness"] == 0.5 and now["rooms"]["Loft"] == "10.0.0.9:8080" and now["transition"] == "ink"
assert json.loads(get("/state"))["look"]["brightness"] == 0.5
for bad in ({"seconds": 0}, {"caption": "yes"}, {"rooms": {"Den": "http://x/"}}, {"nope": 1}, [1]):
    assert post(bad) == 400, bad
assert post({"seconds": 5}, kind="text/plain") == 404 and json.loads(get("/settings.json"))["seconds"] == 4

# a room's own settings sit on top of the shared ones; night hours dim; quiet/night windows wrap midnight
from display import look, room_settings, settings, within
assert post({"overrides": {"Playroom": {"mat": "charcoal"}}, "night": {"on": True, "from": "00:00", "to": "00:00", "brightness": 0.2}}) == 204
assert json.loads(get("/state?room=Playroom"))["look"]["mat"] == "charcoal"
assert json.loads(get("/state?room=Game%20Room"))["look"] == dict(look(settings(path)), mat="paper", brightness=0.2)
at = lambda h: __import__("time").mktime((2026, 1, 1, h, 30, 0, 0, 0, -1))
late = {"on": True, "from": "22:00", "to": "07:00"}
assert within(late, at(23)) and within(late, at(3)) and not within(late, at(12)) and not within(dict(late, on=False), at(23))
assert post({"waves": "grooves", "wave_level": 0.8}) == 204 and post({"waves": "tsunami"}) == 400
assert post({"clock": "analog", "weather": {"on": True, "place": "Portland, Oregon", "unit": "F"}}) == 204
assert json.loads(get("/state"))["look"]["clock"] == "analog" and json.loads(get("/state"))["weather"] is None
assert watch.find_weather({"on": False, "place": "Portland", "unit": "F"}) is None
get("/state?room=Playroom&screen=tv")
assert a.tv_seen > 0 and b.tv_seen == 0
for bad in ({"overrides": {"Den": {"rooms": {}}}}, {"night": {"on": True}}, {"clock": "cuckoo"}, {"weather": {"on": True}}, {"quiet": {"on": True, "from": "25:00", "to": "07:00"}},
            {"fields": ["lyrics"]}, {"pin": "abc"}):
    assert post(bad) == 400, bad

# "play it now" reaches the page; an unknown room is refused
def post_to(where, body, pin=None):
    req = urllib.request.Request("http://127.0.0.1:%d/%s" % (srv.server_port, where), json.dumps(body).encode(),
                                 dict({"Content-Type": "application/json"}, **({"X-Pin": pin} if pin else {})))
    try:
        return urllib.request.urlopen(req).status
    except urllib.error.HTTPError as e:
        return e.code
a.update("http://a/2")
assert post_to("play", {"room": "Playroom", "transition": "sleeve"}) == 204 and post_to("play", {"room": "Nowhere"}) == 400
st = json.loads(get("/state?room=Playroom"))
assert st["play"] == 1 and st["demo"]["transition"] == "sleeve" and st["from"] and st["from"] != st["art"]

# with a PIN set, changes need it, and the PIN itself is never handed out
assert post({"pin": "2468"}) == 204
assert post({"seconds": 9}) == 403 and post_to("play", {"room": "Playroom"}) == 403
assert post_to("settings.json", {"seconds": 9}, pin="2468") == 204
now = json.loads(get("/settings.json"))
assert now["seconds"] == 9 and now["pin_set"] is True and "pin" not in now
print("settings ok")
