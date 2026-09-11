@echo off
title Payjoo ATS

cd /d %~dp0

call .venv\Scripts\activate.bat

python manage.py migrate
python manage.py optimize_db

start "" http://127.0.0.1:8000/

python manage.py runserver 0.0.0.0:8000

pause