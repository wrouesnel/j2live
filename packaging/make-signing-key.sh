#!/bin/bash
# Create the j2live signing key in your personal GnuPG keyring, used to sign
# uploads to the Launchpad PPA. Run it yourself: gpg asks for a passphrase
# through your pinentry, which can save it in your login keyring.
#
# Usage: packaging/make-signing-key.sh
#
# Afterwards it records the fingerprint in packaging/publish.env and exports
# the public key to packaging/j2live-signing-key.asc. Then:
#   gpg --keyserver keyserver.ubuntu.com --send-keys <fingerprint>
# and add the fingerprint at https://launchpad.net/~/+editpgpkeys
set -euo pipefail
cd "$(dirname "$0")"

uid="Will Rouesnel (j2live package signing key) <wrouesnel@wrouesnel.com>"
if [ -n "${GNUPGHOME:-}" ]; then
    echo "GNUPGHOME is set; the release key belongs in your personal keyring" >&2
    exit 1
fi
if gpg --list-secret-keys "=$uid" >/dev/null 2>&1; then
    echo "A key for '$uid' already exists:" >&2
    gpg --list-secret-keys "=$uid" >&2
    exit 1
fi

gpg --quick-generate-key "$uid" rsa4096 sign 3y
fingerprint="$(gpg --with-colons --list-secret-keys "=$uid" | awk -F: '/^fpr/ {print $10; exit}')"
gpg --armor --export "$fingerprint" > j2live-signing-key.asc
sed -i "s/^J2LIVE_SIGNING_KEY=.*/J2LIVE_SIGNING_KEY=\"\${J2LIVE_SIGNING_KEY:-$fingerprint}\"/" publish.env
echo "Created $fingerprint"
echo "Next: gpg --keyserver keyserver.ubuntu.com --send-keys $fingerprint"
echo "      then add it at https://launchpad.net/~/+editpgpkeys"
