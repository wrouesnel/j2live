#!/bin/bash
# Submit the SRPMs built by packaging/rpm/build.sh to COPR, which builds,
# signs and publishes them. Creates the COPR project the first time.
#
# Usage: packaging/rpm/publish-copr.sh [TARGET...]   (el8, el10; default: all)
#
# Needs copr-cli (e.g. `uv tool install copr-cli`) and an API token from
# https://copr.fedorainfracloud.org/api/ saved as ~/.config/copr.
source "$(dirname "$0")/../common.sh"
source "$(dirname "$0")/targets.sh"
source "$PROJECT_ROOT/packaging/publish.env"

TARGETS=("$@")
[ ${#TARGETS[@]} -gt 0 ] || mapfile -t TARGETS < <(all_targets)

command -v copr-cli >/dev/null || { echo "copr-cli is not installed" >&2; exit 1; }
[ -f ~/.config/copr ] || { echo "No COPR API token in ~/.config/copr" >&2; exit 1; }

chroots=()
for target in $(all_targets); do
    for arch in $COPR_ARCHES; do chroots+=("$(target_chroot "$target")-$arch"); done
done

if ! copr-cli get "$COPR_PROJECT" >/dev/null 2>&1; then
    echo "==> Creating COPR project $COPR_PROJECT"
    copr-cli create "$COPR_PROJECT" \
        $(printf -- '--chroot %s ' "${chroots[@]}") \
        --description "j2live: live preview editor for Jinja2 and Ansible templates. https://github.com/wrouesnel/j2live" \
        --instructions "Enable EPEL first (it provides gtksourceview4), then: sudo dnf copr enable ${COPR_PROJECT} && sudo dnf install j2live"
fi

for target in "${TARGETS[@]}"; do
    srpms=("$DIST_DIR/rpm/$target"/*.src.rpm)
    if [ ! -f "${srpms[0]}" ]; then
        echo "No SRPM for $target; run packaging/rpm/build.sh $target first" >&2
        exit 1
    fi
    target_chroots=()
    for arch in $COPR_ARCHES; do target_chroots+=(-r "$(target_chroot "$target")-$arch"); done
    echo "==> $(basename "${srpms[0]}") -> $COPR_PROJECT (${target_chroots[*]})"
    copr-cli build "$COPR_PROJECT" "${target_chroots[@]}" "${srpms[0]}"
done
