#!/usr/bin/env python3
"""Builds BarnesTV.apk (the Android TV / Google TV app) without Android Studio.

Needs Java 11+ and these files (paths via environment variables or the defaults below):
  ANDROID_JAR  android.jar of any API level >= 28       (e.g. from an Android SDK: platforms/android-28/android.jar)
  DX_JAR       dx-30.0.2.jar                            (ships in dex2jar's dex-tools lib folder)
  APKTOOL_JAR  apktool_2.10.0.jar                       (github.com/iBotPeaches/Apktool/releases)
  SIGNER_JAR   uber-apk-signer-1.3.0.jar                (github.com/patrickfav/uber-apk-signer/releases)

    python build.py                                   -> ../web/app/BarnesTV.apk (Barnes branding)
    python build.py --brand tv-app-branding.zip       your name, icon and banner (Appearance -> Branding ->
    python build.py --brand http://server:8420        "TV app branding kit", or straight from your server)
    python build.py --brand kit.zip --apply           also write that branding into res/ (for Android Studio builds)

Without --brand, a kit in android-tv/branding/ (folder) or android-tv/branding.zip is used if there is one.
"""
import argparse
import io
import json
import urllib.request
import zipfile
from xml.sax.saxutils import escape
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "web" / "app" / "BarnesTV.apk"
TOOLS = Path(os.environ.get("BTV_TOOLS", "/tmp/atv/tools"))
ANDROID_JAR = os.environ.get("ANDROID_JAR", "/tmp/atv/ap/android-28/android.jar")
DX_JAR = os.environ.get("DX_JAR", str(next(TOOLS.glob("d2j/*/lib/dx-*.jar"), "")))
APKTOOL_JAR = os.environ.get("APKTOOL_JAR", str(TOOLS / "apktool.jar"))
SIGNER_JAR = os.environ.get("SIGNER_JAR", str(TOOLS / "signer.jar"))


def run(cmd, **kw):
    print("+", " ".join(str(c) for c in cmd[:6]), "...")
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, **kw)
    if r.returncode != 0:
        sys.exit(r.stdout[-3000:] + "\n" + r.stderr[-3000:])
    return r.stdout


# where each file of a branding kit goes inside res/
KIT_FILES = {
    "ic_launcher_foreground.png": ["drawable-nodpi/ic_launcher_foreground.png"],
    "ic_launcher_monochrome.png": ["drawable-nodpi/ic_launcher_monochrome.png"],
    "ic_launcher.png": ["mipmap-xxxhdpi/ic_launcher.png", "drawable/icon.png"],
    "banner.png": ["drawable-xhdpi/banner.png", "drawable/banner.png"],
    "banner-xxhdpi.png": ["drawable-xxxhdpi/banner.png"],
}


def load_kit(src):
    """{filename: bytes} from a branding kit: a zip file, a folder, or a server address (http://host:8420)."""
    if not src:
        for cand in (HERE / "branding", HERE / "branding.zip"):
            if cand.exists():
                src = str(cand)
                break
        else:
            return None
    if src.startswith(("http://", "https://")):
        url = src.rstrip("/")
        if not url.endswith(".zip"):
            url += "/api/brand/tvapp-kit.zip"
        print("+ downloading branding from", url)
        data = urllib.request.urlopen(url, timeout=30).read()
        z = zipfile.ZipFile(io.BytesIO(data))
        return {n: z.read(n) for n in z.namelist()}
    p = Path(src)
    if p.is_dir():
        return {f.name: f.read_bytes() for f in p.iterdir() if f.is_file()}
    with zipfile.ZipFile(p) as z:
        return {n.split("/")[-1]: z.read(n) for n in z.namelist() if not n.endswith("/")}


def apply_kit(kit, res):
    """Write a branding kit into a res/ folder: app name, icon background colour, icon layers and banner."""
    info = json.loads(kit.get("branding.json", b"{}") or b"{}")
    if info.get("name"):
        (res / "values" / "strings.xml").write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n<resources>\n    <string name="app_name">'
            + escape(info["name"]).replace("'", "\\'") + '</string>\n</resources>\n', encoding="utf-8")
    if re.fullmatch(r"#[0-9a-fA-F]{6}", info.get("color") or ""):
        (res / "values" / "colors.xml").write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n<resources>\n    <color name="ic_launcher_background">'
            + info["color"] + '</color>\n</resources>\n', encoding="utf-8")
    for name, targets in KIT_FILES.items():
        if name in kit:
            for t in targets:
                (res / t).parent.mkdir(parents=True, exist_ok=True)
                (res / t).write_bytes(kit[name])
    print(f"+ branding: {info.get('name') or '(name unchanged)'}  colour {info.get('color') or '(unchanged)'}")


def signing_key():
    """Your app-signing key, described by android-tv/keystore.properties (both stay on your computer: they're in
    .gitignore). Made on the first build with the JDK's keytool and a random password. Keep them safe: an app
    update has to be signed with the same key to install over the old version."""
    props = HERE / "keystore.properties"
    if not props.exists():
        legacy = HERE / "barnes-tv.keystore"     # builds before 1.14 used this fixed key: keep using it if it's here
        if legacy.exists():
            info = {"storeFile": legacy.name, "storePassword": "barnestv", "keyAlias": "barnes", "keyPassword": "barnestv"}
        else:
            import secrets
            pw = secrets.token_urlsafe(18)
            info = {"storeFile": "release.keystore", "storePassword": pw, "keyAlias": "tvapp", "keyPassword": pw}
            print("+ creating your signing key (android-tv/release.keystore)")
            run(["keytool", "-genkeypair", "-keystore", HERE / info["storeFile"], "-storetype", "PKCS12",
                 "-alias", info["keyAlias"], "-keyalg", "RSA", "-keysize", "3072", "-validity", "10000",
                 "-storepass", pw, "-keypass", pw, "-dname", "CN=TV app, O=Self-built"])
        props.write_text("".join(f"{k}={v}\n" for k, v in info.items()))
    info = {}
    for line in props.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            info[k.strip()] = v.strip()
    return info


def main():
    ap = argparse.ArgumentParser(description="Build the Android TV app (web/app/BarnesTV.apk)")
    ap.add_argument("--brand", help="branding kit: .zip, folder, or your server's address")
    ap.add_argument("--apply", action="store_true", help="also save the branding into res/ (for Android Studio)")
    ap.add_argument("--keystore-only", action="store_true", help="just create the signing key (for Android Studio)")
    args = ap.parse_args()
    if args.keystore_only:
        print("signing key:", HERE / signing_key()["storeFile"])
        return
    kit = load_kit(args.brand)
    if kit and args.apply:
        apply_kit(kit, HERE / "res")
    gradle = (HERE / "build.gradle").read_text()
    code = re.search(r"versionCode\s+(\d+)", gradle).group(1)
    target = re.search(r"targetSdk\s+(\d+)", gradle).group(1)
    name = re.search(r'versionName\s+"([^"]+)"', gradle).group(1)
    build = HERE / "build"
    shutil.rmtree(build, ignore_errors=True)
    classes, apkdir = build / "classes", build / "apk"
    classes.mkdir(parents=True)
    apkdir.mkdir(parents=True)
    sources = [str(p) for p in (HERE / "src").rglob("*.java")]
    run(["javac", "-source", "8", "-target", "8", "-bootclasspath", ANDROID_JAR, "-cp", ANDROID_JAR,
         "-Xlint:-options", "-d", classes] + sources)
    run(["java", "-cp", DX_JAR, "com.android.dx.command.Main", "--dex", "--min-sdk-version=21",
         f"--output={apkdir / 'classes.dex'}", classes])
    manifest = (HERE / "AndroidManifest.xml").read_text().replace(
        "<manifest xmlns:android=\"http://schemas.android.com/apk/res/android\">",
        f'<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="tv.barnes.broadcast" '
        f'android:versionCode="{code}" android:versionName="{name}">')
    (apkdir / "AndroidManifest.xml").write_text(manifest)
    shutil.copytree(HERE / "res", apkdir / "res")
    if kit:
        apply_kit(kit, apkdir / "res")
    (apkdir / "apktool.yml").write_text(f"""!!brut.androlib.meta.MetaInfo
apkFileName: BarnesTV.apk
compressionType: false
doNotCompress:
- resources.arsc
- png
isFrameworkApk: false
packageInfo:
  forcedPackageId: '127'
  renameManifestPackage: null
sdkInfo:
  minSdkVersion: '21'
  targetSdkVersion: '{target}'
sharedLibrary: false
sparseResources: false
usesFramework:
  ids:
  - 1
  tag: null
version: 2.10.0
versionInfo:
  versionCode: '{code}'
  versionName: {name}
""")
    unsigned = build / "unsigned.apk"
    run(["java", "-jar", APKTOOL_JAR, "b", apkdir, "-o", unsigned, "-f"])
    ks = signing_key()
    run(["java", "-jar", SIGNER_JAR, "-a", unsigned, "-o", build / "signed", "--ks", HERE / ks["storeFile"],
         "--ksAlias", ks["keyAlias"], "--ksPass", ks["storePassword"], "--ksKeyPass", ks["keyPassword"]])
    signed = next((build / "signed").glob("*.apk"))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(signed, OUT)
    print("built", OUT, OUT.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
