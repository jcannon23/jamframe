"""An optional link to a Control4 system, for homes where Control4 plays the music rather than Sonos:
which rooms are playing, and what.

Control4 only gives a controller pass that lasts a day, and renewing it needs the account's email and
password. So those are kept, in control4.json beside the code, readable only by you and never sent to a page.
The sign-in is Control4's own cloud one (the requests and application key are those the open-source pyControl4
library found); after that everything is asked of the controller itself, on the home network.
"""
import base64
import json
import os
import re
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CLOUD = os.environ.get("CONTROL4_CLOUD", "https://apis.control4.com")       # overridden by check.py
APPLICATION_KEY = "78f6791373d61bea49fdb9fb8897f1f3af193f11"
WANTED = "CURRENT MEDIA INFO,PLAYING,PAUSED,STOPPED,POWER_STATE,CURRENT_SELECTED_DEVICE"


class Control4:
    def __init__(self, path=os.path.join(HERE, "control4.json")):
        self.path = path
        try:
            with open(path) as f:
                self.kept = json.load(f)
        except (OSError, ValueError):
            self.kept = {}
        self.error = None
        self.rooms = {}         # room id -> {"name", plus the variables in WANTED}: see poll()
        self.rest_until, self.rooms_at = 0, 0

    @property
    def connected(self):
        return bool(self.kept.get("password"))

    def keep(self, **changes):
        self.kept = {**self.kept, **changes}
        with open(os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
            json.dump(self.kept, f)

    def disconnect(self):
        self.kept, self.rooms, self.error = {}, {}, None
        try:
            os.remove(self.path)
        except OSError:
            pass

    def sign_in(self, username, password, address):
        """Check the account and controller, and keep what is needed to stay signed in. ValueError if refused.
        Three steps, as Control4's own apps do them: sign in to the account, ask which controller it has, ask
        for a pass to that controller."""
        import requests
        try:
            r = requests.post(CLOUD + "/authentication/v1/rest", timeout=10, json={"clientInfo": {
                "device": {"deviceName": "JamFrame", "deviceUUID": "0000000000000000", "make": "JamFrame",
                           "model": "JamFrame", "os": "Android", "osVersion": "10"},
                "userInfo": {"applicationKey": APPLICATION_KEY, "password": password, "userName": username}}})
            account = {"Authorization": "Bearer " + r.json()["authToken"]["token"]}
            controller = requests.get(CLOUD + "/account/v3/rest/accounts", timeout=10, headers=account
                                      ).json()["account"]["controllerCommonName"]
            got = requests.post(CLOUD + "/authentication/v1/rest/authorization", timeout=10, headers=account,
                                json={"serviceInfo": {"commonName": controller, "services": "director"}}).json()["authToken"]
        except (OSError, ValueError, KeyError, TypeError):
            raise ValueError("Control4 did not accept that sign-in")
        self.keep(username=username, password=password, address=address, controller=controller,
                  token=got["token"], expires_at=time.time() + got["validSeconds"] - 600)
        self.error = None

    def get(self, path):
        """One question to the controller. Returns the parsed answer, or None when it failed."""
        import requests
        import urllib3
        if not self.connected or time.time() < self.rest_until:
            return None
        try:
            if time.time() > self.kept.get("expires_at", 0):
                self.sign_in(self.kept["username"], self.kept["password"], self.kept["address"])
            urllib3.disable_warnings()      # the controller's certificate is its own; there is nothing to check it against
            r = requests.get("https://%s%s" % (self.kept["address"], path), timeout=5, verify=False,
                             headers={"Authorization": "Bearer " + self.kept["token"]})
            if r.status_code == 401:
                self.kept["expires_at"] = 0     # signed in again on the next call
            if not r.ok:
                self.error = "The Control4 controller answered %s" % r.status_code
                return None
            self.error = None
            return r.json()
        except (OSError, ValueError, KeyError) as e:
            self.error, self.rest_until = str(e)[:200], time.time() + 20
            return None

    def poll(self):
        """Refresh self.rooms from the controller: every room, with what it is playing."""
        if not self.rooms or time.time() - self.rooms_at > 600:      # rooms are rarely added: asked now and then
            items = self.get("/api/v1/categories/rooms") or self.get("/api/v1/items")
            if items is None:
                return
            names = {i["id"]: i.get("name", "") for i in items if i.get("type") in (8, "room") or i.get("typeName") == "room"}
            self.rooms = {i: dict(self.rooms.get(i, {}), name=n) for i, n in names.items()}
            self.rooms_at = time.time()
        values = self.get("/api/v1/items/variables?varnames=" + WANTED.replace(" ", "%20"))
        for v in values or []:
            if v.get("id") in self.rooms:
                self.rooms[v["id"]][v.get("varName")] = v.get("value")

    def find(self, name):
        """The id of the room called this that plays music, or None. Control4 projects reuse room names
        (a "Living Room" for the lights, another for the audio): the one that has media is the one meant."""
        named = [i for i, r in sorted(self.rooms.items()) if r["name"] == name]
        return next((i for i in named if "CURRENT MEDIA INFO" in self.rooms[i]), named[0] if named else None)

    def now_playing(self, room_id):
        """What a room is playing, or None: {"art" (cover address, may be None), "info" (title, artist, album),
        "duration" (seconds or None), "station" (the channel, on SiriusXM), "next" ({title, artist} or None)}."""
        room = self.rooms.get(room_id) or {}
        media = room.get("CURRENT MEDIA INFO")
        try:
            media = (json.loads(media) if isinstance(media, str) else media or {}).get("mediainfo") or {}
        except ValueError:
            return None
        if str(room.get("POWER_STATE")) != "1" or not media.get("title"):
            return None
        stream = media.get("streamStatus") or ""
        if "status=" in stream and "status=OK_playing" not in stream:
            return None                     # paused
        # Streaming services tuck their own record into the stream's status: this song's length, and the next one
        tracks = []
        packed = re.search(r'title="(.*)"', stream, re.S)
        if packed:
            try:
                tracks = json.loads(packed.group(1).replace('\\"', '"')).get("tracks") or []
            except (ValueError, AttributeError):
                pass
        at = next((n for n, t in enumerate(tracks) if t.get("current")), None)
        now = tracks[at] if at is not None else {}
        after = tracks[at + 1] if at is not None and at + 1 < len(tracks) else None
        try:
            art = base64.b64decode(media.get("img") or "").decode() or None      # the cover's address, base64'd
        except ValueError:
            art = None
        return {"art": art if art and art.startswith("http") else now.get("album_cover_url"),
                "info": {k: str(media.get(k) or "") for k in ("title", "artist", "album")},
                "duration": now.get("duration_ms", 0) / 1000 or None, "station": media.get("channel") or None,
                "next": after and {"title": after.get("track", ""), "artist": after.get("artist", "")}}

    def status(self):
        return {"connected": self.connected, "error": self.error, "controller": self.kept.get("controller"),
                "address": self.kept.get("address"),
                "rooms": sorted({r["name"] for r in self.rooms.values() if "CURRENT MEDIA INFO" in r})}     # the ones with music
