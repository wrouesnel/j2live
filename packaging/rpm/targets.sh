# RHEL releases to build for: "name:build image:COPR chroot"
RPM_TARGETS=(
    "el8:docker.io/library/almalinux:8:epel-8"
    "el10:docker.io/library/almalinux:10:epel-10"
)

_target_field() {
    local entry
    for entry in "${RPM_TARGETS[@]}"; do
        if [ "${entry%%:*}" = "$1" ]; then
            local rest="${entry#*:}"
            case "$2" in
                image) echo "${rest%:*}" ;;
                chroot) echo "${rest##*:}" ;;
            esac
            return
        fi
    done
    echo "unknown target: $1" >&2; return 1
}
target_image() { _target_field "$1" image; }
target_chroot() { _target_field "$1" chroot; }
all_targets() { local e; for e in "${RPM_TARGETS[@]}"; do echo "${e%%:*}"; done; }
