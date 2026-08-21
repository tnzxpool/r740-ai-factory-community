# Architecture and supported scope

## Supported Community path

```text
Browser -> Community control plane :8080 -> trusted OpenAI-compatible backend
```

The control plane serves the functional chat UI, reads a metadata-only model
catalog, reports CPU/NVIDIA hardware and proxies authenticated chat requests.
The backend may be external or the hash-pinned local `llama.cpp` unit produced by
`register-local-model.py`.

Security invariants:

- no bundled/downloaded weights or credentials;
- backend URL is operator configuration;
- local model listener is loopback-only;
- anonymous POST requests are denied;
- generated secrets remain outside Git;
- model and runtime paths/sizes/SHA-256 are checked before unit creation;
- model units conflict, preventing the known heavy services from co-residing.

## Advanced staged stack

The repository also contains production-derived, sanitized components for the
multi-user portal, lifecycle controller, routing, graphics, parser, tools,
sandbox and Windows Local-MCP. These preserve useful contracts and tests, but a
portable public install cannot assume the original Proxmox topology or private
model artifacts.

Therefore:

- the advanced portal profile is a fail-closed UI/configuration preview;
- optional brokers are not started by the supported installer;
- core execution and autorouting remain disabled until an operator assembles
  and qualifies the corresponding services;
- absence of an optional service must produce a controlled unavailable result,
  never a remote fallback.

This boundary is deliberate: the supported Community path is small but actually
runnable, while advanced components are exposed honestly for further integration.
