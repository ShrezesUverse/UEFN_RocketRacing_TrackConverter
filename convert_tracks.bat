@echo off
REM ===================================================================
REM  RR Track Converter
REM  1) In UEFN, select your old tracks, press Ctrl+C
REM  2) Open this file
REM  3) In UEFN, delete old tracks, press Ctrl+V
REM ===================================================================
setlocal
cd /d "%~dp0"

python "%~dp0rr_track_converter.py"
if errorlevel 9009 (
  echo.
  echo Python was not found: Python 3 from https://www.python.org/downloads/ or you didnt installed rr_track_converter.py from the repo
  echo  ^(or use the from the repo .exe build. see README.md^).
)

echo.
pause
