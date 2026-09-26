#!/bin/bash

# Ensure directory is correct
cd "$(dirname "$0")"

echo "=============================================="
echo "      سامانه جذب متقاضیان (ATS) - راه‌اندازی      "
echo "=============================================="

# 1. Setup Virtual Environment
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment (.venv)..."
    python3 -m venv .venv
fi

# 2. Activate Virtual Environment
echo "Activating virtual environment..."
source .venv/bin/activate

# 3. Upgrade pip and install dependencies (Non-blocking in case of network issues)
echo "Installing/checking dependencies..."
pip install --upgrade pip --timeout 5 || echo "Warning: pip upgrade timed out/failed, continuing..."
pip install -r requirements.txt --timeout 5 || echo "Warning: dependencies check timed out/failed, continuing..."

# 4. Apply Database Migrations & Optimization
echo "Applying database migrations and optimizations..."
python manage.py migrate
python manage.py optimize_db

# 5. Initialize/Reset Admin User and profile
echo "Configuring default admin credentials..."
python manage.py shell -c "
from django.contrib.auth.models import User
from apps.accounts.models import UserProfile

u, created = User.objects.get_or_create(username='admin', defaults={'is_superuser': True, 'is_staff': True, 'email': 'admin@example.com'})
u.set_password('admin123')
u.is_superuser = True
u.is_staff = True
u.save()

profile, p_created = UserProfile.objects.get_or_create(user=u)
profile.role = UserProfile.ROLE_ADMIN
profile.save()

print('Admin user configured successfully.')
"

# 6. Start Django Development Server in background
echo "Starting Django server on http://127.0.0.1:8000/ ..."
python manage.py runserver 0.0.0.0:8000 &
SERVER_PID=$!

# Wait a moment for server to spin up
sleep 2

# 7. Open default browser
echo "Opening browser..."
open "http://127.0.0.1:8000/candidates/dashboard/"

echo "=============================================="
echo "          سامانه با موفقیت راه‌اندازی شد          "
echo "=============================================="
echo "آدرس پنل کاربری متقاضیان: http://127.0.0.1:8000/candidates/dashboard/"
echo "آدرس صفحه اصلی / عمومی: http://127.0.0.1:8000/"
echo "آدرس پنل مدیریت جنگو: http://127.0.0.1:8000/admin/"
echo ""
echo "مشخصات ورود ادمین (مدیر سیستم):"
echo "نام کاربری (Username): admin"
echo "رمز عبور (Password): admin123"
echo "=============================================="
echo "برای متوقف کردن سرور، کلیدهای Ctrl+C را فشار دهید."

# Keep script running and handle Ctrl+C to terminate background server process
trap "kill $SERVER_PID; exit" INT
wait
