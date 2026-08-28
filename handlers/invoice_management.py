import os
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters
)
from sqlalchemy import or_, String

from database.db import get_session
from database.models import Invoice, InvoiceStatus, PaymentStatus, Payment, Customer
from utils.invoice_file import generate_invoice_pdf

# وضعیت‌های ConversationHandler برای فاز ۲ (بازه ۲۰۰ تا ۲۹۹)
SEARCH_QUERY = 200
PARTIAL_PAYMENT_AMOUNT = 201
EDIT_SHIPPING_COST = 202
EDIT_DISCOUNT_VAL = 203

async def invoice_mgmt_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📋 لیست فاکتورهای اخیر", callback_data="inv_mgmt_list_1")],
        [InlineKeyboardButton("🔍 جستجوی فاکتور", callback_data="inv_mgmt_search_init")],
        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "📋 **مدیریت فاکتورها**\nلطفاً یک گزینه را انتخاب کنید:"
    
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    return ConversationHandler.END

async def list_invoices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    page = 1
    match = re.match(r"inv_mgmt_list_(\d+)", query.data)
    if match:
        page = int(match.group(1))
        
    per_page = 10
    offset = (page - 1) * per_page
    
    session = get_session()
    total_invoices = session.query(Invoice).count()
    invoices = session.query(Invoice).order_by(Invoice.created_at.desc()).offset(offset).limit(per_page).all()
    
    keyboard = []
    for inv in invoices:
        status_emoji = "✅" if inv.status == InvoiceStatus.final else "📝" if inv.status == InvoiceStatus.draft else "❌"
        btn_text = f"{status_emoji} {inv.invoice_number} | {inv.customer.full_name}"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"inv_mgmt_view_{inv.id}")])
        
    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton("⬅️ صفحه قبل", callback_data=f"inv_mgmt_list_{page-1}"))
    if offset + per_page < total_invoices:
        nav_buttons.append(InlineKeyboardButton("صفحه بعد ➡️", callback_data=f"inv_mgmt_list_{page+1}"))
        
    if nav_buttons:
        keyboard.append(nav_buttons)
        
    keyboard.append([InlineKeyboardButton("🔙 بازگشت به منو", callback_data="inv_mgmt_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = f"📋 **لیست فاکتورها** (صفحه {page}):\nبرای مشاهده جزئیات، روی فاکتور مورد نظر کلیک کنید."
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    session.close()

async def search_init(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [[InlineKeyboardButton("انصراف", callback_data="inv_mgmt_menu")]]
    await query.edit_message_text(
        "🔍 لطفاً عبارت جستجو را وارد کنید:\n(شماره فاکتور، نام مشتری یا تاریخ مثل 2026-08)", 
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return SEARCH_QUERY

async def search_perform(update: Update, context: ContextTypes.DEFAULT_TYPE):
    search_text = update.message.text
    session = get_session()
    
    invoices = session.query(Invoice).join(Invoice.customer).filter(
        or_(
            Invoice.invoice_number.ilike(f"%{search_text}%"),
            Customer.full_name.ilike(f"%{search_text}%"),
            Invoice.created_at.cast(String).ilike(f"%{search_text}%")
        )
    ).limit(10).all()
    
    keyboard = []
    for inv in invoices:
        btn_text = f"{inv.invoice_number} | {inv.customer.full_name}"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"inv_mgmt_view_{inv.id}")])
        
    keyboard.append([InlineKeyboardButton("🔙 بازگشت به جستجو", callback_data="inv_mgmt_search_init")])
    keyboard.append([InlineKeyboardButton("🏠 منوی مدیریت", callback_data="inv_mgmt_menu")])
    
    text = f"نتایج جستجو برای '{search_text}':" if invoices else f"هیچ فاکتوری برای '{search_text}' یافت نشد."
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    session.close()
    return ConversationHandler.END

async def view_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    invoice_id = int(query.data.split("_")[-1])
    session = get_session()
    inv = session.query(Invoice).filter(Invoice.id == invoice_id).first()
    
    if not inv:
        await query.edit_message_text("❌ فاکتور یافت نشد.")
        session.close()
        return
        
    paid_amount = sum(p.amount for p in inv.payments)
    remaining = inv.total_amount - paid_amount
    
    status_map = {
        InvoiceStatus.draft: "پیشنویس 📝",
        InvoiceStatus.final: "نهایی شده ✅",
        InvoiceStatus.cancelled: "باطل شده ❌"
    }
    pay_map = {
        PaymentStatus.paid: "پرداخت کامل 🟢",
        PaymentStatus.partial: "پرداخت جزئی 🟡",
        PaymentStatus.unpaid: "پرداخت نشده 🔴"
    }
    
    text = f"🧾 **فاکتور:** `{inv.invoice_number}`\n"
    text += f"👤 **مشتری:** {inv.customer.full_name}\n"
    text += f"📅 **تاریخ:** {inv.created_at.strftime('%Y-%m-%d %H:%M')}\n"
    text += f"📌 **وضعیت فاکتور:** {status_map.get(inv.status, inv.status.value)}\n"
    text += f"💳 **وضعیت پرداخت:** {pay_map.get(inv.payment_status, inv.payment_status.value)}\n\n"
    
    text += f"جمع اقلام: `{inv.subtotal:,.0f}` تومان\n"
    if inv.discount_value > 0:
        text += f"تخفیف: `{inv.discount_value:,.0f}` تومان\n"
    if inv.shipping_cost > 0:
        text += f"هزینه ارسال: `{inv.shipping_cost:,.0f}` تومان\n"
        
    text += f"**مبلغ نهایی:** `{inv.total_amount:,.0f}` تومان\n"
    text += f"پرداخت شده: `{paid_amount:,.0f}` تومان\n"
    text += f"**باقی‌مانده:** `{remaining:,.0f}` تومان"
    
    keyboard = [
        [InlineKeyboardButton("📄 تولید فایل PDF فاکتور", callback_data=f"inv_mgmt_pdf_{inv.id}")]
    ]
    
    if inv.status == InvoiceStatus.draft:
        # امکانات ویرایش برای فاکتورهای پیش‌نویس
        keyboard.append([
            InlineKeyboardButton("✏️ ویرایش هزینه ارسال", callback_data=f"inv_mgmt_editship_{inv.id}"),
            InlineKeyboardButton("✏️ ویرایش تخفیف", callback_data=f"inv_mgmt_editdisc_{inv.id}")
        ])
        keyboard.append([InlineKeyboardButton("✅ قطعی کردن فاکتور", callback_data=f"inv_mgmt_finalize_{inv.id}")])
        keyboard.append([InlineKeyboardButton("❌ باطل کردن فاکتور", callback_data=f"inv_mgmt_cancel_{inv.id}")])
        
    keyboard.append([InlineKeyboardButton("💳 مدیریت پرداخت", callback_data=f"inv_mgmt_paymenu_{inv.id}")])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="inv_mgmt_list_1")])
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    session.close()

# --- بخش ویرایش فاکتور پیش‌نویس ---
async def edit_shipping_init(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    invoice_id = int(query.data.split("_")[-1])
    context.user_data['edit_invoice_id'] = invoice_id
    keyboard = [[InlineKeyboardButton("انصراف", callback_data=f"inv_mgmt_view_{invoice_id}")]]
    await query.edit_message_text("🚚 لطفاً هزینه ارسال جدید (به تومان) را وارد کنید:", reply_markup=InlineKeyboardMarkup(keyboard))
    return EDIT_SHIPPING_COST

async def edit_shipping_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val_str = update.message.text.replace(",", "").strip()
    if not val_str.isdigit():
        await update.message.reply_text("❌ لطفاً فقط عدد وارد کنید.")
        return EDIT_SHIPPING_COST
    
    invoice_id = context.user_data.get('edit_invoice_id')
    session = get_session()
    inv = session.query(Invoice).filter(Invoice.id == invoice_id).first()
    if inv and inv.status == InvoiceStatus.draft:
        inv.shipping_cost = float(val_str)
        inv.total_amount = inv.subtotal + inv.shipping_cost - inv.discount_value
        session.commit()
    session.close()
    
    keyboard = [[InlineKeyboardButton("🔙 بازگشت به فاکتور", callback_data=f"inv_mgmt_view_{invoice_id}")]]
    await update.message.reply_text("✅ هزینه ارسال فاکتور با موفقیت ویرایش شد.", reply_markup=InlineKeyboardMarkup(keyboard))
    return ConversationHandler.END

async def edit_discount_init(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    invoice_id = int(query.data.split("_")[-1])
    context.user_data['edit_invoice_id'] = invoice_id
    keyboard = [[InlineKeyboardButton("انصراف", callback_data=f"inv_mgmt_view_{invoice_id}")]]
    await query.edit_message_text("🏷 لطفاً مبلغ جدید تخفیف (به تومان) را وارد کنید:", reply_markup=InlineKeyboardMarkup(keyboard))
    return EDIT_DISCOUNT_VAL

async def edit_discount_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val_str = update.message.text.replace(",", "").strip()
    if not val_str.isdigit():
        await update.message.reply_text("❌ لطفاً فقط عدد وارد کنید.")
        return EDIT_DISCOUNT_VAL
    
    invoice_id = context.user_data.get('edit_invoice_id')
    session = get_session()
    inv = session.query(Invoice).filter(Invoice.id == invoice_id).first()
    if inv and inv.status == InvoiceStatus.draft:
        inv.discount_value = float(val_str)
        inv.total_amount = inv.subtotal + inv.shipping_cost - inv.discount_value
        session.commit()
    session.close()
    
    keyboard = [[InlineKeyboardButton("🔙 بازگشت به فاکتور", callback_data=f"inv_mgmt_view_{invoice_id}")]]
    await update.message.reply_text("✅ تخفیف فاکتور با موفقیت ویرایش شد.", reply_markup=InlineKeyboardMarkup(keyboard))
    return ConversationHandler.END

async def finalize_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    invoice_id = int(query.data.split("_")[-1])
    
    session = get_session()
    inv = session.query(Invoice).filter(Invoice.id == invoice_id).first()
    if inv and inv.status == InvoiceStatus.draft:
        inv.status = InvoiceStatus.final
        session.commit()
        text = f"✅ فاکتور `{inv.invoice_number}` با موفقیت قطعی و نهایی شد."
    else:
        text = "❌ امکان نهایی کردن این فاکتور وجود ندارد."
    session.close()
    
    keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data=f"inv_mgmt_view_{invoice_id}")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def cancel_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    invoice_id = int(query.data.split("_")[-1])
    
    session = get_session()
    inv = session.query(Invoice).filter(Invoice.id == invoice_id).first()
    if inv and inv.status == InvoiceStatus.draft:
        inv.status = InvoiceStatus.cancelled
        session.commit()
        text = f"✅ فاکتور `{inv.invoice_number}` با موفقیت باطل شد."
    else:
        text = "❌ امکان ابطال این فاکتور وجود ندارد (ممکن است نهایی شده باشد)."
    session.close()
    
    keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data=f"inv_mgmt_view_{invoice_id}")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

# --- بخش مدیریت پرداخت ---
async def payment_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    invoice_id = int(query.data.split("_")[-1])
    
    keyboard = [
        [InlineKeyboardButton("✅ ثبت پرداخت کامل", callback_data=f"inv_mgmt_setpay_{invoice_id}_paid")],
        [InlineKeyboardButton("⏳ ثبت پرداخت جزئی (مبلغ دلخواه)", callback_data=f"inv_mgmt_partial_{invoice_id}")],
        [InlineKeyboardButton("❌ تغییر به پرداخت نشده", callback_data=f"inv_mgmt_setpay_{invoice_id}_unpaid")],
        [InlineKeyboardButton("🔙 بازگشت به فاکتور", callback_data=f"inv_mgmt_view_{invoice_id}")]
    ]
    await query.edit_message_text("💳 لطفاً وضعیت پرداخت را مشخص کنید:", reply_markup=InlineKeyboardMarkup(keyboard))

async def set_payment_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    invoice_id = int(parts[3])
    status = parts[4]
    
    session = get_session()
    inv = session.query(Invoice).filter(Invoice.id == invoice_id).first()
    if inv:
        if status == 'paid':
            inv.payment_status = PaymentStatus.paid
            paid_amount = sum(p.amount for p in inv.payments)
            if paid_amount < inv.total_amount:
                payment = Payment(invoice_id=inv.id, amount=(inv.total_amount - paid_amount), note="پرداخت کامل سیستم")
                session.add(payment)
        elif status == 'unpaid':
            inv.payment_status = PaymentStatus.unpaid
            for p in inv.payments:
                session.delete(p)
        session.commit()
    session.close()
    
    keyboard = [[InlineKeyboardButton("🔙 بازگشت به فاکتور", callback_data=f"inv_mgmt_view_{invoice_id}")]]
    await query.edit_message_text("✅ وضعیت پرداخت با موفقیت بروزرسانی شد.", reply_markup=InlineKeyboardMarkup(keyboard))

async def start_partial_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    invoice_id = int(query.data.split("_")[-1])
    context.user_data['pay_invoice_id'] = invoice_id
    
    keyboard = [[InlineKeyboardButton("انصراف", callback_data=f"inv_mgmt_view_{invoice_id}")]]
    await query.edit_message_text(
        "⏳ لطفاً مبلغ پرداختی را به صورت عدد (تومان) وارد کنید:", 
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return PARTIAL_PAYMENT_AMOUNT

async def save_partial_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    amount_str = update.message.text.replace(",", "")
    if not amount_str.isdigit():
        await update.message.reply_text("❌ لطفاً فقط عدد وارد کنید.")
        return PARTIAL_PAYMENT_AMOUNT
        
    amount = float(amount_str)
    invoice_id = context.user_data.get('pay_invoice_id')
    
    session = get_session()
    inv = session.query(Invoice).filter(Invoice.id == invoice_id).first()
    if inv:
        payment = Payment(invoice_id=inv.id, amount=amount, note="پرداخت جزئی")
        session.add(payment)
        session.commit() 
        
        paid_amount = sum(p.amount for p in inv.payments)
        if paid_amount >= inv.total_amount:
            inv.payment_status = PaymentStatus.paid
        elif paid_amount > 0:
            inv.payment_status = PaymentStatus.partial
            
        session.commit()
    session.close()
    
    keyboard = [[InlineKeyboardButton("🔙 بازگشت به فاکتور", callback_data=f"inv_mgmt_view_{invoice_id}")]]
    await update.message.reply_text(f"✅ پرداخت جزئی به مبلغ {amount:,.0f} تومان ثبت شد.", reply_markup=InlineKeyboardMarkup(keyboard))
    return ConversationHandler.END

async def generate_pdf_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("در حال تولید فایل PDF، لطفاً صبر کنید...")
    invoice_id = int(query.data.split("_")[-1])
    
    try:
        # بات برای پاس داده شدن به تابع تولید PDF جهت لود لوگو ارسال می‌شود
        filepath = await generate_invoice_pdf(invoice_id, context.bot)
        if filepath and os.path.exists(filepath):
            with open(filepath, 'rb') as f:
                await context.bot.send_document(
                    chat_id=query.message.chat_id, 
                    document=f, 
                    filename=os.path.basename(filepath),
                    caption="📄 فاکتور شما"
                )
        else:
            await query.message.reply_text("❌ خطا در تولید یا یافتن فایل فاکتور.")
    except Exception as e:
        await query.message.reply_text(f"❌ خطای سیستمی: {str(e)}")

def register_invoice_management_handlers(application: Application):
    application.add_handler(CallbackQueryHandler(invoice_mgmt_menu, pattern="^inv_mgmt_menu$"))
    application.add_handler(CallbackQueryHandler(list_invoices, pattern="^inv_mgmt_list_"))
    application.add_handler(CallbackQueryHandler(view_invoice, pattern="^inv_mgmt_view_"))
    application.add_handler(CallbackQueryHandler(cancel_invoice, pattern="^inv_mgmt_cancel_"))
    application.add_handler(CallbackQueryHandler(payment_menu, pattern="^inv_mgmt_paymenu_"))
    application.add_handler(CallbackQueryHandler(set_payment_status, pattern="^inv_mgmt_setpay_"))
    application.add_handler(CallbackQueryHandler(generate_pdf_handler, pattern="^inv_mgmt_pdf_"))
    
    # هندلر قطعی کردن فاکتور (پیش‌نویس)
    application.add_handler(CallbackQueryHandler(finalize_invoice, pattern="^inv_mgmt_finalize_"))
    
    # هندلر جستجو
    search_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(search_init, pattern="^inv_mgmt_search_init$")],
        states={
            SEARCH_QUERY: [MessageHandler(filters.TEXT & ~filters.COMMAND, search_perform)]
        },
        fallbacks=[CallbackQueryHandler(invoice_mgmt_menu, pattern="^inv_mgmt_menu$")],
        map_to_parent={ConversationHandler.END: ConversationHandler.END}
    )
    application.add_handler(search_conv)
    
    # هندلر ویرایش فاکتور پیش‌نویس (هزینه ارسال و تخفیف)
    edit_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(edit_shipping_init, pattern="^inv_mgmt_editship_"),
            CallbackQueryHandler(edit_discount_init, pattern="^inv_mgmt_editdisc_")
        ],
        states={
            EDIT_SHIPPING_COST: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_shipping_save)],
            EDIT_DISCOUNT_VAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_discount_save)]
        },
        fallbacks=[CallbackQueryHandler(view_invoice, pattern="^inv_mgmt_view_")],
        map_to_parent={ConversationHandler.END: ConversationHandler.END}
    )
    application.add_handler(edit_conv)
    
    # هندلر پرداخت جزئی
    pay_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_partial_payment, pattern="^inv_mgmt_partial_")],
        states={
            PARTIAL_PAYMENT_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_partial_payment)]
        },
        fallbacks=[CallbackQueryHandler(view_invoice, pattern="^inv_mgmt_view_")],
        map_to_parent={ConversationHandler.END: ConversationHandler.END}
    )
    application.add_handler(pay_conv)