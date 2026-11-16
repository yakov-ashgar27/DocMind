@echo off
REM Windows: double-click, then open http://localhost:8000
cd /d "%~dp0backend"
python -m pip install -q -r requirements.txt
python run.py
pause
