powershell -Command "Start-Process cmd -ArgumentList '/k cd /d %~dp0 && pip install pillow --quiet && python explorer_bg_tool.py' -Verb RunAs"
REM powershell -Command "Start-Process python -ArgumentList 'explorer_bg_tool.py' -Verb RunAs"
