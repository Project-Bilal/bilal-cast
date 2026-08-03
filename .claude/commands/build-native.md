---
description: Build the Pico W firmware UF2 natively on macOS (Apple Silicon), no Docker
---

Build the MicroPython 1.24 firmware UF2 for the Raspberry Pi Pico W **natively on macOS** — no Docker. This is faster than the Docker path (`/build`), which forces x86 emulation on Apple Silicon. Produces firmware equivalent to `Dockerfile.micropython.1.24.rp2`.

This is a runbook — run the steps, using background tasks for the long ones (toolchain download, submodule init, compile) and monitor them. Report the UF2 path when done.

## Critical gotcha
Do **NOT** use Homebrew's `arm-none-eabi-gcc` — it ships no newlib (empty sysroot), so the build fails with `fatal error: stdio.h: No such file or directory`. Use **Arm's official GNU toolchain** tarball (self-contained, no sudo), as below.

## Step 1 — one-time setup (idempotent; skips work already done)
```bash
set -e
BUILD_DIR="$HOME/.bilalcast-build"
TC_VER="14.2.rel1"
TC_DIR="$BUILD_DIR/arm-gnu-toolchain-${TC_VER}-darwin-arm64-arm-none-eabi"
MP_DIR="$BUILD_DIR/micropython"
mkdir -p "$BUILD_DIR"

# cmake (Homebrew formula is fine)
command -v cmake >/dev/null 2>&1 || /opt/homebrew/bin/brew install cmake

# Arm GNU toolchain (~128 MB) — includes newlib. Run in BACKGROUND, it's slow.
if [ ! -x "$TC_DIR/bin/arm-none-eabi-gcc" ]; then
  curl -L --fail -o "$BUILD_DIR/armgnu.tar.xz" \
    "https://developer.arm.com/-/media/Files/downloads/gnu/${TC_VER}/binrel/arm-gnu-toolchain-${TC_VER}-darwin-arm64-arm-none-eabi.tar.xz"
  tar -xf "$BUILD_DIR/armgnu.tar.xz" -C "$BUILD_DIR"
fi

# MicroPython v1.24.1 (shallow). Submodules are initialized during the build.
[ -d "$MP_DIR" ] || git clone --branch v1.24.1 --depth 1 https://github.com/micropython/micropython "$MP_DIR"

"$TC_DIR/bin/arm-none-eabi-gcc" --version | head -1   # sanity check
```

## Step 2 — apply the two board customizations + stage frozen modules
Mirror `Dockerfile.micropython.1.24.rp2` exactly. **If the Dockerfile's freeze list or seds change, update this too.** macOS uses BSD `sed` (`-i ''`). These are idempotent.
```bash
BUILD_DIR="$HOME/.bilalcast-build"; MP_DIR="$BUILD_DIR/micropython"
REPO="$(git rev-parse --show-toplevel)"
cd "$MP_DIR"

# Patch 1: disable the native LWIP mDNS responder (the app runs its own mdns_client responder)
sed -i '' -E 's/define LWIP_MDNS_RESPONDER([ ]+)1/define LWIP_MDNS_RESPONDER\10/g' ports/rp2/lwip_inc/lwipopts.h
# Patch 2: default DHCP hostname -> bilalcast
sed -i '' -E 's/define MICROPY_PY_NETWORK_HOSTNAME_DEFAULT([ ]+)"[^"]+"/define MICROPY_PY_NETWORK_HOSTNAME_DEFAULT\1"bilalcast"/g' ports/rp2/boards/RPI_PICO_W/mpconfigboard.h

# Frozen "bootstrap kernel" — what a blank-filesystem device needs to onboard + OTA itself.
cd ports/rp2
rm -rf modules/bilalcast
mkdir -p modules/bilalcast
cp -R "$REPO/bilalcast/phew"              modules/bilalcast/phew
cp    "$REPO/bilalcast/captive_portal.py" modules/bilalcast/captive_portal.py
cp    "$REPO/bilalcast/ota.py"            modules/bilalcast/ota.py
cp    "$REPO/_bootstrap.py"               modules/main.py   # frozen entry point

grep -n "LWIP_MDNS_RESPONDER" ports/rp2/lwip_inc/lwipopts.h | head -1
grep -n "HOSTNAME_DEFAULT" ports/rp2/boards/RPI_PICO_W/mpconfigboard.h
find modules/bilalcast -type f | sort   # verify staged
```
Note: everything else (`bilalcast/*.py` app modules, `mdns_client/*`, `www/*`) is delivered via **OTA** (the manifest), not frozen — see the memory note on the frozen-vs-OTA split.

## Step 3 — build (run in BACKGROUND; ~5-15 min first time, faster after)
```bash
BUILD_DIR="$HOME/.bilalcast-build"; MP_DIR="$BUILD_DIR/micropython"
TC_DIR="$BUILD_DIR/arm-gnu-toolchain-14.2.rel1-darwin-arm64-arm-none-eabi"
export PATH="$TC_DIR/bin:/opt/homebrew/bin:$PATH"
export PICO_TOOLCHAIN_PATH="$TC_DIR/bin"
NCPU=$(sysctl -n hw.ncpu)
cd "$MP_DIR"
make -C mpy-cross -j"$NCPU"
cd ports/rp2
rm -rf build-RPI_PICO_W                       # clean, so cmake picks up the toolchain
make BOARD=RPI_PICO_W submodules              # downloads pico-sdk etc.
make BOARD=RPI_PICO_W -j"$NCPU"
ls -la build-RPI_PICO_W/firmware.uf2
```
The UF2 is `~/.bilalcast-build/micropython/ports/rp2/build-RPI_PICO_W/firmware.uf2`. Copy it into the repo for convenience: `cp <that> "$(git rev-parse --show-toplevel)/firmware.mp.1.24.rp2.uf2"` (`*.uf2` is gitignored). The version string shows `v1.24.1-dirty` — the `-dirty` is expected (patched source).

## Step 4 — verify the build (optional but recommended)
```bash
B="$HOME/.bilalcast-build/micropython/ports/rp2/build-RPI_PICO_W"
grep -oE "bilalcast/(captive_portal|ota|phew/[a-z_]+)" "$B/frozen_content.c" | sort -u   # frozen modules present
strings "$B/firmware.elf" | grep -w bilalcast | head -1                                  # hostname baked in
```

## Step 5 — flash (preserves the filesystem: config.json + OTA'd app survive)
```bash
python3 -m pip install --user --quiet mpremote 2>/dev/null   # if missing
NODE=$(ls /dev/cu.usbmodem* 2>/dev/null | head -1)
# Put the Pico into BOOTSEL over serial (or hold the BOOTSEL button while plugging in):
python3 -m mpremote connect "$NODE" bootloader
# Wait for the mass-storage volume, then copy the UF2 (device auto-reboots):
until ls /Volumes/RPI-RP2 >/dev/null 2>&1; do sleep 1; done
cp "$HOME/.bilalcast-build/micropython/ports/rp2/build-RPI_PICO_W/firmware.uf2" /Volumes/RPI-RP2/
```
After it re-enumerates, confirm: `python3 -m mpremote connect $(ls /dev/cu.usbmodem* | head -1) exec "import sys; print(sys.version)"`.

## Notes for future sessions
- `mpremote connect` soft-resets the device and clears the running app's module state (e.g. `discovery._persistent_client` becomes `None`).
- A firmware reflash preserves littlefs — `config.json` and the OTA'd `bilalcast/` app are kept; you don't re-onboard.
- Reflash is only needed to change frozen code (`_bootstrap.py`, and the first-boot fallbacks `phew`/`captive_portal`/`ota`) or to refresh a brand-new device's first-boot experience. Provisioned devices update via OTA.
- Keep the frozen list and the two seds in sync with `Dockerfile.micropython.1.24.rp2`.

Tell the user when the build is complete and where the UF2 is; ask before flashing.
