@echo off
rem Пробный запуск (14.11.2026): программа копируется на этот ПК и запускается оттуда, а настройки, база,
rem журналы и обновления остаются в этой папке на сетевом диске. Сравнить время запуска с Atlas.bat:
rem строка «Запуск: ...» в logs\atlas.log. Копия одна на версию: следующие запуски — без копирования.
set VER=
if exist "%~dp0release\version.txt" set /p VER=<"%~dp0release\version.txt"
if "%VER%"=="" goto broken
if not exist "%~dp0release\%VER%\atlas.exe" goto broken
if "%LOCALAPPDATA%"=="" goto network
set LOCAL=%LOCALAPPDATA%\Atlas\release\%VER%
if exist "%LOCAL%\atlas.exe" goto run
echo Atlas %VER%: копирую программу на этот ПК, это один раз для каждой версии...
if exist "%LOCAL%.part" rmdir /s /q "%LOCAL%.part"
robocopy "%~dp0release\%VER%" "%LOCAL%.part" /E /R:2 /W:2 /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto network
rem Сначала во временную папку, потом переименовать: прерванное копирование не оставит неполную программу
move "%LOCAL%.part" "%LOCAL%" >nul
if not exist "%LOCAL%\atlas.exe" goto network
rem Старые версии на этом ПК больше не нужны: место на диске
for /d %%D in ("%LOCALAPPDATA%\Atlas\release\*") do if /i not "%%~nxD"=="%VER%" rmdir /s /q "%%D" 2>nul

:run
set ATLAS_HOME=%~dp0
start "" /d "%LOCAL%" "%LOCAL%\atlas.exe"
exit /b 0

:network
echo Не удалось скопировать программу на этот ПК: запускаю с сетевого диска.
start "" /d "%~dp0release\%VER%" "%~dp0release\%VER%\atlas.exe"
exit /b 0

:broken
echo Atlas не запущен: не найдена версия "%VER%" из файла release\version.txt
echo Проверьте сетевой диск. Если диск доступен, сообщите тому, кто устанавливал программу.
pause
exit /b 1
