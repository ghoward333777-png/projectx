#!/bin/bash
# QueryBook Control Panel - double-click to open the one panel for all three applications (first time: right-click -> Open -> Open).
DIR="$(cd "$(dirname "$0")" && pwd)"
chmod +x "$DIR/QueryBook-Control-Panel/START-MAC.command" 2>/dev/null
open "$DIR/QueryBook-Control-Panel/START-MAC.command"
