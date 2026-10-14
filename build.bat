@echo off
echo Installing application and build dependencies...
pip install -r requirements.txt
echo Building LAN Chat App executable...
pyinstaller --onefile --windowed --collect-all aiortc --collect-all av --collect-all cv2 --collect-all sounddevice main.py
echo Build complete. The executable will be in the 'dist' folder.
pause
