@echo off
echo Публикация этой версии Atlas в папку установки на сетевом диске.
echo Те, кто уже работает, не пострадают: получат предложение обновиться при следующем запуске.
set /p FOLDER=Папка установки (например R:\Atlas), она должна существовать:
if "%FOLDER:~-1%"=="\" set FOLDER=%FOLDER:~0,-1%
start "" /wait "%~dp0atlas.exe" --publish "%FOLDER%"
echo Код завершения: %errorlevel% (0 - опубликовано)
notepad "%~dp0reports\publish.txt"
