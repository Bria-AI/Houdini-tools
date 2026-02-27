@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..\houdini") do set "BRIA_HOUDINI_ROOT=%%~fI"
for %%I in ("%SCRIPT_DIR%..\..\houdini\packages") do set "HOUDINI_PACKAGE_DIR=%%~fI"
cd /d "%SCRIPT_DIR%..\.."
"D:\Program Files\Side Effects Software\Houdini 21.0.559\bin\houdini.exe"