"""
هسته مرکزی ربات (اجباری برای اجرای یکپارچه فازها).

این فایل هیچ منطق اختصاصی هیچ فازی را در بر ندارد؛ فقط:
  - دستور /start و /menu را مدیریت می‌کند
  - منوی اصلی را می‌سازد که به منوی هر فاز (با callback_data خودش) لینک می‌دهد
  - یک هندلر مشترک با callback_data ثابت "main_menu" برای دکمه‌ی
    "🏠 منوی اصلی" ارائه می‌دهد که در تمام فازها استفاده می‌شود

هر فاز جدید فقط کافیست یک ردیف دکمه به build_main_menu_keyboard اضافه کند.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

import config

MAIN_MENU_TEXT = (
    "🏪 **به ربات مدیریت فروشگاه خوش آمدید** 👋\n"
    "یکی از بخش‌های زیر را انتخاب کنید:"
)


def build_main_menu_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """ساخت کیبورد منوی اصلی؛ گزینه تنظیمات فقط برای ادمین نمایش داده می‌شود."""
    keyboard = [
        [InlineKeyboardButton("🧾 فاکتور", callback_data="inv_new_open_menu")],
        [InlineKeyboardButton("📋 مدیریت فاکتورها", callback_data="inv_mgmt_menu")],
        [InlineKeyboardButton("📊 گزارش‌های مالی", callback_data="report_main")],
        [InlineKeyboardButton("👥 مشتریان (CRM)", callback_data="crm_menu")],
        [InlineKeyboardButton("📦 محصولات و انبار", callback_data="product_menu")],
    ]
    if user_id == config.ADMIN_ID:
        keyboard.append([InlineKeyboardButton("⚙️ تنظیمات", callback_data="settings_menu")])
    return InlineKeyboardMarkup(keyboard)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دستور /start و /menu - نمایش منوی اصلی"""
    await update.message.reply_text(
        MAIN_MENU_TEXT,
        reply_markup=build_main_menu_keyboard(update.effective_user.id),
        parse_mode="Markdown",
    )


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """کال‌بک دکمه‌ی مشترک "main_menu" که از داخل تمام فازها صدا زده می‌شود"""
    query = update.callback_query
    await query.answer()

    keyboard = build_main_menu_keyboard(update.effective_user.id)

    # اگر پیام فعلی عکس/نمودار بود، ویرایش ممکن نیست؛ پیام جدید ارسال می‌شود
    if query.message.photo:
        await query.message.delete()
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=MAIN_MENU_TEXT,
            reply_markup=keyboard,
            parse_mode="Markdown",
        )
    else:
        await query.edit_message_text(MAIN_MENU_TEXT, reply_markup=keyboard, parse_mode="Markdown")


def register_core_handlers(application: Application) -> None:
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("menu", start_command))
    application.add_handler(CallbackQueryHandler(show_main_menu, pattern="^main_menu$"))
