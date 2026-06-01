@echo off
REM Register Federal Radar scheduled tasks
REM Uses daily schedule + "run as soon as possible after missed" flag
REM Each script self-skips if it already ran today/this week

schtasks /Create /TN "FederalRadar_NSF_Daily" /TR "\"C:\Users\kalya\Federal Radar\scripts\scheduled_nsf_refresh.bat\"" /SC DAILY /ST 06:00 /F
if %ERRORLEVEL% EQU 0 (echo [OK] NSF daily task created) else (echo [FAIL] NSF task)

schtasks /Create /TN "FederalRadar_NIH_Daily" /TR "\"C:\Users\kalya\Federal Radar\scripts\scheduled_nih_refresh.bat\"" /SC DAILY /ST 06:05 /F
if %ERRORLEVEL% EQU 0 (echo [OK] NIH daily task created) else (echo [FAIL] NIH task)

schtasks /Create /TN "FederalRadar_USAspending_Weekly" /TR "\"C:\Users\kalya\Federal Radar\scripts\scheduled_usaspending_refresh.bat\"" /SC DAILY /ST 06:10 /F
if %ERRORLEVEL% EQU 0 (echo [OK] USAspending task created) else (echo [FAIL] USAspending task)

echo.
echo Now enabling "run as soon as possible after a scheduled start is missed"...
echo (This ensures tasks run when you open your laptop even if 6 AM was missed)
echo.

REM Use PowerShell to set StartWhenAvailable flag (not available via schtasks CLI)
powershell -nologo -command "$t = Get-ScheduledTask -TaskName 'FederalRadar_NSF_Daily'; $t.Settings.StartWhenAvailable = $true; Set-ScheduledTask -InputObject $t; Write-Host '[OK] NSF - StartWhenAvailable enabled'"
powershell -nologo -command "$t = Get-ScheduledTask -TaskName 'FederalRadar_NIH_Daily'; $t.Settings.StartWhenAvailable = $true; Set-ScheduledTask -InputObject $t; Write-Host '[OK] NIH - StartWhenAvailable enabled'"
powershell -nologo -command "$t = Get-ScheduledTask -TaskName 'FederalRadar_USAspending_Weekly'; $t.Settings.StartWhenAvailable = $true; Set-ScheduledTask -InputObject $t; Write-Host '[OK] USAspending - StartWhenAvailable enabled'"

echo.
echo === Verify tasks ===
schtasks /Query /TN "FederalRadar_NSF_Daily" /FO LIST | findstr "TaskName Status Next"
schtasks /Query /TN "FederalRadar_NIH_Daily" /FO LIST | findstr "TaskName Status Next"
schtasks /Query /TN "FederalRadar_USAspending_Weekly" /FO LIST | findstr "TaskName Status Next"

echo.
echo How it works:
echo   - Tasks are scheduled for 6:00/6:05/6:10 AM daily
echo   - If laptop is asleep at 6 AM, they run as soon as you open it
echo   - NSF and NIH skip if they already ran today
echo   - USAspending skips if it already ran this week
echo.
pause
