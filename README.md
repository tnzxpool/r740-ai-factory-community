# R740 AI Factory Community Edition

A secret-free, weight-free local AI application for Linux workstations and
servers. The supported Community path provides a functional browser chat and
an authenticated OpenAI-compatible proxy. It can use an existing backend or a
local `llama.cpp` server, including CUDA builds for Tesla P40 (compute 6.1).

No production password, host address, certificate, database or model weight is
stored in this repository.

## Quick-start links

Start with the installation guide, then keep the troubleshooting and operations
guides available while configuring a backend or a local model:

- **[Install and run the first chat](https://github.com/tnzxpool/r740-ai-factory-community/blob/main/docs/INSTALL.md)**
- [Troubleshooting](https://github.com/tnzxpool/r740-ai-factory-community/blob/main/docs/TROUBLESHOOTING.md)
- [Operations, upgrade and rollback](https://github.com/tnzxpool/r740-ai-factory-community/blob/main/docs/OPERATIONS.md)
- [Architecture and supported scope](https://github.com/tnzxpool/r740-ai-factory-community/blob/main/docs/ARCHITECTURE.md)
- [Download the latest release](https://github.com/tnzxpool/r740-ai-factory-community/releases/latest)

For the shortest local preview, follow **Five-minute local start** below. For a
Tesla P40 or another NVIDIA GPU, follow the complete installation guide before
registering a GGUF model.

## Choose one supported path

| Goal | Path | Result |
|---|---|---|
| Check the UI and APIs | Docker Compose `cpu` | Control plane and browser chat; inference is disabled until a backend is configured |
| Use an existing OpenAI-compatible backend | Docker Compose `cpu` | Functional chat through the configured backend |
| Use a local GGUF on a Linux/P40 host | Native systemd | Hash-pinned `llama.cpp` service plus functional browser chat |
| Inspect the advanced multi-user UI | Docker Compose `portal` | Configuration preview; optional production-derived services remain disabled |

The `nvidia` Compose profile exposes GPU detection to the control plane; it does
**not** silently download or start a model. Use the native model procedure for a
reviewed local GGUF.

## Five-minute local start

Requirements: Linux, Python 3.10+, Docker Engine and Docker Compose v2.

```sh
git clone https://github.com/tnzxpool/r740-ai-factory-community.git
cd r740-ai-factory-community
./scripts/bootstrap-compose.sh cpu
```

Open <http://127.0.0.1:8080>. Read the administrator token locally (it is not
printed or committed) and paste it in the page:

```sh
cat secrets/admin_token
```

At this point health, hardware and catalog work. Chat reports “backend not
configured” until `R740_INFERENCE_BASE_URL` in `config/runtime.env` points to a
trusted OpenAI-compatible server. For a backend running on the Docker host:

```text
R740_INFERENCE_BASE_URL=http://host.docker.internal:8000
```

Then apply the change and verify it:

```sh
docker compose --profile cpu up -d --build
python3 scripts/verify-install.py --expect-inference --model YOUR_BACKEND_MODEL_ID
```

## Local GGUF on Tesla P40 or another NVIDIA GPU

This path never downloads a model automatically. You choose a licensed GGUF,
record its immutable upstream revision and install it locally.

```sh
sudo ./scripts/preflight.sh systemd-model
sudo ./scripts/install-systemd.sh

# Build the pinned, reviewed llama.cpp revision for Pascal sm_61.
./scripts/build-llama-cpp.sh cuda-p40
sudo install -D -m 0755 build/llama.cpp-build/bin/llama-server \
  /usr/local/libexec/r740-ai-factory/llama-server

# Copy your own reviewed GGUF into the protected model directory.
sudo install -o r740-ai -g r740-ai -m 0640 /path/to/model.gguf \
  /var/lib/r740-ai-factory/models/model.gguf

# Hash, register, install and start the loopback-only model service.
sudo python3 scripts/register-local-model.py \
  --model /var/lib/r740-ai-factory/models/model.gguf \
  --runtime /usr/local/libexec/r740-ai-factory/llama-server \
  --id local-model --display-name "Local model" \
  --license "UPSTREAM-LICENSE" \
  --upstream-repo "owner/repository" --revision "immutable-revision" \
  --install-systemd --start

sudo systemctl enable --now r740-ai-factory
sudo ./scripts/doctor.sh systemd
sudo python3 scripts/verify-install.py \
  --url http://127.0.0.1:8080 \
  --token-file /etc/r740-ai-factory/secrets/admin_token \
  --expect-inference --model local-model
```

See [the complete installation guide](docs/INSTALL.md) before exposing the
service to another machine or changing model parameters.

## Remote access without public exposure

Listeners are local or unencrypted development endpoints. Keep them private.
From a workstation, use an SSH tunnel:

```sh
ssh -L 8080:127.0.0.1:8080 user@server.example
```

Then browse to <http://127.0.0.1:8080>. For permanent LAN/Internet access, add
a separately managed TLS reverse proxy and firewall policy; never publish model,
core, parser, tools, sandbox or administrator ports directly.

## Operations

```sh
# Diagnose Compose or native systemd installs
./scripts/doctor.sh compose
sudo ./scripts/doctor.sh systemd

# Stop/remove Compose containers; local config and data remain
docker compose --profile cpu down

# Remove native units and code, preserving config/data
sudo ./scripts/uninstall-systemd.sh --yes

# Irreversibly remove installation config and state as well
sudo ./scripts/uninstall-systemd.sh --yes --purge-data
```

Detailed references:

- [Installation and first model](docs/INSTALL.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Operations, upgrade and rollback](docs/OPERATIONS.md)
- [Architecture and supported scope](docs/ARCHITECTURE.md)
- [Model provenance policy](model-manifests/README.md)
- [Security policy](SECURITY.md)
- [Optional service portability](docs/SERVICES_PORTABILITY.md)
- [Release history](CHANGELOG.md)

## Validation and release evidence

```sh
./scripts/release-gate.sh
python3 scripts/verify-install.py
# On a clean tagged tree, build a deterministic archive plus SHA-256:
./scripts/package-release.sh 0.2.0
```

GitHub Actions tests Python 3.10/3.12, the real POSIX lock, Windows Local-MCP,
the sanitized core/portal contracts, Compose builds and an authenticated
container E2E against a disposable OpenAI-compatible backend.

## Advanced components

`components/core`, `components/portal`, `services/` and `clients/local-mcp`
contain sanitized, hash-traced versions of the advanced R740 stack. They are
included for development and staged integration, but are not falsely presented
as a one-click clone of the private Proxmox topology. Unsupported features fail
closed when their backend is absent.

## License and model boundary

Original source is licensed under `LGPL-3.0-or-later`; see `COPYING`,
`COPYING.LESSER`, `THIRD_PARTY_NOTICES.md` and the CycloneDX/SPDX inventories.
Model weights are separate works with their own licenses. This repository does
not redistribute them or imply that an upstream model is suitable for a given
use.
