# Core portability boundaries

Service templates and sanitized source are included. The default Community
quickstart intentionally starts only the control plane.

- Model switching and graphics lifecycle require systemd; another init system
  needs a controller adapter.
- GPU exclusion uses POSIX `flock`, and telemetry uses `nvidia-smi`.
- Graphics requires a separately installed, license-compatible PyTorch/Diffusers
  environment and external weights.
- Model availability remains tied to exact size, SHA-256 and local qualification.
- The current safety policy permits one heavy GPU model at a time unless a
  hardware-specific coexistence canary proves otherwise.

These are explicit deployment constraints, not missing private source files.
