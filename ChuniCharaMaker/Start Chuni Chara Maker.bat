@echo off
setlocal
cd /d "%~dp0"
title Chuni Chara Maker

set "HERE=%~dp0"
set "INZIP="
if /i not "%HERE:\AppData\Local\Temp\=%"=="%HERE%" set "INZIP=1"
if /i not "%HERE:.zip\=%"=="%HERE%" set "INZIP=1"
if defined INZIP (
  echo.
  echo  It looks like this is running from inside the zip file.
  echo  Please unzip the whole ChuniCharaMaker folder first ^(right-click the zip,
  echo  "Extract All..."^), then double-click "Start Chuni Chara Maker.bat" in that folder.
  echo.
  pause
  exit /b 1
)

set "PYEXE="
set "PYARGS="
if exist "%USERPROFILE%\miniconda3\python.exe" set "PYEXE=%USERPROFILE%\miniconda3\python.exe"
if not defined PYEXE if exist "%USERPROFILE%\anaconda3\python.exe" set "PYEXE=%USERPROFILE%\anaconda3\python.exe"
if not defined PYEXE (
  where py >nul 2>&1 && (set "PYEXE=py" & set "PYARGS=-3")
)
if not defined PYEXE (
  where python >nul 2>&1 && set "PYEXE=python"
)
if not defined PYEXE (
  echo Python 3 was not found.
  echo Install it from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^), then run this again.
  pause
  exit /b 1
)

"%PYEXE%" %PYARGS% -c "import PIL, numpy, tkinter" >nul 2>&1
if errorlevel 1 (
  echo First run: installing Pillow and numpy...
  "%PYEXE%" %PYARGS% -m pip install pillow numpy
  if errorlevel 1 "%PYEXE%" %PYARGS% -m pip install --user pillow numpy
)

"%PYEXE%" %PYARGS% chuni_chara_maker.py
if errorlevel 1 (
  echo.
  echo Something went wrong - see the message above.
  pause
)
