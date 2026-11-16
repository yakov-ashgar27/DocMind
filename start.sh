#!/usr/bin/env sh
# Mac / Linux: ./start.sh  then open http://localhost:8000
cd "$(dirname "$0")/backend" || exit 1
python3 -m pip install -q -r requirements.txt && python3 run.py
