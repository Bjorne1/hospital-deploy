@echo off
setlocal
cd /d "%~dp0"

set PYTHON_EXE=%cd%\.venv310\Scripts\python.exe
if not exist "%PYTHON_EXE%" (
  echo [ERROR] .venv310 not found. Please create it with:
  echo   py -3.10 -m venv .venv310
  echo Then install dependencies:
  echo   .venv310\Scripts\python.exe -m pip install -r requirements.txt
  echo   .venv310\Scripts\python.exe -m pip install pyinstaller
  exit /b 1
)

"%PYTHON_EXE%" -m PyInstaller --noconfirm --clean "HospitalDeployTool.spec"
if errorlevel 1 (
  exit /b %errorlevel%
)
echo.
echo Build finished:
echo   %cd%\dist\HospitalDeployTool.exe
endlocal
