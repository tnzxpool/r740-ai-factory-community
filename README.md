# R740 AI Factory Community Edition — installer candidate

This is a clean-room, secret-free packaging skeleton. It is intentionally not a
copy of the live R740 deployment. It provides a small working control plane,
CPU/NVIDIA deployment profiles, first-run secret creation, model manifests and
an adapter boundary for an OpenAI-compatible inference server.

## What works now

- `GET /healthz`, `/api/v1/info`, `/api/v1/hardware`, `/api/v1/models`;
- authenticated `POST /api/v1/chat/completions` proxy when an inference backend
  is configured;
- Docker Compose profiles for CPU and NVIDIA hosts;
- a native Linux/systemd installer;
- first-run secrets generated locally with restrictive permissions;
- no bundled model weights and no automatic model download;
- a dependency-free smoke test covering startup, manifests and authentication.

The web UI and control plane work without a GPU. Inference requires an external
OpenAI-compatible backend such as llama.cpp. The package never assumes a Tesla
P40; the NVIDIA adapter reports detected hardware and leaves backend-specific
flags to the operator.

## Quick start with Docker Compose

Requirements: Linux, Docker Engine and Compose v2. For the NVIDIA profile also
install the NVIDIA driver and NVIDIA Container Toolkit.

```sh
./scripts/first-run.sh
docker compose --profile cpu up --build
```

Open `http://localhost:8080`. Use exactly one profile at a time:

```sh
docker compose --profile nvidia up --build
```

The generated admin token remains in `secrets/admin_token`; it is mounted as a
file and is never placed in the image or Compose file. To connect inference,
edit `config/runtime.env` and set `R740_INFERENCE_BASE_URL` to a trusted backend.

## Native Linux/systemd

Run as root on a systemd distribution:

```sh
sudo ./scripts/install-systemd.sh
sudo systemctl enable --now r740-ai-factory
```

The installer places code under `/opt/r740-ai-factory`, configuration and the
admin token under `/etc/r740-ai-factory`, and mutable state under
`/var/lib/r740-ai-factory`. It does not install CUDA, drivers, Docker or models.

Diagnose or remove the native installation with:

```sh
sudo ./scripts/doctor.sh
sudo ./scripts/uninstall-systemd.sh --yes
```

Uninstall preserves configuration and state. Add `--purge-data` only when those
installation-specific directories should be deleted permanently.

## Validation

```sh
python3 tests/smoke_test.py
python3 tests/source_import_test.py
python3 tests/sbom_test.py
```

Generate a deterministic SPDX 2.3 source SBOM with:

```sh
SOURCE_DATE_EPOCH=0 python3 scripts/generate-sbom.py --output dist/source-sbom.spdx.json
```

If Docker is available, also validate the selected profile:

```sh
docker compose --profile cpu config --quiet
```

## Model manifests

`model-manifests/catalog.json` contains metadata only. Entries are disabled by
default and have no download URL. Operators must verify each model's license,
choose a quantization compatible with their hardware, pin an immutable revision
and SHA-256, then explicitly enable it. See `model-manifests/README.md`.

## Security boundary

- Generated files are ignored by Git and permissions are checked at first run.
- The API never returns the admin token or environment contents.
- POST endpoints require `Authorization: Bearer <admin token>`.
- The proxy accepts only the configured backend base URL and applies timeouts.
- HTTPS and public exposure belong at a separately configured reverse proxy.

Do not expose port 8080 directly to the Internet. Use a TLS reverse proxy and
network policy appropriate to the deployment.

## Deliberately missing integration inputs

The production portal, user database, model lifecycle manager, graphics worker,
MCP broker and Proxmox layout were not copied because no single release-ready,
authoritative source tree was identifiable in this workspace. Their integration
points are represented by configuration and adapter contracts rather than stale
candidate files. A release must import reviewed canonical components, add data
migrations and pass product-level E2E tests.

## Staged optional services

Sanitized, hash-traced source is now included for:

- the authenticated Tika/Tesseract parser gateway;
- read-only web/MCP tools with SSRF protections;
- the isolated rootless-Podman sandbox API;
- the Windows Local-MCP read-only connector.

They are not enabled by the base installer. Each service has its own example
configuration, dependency lock or system dependency manifest, unit template and
tests under `services/` or `clients/`. Platform acceptance still requires Linux
for parser/sandbox, SearXNG dependency resolution for tools and Windows DPAPI for
Local-MCP. See `docs/SERVICES_PORTABILITY.md`.

## Licensing status

Source files carry `SPDX-License-Identifier: LGPL-3.0-or-later`. Before publishing,
the repository must include the complete official LGPLv3 and GPLv3 license texts,
copyright ownership, third-party notices and a dependency/model license review.
This candidate does not claim that release licensing is complete.
