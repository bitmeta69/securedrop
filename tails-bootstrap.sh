#!/bin/bash
# bootstrap script to add persistent directories and links required for the
# securedrop-admin debian package under Tails.
set -e
set -x

admin_config_dir='/live/persistence/TailsData_unlocked/securedrop-admin'
admin_config_line='/home/amnesia/.config/securedrop-admin source=securedrop-admin'
persistence_file='/live/persistence/TailsData_unlocked/persistence.conf'

# create the persistent config directory
if [ ! -d "$admin_config_dir" ]; then
  mkdir "$admin_config_dir"
  chown amnesia:amnesia "$admin_config_dir"
  chmod 700 "$admin_config_dir"
fi

# check for the config dir line in persistence.conf and add it if it's missing

if ! grep -qP '^/home/amnesia/.config/securedrop-admin\h+source=securedrop-admin' "$persistence_file"; then
  echo "$admin_config_line" >> $persistence_file
fi

# TODO: add similar config changes to persist the FPF apt repo setup in /etc/apt


