# Contributing

Contributions must use `LGPL-3.0-or-later` for original project code and retain
all third-party notices. Add an SPDX identifier to new source files.

Before submitting a change:

1. run `python3 tests/package_audit.py`;
2. run `python3 tests/smoke_test.py`;
3. do not commit generated secrets, data, model weights or local configuration;
4. document new dependencies and their licenses;
5. use synthetic fixtures only.

Contributors certify that they have the right to submit their work under the
project license. A formal DCO and public maintainer identity will be added
before the first public release.

