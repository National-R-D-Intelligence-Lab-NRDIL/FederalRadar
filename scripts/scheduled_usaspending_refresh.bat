@echo off
setlocal enabledelayedexpansion
REM Weekly USAspending refresh — skip if already ran this week
cd /d "C:\Users\kalya\Federal Radar"
if not exist logs mkdir logs

set "LOCKFILE=logs\.usaspending_last_run"
if exist "%LOCKFILE%" (
    for /f %%A in ('powershell -nologo -command "((Get-Date) - (Get-Item '%LOCKFILE%').LastWriteTime).TotalDays"') do set DAYS_AGO=%%A
    for /f %%B in ('powershell -nologo -command "if ([double]'!DAYS_AGO!' -lt 6) { 'skip' } else { 'run' }"') do set ACTION=%%B
    if "!ACTION!"=="skip" (
        echo %date% %time% - Already ran this week, skipping >> logs\usaspending_refresh.log
        exit /b 0
    )
)

echo %date% %time% - Starting USAspending refresh >> logs\usaspending_refresh.log

REM Backup DB before writing
C:\Python314\python.exe -c "import sys; sys.path.insert(0,'src'); from db import backup_db; backup_db()" >> logs\usaspending_refresh.log 2>&1

REM Download and load
C:\Python314\python.exe scripts\usaspending_api_fetcher.py --all-agencies --fiscal-years 2026 >> logs\usaspending_refresh.log 2>&1
C:\Python314\python.exe scripts\usaspending_api_fetcher.py --load-all-years >> logs\usaspending_refresh.log 2>&1

if %ERRORLEVEL% EQU 0 (
    echo. > "%LOCKFILE%"
    echo %date% %time% - Done [OK] >> logs\usaspending_refresh.log
) else (
    echo %date% %time% - Done [FAILED exit code %ERRORLEVEL%] >> logs\usaspending_refresh.log
)
