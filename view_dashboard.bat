@echo off
rem Opens the Football Safe Picks dashboard in your browser from this folder (no Claude needed).
cd /d "%~dp0"
start "" "http://localhost:8765/output/dashboard/view.html"
python -m http.server 8765
