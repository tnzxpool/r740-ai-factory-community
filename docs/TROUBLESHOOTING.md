# Troubleshooting

Start with:

```sh
./scripts/doctor.sh compose
# or
sudo ./scripts/doctor.sh systemd
```

## Browser says “backend not configured”

The application is healthy but `R740_INFERENCE_BASE_URL` is empty. Set it in the
generated `config/runtime.env` (Compose) or `/etc/r740-ai-factory/runtime.env`
(systemd), then recreate/restart the control plane.

## Docker cannot reach a backend on the host

Use `http://host.docker.internal:PORT`, not `127.0.0.1`; loopback inside a
container refers to the container itself. The supplied Compose file maps
`host.docker.internal` to the Linux host gateway.

## HTTP 401 from chat

Use the local `secrets/admin_token` (Compose) or
`/etc/r740-ai-factory/secrets/admin_token` (systemd). Do not use the portal setup
token. The browser stores the token only in `sessionStorage` for the current tab.

## Model service does not start

```sh
sudo systemctl status r740-model-community --no-pager
sudo journalctl -u r740-model-community -n 100 --no-pager
nvidia-smi
```

Common causes: model/runtime moved after registration, unreadable files, CUDA
architecture mismatch, insufficient VRAM, unsupported GGUF metadata or a context
size that is too large. Registration is hash-bound, so changed files must be
registered again deliberately.

## Tesla P40 build errors

Confirm `nvcc` exists and the toolkit supports architecture 61. Use
`./scripts/build-llama-cpp.sh cuda-p40`. P40 does not provide newer tensor-core
features; keep speculative decoding and flash attention off until separately
qualified.

## Remote browser cannot connect

Native services and the advanced portal intentionally bind loopback. Use an SSH
tunnel or configure a separate TLS reverse proxy. Do not solve this by exposing
model or management ports publicly.

## Compose startup failed

```sh
docker compose --profile cpu ps
docker compose --profile cpu logs --tail=100
docker compose --profile cpu config
```

Rerun `./scripts/first-run.sh`; it creates missing files but does not overwrite
existing configuration or tokens.

## Reset only generated Compose configuration

Stop containers first. Move `config/runtime.env`, `config/portal.env` and the
token files to protected backup storage, then rerun `first-run.sh`. Do not delete
`data/` unless loss of local state is intended.
