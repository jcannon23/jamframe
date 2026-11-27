"""An optional link to one Spotify account: exact position in the song, what is up next, whether the song is
liked, the playlist it comes from, and skip / pause / like from the settings page.

Sign-in is Spotify's own (authorization code with PKCE): JamFrame never sees a password. It needs the Client ID
of an app you register at developer.spotify.com, with this redirect address: http://127.0.0.1:<port>/spotify/callback
What Spotify hands back is kept in spotify.json, beside the code, readable only by you and never sent to a page.
"""
import base64
import hashlib
import json
import os
import secrets
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
ACCOUNTS = os.environ.get("SPOTIFY_ACCOUNTS", "https://accounts.spotify.com")     # overridden by check.py
API = os.environ.get("SPOTIFY_API", "https://api.spotify.com/v1")
SCOPES = "user-read-playback-state user-modify-playback-state user-library-read user-library-modify playlist-read-private"


class Spotify:
    def __init__(self, path=os.path.join(HERE, "spotify.json")):
        self.path = path
        try:
            with open(path) as f:
                self.tokens = json.load(f)
        except (OSError, ValueError):
            self.tokens = {}
        self.pending = {}       # sign-ins under way: state -> code verifier
        self.now = None         # what the account is playing: see poll()
        self.error = None       # why the last call failed, for the settings page
        self.rest_until = 0     # Spotify asked us to slow down until then
        self.context = (None, None)     # (context URI, its name): looked up once per playlist
        self.polls = 0

    @property
    def connected(self):
        return bool(self.tokens.get("refresh_token"))

    def keep(self, tokens):
        self.tokens = tokens
        with open(os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
            json.dump(tokens, f)

    def disconnect(self):
        self.tokens, self.now, self.error = {}, None, None
        try:
            os.remove(self.path)
        except OSError:
            pass

    # ---- signing in
    def login_url(self, client_id, redirect):
        verifier, state = secrets.token_urlsafe(64), secrets.token_urlsafe(16)
        self.pending = {state: verifier}
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        return ACCOUNTS + "/authorize?" + urllib.parse.urlencode({
            "response_type": "code", "client_id": client_id, "scope": SCOPES, "redirect_uri": redirect,
            "state": state, "code_challenge_method": "S256", "code_challenge": challenge})

    def finish(self, client_id, redirect, code, state):
        """The second half of signing in. ValueError when the answer is not for a sign-in we started."""
        verifier = self.pending.pop(state, None)
        if not verifier or not code:
            raise ValueError("not a sign-in started here")
        self.grant(client_id, {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect,
                               "code_verifier": verifier})

    def grant(self, client_id, form):
        import requests
        r = requests.post(ACCOUNTS + "/api/token", data=dict(form, client_id=client_id), timeout=8)
        if not r.ok:
            raise ValueError("Spotify refused the sign-in (%s)" % r.status_code)
        got = r.json()
        self.keep({"access_token": got["access_token"], "expires_at": time.time() + got.get("expires_in", 3600) - 60,
                   "refresh_token": got.get("refresh_token") or self.tokens.get("refresh_token")})

    # ---- talking to it
    def call(self, client_id, method, path, **params):
        """One Web API call. Returns the parsed answer, {} for an empty one, None when it failed."""
        import requests
        if not self.connected or time.time() < self.rest_until:
            return None
        try:
            if time.time() > self.tokens.get("expires_at", 0):
                self.grant(client_id, {"grant_type": "refresh_token", "refresh_token": self.tokens["refresh_token"]})
            r = requests.request(method, API + path, params=params or None, timeout=5,
                                 headers={"Authorization": "Bearer " + self.tokens["access_token"]})
            if r.status_code == 429:
                self.rest_until = time.time() + int(r.headers.get("Retry-After", "30"))
            if r.status_code == 401:
                self.tokens["expires_at"] = 0       # refreshed on the next call
            if not r.ok:
                self.error = "Spotify answered %s" % r.status_code
                return None
            self.error = None
            return r.json() if r.content else {}
        except (OSError, ValueError, KeyError) as e:
            self.error = str(e)
            return None

    def poll(self, client_id):
        """Refresh self.now: None when nothing is playing, else title, artist, uri, playing, progress (seconds),
        at (when read), duration, liked, next ({title, artist} or None) and source (playlist or album name)."""
        state = self.call(client_id, "GET", "/me/player")
        if state is None:
            return                      # failed: keep what we knew
        item = state.get("item")
        if not item or state.get("currently_playing_type", "track") != "track":
            self.now = None
            return
        old, self.polls = self.now or {}, self.polls + 1
        now = {"uri": item["uri"], "title": item["name"], "artist": (item.get("artists") or [{}])[0].get("name", ""),
               "playing": bool(state.get("is_playing")), "progress": state.get("progress_ms", 0) / 1000,
               "at": time.time(), "duration": item.get("duration_ms", 0) / 1000,
               "liked": old.get("liked", False), "next": old.get("next"), "source": old.get("source")}
        changed = now["uri"] != old.get("uri")
        if changed:
            liked = self.call(client_id, "GET", "/me/library/contains", uris=now["uri"])
            now["liked"] = bool(liked and liked[0])
        if changed or self.polls % 10 == 0:         # the queue can be rearranged mid-song
            queue = (self.call(client_id, "GET", "/me/player/queue") or {}).get("queue") or []
            now["next"] = {"title": queue[0].get("name", ""),
                           "artist": (queue[0].get("artists") or [{}])[0].get("name", "")} if queue else None
        uri = (state.get("context") or {}).get("uri")
        if uri != self.context[0]:
            parts = (uri or "").split(":")       # spotify:playlist:<id>
            kind, ident = (parts[1], parts[2]) if len(parts) == 3 else ("", "")
            found = self.call(client_id, "GET", "/%ss/%s" % (kind, ident)) if kind in ("playlist", "album", "artist") else {}
            self.context = (uri, (found or {}).get("name"))
            self.error = None       # Spotify's own mixes cannot be looked up by apps: no name, and not a fault
        now["source"] = self.context[1]
        self.now = now

    def control(self, client_id, action):
        """One of: next, previous, pause, play, like, unlike. True when Spotify took it."""
        uri = (self.now or {}).get("uri")
        calls = {"next": ("POST", "/me/player/next", {}), "previous": ("POST", "/me/player/previous", {}),
                 "pause": ("PUT", "/me/player/pause", {}), "play": ("PUT", "/me/player/play", {}),
                 "like": ("PUT", "/me/library", {"uris": uri}), "unlike": ("DELETE", "/me/library", {"uris": uri})}
        if action not in calls or (action in ("like", "unlike") and not uri):
            raise ValueError("not something Spotify can be asked")
        method, path, params = calls[action]
        done = self.call(client_id, method, path, **params) is not None
        if done and self.now and action in ("like", "unlike"):
            self.now["liked"] = action == "like"
        if done and self.now and action in ("pause", "play"):
            self.now["playing"] = action == "play"
        return done

    def status(self):
        now = self.now and {k: self.now[k] for k in ("title", "artist", "playing", "liked")}
        return {"connected": self.connected, "now": now, "error": self.error}
