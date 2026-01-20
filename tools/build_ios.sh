#!/usr/bin/env bash
set -euo pipefail

# Local helper to archive and export an IPA. Edit the variables below as needed.
PROJECT="swift/MagiCAM.xcodeproj"
SCHEME="ARKitSender"
CONFIG="Release"
ARCHIVE_PATH="./build/ARKitSender.xcarchive"
EXPORT_PATH="./build/export"

mkdir -p ./build

# Optional: set these env vars for signing:
# P12_PATH=~/certs/cert.p12
# P12_PASSWORD=...
# PROV_PATH=~/certs/profile.mobileprovision
# TEAM_ID=YOUR_TEAM_ID
# BUNDLE_ID=com.your.bundle.id
# PROV_NAME="Your Provisioning Profile Name"

if [[ -n "${P12_PATH:-}" ]]; then
  echo "Importing certificate $P12_PATH"
  security import "$P12_PATH" -k ~/Library/Keychains/login.keychain -P "$P12_PASSWORD" -A || true
fi
if [[ -n "${PROV_PATH:-}" ]]; then
  mkdir -p ~/Library/MobileDevice/Provisioning\ Profiles
  cp "$PROV_PATH" ~/Library/MobileDevice/Provisioning\ Profiles/
fi

# Archive
xcodebuild -project "$PROJECT" -scheme "$SCHEME" -configuration "$CONFIG" -archivePath "$ARCHIVE_PATH" clean archive

if [[ -n "${PROV_PATH:-}" && -n "${TEAM_ID:-}" && -n "${BUNDLE_ID:-}" && -n "${PROV_NAME:-}" ]]; then
  cat > exportOptions.plist <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "">
<plist version="1.0">
<dict>
  <key>method</key>
  <string>ad-hoc</string>
  <key>teamID</key>
  <string>${TEAM_ID}</string>
  <key>signingStyle</key>
  <string>manual</string>
  <key>provisioningProfiles</key>
  <dict>
    <key>${BUNDLE_ID}</key>
    <string>${PROV_NAME}</string>
  </dict>
</dict>
</plist>
EOF
  xcodebuild -exportArchive -archivePath "$ARCHIVE_PATH" -exportOptionsPlist exportOptions.plist -exportPath "$EXPORT_PATH"
  echo "Exported to $EXPORT_PATH"
else
  echo "No provisioning/settings found; archived at $ARCHIVE_PATH (you can export locally with exportOptions.plist)"
fi

ls -la build
