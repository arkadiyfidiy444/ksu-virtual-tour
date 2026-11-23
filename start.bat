@echo off
setlocal
cd /d "%~dp0"
set PORT=8080
title KSU 3D walkthrough - local server

echo.
echo  KSU 3D walkthrough - local server
echo  Address: http://localhost:%PORT%
echo  To stop: press Ctrl+C or close this window.
echo.

rem --- look for a working Python (the py launcher first, then python) ---
py -3 -c "import sys" >nul 2>nul
if not errorlevel 1 goto USE_PY
python -c "import sys" >nul 2>nul
if not errorlevel 1 goto USE_PYTHON
where npx >nul 2>nul
if not errorlevel 1 goto USE_NODE
goto NOTHING

:USE_PY
start "" /b cmd /c "ping -n 3 127.0.0.1 >nul & start http://localhost:%PORT%"
py -3 -m http.server %PORT% --bind 127.0.0.1
goto END

:USE_PYTHON
start "" /b cmd /c "ping -n 3 127.0.0.1 >nul & start http://localhost:%PORT%"
python -m http.server %PORT% --bind 127.0.0.1
goto END

:USE_NODE
start "" /b cmd /c "ping -n 4 127.0.0.1 >nul & start http://localhost:%PORT%"
call npx --yes http-server -p %PORT% -a 127.0.0.1 -c-1
goto END

:NOTHING
echo  ERROR: Python or Node.js was not found.
echo  Install Python from https://www.python.org/downloads/
echo  (tick "Add python.exe to PATH") or use the Live Server extension in VS Code.

:END
echo.
echo  Server stopped.
pause
endlocal
