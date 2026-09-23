#!/usr/bin/env bash
# Builds the two installable packages into dist/:
#   mediamarketplace-studio-wordpress-<version>.zip   (WordPress plugin)
#   mediamarketplace-studio-joomla-<version>.zip      (Joomla package)
# Each contains the mms-server binary for Linux x86_64 (and aarch64 when MMS_BIN_ARM64 is set) and the shared PHP runtime.
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION=$(grep -m1 '^version' Cargo.toml | sed 's/.*"\(.*\)".*/\1/')
BIN=${MMS_BIN:-target/release/mms-server}
BIN_ARM64=${MMS_BIN_ARM64:-}
if [ "${SKIP_CARGO:-0}" != "1" ]; then
  cargo build --release -p mms-server
fi
[ -x "$BIN" ] || { echo "missing $BIN"; exit 1; }
# Copies the x86_64 binary and, when built (CI cross-compiles it), the aarch64 one next to it.
install_bins() {
  mkdir -p "$1" && cp "$BIN" "$1/mms-server" && chmod 755 "$1/mms-server"
  if [ -n "$BIN_ARM64" ] && [ -x "$BIN_ARM64" ]; then cp "$BIN_ARM64" "$1/mms-server-aarch64" && chmod 755 "$1/mms-server-aarch64"; fi
}
rm -rf dist/stage && mkdir -p dist/stage

# ---- WordPress ----
WP=dist/stage/wordpress/mediamarketplace-studio
mkdir -p "$WP"
cp -r packages/wordpress/mediamarketplace-studio/. "$WP/"
cp packages/shared/MmsRuntime.php "$WP/includes/MmsRuntime.php"
install_bins "$WP/bin"
( cd dist/stage/wordpress && zip -qr "../../mediamarketplace-studio-wordpress-$VERSION.zip" mediamarketplace-studio )

# ---- Joomla ----
JS=dist/stage/joomla
mkdir -p "$JS/packages"
cp -r packages/joomla/plg_system_mediamarketplace "$JS/plg"
cp packages/shared/MmsRuntime.php "$JS/plg/src/Runtime/MmsRuntime.php"
install_bins "$JS/plg/bin"
( cd "$JS/plg" && zip -qr ../packages/plg_system_mediamarketplace.zip . )
cp -r packages/joomla/com_mediamarketplace "$JS/com"
( cd "$JS/com" && zip -qr ../packages/com_mediamarketplace.zip . )
cp -r packages/joomla/mod_mms_embed "$JS/mod"
( cd "$JS/mod" && zip -qr ../packages/mod_mms_embed.zip . )
cp packages/joomla/pkg_mediamarketplace.xml "$JS/"
( cd "$JS" && zip -q "../../mediamarketplace-studio-joomla-$VERSION.zip" pkg_mediamarketplace.xml packages/*.zip )

rm -rf dist/stage
ls -la dist/*.zip
