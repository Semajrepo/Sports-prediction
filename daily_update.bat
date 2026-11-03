@echo off
rem Daily update for Football Safe Picks, run by Windows Task Scheduler (see README).
rem Refreshes data and picks, then saves the new files to GitHub.
cd /d "%~dp0"
set PY=C:\Users\HP\AppData\Local\Programs\Python\Python313\python.exe
set LOG=output\last_update_run.log

echo === %date% %time% === > %LOG%
git pull -q --rebase >> %LOG% 2>&1
"%PY%" src\update.py >> %LOG% 2>&1
if errorlevel 1 (
  echo Update failed, retrying in 60 seconds... >> %LOG%
  timeout /t 60 /nobreak > nul
  "%PY%" src\update.py >> %LOG% 2>&1
  if errorlevel 1 (
    echo Update failed twice; nothing saved to GitHub. >> %LOG%
    exit /b 1
  )
)

rem Save the day's picks, results and dashboard files to GitHub
git add -A >> %LOG% 2>&1
git commit -q -m "Daily update %date%" >> %LOG% 2>&1
git push -q >> %LOG% 2>&1
echo Done %time% >> %LOG%
