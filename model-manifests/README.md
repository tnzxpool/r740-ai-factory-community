# Model manifest policy

The catalog is data, not an installer. A model may be enabled only after these
fields are completed and independently verified:

1. immutable upstream repository and revision;
2. exact artifact filename and SHA-256;
3. model license identifier and acceptance notes;
4. minimum RAM/VRAM and supported backend;
5. a local functional test result.

No access token belongs in this file. Private repositories must be downloaded by
an operator-controlled tool using a local credential store. The Community
Edition does not redistribute weights or imply permission to use a model.

`local.example.json` is a deliberately invalid starting point for a local model
unit. The supported path computes those fields and installs a loopback-only unit:

```sh
sudo python3 scripts/register-local-model.py \
  --runtime /usr/local/libexec/r740-ai-factory/llama-server \
  --model /var/lib/r740-ai-factory/models/model.gguf \
  --id your-model-id --display-name "Your model" \
  --license Apache-2.0 --upstream-repo owner/repo --revision COMMIT \
  --install-systemd --start
```

The generated unit runs `sha256sum --check` before every start, so changed
runtime or weight files fail closed until they are registered again.

For inspection only, copy the example outside Git, fill exact values, then render:

```sh
python3 scripts/render-model-unit.py /private/model.json --output-dir /tmp/r740-units
```

Rendering refuses symlinks, hash/size drift, arbitrary arguments, public bind
addresses and overwrite. It never installs, enables or starts the generated unit.
