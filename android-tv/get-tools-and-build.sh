#!/usr/bin/env bash
# Builds web/app/BarnesTV.apk without Android Studio. Run it yourself on Linux or macOS:
#     bash android-tv/get-tools-and-build.sh
#     bash android-tv/get-tools-and-build.sh --brand http://<your-server>:8420     (your station's name and icons)
#     bash android-tv/get-tools-and-build.sh --brand tv-app-branding.zip
# Needs: a Java JDK 11+ (javac + java), python3, curl, unzip, git.  Downloads (once, into ~/.cache/barnes-tv-tools):
#   - android.jar (API 28) from github.com/Sable/android-platforms   (compile-time Android API)
#   - dex2jar 2.4 (for its bundled dx-30.0.2.jar)                      github.com/pxb1988/dex2jar
#   - apktool 2.10.0                                                    github.com/iBotPeaches/Apktool
#   - uber-apk-signer 1.3.0                                             github.com/patrickfav/uber-apk-signer
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
T="${BTV_TOOLS:-$HOME/.cache/barnes-tv-tools}"
mkdir -p "$T"
cd "$T"
for tool in javac java python3 curl unzip git; do
  command -v "$tool" >/dev/null || { echo "Please install $tool first (Java: e.g. sudo apt install openjdk-17-jdk)"; exit 1; }
done
if [ ! -f ap/android-28/android.jar ]; then
  echo "Fetching android.jar (API 28)..."
  rm -rf ap
  git clone --depth 1 --filter=blob:none --sparse https://github.com/Sable/android-platforms.git ap
  (cd ap && git sparse-checkout set android-28)
fi
[ -f apktool.jar ] || curl -fL -o apktool.jar https://github.com/iBotPeaches/Apktool/releases/download/v2.10.0/apktool_2.10.0.jar
[ -f signer.jar ] || curl -fL -o signer.jar https://github.com/patrickfav/uber-apk-signer/releases/download/v1.3.0/uber-apk-signer-1.3.0.jar
if ! ls d2j/*/lib/dx-*.jar >/dev/null 2>&1; then
  curl -fL -o dex-tools.zip https://github.com/pxb1988/dex2jar/releases/download/v2.4/dex-tools-v2.4.zip
  unzip -q -o dex-tools.zip -d d2j
fi
BTV_TOOLS="$T" ANDROID_JAR="$T/ap/android-28/android.jar" python3 "$HERE/build.py" "$@"
echo
echo "Done. Open http://<server>:8420/app on the TV - the app is ready to download."
