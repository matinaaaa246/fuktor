import os
import zipfile
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters
)

import config
from database.db import get_session
from database.models import Setting

# بازه State های فاز 6
SET_SHOP_NAME = 601
SET_SHOP_PHONE = 602
SET_INVOICE_PREFIX = 603
SET_INVOICE_COUNTER = 604
SET_SHOP_LOGO = 605  # State جدید برای لوگو

async def settings_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """منوی اصلی تنظیمات (فقط برای ادمین)"""
    user_id = update.effective_user.id
    if user_id != config.ADMIN_ID:
        msg = "⛔️ شما دسترسی به بخش تنظیمات را ندارید."
        if update.callback_query:
            await update.callback_query.answer(msg, show_alert=True)
        else:
            await update.message.reply_text(msg)
        return ConversationHandler.END

    session = get_session()
    try:
        shop_name = session.query(Setting).filter_by(key="shop_name").first()
        shop_phone = session.query(Setting).filter_by(key="shop_phone").first()
        inv_prefix = session.query(Setting).filter_by(key="invoice_prefix").first()
        shop_logo = session.query(Setting).filter_by(key="shop_logo").first()
        
        name_val = shop_name.value if shop_name else "تنظیم نشده"
        phone_val = shop_phone.value if shop_phone else "تنظیم نشده"
        prefix_val = inv_prefix.value if inv_prefix else "INV-"
        logo_status = "ثبت شده ✅" if shop_logo else "تنظیم نشده"
    finally:
        session.close()

    text = (
        "⚙️ **تنظیمات سیستم**\n"
        "━━━━━━━━━━━━━━\n"
        f"🏷 نام فروشگاه: `{name_val}`\n"
        f"📞 شماره تماس: `{phone_val}`\n"
        f"🔢 پیشوند فاکتور: `{prefix_val}`\n"
        f"🖼 وضعیت لوگو: `{logo_status}`\n"
        "━━━━━━━━━━━━━━\n"
        "لطفاً یک گزینه را انتخاب کنید:"
    )

    # URL پنل وب (از config.py - باید HTTPS باشد)
    webapp_url = config.WEBAPP_URL

    keyboard = [
        [InlineKeyboardButton("📊 داشبورد گرافیکی (پنل وب)", web_app=WebAppInfo(url=webapp_url))],
        [InlineKeyboardButton("✏️ تغییر نام فروشگاه", callback_data="settings_edit_name"),
         InlineKeyboardButton("✏️ تغییر شماره تماس", callback_data="settings_edit_phone")],
        [InlineKeyboardButton("🖼 تغییر لوگو", callback_data="settings_edit_logo"),
         InlineKeyboardButton("✏️ تغییر پیشوند فاکتور", callback_data="settings_edit_prefix")],
        [InlineKeyboardButton("💾 بک‌آپ فوری دیتابیس", callback_data="settings_backup_now")],
        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")],
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    
    return ConversationHandler.END


# --- توابع ویرایش تنظیمات ---
async def ask_shop_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [[InlineKeyboardButton("انصراف", callback_data="settings_menu")]]
    await query.edit_message_text("🏷 لطفاً نام جدید فروشگاه را وارد کنید:", reply_markup=InlineKeyboardMarkup(keyboard))
    return SET_SHOP_NAME

async def save_shop_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await _save_setting(update, "shop_name", update.message.text.strip(), "نام فروشگاه")


async def ask_shop_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [[InlineKeyboardButton("انصراف", callback_data="settings_menu")]]
    await query.edit_message_text("📞 لطفاً شماره تماس فروشگاه را وارد کنید:", reply_markup=InlineKeyboardMarkup(keyboard))
    return SET_SHOP_PHONE

async def save_shop_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await _save_setting(update, "shop_phone", update.message.text.strip(), "شماره تماس")


async def ask_invoice_prefix(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [[InlineKeyboardButton("انصراف", callback_data="settings_menu")]]
    await query.edit_message_text("🔢 پیشوند شماره‌گذاری فاکتورها را وارد کنید (مثال: INV-):", reply_markup=InlineKeyboardMarkup(keyboard))
    return SET_INVOICE_PREFIX

async def save_invoice_prefix(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await _save_setting(update, "invoice_prefix", update.message.text.strip(), "پیشوند فاکتور")


# --- توابع مدیریت لوگو ---
async def ask_shop_logo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [[InlineKeyboardButton("انصراف", callback_data="settings_menu")]]
    await query.edit_message_text("🖼 لطفاً تصویر لوگوی فروشگاه را ارسال کنید (به صورت عکس، نه فایل):", reply_markup=InlineKeyboardMarkup(keyboard))
    return SET_SHOP_LOGO

async def save_shop_logo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # گرفتن file_id با کیفیت‌ترین نسخه عکس ارسال شده
    photo_file_id = update.message.photo[-1].file_id
    return await _save_setting(update, "shop_logo", photo_file_id, "لوگوی فروشگاه")


async def _save_setting(update: Update, key: str, value: str, label: str):
    session = get_session()
    try:
        setting = session.query(Setting).filter_by(key=key).first()
        if not setting:
            setting = Setting(key=key, value=value)
            session.add(setting)
        else:
            setting.value = value
        session.commit()
    finally:
        session.close()

    keyboard = [[InlineKeyboardButton("🔙 بازگشت به تنظیمات", callback_data="settings_menu")]]
    await update.message.reply_text(f"✅ {label} با موفقیت ذخیره شد.", reply_markup=InlineKeyboardMarkup(keyboard))
    return ConversationHandler.END


# --- توابع بک‌آپ ---
async def send_database_backup(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    """ساخت فایل زیپ از دیتابیس و ارسال آن"""
    db_path = config.DB_PATH
    if not os.path.exists(db_path):
        await context.bot.send_message(chat_id, "❌ فایل دیتابیس یافت نشد.")
        return

    backup_dir = config.BACKUP_DIR
    os.makedirs(backup_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_path = os.path.join(backup_dir, f"db_backup_{timestamp}.zip")

    try:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            zipf.write(db_path, os.path.basename(db_path))

        with open(zip_path, 'rb') as f:
            await context.bot.send_document(
                chat_id=chat_id,
                document=f,
                caption=f"💾 بک‌آپ دیتابیس\n📅 تاریخ: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            )
    except Exception as e:
        await context.bot.send_message(chat_id, f"❌ خطا در تولید بک‌آپ:\n{str(e)}")

async def manual_backup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("در حال تهیه بک‌آپ...")
    await send_database_backup(context, config.ADMIN_ID)
    
async def manual_backup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.ADMIN_ID:
        return
    await update.message.reply_text("⏳ در حال تهیه بک‌آپ...")
    await send_database_backup(context, config.ADMIN_ID)

async def weekly_backup_job(context: ContextTypes.DEFAULT_TYPE):
    """جاب زمان‌بندی شده برای بک‌آپ هفتگی"""
    await send_database_backup(context, config.ADMIN_ID)


# --- ثبت هندلرها ---
def register_settings_handlers(application: Application):
    """ثبت منوها و Conversation های بخش تنظیمات"""
    # کامند پشتیبان /backup
    application.add_handler(CommandHandler("backup", manual_backup_command))
    application.add_handler(CallbackQueryHandler(manual_backup_callback, pattern="^settings_backup_now$"))

    # هندلر Conversation برای دریافت مقادیر متنی و عکس
    conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(settings_main_menu, pattern="^settings_menu$"),
            CommandHandler("settings", settings_main_menu),
            CallbackQueryHandler(ask_shop_name, pattern="^settings_edit_name$"),
            CallbackQueryHandler(ask_shop_phone, pattern="^settings_edit_phone$"),
            CallbackQueryHandler(ask_invoice_prefix, pattern="^settings_edit_prefix$"),
            CallbackQueryHandler(ask_shop_logo, pattern="^settings_edit_logo$"),
        ],
        states={
            SET_SHOP_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_shop_name)],
            SET_SHOP_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_shop_phone)],
            SET_INVOICE_PREFIX: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_invoice_prefix)],
            SET_SHOP_LOGO: [MessageHandler(filters.PHOTO, save_shop_logo)],
        },
        fallbacks=[CallbackQueryHandler(settings_main_menu, pattern="^settings_menu$")],
        map_to_parent={ConversationHandler.END: ConversationHandler.END}
    )
    application.add_handler(conv_handler)

    # زمان‌بندی بک‌آپ هفتگی (هر ۷ روز یکبار)
    if application.job_queue:
        application.job_queue.run_repeating(
            weekly_backup_job,
            interval=7 * 24 * 60 * 60, # 7 Days in seconds
            first=10 # First run 10 seconds after bot starts, then weekly
        )