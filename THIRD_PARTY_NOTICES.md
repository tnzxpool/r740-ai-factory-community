# Third-party notices

The base control plane uses only the Python standard library. Optional product
components install pinned third-party Python packages under their own licenses.
The generated inventory is `docs/dependencies.cdx.json`; its source mapping is
`config/dependency-licenses.json`.

The main families are FastAPI/Pydantic/Uvicorn/HTTPX/Starlette, portal parsing
and cryptography libraries, Hugging Face graphics libraries, PyTorch, and the
Windows Local-MCP cryptography/WebSocket stack. They are MIT, BSD, Apache-2.0,
MIT-CMU or dual Apache/BSD licensed as recorded in the CycloneDX file. No
dependency is relicensed as LGPL by this project.

Docker, systemd, NVIDIA drivers/toolkit, llama.cpp, Tika, Tesseract, Podman and
SearXNG are external prerequisites or separately operated services and are not
redistributed here. SearXNG is AGPL software; operators must satisfy its source
and network-use obligations independently.

The committed inventory proves declared names, versions and known licenses. It
does not replace a release-time vulnerability scan, wheel/sdist content scan or
platform-specific hash lock.
