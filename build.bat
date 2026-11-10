@echo off
setlocal EnableExtensions
cd /d "%~dp0"

where py >nul 2>&1
if %errorlevel%==0 (
    set "PY=py -3"
) else (
    set "PY=python"
)

%PY% --version >nul 2>&1
if errorlevel 1 (
    echo No se encontro Python 3. Instale Python 3.10 o superior.
    if not "%~1"=="--no-pause" pause
    exit /b 1
)

set "VENV_PY=%~dp0.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo Creando entorno virtual...
    %PY% -m venv .venv
    if errorlevel 1 (
        echo No se pudo crear el entorno virtual.
        if not "%~1"=="--no-pause" pause
        exit /b 1
    )
)

echo Instalando dependencias...
"%VENV_PY%" -m pip install --upgrade pip
if errorlevel 1 goto :fail
"%VENV_PY%" -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 goto :fail
"%VENV_PY%" -m pip install "pyinstaller>=6.3,<7"
if errorlevel 1 goto :fail

echo Generando ejecutable...
"%VENV_PY%" -m PyInstaller --noconfirm --clean --onefile --windowed --name Pomodoro --distpath "%~dp0dist" --workpath "%~dp0build" --specpath "%~dp0build" "%~dp0main.py"
if errorlevel 1 goto :fail

echo.
echo Ejecutable generado: dist\Pomodoro.exe
if not "%~1"=="--no-pause" pause
exit /b 0

:fail
echo.
echo Error al generar el ejecutable.
if not "%~1"=="--no-pause" pause
exit /b 1
