@echo off
python -m venv .venv
call .venv\Scripts\activate
python -m pip install -r requirements.txt
if not exist .env copy .env.example .env
echo.
echo Edit .env with your MySQL details and a strong SECRET_KEY.
echo This local-only version does not require login.
echo Then run: python app.py
pause
