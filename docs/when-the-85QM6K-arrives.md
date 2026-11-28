# Pickup list: the TVs (85QM6K, CanvasTV 75S7SG, 75A300L)

Nothing below can be done until a TV is on the same network as the computer running the watcher.

## What is already done

- The **JamFrame TV app** is written and builds (`scripts/build-tv.sh` → `tv/build/jamframe-tv.apk`). It has
  never run on a TV.
- `scripts/install-tv.sh <TV address> "<Sonos room>"` installs it, grants its two permissions and points it at
  the watcher.
- The watcher needs nothing new: the app asks it for the room's state like any browser does. The settings
  page shows "TV app connected" on the room's row once the app is asking.
- Build tools live in `~/jamframe-tools` on the Mac (JDK 17, Android SDK, adb). They are not in the repo.

## Steps, in order

1. On the TV: Settings → System → About → press "Android TV OS build" seven times. Then Developer options →
   USB debugging on. Note the TV's IP (Network & Internet), and reserve it in the router.
2. Make sure the room has a Sonos speaker, and add the room on the settings page (address left empty).
3. From the Mac: `scripts/install-tv.sh <TV IP> "<Sonos room name>"`. The TV shows an "allow debugging?"
   prompt the first time: accept it on the TV.
4. Success looks like: the TV opens the room's page, and the room's row on the settings page reads
   "TV app connected".

## What has to be checked on the real TV (all unproven)

| Check | How | If it fails |
|---|---|---|
| Page renders and animates smoothly | Play music, change album | Lower the 1920 px cap in `display/index.html` `resize()` |
| Opens by itself from the **home screen** | TV on home, start music | The `SYSTEM_ALERT_WINDOW` grant did not take; check `adb shell appops get com.jamframe.tv` |
| Leaves a **film alone** | Play something in an app, start music | `Watch.free()` reads the front app from usage events; check the `GET_USAGE_STATS` grant |
| Opens from the **screensaver** | Let the screensaver start, start music | `ACTION_DREAMING_STARTED` may not be sent on this TV |
| **Wakes** a sleeping TV | TV in standby, start music | Standby may cut Wi-Fi or stop the service; may need "quick start"/network standby on |
| Closes when the music stops | Stop music, wait the grace time | — |
| Stays away after Home/Back is pressed | Press Home during music | — |
| Starts again after the TV restarts | Unplug, plug in, start music | Boot receiver blocked until the app is opened once |

## Decisions waiting on the TV

- **Putting the TV back to sleep** after it was woken for music is not built. The app only closes its screen
  and lets the TV's own sleep timer take over. Doing it properly needs device-admin rights (as BetterFrame
  uses); decide once we see how the TV behaves.
- **Backlight**: the page dims the picture, not the panel. See whether the QM6K's own picture settings or
  light sensor are enough.

## The Hisense CanvasTV (75S7SG)

A Google TV, so it takes the same route as the 85QM6K: `scripts/install-tv.sh <TV IP> "<Sonos room name>"`, then
the same eight checks in the table above. BetterFrame does not apply: it is written against TCL's internals.

Extra checks for this TV:

| Check | How | If it fails |
|---|---|---|
| JamFrame sees Hisense's art mode as "nobody is using the TV" | Leave the TV showing its art, start music | `Watch.free()` only knows asleep, screensaver and home screen. Find what the art mode is (`adb shell dumpsys activity activities` and `dumpsys dreams` while art is up) and add its package to what counts as free |
| Hisense's art mode comes back when the music stops | Stop music, wait the grace time | The app only closes its own screen; the TV may land on the home screen instead |
| The motion sensor still works afterwards | Leave the room after music stops | — |
| Brightness next to Hisense's own art | Compare by eye | Lower Brightness for this room in settings; the app cannot use the art mode's own dimming |

Known about this TV: its art mode has a built-in uploader on the home network (the TV shows a QR code; the page
is on port 19637 behind a temporary code), documented by one project for the 2024 S7N. It needs the TV's menus
driven for every picture, so it is no way to change covers per song. Not planned.

While JamFrame shows a cover the motion sensor is not in charge: the cover stays up as long as music plays,
with or without anyone in the room.

## The art TV (75A300L)

This one takes the other route: BetterFrame's art mode, installed by `scripts/install-betterframe.sh`, with the
TV's address entered on the room's row. Also never run on a real TV. Before installing:

1. Same debugging steps as above.
2. Confirm the exact model on its label: no "75A300L" turned up in searches, only 75A300W.
3. BetterFrame was only tested by its author on the A400 Pro, a different series. Its backlight control uses a
   TCL-internal service that may differ on the A300: check it before relying on it. This is the least certain
   part of the whole setup.
4. BetterFrame has no license. We install it unmodified from its own repository and copy none of its code.
5. Through BetterFrame the TV shows a still of the cover: no caption, lyrics, waves or animated changes.

If BetterFrame does not work on it, or the still is not enough, the JamFrame TV app is the fallback: the same
install as the 85QM6K, and the full animated screen.
