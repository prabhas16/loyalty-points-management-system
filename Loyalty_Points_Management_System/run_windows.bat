@echo off
python -m venv .venv
call .venv\Scripts\activate
python -m pip install -r requirements.txt
if not exist .env copy .env.example .env
echo.
echo Edit .env and set your MySQL password, then create the database in MySQL.
echo Run: python app.py
pause
