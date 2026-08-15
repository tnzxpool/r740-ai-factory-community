# Local MCP connector 0.2.1

Outbound-only Windows client. It uses public system TLS trust, an Ed25519 device
key protected by CurrentUser DPAPI, single-use pairing, an explicit local folder
allowlist and per-call consent. Guest remains hard-denied. Only directory listing
and text-file reading are supported; shell and writes are absent.

Copy `config.example.json` to the ignored `config.json`, replace the example WSS
hostname and choose allowed folders locally. Valid endpoints must use public WSS,
port 443 or 8448 and exactly `/api/local-mcp/connect`; URL credentials, query,
fragment, IP literals and private CA files fail closed.

Install dependencies from `requirements.lock` using `--require-hashes`. No wheel,
device record, pairing token, audit file or generated configuration is bundled.
`prepare-local.ps1` downloads only hash-approved binary packages, creates a local
virtual environment and copies the example configuration; it does not pair,
connect, create persistence or start a background process.
