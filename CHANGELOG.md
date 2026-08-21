# Changelog

## 0.2.0 - 2026-08-21

- replace the packaging-skeleton landing page with a functional authenticated chat UI;
- add guided Compose bootstrap and Linux/systemd/NVIDIA preflight;
- add a pinned `llama.cpp` P40 build helper and hash-bound local GGUF registration;
- add running-install verification with an authenticated visible-response gate;
- fix systemd portal configuration created after the base installer;
- make uninstall remove portal, core and model units as well as the base service;
- add newcomer installation, troubleshooting and architecture guides;
- add clean journey, documentation, model registration and container E2E tests.
- keep multi-turn chat context with an explicit reset and bounded history;
- support optional backend bearer tokens through a local secret file;
- preserve locally registered model catalogs across upgrades;
- verify runtime and GGUF SHA-256 before every model-service start;
- make browser setup usable on the configured Admin network and keep proxy-header
  enforcement as an explicit opt-in;
- bind host listeners to loopback by default and make diagnostics fail on outage;
- add operations, rollback and deterministic release-package guidance.

## 0.1.0 - 2026-08-15

- initial secret-free source publication and packaging baseline.
