#!/bin/bash
# Sign the source packages built by packaging/deb/build.sh and upload them to
# the Launchpad PPA, which builds and publishes them.
#
# Usage: packaging/deb/publish-ppa.sh [--dry-run] [SERIES...]
#
# --dry-run signs nothing and simulates the upload. DPUT overrides the upload
# command, e.g. DPUT="dput --simulate" to sign but not upload.
source "$(dirname "$0")/../common.sh"
source "$(dirname "$0")/series.sh"
source "$PROJECT_ROOT/packaging/publish.env"

dry_run=0
if [ "${1:-}" = --dry-run ]; then dry_run=1; shift; fi
SERIES=("$@")
[ ${#SERIES[@]} -gt 0 ] || mapfile -t SERIES < <(all_series)

if [ -z "$J2LIVE_SIGNING_KEY" ]; then
    echo "Set J2LIVE_SIGNING_KEY in packaging/publish.env (see packaging/make-signing-key.sh)" >&2
    exit 1
fi
if ! gpg --list-secret-keys "$J2LIVE_SIGNING_KEY" >/dev/null 2>&1; then
    echo "Signing key $J2LIVE_SIGNING_KEY is not in your keyring" >&2
    exit 1
fi

for series in "${SERIES[@]}"; do
    changes=("$DIST_DIR/deb/$series"/*_source.changes)
    if [ ! -f "${changes[0]}" ]; then
        echo "No source package for $series; run packaging/deb/build.sh $series first" >&2
        exit 1
    fi
    echo "==> $(basename "${changes[0]}") -> $PPA"
    if [ $dry_run = 1 ]; then
        dput --simulate --unchecked "$PPA" "${changes[0]}"
    else
        debsign --re-sign -k"$J2LIVE_SIGNING_KEY" "${changes[0]}"
        ${DPUT:-dput} "$PPA" "${changes[0]}"
    fi
done

echo "==> Launchpad will email the upload result and build the packages."
echo "    Users install with: sudo add-apt-repository $PPA && sudo apt install j2live"
