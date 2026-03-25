#!/bin/bash
# ---------------------------------------------------------------------------
# install.sh — Install android-sms-gateway APK on the running emulator
#              and configure it to forward SMS to the local webhook.
#
# Usage:
#   WEBHOOK_URL=http://host.docker.internal:8100/sms ./modules/android/install.sh
#
# Prerequisites:
#   - adb is in PATH (on the host or inside the sandbox container)
#   - Android emulator is running and reachable at localhost:5555 (or ADB_HOST)
#   - APK either bundled here or downloaded at runtime (see APK_URL below)
# ---------------------------------------------------------------------------
set -euo pipefail

ADB_HOST="${ADB_HOST:-localhost}"
ADB_PORT="${ADB_PORT:-5555}"
WEBHOOK_URL="${WEBHOOK_URL:-http://host.docker.internal:8100/sms}"
APK_URL="${APK_URL:-https://github.com/capcom6/android-sms-gateway/releases/latest/download/app-release.apk}"
APK_PATH="/tmp/android-sms-gateway.apk"
PACKAGE_NAME="me.capcom6.smsgateway"

log() { echo "[install.sh] $*"; }
die() { echo "[install.sh] ERROR: $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 1. Connect ADB
# ---------------------------------------------------------------------------
log "Connecting ADB to ${ADB_HOST}:${ADB_PORT}..."
adb connect "${ADB_HOST}:${ADB_PORT}" || die "adb connect failed"

# ---------------------------------------------------------------------------
# 2. Wait for the device to come online
# ---------------------------------------------------------------------------
log "Waiting for device to be ready (may take up to 3 minutes)..."
timeout=180
elapsed=0
while ! adb -s "${ADB_HOST}:${ADB_PORT}" shell getprop sys.boot_completed 2>/dev/null | grep -q "1"; do
    if [ "$elapsed" -ge "$timeout" ]; then
        die "Timed out waiting for device to boot"
    fi
    sleep 5
    elapsed=$((elapsed + 5))
    log "  ...waiting (${elapsed}s / ${timeout}s)"
done
log "Device is ready."

# ---------------------------------------------------------------------------
# 3. Download APK (skip if already present)
# ---------------------------------------------------------------------------
if [ ! -f "$APK_PATH" ]; then
    log "Downloading APK from ${APK_URL}..."
    curl -fsSL -o "$APK_PATH" "$APK_URL" || die "Failed to download APK"
    log "APK downloaded to ${APK_PATH}"
else
    log "APK already present at ${APK_PATH}, skipping download."
fi

# ---------------------------------------------------------------------------
# 4. Install APK
# ---------------------------------------------------------------------------
log "Installing android-sms-gateway..."
adb -s "${ADB_HOST}:${ADB_PORT}" install -r "$APK_PATH" \
    || die "adb install failed"
log "APK installed successfully."

# ---------------------------------------------------------------------------
# 5. Grant required permissions
# ---------------------------------------------------------------------------
log "Granting permissions..."
for perm in \
    android.permission.RECEIVE_SMS \
    android.permission.READ_SMS \
    android.permission.SEND_SMS \
    android.permission.READ_PHONE_STATE; do
    adb -s "${ADB_HOST}:${ADB_PORT}" shell pm grant "$PACKAGE_NAME" "$perm" 2>/dev/null \
        && log "  Granted: $perm" \
        || log "  Skipped (already granted or unavailable): $perm"
done

# ---------------------------------------------------------------------------
# 6. Launch the app
# ---------------------------------------------------------------------------
log "Launching android-sms-gateway..."
adb -s "${ADB_HOST}:${ADB_PORT}" shell monkey \
    -p "$PACKAGE_NAME" \
    -c android.intent.category.LAUNCHER \
    1 > /dev/null

# Give the app a moment to initialise
sleep 3

# ---------------------------------------------------------------------------
# 7. Configure webhook URL via adb intent (if the app supports it)
#    Falls back to a broadcasted intent with the URL as an extra.
# ---------------------------------------------------------------------------
log "Configuring webhook URL: ${WEBHOOK_URL}"
adb -s "${ADB_HOST}:${ADB_PORT}" shell am broadcast \
    -a "me.capcom6.smsgateway.ACTION_SET_WEBHOOK" \
    --es "url" "${WEBHOOK_URL}" \
    2>/dev/null || true

log "Done! android-sms-gateway is installed and configured."
log "Webhook URL: ${WEBHOOK_URL}"
log "Open the app on the emulator to confirm and start the service."
