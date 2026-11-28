<p align="center"><img src="docs/icon.png" width="128" alt="JamFrame icon"></p>
<h1 align="center">JamFrame</h1>
<p align="center">Your TV's art mode, showing the record that's playing.</p>

When music plays on a Sonos speaker, the TV in that room shows the album cover as a muted, matted print,
like the rest of the art on the wall. When the music stops, the TV goes back to what it was showing.

![A cover as JamFrame shows it: faded, on a paper mat](docs/example.jpg)

## What it does

- **Follows each room on its own.** Music in the game room changes the game room TV only. Rooms grouped in
  Sonos show the same cover.
- **Makes covers look like prints.** Less colour and contrast, a warm cast, a paper mat tinted by the cover,
  a soft shadow and paper grain.
- **Animates between covers.** Five changes: Develop (a darkroom print coming up), Dissolve, Ink bleed,
  Sleeve (the cover slides out of the mat) and Fade. Rotate through them, shuffle, or pin one.
- **Captions the print.** Song, artist and album under the cover, like a gallery label.
- **Shows lyrics, if you want them.** Four styles: large and faint either side of the cover, a column in the
  margin, a single line, or typed out as it's sung.
- **Sends sound waves off the cover.** Five styles, coloured by the cover's own edges, moving at the song's
  tempo. In Grooves the mat becomes a record that spins up when a song starts and winds down when it stops.
- **Knows more with Spotify connected** (optional). Lyrics land on the line, the next song shows as this one
  ends, the caption can name the playlist and mark liked songs, and the settings page gets skip, pause and like.
- **Works with SiriusXM, AirPlay and radio**, not just Spotify. The song's own cover rather than a channel
  logo, with the channel shown in a corner. See [What can play](#what-can-play).
- **Fits the screen it's on.** A TV, a tablet on a shelf or a phone standing upright: the cover, mat, caption
  and lyrics size and arrange themselves to the screen's shape.
- **Stays out of the way.** Never takes the screen from someone watching TV, ignores the TV's own sound,
  dims at night, and stays dark during quiet hours.

## How it works

```
Sonos speaker ──▶ watch.py (any always-on computer) ──▶ the TV in that room
  what's playing     picks the cover, serves the screens    shows it
```

`watch.py` asks each Sonos room what it is playing every few seconds. For each room it serves a full-screen
page at `http://<this-computer>:8765/?room=<room name>` that draws the mat, cover, caption and lyrics, and
animates when the album changes. Open that page on anything with a browser to see a room's screen.

For art TVs it instead uploads a finished 4K still of the cover and switches the TV to it: a Samsung Frame
through its own art mode, a TCL art TV through [BetterFrame](https://github.com/spinogrizz/betterframe), a
replacement art mode with a local upload API. Stills carry the print, not the caption, lyrics or waves.

## Quick start

```sh
git clone https://github.com/jcannon23/jamframe.git && cd jamframe
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python watch.py
```

Then open `http://localhost:8765/settings`, add a room under **Rooms** using its name exactly as the Sonos
app shows it, and play something. The preview at the top of the page is that room's screen.

On a Mac, `scripts/install-mac.sh` makes it permanent: a login service keeps the watcher running, and
`~/Applications/JamFrame.app` starts it if needed and opens the settings page. `scripts/install-mac.sh remove`
undoes both.

## Settings

Everything is adjusted at `http://<this-computer>:8765/settings`, from a phone, tablet or laptop. Settings are
split over four tabs; on a phone the preview stays pinned at the top, on a wider screen it sits in a sidebar.
Changes save as you make them and reach the screens within a few seconds.

| Section | Controls |
|---|---|
| Preview | A live copy of the room's screen, and what the room is doing |
| Cover change | Style, length, and **Play it now** to try one |
| Print | Fading, cover size, mat (paper, white, charcoal, or tinted by the cover), grain |
| Caption | On or off; song, artist, album, playlist or channel, a heart if liked; position; size; up next; radio station badge |
| Lyrics | Off, Backdrop, Margin, Line, Typewriter |
| Sound waves | Off, Ripples, Grooves, Pressed, Rays, Strings; strength; colour from the cover's edges or one ink |
| TV size | Each room's TV size in inches; Same real size, so a print is as big on the 85-inch as on the 65-inch |
| Screen | Brightness, dimming at night, burn-in shift |
| When the music stops | How long to wait, then black, the last cover (with the time in a corner), or a clock in one of four faces |
| Spotify | Connect an account; previous, pause, next and like under the preview |
| Weather | On or off, place, °F or °C; shown with the clock and the kept cover |
| Quiet hours | Hours in which nothing is shown |
| Rooms | Sonos room name and the address of its TV; status of each |
| Never show | Line-in and radio stations |
| PIN | Optional, for changing settings |

**Per room:** pick a room at the top of the page and anything you change applies to that room only. The
bedroom can be dimmer and slower than the playroom.

Settings live in `settings.json` next to the code; the page is the easier way to edit it.

## What can play

JamFrame shows whatever a Sonos speaker is playing, however it got there.

| Source | Cover | Song and artist | Position | Extras |
|---|---|---|---|---|
| Spotify on Sonos | From Sonos | Yes | To the second; exact with Spotify connected | Up next, playlist, liked |
| AirPlay from a phone | From the phone | Yes | Yes | Spotify's extras too, when it is Spotify being AirPlayed |
| SiriusXM on Sonos | The song's cover | Yes | From the start of each song | Channel logo and name in the corner |
| SiriusXM over AirPlay | From the phone | Yes | Counted by JamFrame | Channel name in the corner |
| Other radio | The song's cover if it can be found, else the station's logo | When the station sends them | Counted by JamFrame | Station logo and name |
| The TV's own sound | Never shown | | | |

**SiriusXM.** Played from the Sonos app, Sonos passes along the song, artist, album, the channel
("CH 25 - Classic Rewind") and a small cover. JamFrame shows the song's cover, not the channel's logo: a sharp
one found by the song's name when it is from the album SiriusXM names, otherwise the one SiriusXM sent. During
talk and adverts the channel's logo is the picture. Played from the SiriusXM app over AirPlay, the song arrives
as "Artist - Song" with the show as the artist and the channel as the album; JamFrame unpacks that so the
caption reads properly and lyrics and tempo can find the song. No logo comes over AirPlay, so the corner shows
the channel's name alone.

The channel in the corner is under **Settings → Print & caption → Radio station** (off, name, or logo and name).

Lyrics are less reliable on radio: songs are faded and talked over, and timing is counted rather than known.

## Lyrics

Lyrics come from [LRCLIB](https://lrclib.net), a free lyrics database. When lyrics are on, the song, artist
and album names are sent there to look them up; nothing else is. Songs with timed lyrics follow the music
line by line. Songs with only plain lyrics are spread evenly over the song, which is close but not exact.
Songs it does not know show none.

Sound waves move at the song's tempo, which `tempo.py` gets from [Deezer](https://developers.deezer.com/api)
(sent the song and artist names): the listed tempo where there is one, otherwise measured from the 30-second
preview clip. It is the song's speed, not the position of each beat: nothing hears the room. Measuring needs
`afconvert` (on every Mac) or `ffmpeg`; without either, each song gets a made-up tempo of its own.

Weather comes from [Open-Meteo](https://open-meteo.com), also free and without an account. It is sent the place
name you typed, then that place's coordinates.

## Spotify (optional)

Sonos reports where a song is to the second and nothing about what comes next. A connected Spotify account
fills that in. Sign-in is Spotify's own (authorization code with PKCE): JamFrame never sees your password, and
what Spotify hands back stays in `spotify.json` on your computer, readable only by you.

1. At [developer.spotify.com](https://developer.spotify.com/dashboard) create an app. Tick **Web API**, and give
   it the redirect address shown on the settings page: `http://127.0.0.1:8765/spotify/callback`.
2. Paste the app's Client ID into **Settings → Spotify**.
3. On the computer JamFrame runs on, press **Connect Spotify** and approve.

The controls need Spotify Premium. A room uses Spotify's details only while Spotify is playing the same song
that room's speaker is.

## TVs

| Screen | How | Status |
|---|---|---|
| Anything with a browser | Open the room's page full screen | Works |
| A regular Google TV | The **JamFrame TV app** (`tv/`): opens the room's page by itself when music starts, and only when nobody is using the TV | Written and builds; not yet run on a TV |
| A Samsung Frame | Its own art mode, over the home network: the cover is uploaded, shown, and the previous picture put back afterwards. Nothing to install on the TV | Works: shown, restored and cleaned up on a 2020 Frame (LS03T), no flash on the change |
| A TCL art TV | [BetterFrame](https://github.com/spinogrizz/betterframe)'s art mode, fed finished stills | Written and checked against a stand-in TV; not yet run on a real one |

`scripts/install-tv.sh <TV address> "<Sonos room>"` builds and installs the TV app.
`scripts/install-betterframe.sh` installs BetterFrame, unmodified, from its own repository. Both need USB
debugging turned on at the TV. What is left to prove on real TVs is listed in
[docs/when-the-85QM6K-arrives.md](docs/when-the-85QM6K-arrives.md).

### Samsung Frame

In **Settings → Home & accounts → Rooms**, choose "Samsung Frame" for the room and enter the TV's address. The
first time, the TV may ask you to allow "JamFrame": accept with the remote.

- JamFrame only acts while the Frame is **showing art**. A Frame that is being watched, or is off, is left alone.
- The picture goes into "My Photos" with no Samsung mat (the mat is in the picture), and is deleted again when
  the music stops or the album changes. The art that was up before is put back.
- A cover change takes a few seconds: the picture has to be uploaded first.
- Samsung's own brightness, motion sensor and sleep keep working, since the TV never leaves its art mode.

Samsung has changed this interface between model years. It is confirmed on a 2020 Frame (QN75LS03T): the print
fills the screen with no extra mat, the change does not flash, and brightness matches the TV's other art.

## In the box

| File | Does |
|---|---|
| `watch.py` | Follows the Sonos rooms and drives their screens |
| `display.py` | Serves the room pages and the settings page; holds every setting and its limits |
| `display/index.html` | A room's screen: mat, cover, caption, lyrics, the changes between covers |
| `display/settings.html` | The settings page |
| `spotify.py` | The optional Spotify link |
| `tempo.py` | A song's tempo: `python tempo.py "Artist" "Song"` |
| `treat.py` | Cover in, finished 4K print out: `python treat.py cover.jpg out.jpg` |
| `check.py` | Checks the lot against a stand-in TV: `python check.py` |
| `tv/` | The JamFrame TV app for Google TVs |
| `scripts/` | Installers for the Mac, the TV app and BetterFrame; the TV app's build; the icon's drawing |

Try the screens without Sonos: `python display.py one.jpg two.jpg` cycles through your own pictures.

## Good to know

- The computer running `watch.py` has to stay awake, and on the same network as the speakers and TVs.
- Give that computer and each TV a fixed address in your router, so the addresses in the settings stay right.
- The settings page has no password unless you set a PIN. The PIN is a courtesy lock for a home network: it
  travels unencrypted and is stored in `settings.json`.

## Thanks

[SoCo](https://github.com/SoCo/SoCo) for talking to Sonos, [samsung-tv-ws-api](https://github.com/xchwarze/samsung-tv-ws-api)
for talking to the Frame, [BetterFrame](https://github.com/spinogrizz/betterframe)
for the art mode,
[LRCLIB](https://lrclib.net) for the lyrics and [Open-Meteo](https://open-meteo.com) for the weather.

## License

[MIT](LICENSE): use it, change it, share it. BetterFrame is a separate project with its own terms; none of its
code is in this repository.
