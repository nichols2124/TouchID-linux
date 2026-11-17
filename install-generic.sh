#!/usr/bin/env bash
# Minimal installer for any non-Omarchy desktop/compositor: no Omarchy, no
# Hyprland/UWSM integration, no lock-screen UI, no PAM (wire up fingerprint
# PAM for sudo/polkit yourself with tools/install-pam.sh, and for your
# greeter/lock screen with whatever your desktop provides -- e.g. dux-shell's
# `dms-greeter sync --auth`). Nothing here is niri-specific; this is just the
# generic path install.sh itself already supports via T2TOUCH_SKIP_PAM.
set -euo pipefail
(( EUID != 0 )) || { echo "Run as your normal user, not with sudo." >&2; exit 1; }
src=$(cd -- "$(dirname -- "$0")" && pwd -P)
headers=$(pacman -Qoq "/usr/lib/modules/$(uname -r)/vmlinuz")-headers
sudo pacman -S --needed --noconfirm base-devel dkms fprintd python "$headers"
set +e
sudo env T2TOUCH_SKIP_PAM=1 "$src/install.sh" "$@"
rc=$?
set -e
if (( rc == 3 )); then
  echo; echo ">>> A reboot is needed. After rebooting, run again: $src/install-generic.sh"
elif (( rc == 0 )); then
  echo; echo ">>> Done. Log out + log in, then: t2-touchid-enroll  and  fprintd-verify"
fi
exit $rc
