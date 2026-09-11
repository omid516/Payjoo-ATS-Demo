import json
import time
import urllib.request
import urllib.error
import urllib.parse
from django.shortcuts import render, redirect
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.contrib import messages

from .models import SyncSetting, SyncPackageHistory
from .engine import SyncEngine, to_jalali_str, convert_text_dates_to_jalali


import ssl

def _http_request(url, method='GET', data=None, headers=None, timeout=10):
    """
    اجرای امن درخواست HTTP با استفاده از کتابخانه استاندارد پایتون (بدون وابستگی خارجی)
    """
    req_headers = headers or {}
    req_headers.setdefault('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) PayjooATS/1.0')
    req_data = None
    if data is not None:
        if isinstance(data, (dict, list)):
            req_data = json.dumps(data, ensure_ascii=False).encode('utf-8')
            req_headers['Content-Type'] = 'application/json; charset=utf-8'
        elif isinstance(data, str):
            req_data = data.encode('utf-8')
        elif isinstance(data, bytes):
            req_data = data

    # ساخت کانتکست SSL سازگار با تمام هاست‌ها
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    req = urllib.request.Request(url, data=req_data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as response:
            status_code = response.status
            raw_text = response.read().decode('utf-8')
            try:
                json_data = json.loads(raw_text)
            except Exception:
                json_data = None
            return status_code, json_data, raw_text
    except urllib.error.HTTPError as e:
        raw_text = e.read().decode('utf-8') if e.fp else str(e)
        try:
            json_data = json.loads(raw_text)
        except Exception:
            json_data = None
        return e.code, json_data, raw_text
    except urllib.error.URLError as e:
        return 0, None, f"خطای اتصال به سرور: {str(e.reason)}"
    except Exception as e:
        return 0, None, f"خطای غیرمنتظره: {str(e)}"


@login_required
def dashboard_view(request):
    """
    نمایش داشبورد مرکزی همگام‌سازی و انتقال تغییرات
    """
    settings = SyncSetting.get_settings()
    days_param = request.GET.get('days', '30')
    try:
        days = int(days_param)
    except Exception:
        days = 30

    user_full_name = f"{request.user.first_name} {request.user.last_name}".strip()
    user_display_name = user_full_name if user_full_name else (request.user.username or 'کارشناس سامانه')

    # در صورتی که نام کارشناس در تنظیمات پیش‌فرض باشد، با نام کاربر جاری جایگزین می‌شود
    if not settings.specialist_name or settings.specialist_name == 'کارشناس تامین سرمایه انسانی':
        settings.specialist_name = user_display_name
        settings.save(update_fields=['specialist_name'])

    exportable = SyncEngine.get_exportable_summary(days=days)
    history = SyncPackageHistory.objects.all()[:20]

    context = {
        'settings': settings,
        'user_display_name': user_display_name,
        'exportable': exportable,
        'history': history,
        'current_days': days,
    }
    return render(request, 'sync_hub/dashboard.html', context)


@login_required
def ping_server_view(request):
    """
    تست برخط وضعیت اتصال به سرور
    """
    settings = SyncSetting.get_settings()
    start_time = time.time()
    
    url = f"{settings.server_url.rstrip('/')}?action=ping&api_key={urllib.parse.quote(settings.api_key)}"
    headers = {'X-API-KEY': settings.api_key}
    status_code, json_data, raw_text = _http_request(url, method='GET', headers=headers, timeout=8)
    latency_ms = round((time.time() - start_time) * 1000)

    if status_code == 200 and json_data and json_data.get('success'):
        settings.last_sync_check = timezone.now()
        settings.save(update_fields=['last_sync_check'])
        return JsonResponse({
            'success': True,
            'latency_ms': latency_ms,
            'message': 'ارتباط با سرور برقرار است.'
        })
    else:
        err = json_data.get('error') if json_data else raw_text[:200]
        return JsonResponse({
            'success': False,
            'latency_ms': latency_ms,
            'error': f'عدم دسترسی به سرور: {err}'
        })


@login_required
def save_settings_view(request):
    """
    ذخیره تنظیمات اتصال به سرور
    """
    if request.method == 'POST':
        settings = SyncSetting.get_settings()
        settings.server_url = request.POST.get('server_url', '').strip()
        settings.api_key = request.POST.get('api_key', '').strip()
        settings.specialist_name = request.POST.get('specialist_name', '').strip()
        settings.save()
        messages.success(request, 'تنظیمات اتصال به سرور با موفقیت به‌روزرسانی شد.')
    return redirect('sync_hub:dashboard')


@login_required
@csrf_exempt
def export_and_upload_view(request):
    """
    تولید بسته تغییرات و ارسال مستقیم به سرور یا دریافت فایل
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'متد نامعتبر است.'}, status=405)

    settings = SyncSetting.get_settings()
    try:
        body = json.loads(request.body)
    except Exception:
        body = request.POST

    user_full = f"{request.user.first_name} {request.user.last_name}".strip()
    author = body.get('author') or user_full or request.user.username or settings.specialist_name or 'کارشناس سامانه'
    title = body.get('title') or f"بسته تغییرات {to_jalali_str(timezone.now())}"
    target = body.get('target', 'upload')  # 'upload' یا 'download'
    selection = body.get('selection', {})

    try:
        package = SyncEngine.export_package(author=author, title=title, selection=selection)
    except Exception as e:
        return JsonResponse({'success': False, 'error': f'خطا در ایجاد بسته: {str(e)}'})

    if target == 'upload':
        # ارسال مستقیم به سرور
        url = f"{settings.server_url.rstrip('/')}?action=upload&api_key={urllib.parse.quote(settings.api_key)}"
        headers = {'X-API-KEY': settings.api_key}
        status_code, json_data, raw_text = _http_request(url, method='POST', data=package, headers=headers, timeout=20)

        if status_code == 200 and json_data and json_data.get('success'):
            SyncPackageHistory.objects.create(
                package_id=package['package_id'],
                direction='OUTGOING',
                author=author,
                title=title,
                summary=package['summary'],
                payload=package,
                status='EXPORTED',
            )
            return JsonResponse({
                'success': True,
                'message': 'بسته با موفقیت به سرور ارسال شد.',
                'package_id': package['package_id'],
                'server_response': json_data
            })
        else:
            err = json_data.get('error') if json_data else raw_text[:300]
            return JsonResponse({'success': False, 'error': f'خطای سرور مقصد ({status_code}): {err}'})

    else:
        # ذخیره در تاریخچه محلی برای دانلود فایل
        SyncPackageHistory.objects.create(
            package_id=package['package_id'],
            direction='OUTGOING',
            author=author,
            title=title,
            summary=package['summary'],
            payload=package,
            status='EXPORTED',
        )
        return JsonResponse({
            'success': True,
            'package_id': package['package_id'],
            'package': package,
        })


@login_required
def download_package_file_view(request, package_id):
    """
    دانلود فایل .atspack بسته تغییرات
    """
    pkg = SyncPackageHistory.objects.filter(package_id=package_id).first()
    if not pkg:
        return HttpResponse("بسته یافت نشد.", status=404)

    content = json.dumps(pkg.payload, ensure_ascii=False, indent=2)
    response = HttpResponse(content, content_type='application/json; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="ats_changeset_{package_id}.atspack"'
    return response

download_file_view = download_package_file_view


@login_required
def fetch_server_packages_view(request):
    """
    فراخوانی لیست بسته‌های موجود روی سرور همراه با تطبیق وضعیت محلی
    """
    settings = SyncSetting.get_settings()
    url = f"{settings.server_url.rstrip('/')}?action=list&api_key={urllib.parse.quote(settings.api_key)}"
    headers = {'X-API-KEY': settings.api_key}
    status_code, json_data, raw_text = _http_request(url, method='GET', headers=headers, timeout=8)

    if status_code == 200 and json_data and json_data.get('success'):
        # تطبیق هوشمند با وضعیت ذخیره شده در دیتابیس محلی
        local_histories = {h.package_id: h.status for h in SyncPackageHistory.objects.all()}
        for pkg in json_data.get('packages', []):
            pid = pkg.get('package_id')
            if pid in local_histories:
                local_st = local_histories[pid]
                pkg['local_status'] = local_st
                if local_st == 'MERGED':
                    pkg['status'] = 'MERGED'
                elif local_st == 'REVIEWED' and pkg.get('status') == 'PENDING':
                    pkg['status'] = 'REVIEWED'

            # تبدیل تاریخ‌ها و عناوین به شمسی
            created_val = pkg.get('created_at') or pkg.get('server_received_at')
            pkg['created_at_jalali'] = to_jalali_str(created_val)
            if pkg.get('server_received_at'):
                pkg['server_received_at_jalali'] = to_jalali_str(pkg['server_received_at'])
            if pkg.get('title'):
                pkg['title'] = convert_text_dates_to_jalali(pkg['title'])
        return JsonResponse(json_data)
    else:
        err = json_data.get('error') if json_data else raw_text[:200]
        return JsonResponse({'success': False, 'error': f'خطا در دریافت لیست از سرور ({status_code}): {err}'})


@login_required
@csrf_exempt
def preview_diff_view(request):
    """
    دریافت و تحلیل بسته برای نمایش جدول تفاوت‌ها (Diff Modal) و علامت‌گذاری وضعیت بررسی
    """
    settings = SyncSetting.get_settings()
    package_data = None
    pkg_id = request.GET.get('package_id')

    if request.method == 'POST' and request.FILES.get('package_file'):
        # بارگذاری فایل دستی
        uploaded = request.FILES['package_file']
        try:
            package_data = json.loads(uploaded.read().decode('utf-8'))
        except Exception as e:
            return JsonResponse({'success': False, 'error': f'فایل بسته نامعتبر است: {str(e)}'}, status=400)

    elif pkg_id:
        # دریافت از سرور
        url = f"{settings.server_url.rstrip('/')}?action=download&package_id={urllib.parse.quote(pkg_id)}&api_key={urllib.parse.quote(settings.api_key)}"
        headers = {'X-API-KEY': settings.api_key}
        status_code, json_data, raw_text = _http_request(url, method='GET', headers=headers, timeout=10)

        if status_code == 200 and json_data and json_data.get('success'):
            package_data = json_data.get('package')
            
            # ثبت در تاریخچه محلی به عنوان بررسی شده (در صورتی که هنوز ادغام نشده باشد)
            history_item = SyncPackageHistory.objects.filter(package_id=pkg_id).first()
            if not history_item or history_item.status != 'MERGED':
                SyncPackageHistory.objects.update_or_create(
                    package_id=pkg_id,
                    defaults={
                        'direction': 'INCOMING',
                        'author': package_data.get('author', 'همکار'),
                        'title': convert_text_dates_to_jalali(package_data.get('title', 'بسته دریافتی')),
                        'summary': package_data.get('summary', {}),
                        'payload': package_data,
                        'status': 'REVIEWED',
                    }
                )
                # اعلام بررسی روی سرور
                try:
                    update_url = f"{settings.server_url.rstrip('/')}?action=update_status&api_key={urllib.parse.quote(settings.api_key)}"
                    update_payload = urllib.parse.urlencode({
                        'package_id': pkg_id,
                        'status': 'REVIEWED',
                        'updated_by': request.user.get_full_name() or request.user.username or 'کارشناس بررسی کننده',
                        'api_key': settings.api_key,
                    }).encode('utf-8')
                    req = urllib.request.Request(update_url, data=update_payload, headers=headers, method='POST')
                    urllib.request.urlopen(req, timeout=3)
                except Exception:
                    pass
        else:
            return JsonResponse({'success': False, 'error': f'خطا در دانلود بسته از سرور ({status_code})'})

    diff_report = SyncEngine.analyze_package_diff(package_data)

    clean_title = convert_text_dates_to_jalali(package_data.get('title', ''))

    return JsonResponse({
        'success': True,
        'package_info': {
            'package_id': package_data.get('package_id'),
            'author': package_data.get('author'),
            'title': clean_title,
            'created_at': package_data.get('created_at'),
            'created_at_jalali': to_jalali_str(package_data.get('created_at')),
            'summary': package_data.get('summary', {}),
        },
        'diff': diff_report,
        'package_raw': package_data,
    })


@login_required
@csrf_exempt
def apply_merge_view(request):
    """
    تایید و اعمال نهایی بسته تغییرات در دیتابیس محلی
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'متد نامعتبر است.'}, status=405)

    settings = SyncSetting.get_settings()
    try:
        body = json.loads(request.body)
    except Exception:
        return JsonResponse({'success': False, 'error': 'فرمت داده نامعتبر است.'}, status=400)

    package_data = body.get('package_data')
    if not package_data or not package_data.get('package_id'):
        return JsonResponse({'success': False, 'error': 'بسته معتبر نیست.'}, status=400)

    try:
        # اعمال در دیتابیس محلی
        operator_name = request.user.get_full_name() or request.user.username or 'مدیر سیستم'
        results = SyncEngine.apply_package(package_data, applied_by=operator_name)

        # ثبت در تاریخچه
        SyncPackageHistory.objects.update_or_create(
            package_id=package_data['package_id'],
            defaults={
                'direction': 'INCOMING',
                'author': package_data.get('author', 'نامشخص'),
                'title': package_data.get('title', 'بسته همگام‌سازی'),
                'summary': package_data.get('summary', {}),
                'payload': package_data,
                'status': 'MERGED',
                'merge_report': results,
                'applied_at': timezone.now(),
            }
        )

        # علامت‌گذاری قطعی روی سرور
        try:
            url = f"{settings.server_url.rstrip('/')}?action=update_status&api_key={urllib.parse.quote(settings.api_key)}"
            headers = {'X-API-KEY': settings.api_key}
            update_payload = urllib.parse.urlencode({
                'package_id': package_data['package_id'],
                'status': 'MERGED',
                'updated_by': operator_name,
                'api_key': settings.api_key,
            }).encode('utf-8')
            req = urllib.request.Request(url, data=update_payload, headers=headers, method='POST')
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass

        return JsonResponse({
            'success': True,
            'message': 'تغییرات با موفقیت در پایگاه‌داده محلی ادغام و وضعیت بسته به «ادغام شده» به‌روزرسانی شد.',
            'results': results,
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': f'خطا در اعمال تغییرات: {str(e)}'}, status=500)


@login_required
def batch_scan_view(request):
    """
    پایش کلی و یکپارچه تمام بسته‌های بررسی‌نشده روی سرور
    """
    settings = SyncSetting.get_settings()
    url = f"{settings.server_url.rstrip('/')}?action=list&api_key={urllib.parse.quote(settings.api_key)}"
    headers = {'X-API-KEY': settings.api_key}
    status_code, json_data, raw_text = _http_request(url, method='GET', headers=headers, timeout=10)

    if status_code != 200 or not json_data or not json_data.get('success'):
        err = json_data.get('error') if json_data else raw_text[:200]
        return JsonResponse({'success': False, 'error': f'خطا در ارتباط با سرور: {err}'})

    local_histories = {h.package_id: h.status for h in SyncPackageHistory.objects.all()}
    pending_packages = []
    
    for p in json_data.get('packages', []):
        pid = p.get('package_id')
        local_st = local_histories.get(pid)
        if local_st != 'MERGED' and p.get('status') != 'MERGED':
            pending_packages.append(p)

    if not pending_packages:
        return JsonResponse({
            'success': True,
            'has_pending': False,
            'message': 'هیچ بسته جدید یا در انتظار بررسی روی سرور وجود ندارد.',
            'packages': [],
            'stats': {
                'total_packages': 0,
                'total_items': 0,
                'needed_items': 0,
                'identical_items': 0,
            }
        })

    # دانلود و پایش تک تک بسته‌ها
    scanned_packages = []
    total_items = 0
    total_needed = 0
    total_identical = 0

    for p in pending_packages:
        pid = p.get('package_id')
        dl_url = f"{settings.server_url.rstrip('/')}?action=download&package_id={urllib.parse.quote(pid)}&api_key={urllib.parse.quote(settings.api_key)}"
        _, dl_json, _ = _http_request(dl_url, method='GET', headers=headers, timeout=10)
        
        if dl_json and dl_json.get('success') and dl_json.get('package'):
            pkg_data = dl_json.get('package')
            diff_report = SyncEngine.analyze_package_diff(pkg_data)
            
            total_items += diff_report['total_items']
            total_needed += diff_report['needed_items']
            total_identical += diff_report['identical_items']
            
            created_dt = pkg_data.get('created_at', p.get('created_at', ''))
            scanned_packages.append({
                'package_id': pid,
                'author': pkg_data.get('author', p.get('author', 'نامشخص')),
                'title': convert_text_dates_to_jalali(pkg_data.get('title', p.get('title', 'بسته همگام‌سازی'))),
                'created_at': created_dt,
                'created_at_jalali': to_jalali_str(created_dt),
                'total_items': diff_report['total_items'],
                'needed_items': diff_report['needed_items'],
                'identical_items': diff_report['identical_items'],
                'is_all_identical': diff_report['is_all_identical'],
                'scan_verdict': diff_report['scan_verdict'],
                'package_raw': pkg_data,
            })

    return JsonResponse({
        'success': True,
        'has_pending': True,
        'packages': scanned_packages,
        'stats': {
            'total_packages': len(scanned_packages),
            'total_items': total_items,
            'needed_items': total_needed,
            'identical_items': total_identical,
        }
    })


@login_required
@csrf_exempt
def batch_apply_view(request):
    """
    اعمال دسته‌ای و همزمان بسته‌های انتخاب‌شده در دیتابیس
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'متد نامعتبر است.'}, status=405)

    settings = SyncSetting.get_settings()
    try:
        body = json.loads(request.body)
    except Exception:
        return JsonResponse({'success': False, 'error': 'فرمت داده نامعتبر است.'}, status=400)

    packages_to_apply = body.get('packages', [])
    if not packages_to_apply:
        return JsonResponse({'success': False, 'error': 'هیچ بسته‌ای برای اعمال ارسال نشده است.'}, status=400)

    operator_name = request.user.get_full_name() or request.user.username or 'مدیر سیستم'
    applied_count = 0
    total_results = {
        'jobs_created': 0,
        'jobs_updated': 0,
        'descriptions_saved': 0,
        'models_saved': 0,
        'scores_applied': 0,
        'candidates_created': 0,
    }

    for pkg_data in packages_to_apply:
        pid = pkg_data.get('package_id')
        if not pid:
            continue
        try:
            res = SyncEngine.apply_package(pkg_data, applied_by=operator_name)
            for k in total_results:
                total_results[k] += res.get(k, 0)

            # ثبت تاریخچه محلی
            SyncPackageHistory.objects.update_or_create(
                package_id=pid,
                defaults={
                    'direction': 'INCOMING',
                    'author': pkg_data.get('author', 'نامشخص'),
                    'title': pkg_data.get('title', 'بسته همگام‌سازی'),
                    'summary': pkg_data.get('summary', {}),
                    'payload': pkg_data,
                    'status': 'MERGED',
                    'merge_report': res,
                    'applied_at': timezone.now(),
                }
            )

            # اعلام وضعیت به سرور
            try:
                url = f"{settings.server_url.rstrip('/')}?action=update_status&api_key={urllib.parse.quote(settings.api_key)}"
                headers = {'X-API-KEY': settings.api_key}
                update_payload = urllib.parse.urlencode({
                    'package_id': pid,
                    'status': 'MERGED',
                    'updated_by': operator_name,
                    'api_key': settings.api_key,
                }).encode('utf-8')
                req = urllib.request.Request(url, data=update_payload, headers=headers, method='POST')
                urllib.request.urlopen(req, timeout=3)
            except Exception:
                pass

            applied_count += 1
        except Exception:
            continue

    return JsonResponse({
        'success': True,
        'applied_packages_count': applied_count,
        'total_results': total_results,
        'message': f"تعداد {applied_count} بسته با موفقیت در پایگاه‌داده ادغام و اعمال شد."
    })


@login_required
@csrf_exempt
def save_settings_view(request):
    """
    ذخیره تنظیمات اتصال به سرور همگام‌سازی
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'متد نامعتبر است.'}, status=405)

    settings = SyncSetting.get_settings()
    settings.server_url = request.POST.get('server_url', settings.server_url)
    settings.api_key = request.POST.get('api_key', settings.api_key)
    settings.specialist_name = request.POST.get('specialist_name', settings.specialist_name)
    settings.save()

    messages.success(request, 'تنظیمات همگام‌سازی با موفقیت ذخیره شد.')
    return redirect('sync_hub:dashboard')
