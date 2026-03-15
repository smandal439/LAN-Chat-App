@echo off
echo Installing PyInstaller...
pip install pyinstaller
echo Building LAN Chat App executable...
pyinstaller --onefile --windowed main.py
echo Build complete. The executable will be in the 'dist' folder.
pause
