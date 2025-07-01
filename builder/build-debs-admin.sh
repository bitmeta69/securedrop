#!/bin/bash
# Build securedrop-admin packages. This runs *inside* the container.

set -euxo pipefail

source /etc/os-release

# Install virtualenv in the right place
mkdir -p /usr/share/securedrop-admin
cd /usr/share/securedrop-admin
virtualenv --python=python3 venv
./venv/bin/pip3 install --no-deps -r /src/admin/requirements.txt --require-hashes
./venv/bin/pip3 install /src/admin

# Build the package in /srv/securedrop-admin
mkdir -p /srv/securedrop-admin
cp -R /src/admin/debian /srv/securedrop-admin/

# Copy ansible-base
cp -R /src/install_files/ansible-base /srv/securedrop-admin/

# Copy venv
cp -R /usr/share/securedrop-admin/venv /srv/securedrop-admin/

# Copy translations
cp -R /src/securedrop/translations /srv/securedrop-admin/
cp /src/securedrop/i18n.json /srv/securedrop-admin/

# Extract the version string
cat /src/securedrop/version.py | cut -d'"' -f2 > /srv/securedrop-admin/version.txt

# Copy binaries
mkdir -p /srv/securedrop-admin/bin
cp /src/admin/bin/validate-gpg-key.sh /srv/securedrop-admin/bin/
cp /src/admin/bin/securedrop-admin-packaged /srv/securedrop-admin/bin/securedrop-admin

cd /srv/securedrop-admin

# Add the distro suffix to the version
bash /fixup-changelog

find /src/securedrop-admin

# Build the package
dpkg-buildpackage -us -uc

# Copy the built artifacts back and print checksums
source /etc/os-release
mkdir -p "/src/build/${VERSION_CODENAME}"
mv -v ../*.{buildinfo,changes,deb,tar.gz} "/src/build/${VERSION_CODENAME}"
cd "/src/build/${VERSION_CODENAME}"
sha256sum ./*
chown -R "$HOST_UID:$HOST_GID" "/src/build/${VERSION_CODENAME}"
