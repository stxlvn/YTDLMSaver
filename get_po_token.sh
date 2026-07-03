#!/bin/bash
# Генерирует PO-токен и сохраняет его в файл
/usr/bin/youtube-po-token-generator 2>/dev/null | jq -r '.poToken' > /root/ReSave/po_token.txt
