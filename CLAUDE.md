# j2live

GTK live preview editor for Jinja2/Ansible templates. See README.md for
usage and packaging/README.md for how packages are built and released.

## Packaging and publishing

- Packages: Ubuntu 24.04 (noble) and 26.04 (resolute) debs, published to the
  Launchpad PPA `ppa:w-rouesnel/j2live`; RHEL 8 and 10 RPMs, published to the
  COPR project `wrouesnel/j2live` (chroots `epel-8-x86_64`, `epel-10-x86_64`).
- PPA uploads are signed with the shared Launchpad key
  `2A128435A6FE8BD751AA578720959AB807096ADB`, set in `packaging/publish.env`.
  COPR signs RPMs with its own project key.
- `.github/workflows/packaging.yml` builds and smoke tests every package on
  pull requests and pushes to master. Publishing is done locally with
  `packaging/deb/publish-ppa.sh` and `packaging/rpm/publish-copr.sh`.
- RHEL 8 bundles its Python dependencies in `/opt/j2live`, built offline from
  `dist/rpm/j2live-vendor-<version>.tar.gz` (`packaging/rpm/make-vendor.sh`).
- Container builds stand in for RHEL with AlmaLinux images.
