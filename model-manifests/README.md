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
unit. Copy it outside Git, fill the exact runtime/model byte sizes and SHA-256
values, then render a loopback-only, disabled systemd unit with:

```sh
python3 scripts/render-model-unit.py /private/model.json --output-dir /tmp/r740-units
```

Rendering refuses symlinks, hash/size drift, arbitrary arguments, public bind
addresses and overwrite. It never installs, enables or starts the generated unit.
