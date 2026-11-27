#!/bin/sh
# Make JamFrame permanent on this Mac:
#   - a login service that keeps the watcher running (starts at login, restarts if it stops)
#   - ~/Applications/JamFrame.app, which starts the watcher if it is not running and opens the settings page
# Usage: scripts/install-mac.sh            install and start
#        scripts/install-mac.sh remove     stop and uninstall
# Log: ~/Library/Logs/jamframe.log
set -e
here=$(cd "$(dirname "$0")/.." && pwd)
label=com.jamframe.watch
plist="$HOME/Library/LaunchAgents/$label.plist"
app="$HOME/Applications/JamFrame.app"
launchctl bootout "gui/$(id -u)" "$plist" 2>/dev/null || true
if [ "$1" = "remove" ]; then rm -rf "$plist" "$app"; echo "removed"; exit 0; fi
[ -x "$here/.venv/bin/python" ] || { echo "no $here/.venv: create it and pip install -r requirements.txt first"; exit 1; }

mkdir -p "$HOME/Library/LaunchAgents"
cat > "$plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$label</string>
  <key>ProgramArguments</key><array>
    <string>$here/.venv/bin/python</string><string>-u</string><string>$here/watch.py</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/jamframe.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/jamframe.log</string>
</dict></plist>
PLIST

rm -rf "$app"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
cp "$here/mac/JamFrame.icns" "$app/Contents/Resources/"
cat > "$app/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>JamFrame</string>
  <key>CFBundleIdentifier</key><string>com.jamframe.app</string>
  <key>CFBundleExecutable</key><string>JamFrame</string>
  <key>CFBundleIconFile</key><string>JamFrame</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSUIElement</key><true/>
</dict></plist>
PLIST
cat > "$app/Contents/MacOS/JamFrame" <<APP
#!/bin/sh
# Start the watcher if it is not running, then open the settings page.
service="gui/\$(id -u)"
launchctl print "\$service/$label" >/dev/null 2>&1 || launchctl bootstrap "\$service" "$plist"
launchctl kickstart "\$service/$label"
for try in 1 2 3 4 5 6 7 8 9 10; do
  curl -s -o /dev/null -m 1 http://localhost:8765/settings && break
  sleep 1
done
open http://localhost:8765/settings
APP
chmod +x "$app/Contents/MacOS/JamFrame"

launchctl bootstrap "gui/$(id -u)" "$plist"
echo "running; open JamFrame from ~/Applications, or http://localhost:8765/settings"
