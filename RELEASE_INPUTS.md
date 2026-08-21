# Advanced integration roadmap

The supported Community control-plane path is installable and independently
tested. The following items apply only to promotion of the complete private
multi-service feature set; they do not invalidate the documented Community path.

- portable orchestration of every advanced core/graphics/parser/tools/sandbox
  service without assuming Proxmox container IDs or private addresses;
- a complete upgrade migration chain for databases created by older private
  deployments;
- clean-machine NVIDIA/P40 acceptance with operator-supplied model weights;
- optional reverse-proxy recipes for specific distributions;
- reproducible, target-specific SearXNG/parser/sandbox dependency images;
- product E2E for multi-user queueing, model switching, graphics, OCR, document
  ingestion and restart recovery across all optional services.

No advanced integration may weaken the current secret-free, local-only and
fail-closed defaults.
