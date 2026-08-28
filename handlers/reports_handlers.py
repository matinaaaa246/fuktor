# handlers/reports_handlers.py

import io
import os
import re
from datetime import datetime, timedelta

import matplotlib
# تنظیم بک‌اند matplotlib روی Agg برای جلوگیری از خطاهای محیط بدون رابط کاربری (Server/Headless)
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CallbackQueryHandler, ContextTypes, ConversationHandler, MessageHandler, filters
)
from sqlalchemy import func

import arabic_reshaper
from bidi.algorithm import get_display

import config
from database.db import get_session
from database.models import Invoice, InvoiceStatus, InvoiceItem

# بازه state برای فاز ۳ (برای ورود تاریخ سفارشی)
WAITING_FOR_DATE = 300

def reshape_persian(text: str) -> str:
    """اصلاح جهت و اتصال حروف فارسی برای استفاده در Matplotlib"""
    if not text:
        return ""
    reshaped = arabic_reshaper.reshape(str(text))
    return get_display(reshaped)

def create_chart(x_labels, y_values, title, xlabel, ylabel):
    """تولید یک تصویر نمودار میله‌ای با استفاده از Matplotlib مطابق با Design Tokens سیستم"""
    
    # تلاش برای لود فونت اختصاصی در صورت وجود
    font_path = os.path.join(config.BASE_DIR, 'webapp', 'static', 'fonts', 'Vazirmatn-Regular.ttf')
    if os.path.exists(font_path):
        font_manager.fontManager.addfont(font_path)
        prop = font_manager.FontProperties(fname=font_path)
        plt.rcParams['font.family'] = prop.get_name()
    
    fig, ax = plt.subplots(figsize=(8, 5))
    
    # رنگ‌های سیستم دیزاین
    bg_primary = '#0B0B10'
    bg_panel = '#15151C'
    accent_1 = '#7C5CFF' # بنفش
    text_primary = '#F2F1F7'
    text_muted = '#8B8A99'
    
    fig.patch.set_facecolor(bg_primary)
    ax.set_facecolor(bg_panel)
    
    # رسم نمودار میله‌ای
    ax.bar(x_labels, y_values, color=accent_1, edgecolor='#3B8CFF', linewidth=1, alpha=0.8)
    
    # تنظیم متون و لیبل‌ها (با تابع reshape_persian)
    ax.set_title(reshape_persian(title), color=text_primary, fontsize=14, pad=15)
    ax.set_xlabel(reshape_persian(xlabel), color=text_primary, fontsize=12, labelpad=10)
    ax.set_ylabel(reshape_persian(ylabel), color=text_primary, fontsize=12, labelpad=10)
    
    ax.tick_params(colors=text_primary)
    for spine in ax.spines.values():
        spine.set_color(text_muted)
    
    ax.grid(color='#1C1C26', linestyle='--', linewidth=1, axis='y', alpha=0.7)
    
    # مدیریت چرخش و تعداد لیبل‌های محور X برای جلوگیری از شلوغی
    if len(x_labels) > 15:
        step = max(1, len(x_labels) // 10)
        ax.set_xticks(range(0, len(x_labels), step))
        ax.set_xticklabels([x_labels[i] for i in range(0, len(x_labels), step)], rotation=45, ha='right')
    else:
        plt.xticks(rotation=45, ha='right')
        
    plt.tight_layout()
    
    # ذخیره در حافظه
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=150, facecolor=fig.get_facecolor())
    buf.seek(0)
    plt.close(fig)
    return buf

async def report_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش منوی اصلی گزارش‌ها"""
    keyboard = [
        [InlineKeyboardButton("💰 گزارش درآمد", callback_data="report_tf_revenue")],
        [InlineKeyboardButton("📈 پرفروش‌ترین محصولات", callback_data="report_tf_top_products")],
        [InlineKeyboardButton("📉 کم‌فروش‌ترین محصولات", callback_data="report_tf_worst_products")],
        [InlineKeyboardButton("🎁 مجموع تخفیف‌ها", callback_data="report_tf_discounts")],
        [InlineKeyboardButton("🚚 مجموع هزینه‌های ارسال", callback_data="report_tf_shipping")],
        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "📊 **منوی گزارش‌های مالی**\nلطفاً نوع گزارش مورد نظر خود را انتخاب کنید:"
    
    if update.callback_query:
        await update.callback_query.answer()
        # فقط در صورتی که پیام عکس نباشد می‌توانیم ویرایش کنیم
        if update.callback_query.message.photo:
            await update.callback_query.message.delete()
            await context.bot.send_message(chat_id=update.effective_chat.id, text=text, reply_markup=reply_markup, parse_mode='Markdown')
        else:
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    
    return ConversationHandler.END

async def select_timeframe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش انتخابگر بازه زمانی بر اساس نوع گزارش"""
    query = update.callback_query
    await query.answer()
    report_type = query.data.split("_")[2] 
    
    keyboard = [
        [InlineKeyboardButton("امروز", callback_data=f"report_do_{report_type}_today"),
         InlineKeyboardButton("دیروز", callback_data=f"report_do_{report_type}_yesterday")],
        [InlineKeyboardButton("۷ روز اخیر", callback_data=f"report_do_{report_type}_week"),
         InlineKeyboardButton("این ماه", callback_data=f"report_do_{report_type}_month")],
        [InlineKeyboardButton("بازه دلخواه", callback_data=f"report_custom_{report_type}")],
        [InlineKeyboardButton("🔙 بازگشت به گزارش‌ها", callback_data="report_main")]
    ]
    
    text = "🗓 لطفاً بازه زمانی گزارش را مشخص کنید:"
    if query.message.photo:
        await query.message.delete()
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    
    return ConversationHandler.END

async def ask_custom_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """درخواست بازه زمانی سفارشی از کاربر"""
    query = update.callback_query
    await query.answer()
    report_type = query.data.split("_")[2]
    context.user_data['custom_report_type'] = report_type
    
    keyboard = [[InlineKeyboardButton("انصراف", callback_data="report_main")]]
    text = (
        "🗓 **انتخاب بازه دلخواه**\n\n"
        "لطفاً تاریخ شروع و پایان را با فرمت `YYYY-MM-DD YYYY-MM-DD` (فقط با یک فاصله) وارد کنید.\n"
        "مثال: `2026-08-01 2026-08-31`"
    )
    
    if query.message.photo:
        await query.message.delete()
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    else:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        
    return WAITING_FOR_DATE

async def process_custom_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش متن ورودی برای بازه زمانی سفارشی و تولید گزارش"""
    text = update.message.text
    match = re.match(r"^(\d{4}-\d{2}-\d{2})\s+(\d{4}-\d{2}-\d{2})$", text.strip())
    
    if not match:
        await update.message.reply_text(
            "❌ فرمت نامعتبر است. لطفاً تاریخ را دقیقاً مشابه مثال وارد کنید:\n`2026-08-01 2026-08-31`", 
            parse_mode='Markdown'
        )
        return WAITING_FOR_DATE
        
    try:
        start_date = datetime.strptime(match.group(1), "%Y-%m-%d").replace(hour=0, minute=0, second=0)
        end_date = datetime.strptime(match.group(2), "%Y-%m-%d").replace(hour=23, minute=59, second=59)
    except ValueError:
        await update.message.reply_text("❌ تاریخ وارد شده نامعتبر است. لطفاً مجدداً تلاش کنید.")
        return WAITING_FOR_DATE
        
    report_type = context.user_data.get('custom_report_type', 'revenue')
    await process_report_logic(update, context, report_type, start_date, end_date, "بازه دلخواه")
    return ConversationHandler.END

async def generate_report_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت دکمه‌های بازه‌های زمانی پیش‌فرض"""
    query = update.callback_query
    await query.answer()
    
    parts = query.data.split("_")
    report_type = parts[2]
    timeframe = parts[3]
    
    now = datetime.now()
    end_date = now.replace(hour=23, minute=59, second=59, microsecond=999999)
    start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
    tf_label = "امروز"
    
    if timeframe == "yesterday":
        start_date -= timedelta(days=1)
        end_date -= timedelta(days=1)
        tf_label = "دیروز"
    elif timeframe == "week":
        start_date -= timedelta(days=6) # شامل امروز (مجموعا ۷ روز)
        tf_label = "۷ روز اخیر"
    elif timeframe == "month":
        start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        tf_label = "این ماه"
        
    await process_report_logic(update, context, report_type, start_date, end_date, tf_label, query=query)

async def process_report_logic(update: Update, context: ContextTypes.DEFAULT_TYPE, 
                               report_type: str, start_date: datetime, end_date: datetime, 
                               tf_label: str, query=None):
    """هسته پردازشی اصلی دیتابیس برای تهیه و ارسال انواع گزارشات"""
    session = get_session()
    
    # نمایش پیام در حال پردازش
    status_msg = None
    if query:
        if query.message.photo:
            await query.message.delete()
            status_msg = await context.bot.send_message(chat_id=query.message.chat_id, text="⏳ در حال استخراج گزارش...")
        else:
            status_msg = await query.edit_message_text("⏳ در حال استخراج گزارش...")
    else:
        status_msg = await update.message.reply_text("⏳ در حال استخراج گزارش...")
        
    try:
        # فیلتر پایه برای تمام فاکتورهای نهایی شده در این بازه زمانی
        base_query = session.query(Invoice).filter(
            Invoice.status == InvoiceStatus.final,
            Invoice.created_at >= start_date,
            Invoice.created_at <= end_date
        )
        invoices = base_query.all()
        
        reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به گزارش‌ها", callback_data="report_main")]])
        
        if report_type == "revenue":
            # آماده‌سازی دیتاست روزانه حتی اگر فروش ۰ باشد
            daily_rev = {}
            curr = start_date
            while curr <= end_date:
                daily_rev[curr.date()] = 0
                curr += timedelta(days=1)
                
            for inv in invoices:
                daily_rev[inv.created_at.date()] += inv.total_amount
                
            sorted_dates = sorted(daily_rev.keys())
            x_labels = [d.strftime("%m-%d") for d in sorted_dates]
            y_values = [daily_rev[d] for d in sorted_dates]
            
            total_rev = sum(y_values)
            text = f"💰 **گزارش درآمد** ({tf_label})\n\n"
            text += f"🗓 از `{start_date.strftime('%Y-%m-%d')}` تا `{end_date.strftime('%Y-%m-%d')}`\n"
            text += f"مجموع درآمد: `{total_rev:,.0f}` تومان\n"
            
            # مقایسه ماهانه
            if tf_label == "این ماه":
                last_month_end = start_date - timedelta(seconds=1)
                last_month_start = last_month_end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                
                prev_invoices = session.query(Invoice).filter(
                    Invoice.status == InvoiceStatus.final,
                    Invoice.created_at >= last_month_start,
                    Invoice.created_at <= last_month_end
                ).all()
                prev_rev = sum(i.total_amount for i in prev_invoices)
                
                text += f"درآمد ماه قبل: `{prev_rev:,.0f}` تومان\n"
                if prev_rev > 0:
                    growth = ((total_rev - prev_rev) / prev_rev) * 100
                    emoji = "🟢" if growth >= 0 else "🔴"
                    text += f"رشد/افت نسبت به ماه قبل: %`{abs(growth):.1f}` {emoji}\n"
                else:
                    text += "رشد/افت: (بدون سابقه فروش در ماه قبل) ⚪️\n"
            
            # تولید عکس نمودار
            chart_buf = create_chart(x_labels, y_values, f"روند درآمد - {tf_label}", "تاریخ", "مبلغ (تومان)")
            
            await status_msg.delete()
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=chart_buf,
                caption=text,
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
            
        elif report_type in ["top_products", "worst_products"]:
            # گزارش محصولات از روی جدول InvoiceItem
            items_query = session.query(
                InvoiceItem.product_name,
                func.sum(InvoiceItem.quantity).label('total_qty')
            ).join(Invoice).filter(
                Invoice.status == InvoiceStatus.final,
                Invoice.created_at >= start_date,
                Invoice.created_at <= end_date
            ).group_by(InvoiceItem.product_name).all()
            
            items_list = [(i[0], i[1]) for i in items_query]
            
            if report_type == "top_products":
                items_list.sort(key=lambda x: x[1], reverse=True)
                title = "📈 پرفروش‌ترین محصولات"
            else:
                items_list.sort(key=lambda x: x[1])
                title = "📉 کم‌فروش‌ترین محصولات"
                
            items_list = items_list[:10] # فقط ۱۰ محصول اول
            text = f"{title} ({tf_label})\n\n"
            text += f"🗓 از `{start_date.strftime('%Y-%m-%d')}` تا `{end_date.strftime('%Y-%m-%d')}`\n\n"
            
            for idx, (name, qty) in enumerate(items_list, 1):
                text += f"{idx}. {name} - `{qty}` عدد\n"
            
            if not items_list:
                text += "❌ هیچ داده‌ای در این بازه یافت نشد."
                
            await status_msg.edit_text(text, parse_mode='Markdown', reply_markup=reply_markup)
            
        elif report_type == "discounts":
            tot = sum(i.discount_value for i in invoices)
            text = (
                f"🎁 **گزارش تخفیف‌های اعطاشده** ({tf_label})\n\n"
                f"🗓 از `{start_date.strftime('%Y-%m-%d')}` تا `{end_date.strftime('%Y-%m-%d')}`\n\n"
                f"مجموع مبلغ تخفیف‌ها:\n`{tot:,.0f}` تومان"
            )
            await status_msg.edit_text(text, parse_mode='Markdown', reply_markup=reply_markup)
            
        elif report_type == "shipping":
            tot = sum(i.shipping_cost for i in invoices)
            text = (
                f"🚚 **گزارش هزینه‌های ارسال** ({tf_label})\n\n"
                f"🗓 از `{start_date.strftime('%Y-%m-%d')}` تا `{end_date.strftime('%Y-%m-%d')}`\n\n"
                f"مجموع هزینه‌های پست/پیک:\n`{tot:,.0f}` تومان"
            )
            await status_msg.edit_text(text, parse_mode='Markdown', reply_markup=reply_markup)
            
    finally:
        session.close()

def register_reports_handlers(application: Application):
    """
    ثبت تمام هندلرهای فاز ۳ در ربات تلگرام.
    این تابع باید درون main.py صدا زده شود.
    """
    # هندلرهای ساده و بدون استیت برای گزارش‌های استاندارد
    application.add_handler(CallbackQueryHandler(report_main_menu, pattern="^report_main$"))
    application.add_handler(CallbackQueryHandler(select_timeframe, pattern="^report_tf_.*"))
    application.add_handler(CallbackQueryHandler(generate_report_callback, pattern="^report_do_.*"))
    
    # هندلر State-based برای گرفتن تاریخ‌های دلخواه
    date_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(ask_custom_date, pattern="^report_custom_.*")],
        states={
            WAITING_FOR_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_custom_date)]
        },
        fallbacks=[CallbackQueryHandler(report_main_menu, pattern="^report_main$")],
        map_to_parent={ConversationHandler.END: ConversationHandler.END}
    )
    application.add_handler(date_conv_handler)