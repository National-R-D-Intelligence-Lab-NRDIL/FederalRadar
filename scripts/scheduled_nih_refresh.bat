@echo off
setlocal enabledelayedexpansion
REM Daily NIH refresh — skip if already ran today
cd /d "C:\Users\kalya\Federal Radar"
if not exist logs mkdir logs

set "LOCKFILE=logs\.nih_last_run"
if exist "%LOCKFILE%" (
    for /f %%A in ('powershell -nologo -command "(Get-Item '%LOCKFILE%').LastWriteTime.ToString('yyyy-MM-dd')"') do set LAST=%%A
    for /f %%B in ('powershell -nologo -command "Get-Date -Format yyyy-MM-dd"') do set TODAY=%%B
    if "!LAST!"=="!TODAY!" (
        echo %date% %time% - Already ran today, skipping >> logs\nih_refresh.log
        exit /b 0
    )
)

echo %date% %time% - Starting NIH refresh >> logs\nih_refresh.log

REM Backup DB before writing (skips if NSF already backed up today)
C:\Python314\python.exe -c "import sys; sys.path.insert(0,'src'); from db import backup_db; backup_db()" >> logs\nih_refresh.log 2>&1

REM Run fetcher
C:\Python314\python.exe scripts\nih_api_fetcher.py --days 2 >> logs\nih_refresh.log 2>&1

if %ERRORLEVEL% EQU 0 (
    echo. > "%LOCKFILE%"
    echo %date% %time% - Done [OK] >> logs\nih_refresh.log
) else (
    echo %date% %time% - Done [FAILED exit code %ERRORLEVEL%] >> logs\nih_refresh.log
)
