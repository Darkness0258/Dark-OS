#!/bin/bash
set -e
KEY_PATH="/workspace/airootfs/home/darkos/.ssh/authorized_keys"
mkdir -p "$(dirname "$KEY_PATH")"
cat > "$KEY_PATH" << 'KEYEOF'
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHNlbmRlci12bWFyZ2VyLXRlc3Qtc2VydmVyLWNlcnRpZnlAZXhhbXBsZS5jb20= darkos-vmware-test
KEYEOF
chmod 700 "$(dirname "$KEY_PATH")"
chmod 600 "$KEY_PATH"
echo "SSH key injected into ISO profile at $KEY_PATH"
