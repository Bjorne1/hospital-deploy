@echo off
setlocal
pushd "%~dp0." >nul

set "PYTHON_EXE=%CD%\.venv310\Scripts\python.exe"
set "ENTRY_SCRIPT=%CD%\launch.py"
"%PYTHON_EXE%" "%ENTRY_SCRIPT%"
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
  echo.
  echo [ERROR] hospital-deploy start failed, exit code %EXIT_CODE%
  pause
)

popd >nul
endlocal & exit /b %EXIT_CODE%
