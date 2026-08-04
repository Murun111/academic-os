#!/bin/bash
# Build the distributable: PyInstaller freeze → Academic OS.app → unsigned DMG.
# Run from anywhere: ./scripts/build_dmg.sh
# Output: dist/AcademicOS.dmg
#
# NOTE: unsigned. First launch on another Mac needs right-click → Open.
# Proper signing/notarization requires an Apple Developer account:
#   codesign --deep --force --sign "Developer ID Application: ..." "dist/Academic OS.app"
#   xcrun notarytool submit dist/AcademicOS.dmg --keychain-profile ... --wait
set -euo pipefail
cd "$(dirname "$0")/.."

echo "── 1/4 building webui"
(cd webui && VITE_API_MODE=real npm run build >/dev/null)

echo "── 2/4 freezing backend (PyInstaller)"
.venv/bin/pyinstaller --noconfirm --clean --name academic-os \
  --paths . \
  --add-data "webui/dist:webui/dist" \
  --add-data "examples/agents:examples/agents" \
  --hidden-import backend.app \
  --collect-submodules backend \
  --collect-submodules uvicorn \
  --collect-submodules apscheduler \
  --collect-submodules pydantic \
  scripts/serve_frozen.py >/dev/null

echo "── 3/4 assembling Academic OS.app"
APP="dist/Academic OS.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp -R dist/academic-os "$APP/Contents/Resources/academic-os"

cat > "$APP/Contents/Info.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Academic OS</string>
  <key>CFBundleDisplayName</key><string>Academic OS</string>
  <key>CFBundleIdentifier</key><string>org.academicos.app</string>
  <key>CFBundleVersion</key><string>0.1.0</string>
  <key>CFBundleShortVersionString</key><string>0.1.0</string>
  <key>CFBundleExecutable</key><string>AcademicOS</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST

cat > "$APP/Contents/MacOS/AcademicOS" << 'LAUNCH'
#!/bin/bash
# Academic OS launcher — the .app process IS the server; quit it from the
# Dock to stop. Data lives in ~/.academic-os, untouched by app updates.
DIR="$(cd "$(dirname "$0")/../Resources/academic-os" && pwd)"
exec "$DIR/academic-os"
LAUNCH
chmod +x "$APP/Contents/MacOS/AcademicOS"

echo "── 4/4 creating DMG"
rm -f dist/AcademicOS.dmg
STAGE="$(mktemp -d)"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname "Academic OS" -srcfolder "$STAGE" -ov -format UDZO \
  dist/AcademicOS.dmg >/dev/null
rm -rf "$STAGE"

echo "done: $(du -sh dist/AcademicOS.dmg | cut -f1) → dist/AcademicOS.dmg"
