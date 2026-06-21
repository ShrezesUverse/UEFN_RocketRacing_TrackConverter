@echo off
REM ===================================================================
REM  Rocket Racing Track Converter - double-click launcher
REM  1) In UEFN: select your old tracks, press Ctrl+C.
REM  2) Double-click this file.
REM  3) In UEFN: delete the old tracks, press Ctrl+V.
REM ===================================================================
setlocal
cd /d "%~dp0"

python "%~dp0rr_track_converter.py"
if errorlevel 9009 (
  echo.
  echo Python was not found. Install Python 3 from https://www.python.org/downloads/
  echo  ^(or use the standalone .exe build - see README_HOW_TO_USE.txt^).
)

echo.
pause
