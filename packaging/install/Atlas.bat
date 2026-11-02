@echo off
rem Запуск действующей версии Atlas: номер в файле release\version.txt
set VER=
if exist "%~dp0release\version.txt" set /p VER=<"%~dp0release\version.txt"
if "%VER%"=="" goto broken
if not exist "%~dp0release\%VER%\atlas.exe" goto broken
start "" /d "%~dp0release\%VER%" "%~dp0release\%VER%\atlas.exe"
exit /b 0

:broken
echo Atlas не запущен: не найдена версия "%VER%" из файла release\version.txt
echo Проверьте сетевой диск. Если диск доступен, сообщите тому, кто устанавливал программу.
pause
exit /b 1
