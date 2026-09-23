#!/usr/bin/env bash
# Builds the two installable packages into dist/:
#   mediamarketplace-studio-wordpress-<version>.zip   (WordPress plugin)
#   mediamarketplace-studio-joomla-<version>.zip      (Joomla package)
# Each contains the mms-server binary for Linux x86_64 and the shared PHP runtime.
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION=$(grep -m1 '^version' Cargo.toml | sed 's/.*"\(.*\)".*/\1/')
BIN=target/release/mms-server
if [ "${SKIP_CARGO:-0}" != "1" ]; then
  cargo build --release -p mms-server
fi
[ -x "$BIN" ] || { echo "missing $BIN"; exit 1; }
rm -rf dist/stage && mkdir -p dist/stage

# ---- WordPress ----
WP=dist/stage/wordpress/mediamarketplace-studio
mkdir -p "$WP"
cp -r packages/wordpress/mediamarketplace-studio/. "$WP/"
cp packages/shared/MmsRuntime.php "$WP/includes/MmsRuntime.php"
mkdir -p "$WP/bin" && cp "$BIN" "$WP/bin/mms-server" && chmod 755 "$WP/bin/mms-server"
( cd dist/stage/wordpress && zip -qr "../../mediamarketplace-studio-wordpress-$VERSION.zip" mediamarketplace-studio )

# ---- Joomla ----
JS=dist/stage/joomla
mkdir -p "$JS/packages"
cp -r packages/joomla/plg_system_mediamarketplace "$JS/plg"
cp packages/shared/MmsRuntime.php "$JS/plg/src/Runtime/MmsRuntime.php"
mkdir -p "$JS/plg/bin" && cp "$BIN" "$JS/plg/bin/mms-server" && chmod 755 "$JS/plg/bin/mms-server"
( cd "$JS/plg" && zip -qr ../packages/plg_system_mediamarketplace.zip . )
cp -r packages/joomla/com_mediamarketplace "$JS/com"
( cd "$JS/com" && zip -qr ../packages/com_mediamarketplace.zip . )
cp -r packages/joomla/mod_mms_embed "$JS/mod"
( cd "$JS/mod" && zip -qr ../packages/mod_mms_embed.zip . )
cp packages/joomla/pkg_mediamarketplace.xml "$JS/"
( cd "$JS" && zip -q "../../mediamarketplace-studio-joomla-$VERSION.zip" pkg_mediamarketplace.xml packages/*.zip )

rm -rf dist/stage
ls -la dist/*.zip
