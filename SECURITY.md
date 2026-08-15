# Security policy

Do not report vulnerabilities with credentials, private keys, production logs
or user data attached. Provide a minimal reproduction with synthetic values.

The public package must never contain runtime environment files, databases,
tokens, certificates, model weights or deployment-specific addresses. Secrets
are generated locally by `scripts/first-run.sh` and mounted from files.

The default HTTP listener is intended for local testing. Use an authenticated
TLS reverse proxy and restrictive firewall before exposing it to a network.

Until a public security contact is selected, report issues privately to the
repository maintainer rather than opening an issue containing exploit details.

