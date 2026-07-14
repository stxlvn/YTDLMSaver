#!/bin/bash
# Генерирует PO-токен и сохраняет его в файл
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
/usr/bin/youtube-po-token-generator 2>/dev/null | jq -r '.poToken' > "$SCRIPT_DIR/po_token.txt"
