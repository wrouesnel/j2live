#!/bin/bash
# Build the SRPM and RPM for one or more RHEL releases in containers, then
# install each RPM in a clean container and smoke test it.
#
# Usage: packaging/rpm/build.sh [TARGET...]   (el8, el10; default: all)
#
# Environment:
#   SKIP_TEST=1   Don't smoke test the built packages
#
# Output: dist/rpm/<target>/ with the SRPM and RPMs.
# packaging/rpm/publish-copr.sh submits the SRPMs to COPR.
source "$(dirname "$0")/../common.sh"
source "$(dirname "$0")/targets.sh"

VERSION="$(upstream_version)"
spec_version="$(sed -n 's/^Version: *//p' "$PROJECT_ROOT/packaging/rpm/j2live.spec")"
if [ "$spec_version" != "$VERSION" ]; then
    echo "j2live.spec Version ($spec_version) doesn't match pyproject.toml ($VERSION)" >&2
    exit 1
fi

TARGETS=("$@")
[ ${#TARGETS[@]} -gt 0 ] || mapfile -t TARGETS < <(all_targets)

vendor="$DIST_DIR/rpm/j2live-vendor-$VERSION.tar.gz"
for target in "${TARGETS[@]}"; do
    if [ "$target" = el8 ] && [ ! -f "$vendor" ]; then
        "$PROJECT_ROOT/packaging/rpm/make-vendor.sh"
    fi
done

# Prepare and enter an EL container with EPEL and CRB/PowerTools enabled,
# like COPR's epel-N chroots.
enable_repos='dnf -q -y install epel-release dnf-plugins-core >/dev/null
    dnf config-manager --set-enabled powertools 2>/dev/null || dnf config-manager --set-enabled crb'

for target in "${TARGETS[@]}"; do
    image="$(target_image "$target")"
    out="$DIST_DIR/rpm/$target"
    work="$(mktemp -d)"
    trap 'podman unshare rm -rf "$work" 2>/dev/null || rm -rf "$work"' EXIT
    rm -rf "$out"; mkdir -p "$out" "$work/SOURCES" "$work/SPECS"

    echo "==> Building j2live $VERSION for $target"
    source_tarball "$work/SOURCES/j2live-$VERSION.tar.gz" "j2live-$VERSION" debian dist
    cp "$vendor" "$work/SOURCES/" 2>/dev/null || true
    cp "$PROJECT_ROOT/packaging/rpm/j2live.spec" "$work/SPECS/"

    "$CONTAINER_ENGINE" run --rm -v "$work:/root/rpmbuild:Z" "$image" bash -euc "
        set -o pipefail
        $enable_repos
        dnf -q -y install rpm-build >/dev/null
        cd /root/rpmbuild
        rpmbuild -bs SPECS/j2live.spec
        dnf -q -y builddep SRPMS/*.src.rpm >/dev/null
        rpmbuild --rebuild SRPMS/*.src.rpm 2>&1 | grep -vE '^(\\+|Executing|Processing files)'
        if [ '$CONTAINER_ENGINE' = docker ]; then chown -R $(id -u):$(id -g) /root/rpmbuild; fi
    "
    find "$work/SRPMS" "$work/RPMS" -name '*.rpm' ! -name '*.nosrc.rpm' -exec cp {} "$out/" \;
    podman unshare rm -rf "$work" 2>/dev/null || rm -rf "$work"; trap - EXIT
    echo "==> Built:"; ls -1 "$out"

    if [ "${SKIP_TEST:-0}" != 1 ]; then
        echo "==> Smoke testing on $target"
        "$CONTAINER_ENGINE" run --rm -v "$out:/rpms:ro,Z" \
            -v "$PROJECT_ROOT/packaging/smoke-test.py:/smoke-test.py:ro,Z" "$image" bash -euc "
            $enable_repos
            dnf -q -y install \$(ls /rpms/*.rpm | grep -v 'src\\.rpm\$') >/dev/null
            j2live --help >/dev/null
            test -f /usr/share/applications/com.wrouesnel.j2live.desktop
            test -f /usr/share/j2live/ansible/action_plugins/j2live_template.py
            # The interpreter j2live itself runs under
            python=\$(head -1 \$(readlink -f /usr/bin/j2live) | sed 's/^#!//')
            # RHEL 10 has no Xvfb; run a headless Wayland compositor with Xwayland
            if dnf -q -y install xorg-x11-server-Xvfb xorg-x11-xauth >/dev/null 2>&1; then
                run_display() { xvfb-run -a \"\$@\"; }
            else
                dnf -q -y install xwayland-run weston xorg-x11-xauth >/dev/null
                export XDG_RUNTIME_DIR=/tmp/xdg; mkdir -m 0700 -p \$XDG_RUNTIME_DIR
                run_display() { xwfb-run -c weston -- \"\$@\"; }
            fi
            run_display \$python /smoke-test.py
            # And with the distribution's own ansible-core
            dnf -q -y install ansible-core >/dev/null
            ansible_python=\$(head -1 /usr/bin/ansible | sed 's/^#! *//; s/ .*//')
            run_display \$python /smoke-test.py --python \$ansible_python
        "
    fi
done
