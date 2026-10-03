# Packaging

j2live is packaged for:

| Distribution | Package | Published to | How |
| --- | --- | --- | --- |
| Ubuntu 24.04 (noble) | `j2live_*~noble1_all.deb` | Launchpad PPA `ppa:w-rouesnel/j2live` | system Python and libraries |
| Ubuntu 26.04 (resolute) | `j2live_*~resolute1_all.deb` | Launchpad PPA | system Python and libraries |
| RHEL 10 and rebuilds | `j2live-*.el10.noarch.rpm` | COPR `j2live` | system Python and libraries |
| RHEL 8 and rebuilds | `j2live-*.el8.x86_64.rpm` | COPR `j2live` | private Python 3.12 environment in `/opt/j2live` |

RHEL 8's GTK bindings only exist for its Python 3.6, which is too old, so its
package bundles PyGObject and the other Python dependencies, built against
the system GTK from vendored sources (`rpm/el8-requirements.in`). Both RHEL
packages need EPEL for `gtksourceview4`.

Everything builds in containers (`podman` by default; set
`CONTAINER_ENGINE=docker` to use docker), using AlmaLinux images to stand in
for RHEL. Each build installs its package in a clean container and runs
`smoke-test.py` under a virtual display, with plain Jinja2 and with the
distribution's own ansible-core.

## Building

```
packaging/deb/build.sh          # Ubuntu, all series -> dist/deb/<series>/
packaging/rpm/build.sh          # RHEL, all targets -> dist/rpm/<target>/
packaging/rpm/build.sh el8      # just one
```

The RHEL 8 build needs `dist/rpm/j2live-vendor-<version>.tar.gz`, which
`rpm/make-vendor.sh` downloads (the build runs it if it's missing). Re-run it
after changing `rpm/el8-requirements.in`.

## Releasing

1. Bump `version` in `pyproject.toml` and `Version` in `rpm/j2live.spec`, and
   add entries to `debian/changelog` and the spec's `%changelog`.
2. Build and test everything: `packaging/deb/build.sh && packaging/rpm/build.sh`
3. Publish:
   ```
   packaging/deb/publish-ppa.sh      # signs the source uploads and dputs them
   packaging/rpm/publish-copr.sh     # submits the SRPMs to COPR
   ```
4. Tag the release (`git tag -s v<version>`) and push the tag. GitHub
   Releases carry only the source; packages are published through the PPA
   and COPR, never as release assets.

To rebuild the same version for the PPA (for example after a packaging fix),
bump `PPA_REVISION` (`PPA_REVISION=2 packaging/deb/build.sh`); for COPR bump
the spec's `Release`.

## One-time setup

**Signing key.** PPA uploads are signed with the shared Launchpad key
`2A128435A6FE8BD751AA578720959AB807096ADB` ("Will Rouesnel (GPG key for
launchpad signing)"), already registered on the `~w-rouesnel` Launchpad
account. `publish-ppa.sh` unlocks it with the passphrase from the login
keyring (`secret-tool lookup service gpg-passphrase fingerprint <fpr>`), or
gpg's pinentry if there isn't one.

**Launchpad.** Create a PPA named `j2live` at
<https://launchpad.net/~w-rouesnel/+activate-ppa>.

**COPR.** Log in at <https://copr.fedorainfracloud.org>, save your API token
from <https://copr.fedorainfracloud.org/api/> as `~/.config/copr`, and install
`copr-cli` (`uv tool install copr-cli`). `publish-copr.sh` creates the
project on first use. COPR signs the RPMs and repository with its own key for
the project.

Settings such as the PPA and COPR project names live in `publish.env`.
