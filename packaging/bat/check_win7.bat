@echo off
echo Проверка Atlas. Окно откроется и закроется само, ничего не нажимайте.
start "" /wait "%~dp0atlas.exe" --selfcheck "%~dp0reports"
echo Код завершения: %errorlevel% (0 - все работает)
echo Отчет: %~dp0reports\selfcheck.txt
pause
