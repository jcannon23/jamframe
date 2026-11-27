#!/usr/bin/env bash
# Build BetterFrame from its own repo (pinned to the commit we audited) and install it on the TV.
# Its code stays out of this repo: it has no license, so we use it, we don't copy it.
# Needs: adb, the Android SDK in ANDROID_HOME, a JDK 17+ in JAVA_HOME, USB debugging on on the TV.
# Usage: TV=<tv-address> scripts/install-betterframe.sh      Undo: TV=<tv-address> vendor/betterframe/scripts/rollback.sh
set -euo pipefail
cd "$(dirname "$0")/.."
: "${TV:?set TV to the TV address, e.g. TV=192.168.1.50}"
COMMIT=3a84de7
[ -d vendor/betterframe ] || git clone https://github.com/spinogrizz/betterframe.git vendor/betterframe
git -C vendor/betterframe checkout -q "$COMMIT"
TV="$TV" vendor/betterframe/scripts/install.sh
