#!/usr/bin/env bash
# Starts DocMind in the background inside a GitHub Codespace (port 8000, private to your GitHub account).
mkdir -p ${DOCMIND_DATA_DIR:-/workspaces/docmind-data}
cd "$(dirname "$0")/../backend" || exit 1
if ! curl -s -o /dev/null http://127.0.0.1:8000/api/meta; then
  setsid nohup python run.py > ${DOCMIND_DATA_DIR:-/workspaces/docmind-data}/server.log 2>&1 < /dev/null &
fi
