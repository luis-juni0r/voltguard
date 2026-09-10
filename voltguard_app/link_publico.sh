#!/usr/bin/env bash
# Link público temporário (Linux/macOS). Requer cloudflared: https://github.com/cloudflare/cloudflared/releases
cd "$(dirname "$0")"
command -v cloudflared >/dev/null || { echo "Instale o cloudflared primeiro."; exit 1; }
echo "Procure a linha https://XXXX.trycloudflare.com — esse é o link. Ctrl+C encerra."
cloudflared tunnel --url http://localhost:5000
