#!/bin/sh
# Builds the Google TV app: tv/build/jamframe-tv.apk. No Gradle: four Android tools and javac.
# Needs a JDK 17 and the Android SDK (build-tools 34.0.0, platform android-34). By default it looks in
# ~/jamframe-tools, where this project keeps its own copy; set JAVA_HOME / ANDROID_HOME to use others.
set -e
here=$(cd "$(dirname "$0")/.." && pwd)
tools="$HOME/jamframe-tools"
JAVA_HOME=${JAVA_HOME:-$(ls -d "$tools"/jdk-17*/Contents/Home 2>/dev/null | head -1)}
ANDROID_HOME=${ANDROID_HOME:-$tools/sdk}
bt="$ANDROID_HOME/build-tools/34.0.0"
jar="$ANDROID_HOME/platforms/android-34/android.jar"
[ -x "$JAVA_HOME/bin/javac" ] && [ -x "$bt/aapt2" ] && [ -f "$jar" ] || { echo "JDK 17 or Android SDK not found"; exit 1; }
export JAVA_HOME PATH="$JAVA_HOME/bin:$PATH"

out="$here/tv/build"
rm -rf "$out" && mkdir -p "$out/classes" "$out/dex"
"$bt/aapt2" compile --dir "$here/tv/res" -o "$out/res.zip"
"$bt/aapt2" link -o "$out/unsigned.apk" -I "$jar" --manifest "$here/tv/AndroidManifest.xml" "$out/res.zip"
javac -Xlint:-options -source 8 -target 8 -classpath "$jar" -d "$out/classes" "$here"/tv/src/com/jamframe/tv/*.java
"$bt/d8" --lib "$jar" --min-api 26 --output "$out/dex" $(find "$out/classes" -name '*.class')
(cd "$out/dex" && zip -q -j ../unsigned.apk classes.dex)
"$bt/zipalign" -f 4 "$out/unsigned.apk" "$out/aligned.apk"

# A key of our own, made once and kept out of git: updates must be signed with the same one.
key="$here/tv/jamframe.keystore"
[ -f "$key" ] || keytool -genkeypair -keystore "$key" -storepass jamframe -keypass jamframe -alias jamframe \
    -keyalg RSA -keysize 2048 -validity 10000 -dname "CN=JamFrame" >/dev/null 2>&1
"$bt/apksigner" sign --ks "$key" --ks-pass pass:jamframe --key-pass pass:jamframe --out "$out/jamframe-tv.apk" "$out/aligned.apk"
"$bt/apksigner" verify "$out/jamframe-tv.apk"
echo "built tv/build/jamframe-tv.apk"
