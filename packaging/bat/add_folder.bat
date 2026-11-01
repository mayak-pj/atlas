@echo off
echo Добавление папки с фото в Atlas. Папка только читается, ничего не копируется и не меняется.
set /p FOLDER=Папка с фото (например R:\Однотипность\Проект\Деталь\31.10):
if "%FOLDER:~-1%"=="\" set FOLDER=%FOLDER:~0,-1%
set /p KIND=Вид проекта (A или B):
set /p PROJECT=Проект:
set /p DEVICE=Устройство:
set /p PART=Название детали:
set /p DATE=Дата папки ГГГГ-ММ-ДД (пусто - сегодня):
if "%DATE%"=="" (
start "" /wait "%~dp0atlas.exe" --addfolder "%FOLDER%" --kind "%KIND%" --project "%PROJECT%" --device "%DEVICE%" --part "%PART%"
) else (
start "" /wait "%~dp0atlas.exe" --addfolder "%FOLDER%" --kind "%KIND%" --project "%PROJECT%" --device "%DEVICE%" --part "%PART%" --date "%DATE%"
)
echo Код завершения: %errorlevel% (0 - добавлено)
type "%~dp0reports\addfolder.txt"
pause
