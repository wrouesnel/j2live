# Ubuntu releases to build for: "series:image"
DEB_SERIES=(
    "noble:docker.io/library/ubuntu:24.04"
    "resolute:docker.io/library/ubuntu:26.04"
)

series_image() {
    local entry
    for entry in "${DEB_SERIES[@]}"; do
        if [ "${entry%%:*}" = "$1" ]; then echo "${entry#*:}"; return; fi
    done
    echo "unknown series: $1" >&2; return 1
}

all_series() {
    local entry
    for entry in "${DEB_SERIES[@]}"; do echo "${entry%%:*}"; done
}
