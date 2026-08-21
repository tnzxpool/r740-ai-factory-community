# Installation guide

This guide starts from a clean Linux host. Commands do not require access to the
private R740 deployment and do not place credentials in Git.

## 1. Host requirements

Minimum for the control plane:

- x86-64 Linux;
- Python 3.10 or newer (3.11+ for the advanced portal/core);
- 5 GiB free for application/build files;
- Docker Engine + Compose v2, **or** a systemd distribution.

For a local NVIDIA model:

- an NVIDIA driver which supports the selected CUDA toolkit;
- NVIDIA Container Toolkit when using the Compose `nvidia` profile;
- CUDA toolkit with `nvcc` when building `llama.cpp`;
- CMake, Git and a C++ compiler;
- enough RAM, VRAM and storage for the exact quantization;
- Tesla P40 uses CUDA compute capability 6.1 (`cuda-p40` build mode).

Run the matching read-only preflight first:

```sh
./scripts/preflight.sh compose-cpu
./scripts/preflight.sh compose-nvidia
sudo ./scripts/preflight.sh systemd-control
sudo ./scripts/preflight.sh systemd-model
sudo ./scripts/preflight.sh systemd-core
```

## 2. Docker Compose control plane

```sh
./scripts/bootstrap-compose.sh cpu
```

Generated local files:

- `config/runtime.env`: listener/backend settings;
- `config/portal.env`: advanced portal settings;
- `secrets/admin_token`: control-plane bearer token;
- `secrets/setup_token`: one-time advanced-portal setup token;
- `data/`: mutable control-plane data;
- `models/`: optional read-only model mount.

All are ignored by Git. The bootstrap never prints a token.

### Connect an existing backend

The backend must implement `POST /v1/chat/completions`. Edit only the generated
`config/runtime.env`:

```text
R740_INFERENCE_BASE_URL=http://host.docker.internal:8000
```

If the backend needs a bearer token, store it in
`secrets/backend_api_key` (mode 0600) and set the container-visible path:

```text
R740_INFERENCE_API_KEY_FILE=/run/local-secrets/backend_api_key
```

For native systemd, use an absolute root-owned file under
`/etc/r740-ai-factory/secrets/` readable by the `r740-ai` group.

Recreate and verify:

```sh
docker compose --profile cpu up -d --build
python3 scripts/verify-install.py --expect-inference --model YOUR_BACKEND_MODEL_ID
```

Use `compose-nvidia` only to check NVIDIA visibility in the control-plane
container. It does not provide a model runtime.

### Advanced portal preview

```sh
./scripts/bootstrap-compose.sh portal
```

Open <http://127.0.0.1:8081>. The setup token is in
`secrets/setup_token`. Missing core/parser/tools/sandbox services remain disabled
and return controlled errors. This profile demonstrates the multi-user UI; the
supported inference path is the control plane above.

## 3. Native systemd control plane

```sh
sudo ./scripts/preflight.sh systemd-control
sudo ./scripts/install-systemd.sh
sudo systemctl enable --now r740-ai-factory
sudo ./scripts/doctor.sh systemd
```

Layout:

- code: `/opt/r740-ai-factory`;
- configuration/secrets: `/etc/r740-ai-factory`;
- state/models: `/var/lib/r740-ai-factory`;
- listener: port 8080 (configured in `runtime.env`).

The installer does not overwrite an existing configuration and does not install
drivers, CUDA or model weights.

## 4. Build the reviewed llama.cpp runtime

Install distro packages for Git, CMake, a C++ compiler and (for GPU) CUDA. Then,
as a normal build user:

```sh
./scripts/build-llama-cpp.sh cuda-p40
```

The script fetches only the pinned revision recorded in the script, checks the
resulting commit, disables the optional curl downloader and builds
`llama-server` for `sm_61`. For newer GPUs use `cuda`; for a CPU-only functional
test use `cpu`.

Install the resulting executable outside a home directory because the service
uses `ProtectHome=true`:

```sh
sudo install -D -m 0755 build/llama.cpp-build/bin/llama-server \
  /usr/local/libexec/r740-ai-factory/llama-server
```

## 5. Add one local model

Download a model yourself using an upstream-approved method. Verify its license,
immutable revision and expected hash before copying it. No Hub token belongs in
the command history, manifest or repository.

```sh
sudo install -o r740-ai -g r740-ai -m 0640 /path/to/model.gguf \
  /var/lib/r740-ai-factory/models/model.gguf

sudo python3 scripts/register-local-model.py \
  --model /var/lib/r740-ai-factory/models/model.gguf \
  --runtime /usr/local/libexec/r740-ai-factory/llama-server \
  --id local-model --display-name "Local model" \
  --license "UPSTREAM-LICENSE" \
  --upstream-repo "owner/repository" --revision "immutable-revision" \
  --ctx-size 8192 --gpu-layers 99 \
  --install-systemd --start
```

Registration:

1. hashes runtime/model (and optional mmproj);
2. renders a loopback-only unit whose `ExecStartPre` rechecks every artifact hash;
3. backs up existing catalog/config files;
4. records provenance outside Git;
5. updates the local catalog and backend URL;
6. optionally starts the model and waits for health.

Use `--mmproj /var/lib/.../projector.gguf` for a compatible multimodal projector.
Only one Community model unit is registered by this simplified workflow.

## 6. Acceptance

```sh
sudo systemctl status r740-model-community r740-ai-factory --no-pager
sudo ./scripts/doctor.sh systemd
sudo python3 scripts/verify-install.py \
  --url http://127.0.0.1:8080 \
  --token-file /etc/r740-ai-factory/secrets/admin_token \
  --expect-inference --model local-model
```

The verification proves health, hardware/catalog endpoints, anonymous denial
and one authenticated visible response. It does not benchmark model quality.

## 7. Remote use and TLS

Keep the application on a private listener during tests. Recommended temporary
access:

```sh
ssh -L 8080:127.0.0.1:8080 user@server.example
```

For persistent exposure, deploy a TLS reverse proxy separately. Restrict access
by firewall and never expose the model/core/management ports directly.

## 8. Upgrade, backup and removal

Follow the exact backup, upgrade, rollback and token-rotation procedure in
[OPERATIONS.md](OPERATIONS.md). The installer preserves the operator model
catalog and existing configuration; acceptance is incomplete until both
`doctor.sh` and `verify-install.py` pass.

Removal preserving data:

```sh
sudo ./scripts/uninstall-systemd.sh --yes
```

Permanent removal of application-owned configuration and state:

```sh
sudo ./scripts/uninstall-systemd.sh --yes --purge-data
```

The purge option is intentionally explicit and irreversible.
