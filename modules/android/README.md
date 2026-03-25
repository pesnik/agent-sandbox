# Android Module

Runs a full Android 13 emulator inside Docker using [budtmo/docker-android](https://github.com/budtmo/docker-android).

## Ports

| Port | Description |
|------|-------------|
| 5555 | ADB over TCP |
| 6081 | noVNC for Android screen (host port; mapped from container's 6080) |

## Quick Start

### Standalone

```bash
cd modules/android
docker compose up -d
```

### With core sandbox

```bash
# From repo root
docker compose -f docker-compose.yml -f docker-compose.android.yml up -d
```

## Install android-sms-gateway

Once the emulator is running:

```bash
WEBHOOK_URL=http://host.docker.internal:8100/sms \
  ./modules/android/install.sh
```

This will:
1. Wait for the emulator to fully boot
2. Download the latest android-sms-gateway APK
3. Install it and grant SMS permissions
4. Configure it to POST incoming SMS to `WEBHOOK_URL`

## ADB Access

```bash
adb connect localhost:5555
adb devices
adb shell
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ANDROID_DEVICE` | `Samsung Galaxy S10` | Device profile for the emulator |
| `ANDROID_ADB_PORT` | `5555` | Host port for ADB |
| `ANDROID_NOVNC_PORT` | `6081` | Host port for the Android noVNC view |
| `WEBHOOK_URL` | `http://host.docker.internal:8100/sms` | SMS webhook URL for install.sh |
