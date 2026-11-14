@echo off
rem Отчёт о том, как лежат фото папки (метка поворота EXIF, поворот в Atlas): перетащите папку с фото на этот файл.
rem Отчёт откроется в Блокноте; он лежит в reports\photoinfo.txt — его можно привезти вместо самих фото.
set VER=
if exist "%~dp0release\version.txt" set /p VER=<"%~dp0release\version.txt"
if "%VER%"=="" goto broken
if "%~1"=="" goto usage
start "" /wait /d "%~dp0release\%VER%" "%~dp0release\%VER%\atlas.exe" --photoinfo "%~1"
start "" notepad "%~dp0reports\photoinfo.txt"
exit /b 0

:usage
echo Перетащите папку с фото на этот файл.
pause
exit /b 1

:broken
echo Не найдена версия из файла release\version.txt
pause
exit /b 1
