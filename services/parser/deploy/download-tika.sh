#!/bin/sh
# SPDX-License-Identifier: LGPL-3.0-or-later
set -eu

version=3.3.2
expected=71ca551380e5eab1add99101f4597a8a49a6a18c6143d6874ee9599ca10ae00e
destination=${1:?usage: download-tika.sh DESTINATION}
temporary="${destination}.download"
trap 'rm -f "$temporary"' EXIT HUP INT TERM
curl --fail --location --proto '=https' --tlsv1.2 \
  "https://downloads.apache.org/tika/${version}/tika-app-${version}.jar" \
  --output "$temporary"
actual=$(sha256sum "$temporary" | awk '{print $1}')
test "$actual" = "$expected"
install -m 0644 "$temporary" "$destination"

