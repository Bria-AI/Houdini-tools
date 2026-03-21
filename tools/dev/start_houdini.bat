@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
REM Repo root is the package dir (bria_houdini.json lives there)
for %%I in ("%SCRIPT_DIR%..\..") do set "HOUDINI_PACKAGE_DIR=%%~fI"
cd /d "%SCRIPT_DIR%..\.."
"D:\Program Files\Side Effects Software\Houdini 21.0.559\bin\houdini.exe"