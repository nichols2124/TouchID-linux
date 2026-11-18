#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
set -euo pipefail
case ${0##*/} in
  t2-touchid-status) exec /opt/t2-touchid/.venv/bin/python -I \
    /opt/t2-touchid/src/t2-touchid-client.py status "$@" ;;
  t2-touchid-list) exec /opt/t2-touchid/.venv/bin/python -I \
    /opt/t2-touchid/src/t2-touchid-client.py list "$@" ;;
  t2-touchid-count) exec /opt/t2-touchid/.venv/bin/python -I \
    /opt/t2-touchid/src/t2-touchid-client.py count "$@" ;;
  t2-touchid-verify) exec /opt/t2-touchid/.venv/bin/python -I \
    /opt/t2-touchid/src/t2-touchid-client.py verify "$@" ;;
  # Admin/diagnostic names kept for anyone still using the exact old path;
  # `t2touch <name>` is the discoverable form (see t2_touchid_cli.py's
  # ADMIN_TARGETS). Both converge on the same real implementation file.
  t2-touchid-doctor) exec /usr/local/bin/t2touch doctor "$@" ;;
  t2-touchid-manage) exec /usr/local/bin/t2touch manage "$@" ;;
  t2-touchid-identities) exec /usr/local/bin/t2touch identities "$@" ;;
  t2-touchid-user-map) exec /usr/local/bin/t2touch user-map "$@" ;;
  t2-touchid-baseline) exec /usr/local/bin/t2touch baseline "$@" ;;
  t2-touchid-inventory) exec /usr/local/bin/t2touch inventory "$@" ;;
  t2-touchid-identify-finger) exec /usr/local/bin/t2touch identify-finger "$@" ;;
  t2-touchid-provision-catacomb) exec /usr/local/bin/t2touch provision-catacomb "$@" ;;
  t2-touchid-post-reboot) exec /usr/local/bin/t2touch post-reboot "$@" ;;
  t2-native-authority-rebind) exec /usr/local/bin/t2touch authority-rebind "$@" ;;
  t2-touchid-fprint-status) exec /usr/local/bin/t2touch fprint-status "$@" ;;
  t2-touchid-enroll) exec /usr/local/bin/t2touch enroll-cli "$@" ;;
  *) echo "Unknown Touch ID command" >&2; exit 2 ;;
esac
