#!/bin/bash
# QueryBook — double-click to start all three applications and the Control Panel (first time: right-click -> Open -> Open).
DIR="$(cd "$(dirname "$0")" && pwd)"
for app in QueryBook-Language QueryBook-STEM QueryBook-History-News QueryBook-Control-Panel; do
  chmod +x "$DIR/$app/START-MAC.command" 2>/dev/null
  open "$DIR/$app/START-MAC.command"
done
