#!/bin/bash
# gpg, unlocking the signing key with its passphrase from the login keyring,
# for use as debsign's signing program. Falls back to gpg's own pinentry if
# the keyring has no passphrase for the key.
#
# Usage: J2LIVE_SIGNING_KEY=<fingerprint> gpg-keyring-passphrase.sh [gpg args...]
set -euo pipefail

passphrase_fd() {
    secret-tool lookup service gpg-passphrase fingerprint "$J2LIVE_SIGNING_KEY" 2>/dev/null
}

if command -v secret-tool >/dev/null && [ -n "$(passphrase_fd | head -c1)" ]; then
    # The passphrase only ever travels through a pipe to gpg
    exec gpg --batch --pinentry-mode loopback --passphrase-fd 3 "$@" 3< <(passphrase_fd)
fi
exec gpg "$@"
