@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (echo Primero ejecuta iniciar.bat una vez. & pause & exit /b 1)
".venv\Scripts\python.exe" tests\test_plataforma.py
echo.
pause
