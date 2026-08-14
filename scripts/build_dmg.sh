#!/bin/bash
# Build the distributable: PyInstaller freeze → Academic OS.app → DMG.
# Run from anywhere: ./scripts/build_dmg.sh
# Output: dist/AcademicOS.dmg
#
# Signing is automatic when a "Developer ID Application" identity is in the
# keychain (override with SIGN_ID=""). Notarization prefers Apple ID
# credentials when NOTARY_APPLE_ID + NOTARY_PASSWORD are set (CI path — team
# ID is 4ULN66CM6Q), otherwise falls back to a notarytool keychain profile
# (default name "academicos", local-dev path; override NOTARY_PROFILE, or
# NOTARY_PROFILE="" to skip). Without either, output is unsigned and first
# launch on another Mac needs right-click → Open.
set -euo pipefail
cd "$(dirname "$0")/.."

# STAGE splits the build so CI can keep the signing keychain away from
# third-party code: STAGE=prep runs everything that executes npm/PyInstaller
# (steps 0-2) and stops; STAGE=package assembles/signs/notarizes from the
# existing dist/ (steps 3-4). Unset = full build (local dev).
STAGE="${STAGE-}"

if [ "$STAGE" != "package" ]; then

LLAMA_BUILD="b10273"
# sha256 of the official ggml-org release asset — this binary gets swept into
# our codesign + notarization, so a tampered upstream would ship as OUR signed
# app. Pinned hash makes that a hard build failure instead. Recompute when
# bumping LLAMA_BUILD: shasum -a 256 <asset>.
LLAMA_SHA256="fb3bf11c718db3abf2474a01a241ed1843b7619c2421ce24c6f6aec22dee522c"
if [ ! -x vendor/llama/llama-server ]; then
  echo "── 0/4 fetching llama-server ($LLAMA_BUILD, macOS arm64)"
  mkdir -p vendor/llama
  curl -fsSL "https://github.com/ggml-org/llama.cpp/releases/download/$LLAMA_BUILD/llama-$LLAMA_BUILD-bin-macos-arm64.tar.gz" -o /tmp/llama-dl.tar.gz
  echo "$LLAMA_SHA256  /tmp/llama-dl.tar.gz" | shasum -a 256 -c - \
    || { echo "FATAL: llama-server tarball sha256 mismatch — refusing to sign it"; rm -f /tmp/llama-dl.tar.gz; exit 1; }
  TMPX="$(mktemp -d)"
  tar -xzf /tmp/llama-dl.tar.gz -C "$TMPX"
  cp "$TMPX"/llama-*/llama-server "$TMPX"/llama-*/*.dylib vendor/llama/
  rm -rf "$TMPX" /tmp/llama-dl.tar.gz
fi

echo "── 1/4 building webui"
(cd webui && VITE_API_MODE=real npm run build >/dev/null)

echo "── 2/4 freezing backend (PyInstaller)"
.venv/bin/pyinstaller --noconfirm --clean --name academic-os \
  --paths . \
  --add-data "webui/dist:webui/dist" \
  --add-data "examples/agents:examples/agents" \
  --add-data "vendor/llama:vendor/llama" \
  --hidden-import backend.app \
  --collect-submodules backend \
  --collect-submodules uvicorn \
  --collect-submodules apscheduler \
  --collect-submodules pydantic \
  scripts/serve_frozen.py >/dev/null

fi  # STAGE != package

if [ "$STAGE" = "prep" ]; then
  echo "── prep stage done (webui built, backend frozen). Run STAGE=package to sign + package."
  exit 0
fi

echo "── 3/4 assembling Academic OS.app"
APP="dist/Academic OS.app"
VERSION="$(sed -n 's/^APP_VERSION = "\(.*\)"/\1/p' backend/version.py)"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp -R dist/academic-os "$APP/Contents/Resources/academic-os"

cat > "$APP/Contents/Info.plist" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Academic OS</string>
  <key>CFBundleDisplayName</key><string>Academic OS</string>
  <key>CFBundleIdentifier</key><string>org.academicos.app</string>
  <key>CFBundleVersion</key><string>${VERSION}</string>
  <key>CFBundleShortVersionString</key><string>${VERSION}</string>
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

# ── code signing: auto-detect a Developer ID Application identity unless
# SIGN_ID is set (SIGN_ID="" forces an unsigned build, e.g. on CI without certs)
SIGN_ID="${SIGN_ID-$(security find-identity -v -p codesigning 2>/dev/null \
  | awk -F'"' '/Developer ID Application/ {print $2; exit}')}"
if [ -n "$SIGN_ID" ]; then
  echo "── signing as: $SIGN_ID"
  ENT="$(mktemp -t entitlements).plist"
  # PyInstaller loads its own Python + extension dylibs, and llama-server JITs
  # Metal kernels — both need these two relaxations under the hardened runtime
  cat > "$ENT" << 'ENTITLEMENTS'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>com.apple.security.cs.allow-unsigned-executable-memory</key><true/>
  <key>com.apple.security.cs.disable-library-validation</key><true/>
</dict>
</plist>
ENTITLEMENTS
  # sign inside-out: every Mach-O in the frozen tree, then the bundle itself
  find "$APP/Contents/Resources" -type f \
    \( -name '*.dylib' -o -name '*.so' -o -perm +111 \) -print0 \
    | while IFS= read -r -d '' f; do
        file -b "$f" | grep -q 'Mach-O' || continue
        codesign --force --options runtime --timestamp \
          --entitlements "$ENT" --sign "$SIGN_ID" "$f" 2>/dev/null
      done
  codesign --force --options runtime --timestamp \
    --entitlements "$ENT" --sign "$SIGN_ID" "$APP"
  rm -f "$ENT"
  codesign --verify --deep --strict "$APP"
fi

echo "── 4/4 creating DMG"
rm -f dist/AcademicOS.dmg
STAGE="$(mktemp -d)"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname "Academic OS" -srcfolder "$STAGE" -ov -format UDZO \
  dist/AcademicOS.dmg >/dev/null
rm -rf "$STAGE"

if [ -n "$SIGN_ID" ]; then
  codesign --force --sign "$SIGN_ID" dist/AcademicOS.dmg
  if [ -n "${NOTARY_APPLE_ID-}" ] && [ -n "${NOTARY_PASSWORD-}" ]; then
    echo "── notarizing via Apple ID (a few minutes)"
    xcrun notarytool submit dist/AcademicOS.dmg \
      --apple-id "$NOTARY_APPLE_ID" --team-id 4ULN66CM6Q --password "$NOTARY_PASSWORD" --wait
    xcrun stapler staple dist/AcademicOS.dmg
    spctl -a -t open --context context:primary-signature -v dist/AcademicOS.dmg \
      && echo "── Gatekeeper: accepted"
  else
    NOTARY_PROFILE="${NOTARY_PROFILE-academicos}"
    if [ -n "$NOTARY_PROFILE" ] \
       && xcrun notarytool history --keychain-profile "$NOTARY_PROFILE" >/dev/null 2>&1; then
      echo "── notarizing (a few minutes)"
      xcrun notarytool submit dist/AcademicOS.dmg \
        --keychain-profile "$NOTARY_PROFILE" --wait
      xcrun stapler staple dist/AcademicOS.dmg
      spctl -a -t open --context context:primary-signature -v dist/AcademicOS.dmg \
        && echo "── Gatekeeper: accepted"
    else
      echo "── notarization skipped (no '$NOTARY_PROFILE' keychain profile and no"
      echo "   NOTARY_APPLE_ID/NOTARY_PASSWORD — run: xcrun notarytool store-credentials"
      echo "   academicos --apple-id ... --team-id 4ULN66CM6Q --password ...)"
    fi
  fi
fi

echo "done: $(du -sh dist/AcademicOS.dmg | cut -f1) → dist/AcademicOS.dmg"
