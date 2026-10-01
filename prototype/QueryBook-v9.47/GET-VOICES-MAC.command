#!/bin/bash
# ============================================================
#   QueryBook — GET VOICES (one time).  Double-click this.
#   Installs espeak-ng (free, open-source) so QueryBook can
#   SPEAK every language with a real voice, offline.
#   macOS already has a built-in voice ("say"); this adds the
#   high-accuracy multilingual espeak-ng voices.
# ============================================================
cd "$(dirname "$0")" || exit 1
echo
if command -v espeak-ng >/dev/null 2>&1; then
  echo "espeak-ng is already installed. You're all set — just (re)start QueryBook."
  read -r -p "Press Return to close."; exit 0
fi
if command -v brew >/dev/null 2>&1; then
  echo "Installing espeak-ng via Homebrew..."
  brew install espeak-ng
  echo
  echo "Done. Restart QueryBook (START-MAC.command). Every language will speak."
else
  echo "Homebrew is not installed. Two choices:"
  echo "  1) macOS already speaks via its built-in voice — you may not need this."
  echo "  2) To add espeak-ng: install Homebrew from https://brew.sh then re-run this."
fi
read -r -p "Press Return to close."
