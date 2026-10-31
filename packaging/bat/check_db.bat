@echo off
echo Проверка базы на сетевом диске. Идет 2 минуты, рабочие данные не затрагивает.
echo Укажите подпапку, например R:\Atlas\test (на двух ПК - одну и ту же).
set /p FOLDER=Папка:
if "%FOLDER:~-1%"=="\" set FOLDER=%FOLDER:~0,-1%
start "" /wait "%~dp0atlas.exe" --dbcheck "%FOLDER%" --report "%~dp0reports" --seconds 120
echo Код завершения: %errorlevel% (0 - данные целы)
echo Отчет: %~dp0reports\dbcheck_%COMPUTERNAME%.txt
pause
