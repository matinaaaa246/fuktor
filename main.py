"""
نقطه‌ی ورود اصلی ربات تلگرام (اجباری - این فایل فقط باید register_* هر فاز را صدا بزند).

هر فاز جدید فقط باید تابع register_<phase>_handlers خودش را اینجا import
و صدا بزند و نباید به کد فازهای دیگر دست بزند.
"""

import logging
import threading

from telegram import Update
from telegram.ext import Application

import config
from database.db import init_db

# هسته مرکزی: منوی اصلی که تمام فازها را به هم متصل می‌کند
from handlers.core_handlers import register_core_handlers

# ایمپورت کردن هندلرهای فازهای توسعه داده شده
from handlers.invoice_handlers import register_invoice_handlers
from handlers.invoice_management import register_invoice_management_handlers
from handlers.reports_handlers import register_reports_handlers

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def start_webapp_server() -> None:
    """اجرای پنل وب گرافیکی (فاز ۶) در یک ترد جداگانه، همزمان با ربات تلگرام"""
    from webapp.web_server import app as flask_app

    flask_app.run(host="0.0.0.0", port=config.WEBAPP_PORT, use_reloader=False, debug=False)


def main() -> None:
    init_db()

    application = Application.builder().token(config.BOT_TOKEN).build()

    # هسته مرکزی: /start ، /menu و منوی اصلی مشترک بین همه‌ی فازها
    register_core_handlers(application)

    # فاز ۱: فاکتور جدید (پیاده‌سازی شده)
    register_invoice_handlers(application)

    # فاز ۲: مدیریت فاکتورها (پیاده‌سازی شده)
    register_invoice_management_handlers(application)

    # فاز ۳: گزارش‌ها (پیاده‌سازی شده)
    register_reports_handlers(application)

    # فاز ۴: مدیریت مشتریان / CRM
    from handlers.crm_handlers import register_crm_handlers
    register_crm_handlers(application)

    # فاز ۵: محصولات و انبار
    from handlers.product_handlers import register_product_handlers
    register_product_handlers(application)

    # فاز ۶: تنظیمات
    from handlers.settings_handlers import register_settings_handlers
    register_settings_handlers(application)

    # اجرای پنل وب گرافیکی (Flask) به‌صورت پس‌زمینه همراه با ربات
    webapp_thread = threading.Thread(target=start_webapp_server, daemon=True)
    webapp_thread.start()
    logger.info("پنل وب روی پورت %s در حال اجراست...", config.WEBAPP_PORT)

    logger.info("ربات در حال اجراست...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
