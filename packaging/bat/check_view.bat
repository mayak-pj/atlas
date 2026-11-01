@echo off
echo Замер скорости просмотра фото. Идет 5-15 минут, окна открываются сами, ничего не нажимать.
echo Рабочие данные не затрагивает, фото только читаются.
echo Укажите папку с настоящими фото на сетевом диске. Пусто - тестовые фото на этом ПК (нужно 5 ГБ).
set /p FOLDER=Папка:
if "%FOLDER%"=="" goto generated
if "%FOLDER:~-1%"=="\" set FOLDER=%FOLDER:~0,-1%
start "" /wait "%~dp0atlas.exe" --viewbench "%FOLDER%" --report "%~dp0reports"
goto done
:generated
start "" /wait "%~dp0atlas.exe" --viewbench --report "%~dp0reports"
:done
echo Код завершения: %errorlevel% (0 - замер прошел)
echo Отчет: %~dp0reports\viewbench_%COMPUTERNAME%.txt
pause
