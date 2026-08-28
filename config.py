"""
تنظیمات کلی پروژه (اجباری - نام متغیرها را تغییر ندهید).
"""

import os

# توکن ربات تلگرام - این مقدار را با توکن واقعی جایگزین کنید
BOT_TOKEN = os.getenv("BOT_TOKEN", "PUT_YOUR_BOT_TOKEN_HERE")

# آیدی عددی تلگرام ادمین اصلی ربات
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# مسیر فایل دیتابیس SQLite
DB_PATH = os.path.join(BASE_DIR, "shop.db")

# مسیر پوشه بکاپ‌ها
BACKUP_DIR = os.path.join(BASE_DIR, "backups")

# مسیر پوشه خروجی فایل‌های فاکتور (متن ساده / تصویر / PDF)
INVOICE_OUTPUT_DIR = os.path.join(BASE_DIR, "invoice_outputs")

# آدرس عمومی پنل وب گرافیکی (فاز ۶) - باید HTTPS و از بیرون در دسترس باشد
# چون تلگرام Web App فقط با HTTPS کار می‌کند (برای تست لوکال از ngrok یا مشابه آن استفاده کنید)
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://your-domain.com/dashboard")

# پورتی که سرور Flask پنل وب روی آن اجرا می‌شود
WEBAPP_PORT = int(os.getenv("WEBAPP_PORT", "5000"))
