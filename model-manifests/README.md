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

