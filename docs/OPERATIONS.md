<!-- SPDX-FileCopyrightText: 2026 R740 AI Factory contributors -->
<!-- SPDX-License-Identifier: LGPL-3.0-or-later -->

# Operations

## Status

Compose:

```sh
docker compose --profile cpu ps
./scripts/doctor.sh compose
python3 scripts/verify-install.py
```

Systemd:

```sh
sudo systemctl status r740-ai-factory 'r740-model-*'
sudo ./scripts/doctor.sh systemd
sudo python3 scripts/verify-install.py --token-file /etc/r740-ai-factory/secrets/admin_token
```

## Upgrade with rollback

1. Stop the control plane and model units.
2. Save configuration, state and unit definitions with metadata.
3. Pull the reviewed release and rerun the installer. The installer preserves
   `model-manifests/catalog.json` and `/etc/r740-ai-factory`.
4. Start services and run `doctor.sh` plus `verify-install.py`.
5. If either fails, stop services, restore the saved directories, reload systemd
   and rerun both gates before accepting rollback.

Example backup (model weights and an external llama.cpp runtime are deliberately
separate; back them up according to their own storage policy):

```sh
sudo systemctl stop r740-ai-factory 'r740-model-*'
stamp=$(date -u +%Y%m%dT%H%M%SZ)
sudo tar --xattrs --acls -C / -czf "/root/r740-community-$stamp.tgz" \
  etc/r740-ai-factory opt/r740-ai-factory var/lib/r740-ai-factory \
  etc/systemd/system/r740-ai-factory.service
```

## Token rotation

Write a new random value to the token file without printing it, keep mode 0640
and owner `root:r740-ai`, then restart the control plane. Existing browser tabs
must enter the new token.

## Uninstall

`sudo scripts/uninstall-systemd.sh` removes services and application code while
preserving configuration and state. `--purge-data` removes those directories too.
The operator-installed llama.cpp runtime, model weights, backup archives and the
service account are retained intentionally.
