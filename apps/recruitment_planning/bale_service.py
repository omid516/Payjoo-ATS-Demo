import json
import logging
import urllib.request
import urllib.error
from django.conf import settings

logger = logging.getLogger(__name__)

BALE_SERVER_URL = "https://zarfy.ir/payjoo-bot/bot.php"

def normalize_digits(s):
    if not s:
        return ""
    persian_arabic = {
        '۰': '0', '۱': '1', '۲': '2', '۳': '3', '۴': '4',
        '۵': '5', '۶': '6', '۷': '7', '۸': '8', '۹': '9',
        '٠': '0', '١': '1', '٢': '2', '٣': '3', '٤': '4',
        '٥': '5', '٦': '6', '٧': '7', '٨': '8', '٩': '9'
    }
    for k, v in persian_arabic.items():
        s = s.replace(k, v)
    return s.strip()

def normalize_jalali_date(val):
    if not val:
        return ""
    clean = normalize_digits(str(val)).replace('-', '/')
    parts = clean.split('/')
    if len(parts) == 3:
        try:
            return f"{int(parts[0]):04d}/{int(parts[1]):02d}/{int(parts[2]):02d}"
        except ValueError:
            return clean
    return clean

def normalize_time(val):
    if not val:
        return "10:00"
    clean = normalize_digits(str(val))
    parts = clean.split(':')
    if len(parts) == 2:
        try:
            return f"{int(parts[0]):02d}:{int(parts[1]):02d}"
        except ValueError:
            return clean
    return clean

def fetch_bale_schedules(timeout=8):
    """
    دریافت تمام رویدادهای زمان‌بندی ارزیابی از سرور مرکزی وب‌هوک بله (zarfy.ir)
    """
    req = urllib.request.Request(
        BALE_SERVER_URL,
        headers={
            'User-Agent': 'Payjoo-ATS-WebClient/2.0',
            'Accept': 'application/json'
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                raw_data = resp.read().decode('utf-8')
                data = json.loads(raw_data)
                if isinstance(data, list):
                    # Sanitize items
                    sanitized = []
                    for item in data:
                        if not isinstance(item, dict):
                            continue
                        j_date = normalize_jalali_date(item.get('jalali_date', ''))
                        if not j_date:
                            continue
                        item['jalali_date'] = j_date
                        item['time'] = normalize_time(item.get('time', '10:00'))
                        item['request_number'] = normalize_digits(str(item.get('request_number') or ''))
                        item['job_code'] = normalize_digits(str(item.get('job_code') or ''))
                        if not item.get('job_code') and item.get('request_number'):
                            item['job_code'] = item['request_number']
                        sanitized.append(item)
                    return sanitized
    except Exception as e:
        logger.warning(f"Error fetching bale schedules from {BALE_SERVER_URL}: {e}")
        return []
    return []

def save_bale_schedule(item_data, timeout=8):
    """
    ثبت یا ویرایش یک رویداد زمان‌بندی روی سرور مرکزی بله
    """
    payload = {
        "action": "save_item",
        "item": item_data
    }
    json_bytes = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(
        BALE_SERVER_URL,
        data=json_bytes,
        headers={
            'Content-Type': 'application/json; charset=utf-8',
            'User-Agent': 'Payjoo-ATS-WebClient/2.0',
            'Accept': 'application/json'
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                raw = resp.read().decode('utf-8')
                return json.loads(raw)
    except Exception as e:
        logger.error(f"Error saving schedule to bale server: {e}")
        return {"ok": False, "error": str(e)}
    return {"ok": False, "error": "Unknown error"}

def delete_bale_schedule(item_id, req_num="", job_code="", j_date="", time_val="", timeout=8):
    """
    حذف یک رویداد زمان‌بندی از سرور مرکزی بله
    """
    payload = {
        "action": "delete_item",
        "id": item_id,
        "request_number": req_num,
        "job_code": job_code,
        "jalali_date": j_date,
        "time": time_val
    }
    json_bytes = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(
        BALE_SERVER_URL,
        data=json_bytes,
        headers={
            'Content-Type': 'application/json; charset=utf-8',
            'User-Agent': 'Payjoo-ATS-WebClient/2.0',
            'Accept': 'application/json'
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                raw = resp.read().decode('utf-8')
                return json.loads(raw)
    except Exception as e:
        logger.error(f"Error deleting schedule from bale server: {e}")
        return {"ok": False, "error": str(e)}
    return {"ok": False, "error": "Unknown error"}
