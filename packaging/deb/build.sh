#!/bin/bash
# Build the Ubuntu source and binary packages for one or more series in
# containers, then install each .deb in a clean container and smoke test it.
#
# Usage: packaging/deb/build.sh [SERIES...]   (default: all supported series)
#
# Environment:
#   DEB_REVISION  Debian revision of the package (default 1)
#   PPA_REVISION  PPA rebuild number (default 1)
#   SKIP_TEST=1   Don't smoke test the built packages
#
# Output: dist/deb/<series>/ with an unsigned source package and the .deb.
# packaging/deb/publish-ppa.sh signs and uploads the source packages.
source "$(dirname "$0")/../common.sh"
source "$(dirname "$0")/series.sh"

DEB_REVISION="${DEB_REVISION:-1}"
PPA_REVISION="${PPA_REVISION:-1}"
VERSION="$(upstream_version)"
SERIES=("$@")
[ ${#SERIES[@]} -gt 0 ] || mapfile -t SERIES < <(all_series)

for series in "${SERIES[@]}"; do
    image="$(series_image "$series")"
    out="$DIST_DIR/deb/$series"
    work="$(mktemp -d)"
    trap 'rm -rf "$work"' EXIT
    rm -rf "$out"; mkdir -p "$out"

    package_version="$VERSION-${DEB_REVISION}ppa${PPA_REVISION}~${series}1"
    echo "==> Building j2live $package_version for $series"

    source_tarball "$work/j2live_$VERSION.orig.tar.gz" "j2live-$VERSION" debian dist
    tar -xzf "$work/j2live_$VERSION.orig.tar.gz" -C "$work"
    cp -r "$PROJECT_ROOT/debian" "$work/j2live-$VERSION/"

    # A changelog entry for this series on top of the packaging's own
    {
        echo "j2live ($package_version) $series; urgency=medium"
        echo
        echo "  * Build for $series."
        echo
        echo " -- $MAINTAINER  $(date -R)"
        echo
        cat "$PROJECT_ROOT/debian/changelog"
    } > "$work/j2live-$VERSION/debian/changelog"

    "$CONTAINER_ENGINE" run --rm -v "$work:/build:Z" -w "/build/j2live-$VERSION" "$image" bash -euc '
        export DEBIAN_FRONTEND=noninteractive
        apt-get -qq update
        apt-get -qq install -y --no-install-recommends devscripts equivs >/dev/null
        mk-build-deps -i -r -t "apt-get -qq -y --no-install-recommends" debian/control >/dev/null
        # Launchpad only accepts source uploads; -sa includes the orig
        # tarball, which the first upload of a version to a PPA needs
        dpkg-buildpackage -us -uc -S -sa
        dpkg-buildpackage -us -uc -b
        rm -f ../*build-deps*
        # Rootful engines leave root-owned files; rootless podman maps root to us
        if [ "'"$CONTAINER_ENGINE"'" = docker ]; then chown -R '"$(id -u):$(id -g)"' /build; fi
    '
    find "$work" -maxdepth 1 -type f -exec cp {} "$out/" \;
    rm -rf "$work"; trap - EXIT
    echo "==> Built:"; ls -1 "$out"

    if [ "${SKIP_TEST:-0}" != 1 ]; then
        echo "==> Smoke testing on $series"
        "$CONTAINER_ENGINE" run --rm -v "$out:/debs:ro,Z" \
            -v "$PROJECT_ROOT/packaging/smoke-test.py:/smoke-test.py:ro,Z" "$image" bash -euc '
            export DEBIAN_FRONTEND=noninteractive
            apt-get -qq update
            apt-get -qq install -y /debs/j2live_*_all.deb xvfb xauth >/dev/null
            j2live --help >/dev/null
            test -f /usr/share/applications/com.wrouesnel.j2live.desktop
            test -f /usr/share/j2live/ansible/action_plugins/j2live_template.py
            xvfb-run -a /usr/bin/python3 /smoke-test.py
            # And with the distribution'"'"'s own ansible-core
            apt-get -qq install -y --no-install-recommends ansible-core >/dev/null
            xvfb-run -a /usr/bin/python3 /smoke-test.py --python /usr/bin/python3
        '
    fi
done
