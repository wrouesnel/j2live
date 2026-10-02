#!/bin/bash
# Download the Python packages bundled on RHEL 8 into a vendor tarball, in an
# AlmaLinux 8 container so sdists are resolved for that platform.
#
# Usage: packaging/rpm/make-vendor.sh
# Output: dist/rpm/j2live-vendor-<version>.tar.gz
#
# Compiled packages are kept as sdists and built in the RPM build, so the
# tarball is architecture independent.
source "$(dirname "$0")/../common.sh"

VERSION="$(upstream_version)"
out="$DIST_DIR/rpm"
mkdir -p "$out"
work="$(mktemp -d)"
trap 'podman unshare rm -rf "$work" 2>/dev/null || rm -rf "$work"' EXIT

cp "$PROJECT_ROOT/packaging/rpm/el8-requirements.in" "$work/"
"$CONTAINER_ENGINE" run --rm -v "$work:/work:Z" -w /work docker.io/library/almalinux:8 bash -euc '
    dnf -q -y install epel-release >/dev/null
    dnf config-manager --set-enabled powertools
    dnf -q -y install python3.12-devel gcc gobject-introspection-devel cairo-gobject-devel \
        cairo-devel pkgconf-pkg-config ninja-build >/dev/null
    python3.12 -m venv /venv
    /venv/bin/pip -q install --upgrade pip
    mkdir -p vendor
    /venv/bin/pip download -q -d vendor -r el8-requirements.in \
        --no-binary pygobject,pycairo,markupsafe,ruamel.yaml.clib
    (cd vendor && sha256sum * > SHA256SUMS)
'
tar -C "$work" --sort=name --owner=0 --group=0 --mtime='2026-01-01 00:00Z' \
    --transform "s,^vendor,j2live-vendor-$VERSION," -czf "$out/j2live-vendor-$VERSION.tar.gz" vendor
echo "==> $out/j2live-vendor-$VERSION.tar.gz"
tar -tzf "$out/j2live-vendor-$VERSION.tar.gz" | sed 's,^[^/]*/,  ,' | grep -v '^  $'
