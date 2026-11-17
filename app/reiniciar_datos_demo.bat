@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Esto BORRA la base local y la vuelve a crear con datos ficticios.
set /p OK=Escribe SI para continuar: 
if /I not "%OK%"=="SI" exit /b 0
if exist "instance\plataforma.db" del "instance\plataforma.db"
".venv\Scripts\python.exe" -m flask --app wsgi demo
pause
