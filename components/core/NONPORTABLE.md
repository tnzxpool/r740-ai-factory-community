# Remaining non-portable behaviour

This staging removes private addresses, live paths and secret values, but deliberately
does not pretend that the CT101 control plane is hardware- or OS-neutral.

- Model switching and graphics lifecycle call `systemctl`; another init system needs a
  controller adapter. Unit names are configurable and validated, but units are not yet
  included in this staging.
- GPU exclusion uses POSIX `flock`; model and graphics managers also use `grp`, `chown`
  and root-owned qualification files. Windows/macOS need a different process/ownership
  adapter. The Windows test run therefore skips the real `flock` test.
- GPU telemetry calls `nvidia-smi`; graphics requires CUDA, PyTorch, Diffusers and an
  NVIDIA-compatible GPU. The pinned overlay is the P40/CUDA-11.8 qualified profile,
  not a universal dependency.
- Model availability is tied to exact byte sizes, hashes, canary markers and selected
  GGUF/mmproj filenames. A generic installer must build model manifests and attestation
  files instead of weakening these checks.
- Storage telemetry invokes GNU `du -sb`; non-GNU systems need an implementation using
  native APIs.
- Runtime still assumes one heavy model and a single inference slot. This is a safety
  invariant for this edition, not an automatic multi-GPU scheduler.
- The live unit used a separate Python overlay for Diffusers. The public installer must
  reproduce this dependency set or create one locked environment; neither model weights
  nor the private overlay are included here.
- The source retains P40-specific qualification thresholds and model identifiers. They
  are metadata/guardrails, not proof that unrelated hardware has passed qualification.
