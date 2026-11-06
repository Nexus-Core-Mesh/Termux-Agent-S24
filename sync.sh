#!/bin/bash
cd "$(dirname "$0")"
echo "[*] Pulling latest changes from origin..."
git pull origin main
echo "[*] Current status:"
git status --short
