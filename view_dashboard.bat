@echo off
rem Opens the Football Safe Picks dashboard in your browser from this folder (no Claude needed).
cd /d "%~dp0"
rem Get the latest picks saved by the GitHub daily update
git pull -q --rebase
start "" "http://localhost:8765/output/dashboard/view.html"
python -m http.server 8765
