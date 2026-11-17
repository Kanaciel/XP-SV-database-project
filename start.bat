@echo off
rem Starts the scanner and/or the web app (see README, "Running the scanner").
cd /d "%~dp0"
if not exist ".venv\Scripts\activate.bat" (
    echo No .venv found in %CD%
    echo Create it first:  python -m venv .venv  then  .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)
call ".venv\Scripts\activate.bat"

echo.
echo   1. Scanner + web app  (scanner_stable)
echo   2. Scanner + web app  (scanner_testing)
echo   3. Scanner only       (scanner_stable)
echo   4. Web app only       (scanner_stable database)
echo.
choice /c 1234 /n /m "Pick 1-4: "
set MODE=%errorlevel%

if %MODE%==1 python main.py
if %MODE%==2 python main.py --testing
if %MODE%==3 python main.py scanner
if %MODE%==4 python main.py web

echo.
pause
