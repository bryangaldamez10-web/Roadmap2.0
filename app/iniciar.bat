@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Iniciado %date% %time% > arranque.log
title Plataforma de Distribucion
set VPY=.venv\Scripts\python.exe

where py >nul 2>nul && (set PY=py) || (set PY=python)

if not exist "%VPY%" (
  echo Creando entorno de Python por primera vez...
  %PY% -m venv .venv
)
if not exist "%VPY%" (
  echo.
  echo No se encontro Python. Instala Python 3.13 desde python.org y marca "Add python.exe to PATH".
  pause
  exit /b 1
)

echo Revisando dependencias...
"%VPY%" -m pip install --disable-pip-version-check -r requirements-local.txt > instalacion.log 2>&1
type instalacion.log
"%VPY%" -c "import flask, openpyxl" 2>nul
if errorlevel 1 (
  echo.
  echo No se pudieron instalar las dependencias. Copia el mensaje de arriba y envialo.
  pause
  exit /b 1
)

if not exist "instance\plataforma.db" (
  echo Creando base de datos local con datos FICTICIOS...
  "%VPY%" -m flask --app wsgi demo
)
"%VPY%" -m flask --app wsgi init-db >nul

echo.
echo ============================================================
echo  Plataforma lista en:  http://127.0.0.1:5000
echo  Usuarios: admin.demo, supervisor.demo, validador.demo,
echo            ruta.ds0099, ventas.demo   (clave: Demo-2026)
echo  Para detenerla: cierra esta ventana o presiona Ctrl+C
echo ============================================================
echo.
start "" http://127.0.0.1:5000
"%VPY%" -m flask --app wsgi run --debug
pause
