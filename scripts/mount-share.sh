#!/usr/bin/env bash
# Example SMB mount helper. Edit SHARE, USER, and credentials before use.
set -euo pipefail

SHARE="${1:-//SERVER/theater-archive}"
MOUNT="${2:-/mnt/theater-archive}"
CREDS="${3:-/etc/theater-app/smb.credentials}"

sudo mkdir -p "$MOUNT"

if [[ ! -f "$CREDS" ]]; then
  echo "Create $CREDS with:"
  echo "  username=your_user"
  echo "  password=your_password"
  echo "  domain=WORKGROUP"
  exit 1
fi

sudo mount -t cifs "$SHARE" "$MOUNT" -o credentials="$CREDS",uid=$(id -u),gid=$(id -g),file_mode=0664,dir_mode=0775

echo "Mounted $SHARE at $MOUNT"
echo "Add to /etc/fstab for boot persistence:"
echo "$SHARE $MOUNT cifs credentials=$CREDS,uid=1000,gid=1000,file_mode=0664,dir_mode=0775,_netdev,x-systemd.automount 0 0"
