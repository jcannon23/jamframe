#!/bin/sh
# Puts the JamFrame TV app on a Google TV and points it at this computer's watcher.
# On the TV first: Settings > System > About > press "Android TV OS build" seven times,
# then Developer options > USB debugging on. Accept the prompt the TV shows on first connection.
# Usage: scripts/install-tv.sh <TV address> "<Sonos room name>" [watcher address]
#   e.g. scripts/install-tv.sh 192.168.1.60 "Game Room"
set -e
[ $# -ge 2 ] || { sed -n 2,7p "$0"; exit 1; }
here=$(cd "$(dirname "$0")/.." && pwd)
adb=$(command -v adb || echo "$HOME/jamframe-tools/sdk/platform-tools/adb")
tv="$1:5555"; room="$2"
server=${3:-http://$(ipconfig getifaddr en0 || ipconfig getifaddr en1):8765}
[ -f "$here/tv/build/jamframe-tv.apk" ] || "$here/scripts/build-tv.sh"
"$adb" connect "$tv"
"$adb" -s "$tv" install -r "$here/tv/build/jamframe-tv.apk"
# open over the home screen, and see which app is in front (so a film is never interrupted)
"$adb" -s "$tv" shell appops set com.jamframe.tv SYSTEM_ALERT_WINDOW allow
"$adb" -s "$tv" shell appops set com.jamframe.tv GET_USAGE_STATS allow
"$adb" -s "$tv" shell am start -n com.jamframe.tv/.Main --es server "$server" --es room "'$room'"
echo "installed: the TV now shows '$room' from $server"
