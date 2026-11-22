@echo off
setlocal
pushd "%~dp0" || (
    echo Could not open the PyXasecoMP folder.
    pause
    exit /b 1
)

py -3.12 -X utf8 main.py --run --host 127.0.0.1 --port 5000 %*
set "result=%errorlevel%"
popd

if not "%result%"=="0" if not "%result%"=="130" (
    echo PyXasecoMP exited with code %result%.
    pause
)
exit /b %result%
