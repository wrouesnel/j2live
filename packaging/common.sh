# Shared helpers for packaging scripts. Source from bash.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="${DIST_DIR:-$PROJECT_ROOT/dist}"
CONTAINER_ENGINE="${CONTAINER_ENGINE:-podman}"

MAINTAINER="Will Rouesnel <wrouesnel@wrouesnel.com>"

# Upstream version from pyproject.toml
upstream_version() {
    sed -n 's/^version = "\(.*\)"/\1/p' "$PROJECT_ROOT/pyproject.toml" | head -1
}

# Write an upstream source tarball of the files git knows about (committed or
# not, so a work in progress can be test built), excluding paths given as
# arguments. Usage: source_tarball OUTPUT PREFIX [EXCLUDE...]
source_tarball() {
    local output="$1" prefix="$2"; shift 2
    local filter='^$'
    if [ $# -gt 0 ]; then
        filter="^($(IFS='|'; echo "$*"))(/|$)"
    fi
    (cd "$PROJECT_ROOT" &&
        git ls-files --cached --others --exclude-standard -z |
        grep -zvE "$filter" |
        while IFS= read -r -d '' f; do [ -e "$f" ] && printf '%s\0' "$f"; done |
        tar --null --files-from=- --transform "s,^,$prefix/," \
            --sort=name --owner=0 --group=0 --mtime='2026-01-01 00:00Z' -cf - |
        # Byte-identical across builds: every series shares one orig tarball
        gzip -9n > "$output")
}
