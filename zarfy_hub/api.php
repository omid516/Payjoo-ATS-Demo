<?php
/**
 * Payjoo ATS - Central Sync Hub API for zarfy.ir
 * 
 * اسکریپت مرکزی مدیریت و همگام‌سازی بسته‌های تغییرات چندکاربره سامانه Payjoo ATS
 * این فایل به همراه پوشه packages/ روی هاست قرار می‌گیرد.
 */

header('Content-Type: application/json; charset=utf-8');
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: GET, POST, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type, X-API-KEY, Authorization');

if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') {
    http_response_code(200);
    exit;
}

// تنظیمات امنیتی
define('API_SECRET_KEY', 'ats_secret_key_zarfy_2026'); // کلید امنیتی تطبیق با کلاینت‌ها
define('STORAGE_DIR', __DIR__ . '/packages');

// ساخت پوشه ذخیره‌سازی در صورت عدم وجود
if (!is_dir(STORAGE_DIR)) {
    mkdir(STORAGE_DIR, 0755, true);
    // ساخت فایل .htaccess محافظت کننده در پوشه ذخیره
    file_put_contents(STORAGE_DIR . '/.htaccess', "Deny from all\n");
}

function send_json($data, $code = 200) {
    http_response_code($code);
    echo json_encode($data, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT);
    exit;
}

// بررسی احراز هویت با API Key
function check_auth() {
    $provided_key = '';
    if (isset($_REQUEST['api_key']) && !empty($_REQUEST['api_key'])) {
        $provided_key = $_REQUEST['api_key'];
    } elseif (isset($_SERVER['HTTP_X_API_KEY']) && !empty($_SERVER['HTTP_X_API_KEY'])) {
        $provided_key = $_SERVER['HTTP_X_API_KEY'];
    } elseif (function_exists('getallheaders')) {
        $headers = array_change_key_case(getallheaders(), CASE_LOWER);
        if (isset($headers['x-api-key'])) {
            $provided_key = $headers['x-api-key'];
        }
    }
    
    if ($provided_key !== API_SECRET_KEY) {
        send_json([
            'success' => false,
            'error' => 'احراز هویت ناموفق: کلید امنیتی (API Key) نامعتبر است.'
        ], 401);
    }
}

$action = isset($_GET['action']) ? trim($_GET['action']) : '';

switch ($action) {
    case 'ping':
        // تست اتصال و بررسی سلامت سرور
        check_auth();
        send_json([
            'success' => true,
            'server' => 'zarfy.ir ATS Sync Hub',
            'status' => 'ONLINE',
            'timestamp' => date('Y-m-d H:i:s'),
            'packages_count' => count(glob(STORAGE_DIR . '/*.json'))
        ]);
        break;

    case 'upload':
        // آپلود بسته تغییرات جدید
        check_auth();
        if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
            send_json(['success' => false, 'error' => 'متد درخواست باید POST باشد.'], 405);
        }

        $input_raw = file_get_contents('php://input');
        if (empty($input_raw)) {
            send_json(['success' => false, 'error' => 'محتوای ارسالی خالی است.'], 400);
        }

        $package_data = json_decode($input_raw, true);
        if (!$package_data || !isset($package_data['package_id'])) {
            send_json(['success' => false, 'error' => 'فرمت بسته تغییرات نامعتبر است.'], 400);
        }

        $package_id = preg_replace('/[^a-zA-Z0-9_\-]/', '', $package_data['package_id']);
        if (empty($package_id)) {
            $package_id = 'pkg_' . uniqid();
            $package_data['package_id'] = $package_id;
        }

        // اضافه کردن متادیتای سرور
        $package_data['server_received_at'] = date('Y-m-d H:i:s');
        if (!isset($package_data['status'])) {
            $package_data['status'] = 'PENDING';
        }

        $file_path = STORAGE_DIR . '/' . $package_id . '.json';
        $saved = file_put_contents($file_path, json_encode($package_data, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT));

        if ($saved === false) {
            send_json(['success' => false, 'error' => 'خطا در ذخیره‌سازی بسته روی سرور.'], 500);
        }

        send_json([
            'success' => true,
            'message' => 'بسته تغییرات با موفقیت روی سرور zarfy.ir ثبت شد.',
            'package_id' => $package_id,
            'author' => isset($package_data['author']) ? $package_data['author'] : 'نامشخص',
            'timestamp' => $package_data['server_received_at']
        ]);
        break;

    case 'list':
        // دریافت لیست بسته‌های موجود در سرور
        check_auth();
        $files = glob(STORAGE_DIR . '/*.json');
        $packages = [];

        foreach ($files as $file) {
            $content = file_get_contents($file);
            $pkg = json_decode($content, true);
            if ($pkg && isset($pkg['package_id'])) {
                // فقط متادیتا و خلاصه را در لیست برمی‌گردانیم تا سبک باشد
                $packages[] = [
                    'package_id' => $pkg['package_id'],
                    'author' => isset($pkg['author']) ? $pkg['author'] : 'کارشناس',
                    'title' => isset($pkg['title']) ? $pkg['title'] : 'بسته تغییرات بدون عنوان',
                    'created_at' => isset($pkg['created_at']) ? $pkg['created_at'] : '',
                    'server_received_at' => isset($pkg['server_received_at']) ? $pkg['server_received_at'] : '',
                    'status' => isset($pkg['status']) ? $pkg['status'] : 'PENDING',
                    'items_count' => isset($pkg['summary']) ? $pkg['summary'] : [
                        'jobs' => isset($pkg['data']['jobs']) ? count($pkg['data']['jobs']) : 0,
                        'templates' => isset($pkg['data']['job_descriptions']) ? count($pkg['data']['job_descriptions']) : 0,
                        'competencies' => isset($pkg['data']['competencies']) ? count($pkg['data']['competencies']) : 0,
                        'scores' => isset($pkg['data']['scores']) ? count($pkg['data']['scores']) : 0,
                        'settings' => isset($pkg['data']['settings']) ? count($pkg['data']['settings']) : 0,
                    ],
                    'size_kb' => round(filesize($file) / 1024, 2)
                ];
            }
        }

        // مرتب‌سازی بر اساس جدیدترین
        usort($packages, function($a, $b) {
            return strcmp($b['server_received_at'], $a['server_received_at']);
        });

        send_json([
            'success' => true,
            'total' => count($packages),
            'packages' => $packages
        ]);
        break;

    case 'download':
        // دریافت محتوای کامل یک بسته برای بررسی و تایید
        check_auth();
        $package_id = isset($_GET['package_id']) ? preg_replace('/[^a-zA-Z0-9_\-]/', '', $_GET['package_id']) : '';
        if (empty($package_id)) {
            send_json(['success' => false, 'error' => 'شناسه بسته مشخص نشده است.'], 400);
        }

        $file_path = STORAGE_DIR . '/' . $package_id . '.json';
        if (!file_exists($file_path)) {
            send_json(['success' => false, 'error' => 'بسته مورد نظر روی سرور یافت نشد.'], 404);
        }

        $content = file_get_contents($file_path);
        $pkg = json_decode($content, true);
        send_json([
            'success' => true,
            'package' => $pkg
        ]);
        break;

    case 'update_status':
        // تغییر وضعیت بسته (علامت‌گذاری به عنوان REVIEWED یا MERGED یا REJECTED یا PENDING)
        check_auth();
        $input_json = json_decode(file_get_contents('php://input'), true);
        
        $package_id = '';
        if (isset($_REQUEST['package_id']) && !empty($_REQUEST['package_id'])) {
            $package_id = $_REQUEST['package_id'];
        } elseif ($input_json && isset($input_json['package_id'])) {
            $package_id = $input_json['package_id'];
        }
        $package_id = preg_replace('/[^a-zA-Z0-9_\-]/', '', $package_id);

        $new_status = '';
        if (isset($_REQUEST['status']) && !empty($_REQUEST['status'])) {
            $new_status = strtoupper(trim($_REQUEST['status']));
        } elseif ($input_json && isset($input_json['status'])) {
            $new_status = strtoupper(trim($input_json['status']));
        }

        $valid_statuses = ['PENDING', 'REVIEWED', 'MERGED', 'REJECTED'];
        if (empty($package_id) || !in_array($new_status, $valid_statuses)) {
            send_json(['success' => false, 'error' => 'پارامترهای وضعیت یا شناسه بسته نامعتبر است.'], 400);
        }

        $file_path = STORAGE_DIR . '/' . $package_id . '.json';
        if (!file_exists($file_path)) {
            send_json(['success' => false, 'error' => 'بسته مورد نظر یافت نشد.'], 404);
        }

        $content = file_get_contents($file_path);
        $pkg = json_decode($content, true);
        $pkg['status'] = $new_status;
        $pkg['updated_at'] = date('Y-m-d H:i:s');
        
        $updated_by = 'کاربر سامانه';
        if (isset($_REQUEST['updated_by']) && !empty($_REQUEST['updated_by'])) {
            $updated_by = $_REQUEST['updated_by'];
        } elseif ($input_json && isset($input_json['updated_by'])) {
            $updated_by = $input_json['updated_by'];
        }
        $pkg['updated_by'] = $updated_by;

        file_put_contents($file_path, json_encode($pkg, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT));

        send_json([
            'success' => true,
            'message' => 'وضعیت بسته با موفقیت به‌روزرسانی شد.',
            'package_id' => $package_id,
            'status' => $new_status,
            'updated_by' => $updated_by
        ]);
        break;

    default:
        send_json([
            'success' => false,
            'message' => 'Payjoo ATS Sync Hub Endpoint',
            'valid_actions' => ['ping', 'upload', 'list', 'download', 'update_status']
        ], 400);
        break;
}
