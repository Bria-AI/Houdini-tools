#!/bin/bash

# Resolve script location dynamically
SCRIPT_DIR="$(cd "$(dirname "$0")/../.." && pwd -P)"

# Bria-specific vars
export BRIA_HOUDINI_ROOT="$(cd "$SCRIPT_DIR/houdini" && pwd -P)"
export HOUDINI_PACKAGE_DIR="$(cd "$SCRIPT_DIR/houdini/packages" && pwd -P)"

# TLS/SSL certificate bundle for Houdini's embedded Python on macOS
BRIA_CA_BUNDLE_PATH=""
for candidate in \
	"/etc/ssl/cert.pem" \
	"/private/etc/ssl/cert.pem" \
	"/opt/homebrew/etc/ca-certificates/cert.pem"; do
	if [[ -f "$candidate" ]]; then
		BRIA_CA_BUNDLE_PATH="$candidate"
		break
	fi
done

if [[ -n "$BRIA_CA_BUNDLE_PATH" ]]; then
	export BRIA_CA_BUNDLE="$BRIA_CA_BUNDLE_PATH"
	export SSL_CERT_FILE="$BRIA_CA_BUNDLE_PATH"
	export REQUESTS_CA_BUNDLE="$BRIA_CA_BUNDLE_PATH"
fi

cd "$SCRIPT_DIR"

/Applications/Houdini/Current/Frameworks/Houdini.framework/Versions/Current/Resources/bin/houdini