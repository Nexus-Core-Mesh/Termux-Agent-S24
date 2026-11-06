#!/bin/bash
cd "$(dirname "$0")"

echo "[*] Cleaning up Python bytecode cache and artifacts..."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
rm -f workspace/workspace 2>/dev/null

echo "[*] Stashing local runtime state..."
git stash -u

echo "[*] Pulling latest changes from origin..."
git pull origin main

echo "[*] Restoring local runtime state..."
git stash pop 2>/dev/null || true

echo "[*] Current status:"
git status --short
