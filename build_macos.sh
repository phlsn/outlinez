#!/bin/bash
# Baut dist/Outlinez-<Version>-macOS.dmg (auf einem Mac oder in GitHub Actions).
#
# Optional signieren und notarisieren (Apple-Developer-Konto nötig), sonst ad-hoc-signiert:
#   MACOS_SIGN_IDENTITY="Developer ID Application: Name (TEAMID)"
#   MACOS_NOTARY_APPLE_ID, MACOS_NOTARY_PASSWORD (App-spezifisches Passwort), MACOS_NOTARY_TEAM_ID
set -euo pipefail
cd "$(dirname "$0")"

VERSION=$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)
ARCH=$(uname -m)  # arm64 (Apple Silicon) oder x86_64 (Intel)
APP="build/Outlinez.app"
RES="$APP/Contents/Resources"
echo "Outlinez $VERSION ($ARCH)"

rm -rf build/Outlinez.app build/dmg build/Outlinez.iconset
mkdir -p "$APP/Contents/MacOS" "$RES/app/static" "$RES/app/assets" "$RES/bin" dist

# App-Dateien
cp app.py server.py core.py effects.py export.py psd.py jobs.py paths.py modelinfo.py cli.py setup_models.py \
   pyproject.toml uv.lock README.md installer/THIRD-PARTY.txt installer/fetch.py installer/macos/firstrun.py "$RES/app/"

# Download-Liste für die Ersteinrichtung (Fortschritt, Rate, Restzeit) und beigelegte Wheels
uv run --no-project --python 3.12 --with packaging python installer/make_manifest.py mac "$RES/app/manifest.json"
cp static/* "$RES/app/static/"
echo "$VERSION" > "$RES/VERSION"
cp installer/macos/Outlinez "$APP/Contents/MacOS/Outlinez"
chmod +x "$APP/Contents/MacOS/Outlinez"

# uv und Python mitliefern (Python 3.12 aus python-build-standalone, wie unter Windows)
cp "$(command -v uv)" "$RES/bin/uv"
uv python install 3.12
PY=$(ls -d "$(uv python dir)"/cpython-3.12.*-macos-*-none | sort -V | tail -1)
cp -R "$PY" "$RES/python"
find "$RES/python" -name __pycache__ -type d -prune -exec rm -rf {} +

# Symbol aus dem Logo (static/icon.png, 512 px)
mkdir build/Outlinez.iconset
for s in 16 32 128 256 512; do
  sips -z $s $s static/icon.png --out "build/Outlinez.iconset/icon_${s}x${s}.png" >/dev/null
  d=$((s * 2)); [ $d -le 512 ] && sips -z $d $d static/icon.png --out "build/Outlinez.iconset/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns build/Outlinez.iconset -o "$RES/Outlinez.icns"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Outlinez</string>
  <key>CFBundleDisplayName</key><string>Outlinez</string>
  <key>CFBundleIdentifier</key><string>app.outlinez</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleExecutable</key><string>Outlinez</string>
  <key>CFBundleIconFile</key><string>Outlinez</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST

# Signieren: mit Developer ID falls vorhanden, sonst ad hoc (Pflicht auf Apple Silicon).
# Mit Developer ID ist für die Notarisierung die gehärtete Laufzeit nötig; die Ausnahme
# disable-library-validation erlaubt PyTorch & Co., die erst beim ersten Start geladen werden.
IDENTITY="${MACOS_SIGN_IDENTITY:--}"
SIGN_OPTS=(--force --sign "$IDENTITY")
if [ "$IDENTITY" != "-" ]; then
  SIGN_OPTS+=(--timestamp --options runtime --entitlements installer/macos/entitlements.plist)
fi
while IFS= read -r -d '' f; do
  file -b "$f" | grep -q "Mach-O" && codesign "${SIGN_OPTS[@]}" "$f"
done < <(find "$RES/python" "$RES/bin" -type f -print0)
codesign "${SIGN_OPTS[@]}" "$APP"
codesign --verify --deep --strict "$APP"

# DMG mit Verknüpfung zum Programme-Ordner
mkdir -p build/dmg
cp -R "$APP" build/dmg/
ln -s /Applications build/dmg/Programme
DMG="dist/Outlinez-$VERSION-macOS-$ARCH.dmg"
rm -f "$DMG"
hdiutil create -volname "Outlinez" -srcfolder build/dmg -ov -format UDZO "$DMG" >/dev/null

if [ -n "${MACOS_NOTARY_APPLE_ID:-}" ] && [ "$IDENTITY" != "-" ]; then
  codesign --sign "$IDENTITY" "$DMG"
  xcrun notarytool submit "$DMG" --apple-id "$MACOS_NOTARY_APPLE_ID" --password "$MACOS_NOTARY_PASSWORD" \
    --team-id "$MACOS_NOTARY_TEAM_ID" --wait
  xcrun stapler staple "$DMG"
fi

echo "Fertig: $DMG ($(du -h "$DMG" | cut -f1))"
