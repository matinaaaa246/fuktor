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
from sqlalchemy import or_, func, desc

from database.db import get_session
from database.models import Customer, Invoice, InvoiceStatus

# بازه Stateهای تعیین شده برای فاز ۴ (مدیریت مشتریان)
CRM_SEARCH = 400
CRM_EDIT_NOTE = 401
CRM_TOP_N = 402

async def crm_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """منوی اصلی بخش مدیریت مشتریان (CRM)"""
    keyboard = [
        [InlineKeyboardButton("👥 لیست تمام مشتریان", callback_data="crm_list_1")],
        [InlineKeyboardButton("🔍 جستجوی مشتری", callback_data="crm_search_init")],
        [InlineKeyboardButton("🏆 برترین مشتریان", callback_data="crm_top_init")],
        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "👥 **مدیریت مشتریان (CRM)**\nلطفاً یک گزینه را انتخاب کنید:"
    
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    
    return ConversationHandler.END


async def list_customers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش لیست مشتریان به صورت صفحه‌بندی‌شده"""
    query = update.callback_query
    await query.answer()
    
    page = 1
    match = re.match(r"crm_list_(\d+)", query.data)
    if match:
        page = int(match.group(1))
        
    per_page = 10
    offset = (page - 1) * per_page
    
    session = get_session()
    try:
        total_customers = session.query(Customer).count()
        customers = session.query(Customer).order_by(Customer.created_at.desc()).offset(offset).limit(per_page).all()
        
        keyboard = []
        for cus in customers:
            btn_text = f"👤 {cus.full_name} | {cus.phone}"
            keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"crm_profile_{cus.id}")])
            
        nav_buttons = []
        if page > 1:
            nav_buttons.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"crm_list_{page-1}"))
        if offset + per_page < total_customers:
            nav_buttons.append(InlineKeyboardButton("بعدی ➡️", callback_data=f"crm_list_{page+1}"))
            
        if nav_buttons:
            keyboard.append(nav_buttons)
            
        keyboard.append([InlineKeyboardButton("🔙 بازگشت به منو", callback_data="crm_menu")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        text = f"👥 **لیست مشتریان** (صفحه {page}):\nبرای مشاهده پروفایل روی نام کلیک کنید."
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    finally:
        session.close()


async def search_init(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت عبارت جستجو از کاربر"""
    query = update.callback_query
    await query.answer()
    keyboard = [[InlineKeyboardButton("انصراف", callback_data="crm_menu")]]
    await query.edit_message_text(
        "🔍 لطفاً نام یا شماره تماس مشتری را وارد کنید:", 
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CRM_SEARCH


async def search_perform(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """جستجوی مشتری بر اساس نام یا شماره تلفن"""
    search_text = update.message.text.strip()
    session = get_session()
    
    try:
        customers = session.query(Customer).filter(
            or_(
                Customer.full_name.ilike(f"%{search_text}%"),
                Customer.phone.ilike(f"%{search_text}%")
            )
        ).limit(10).all()
        
        keyboard = []
        for cus in customers:
            btn_text = f"👤 {cus.full_name} | {cus.phone}"
            keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"crm_profile_{cus.id}")])
            
        keyboard.append([InlineKeyboardButton("🔙 جستجوی مجدد", callback_data="crm_search_init")])
        keyboard.append([InlineKeyboardButton("🏠 منوی مشتریان", callback_data="crm_menu")])
        
        if customers:
            text = f"🔍 نتایج یافت‌شده برای `{search_text}`:"
        else:
            text = f"❌ هیچ مشتری با عبارت `{search_text}` یافت نشد."
            
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    finally:
        session.close()
    
    return ConversationHandler.END


async def customer_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش پروفایل کامل یک مشتری به همراه آمار خریدها"""
    query = update.callback_query
    await query.answer()
    
    customer_id = int(query.data.split("_")[-1])
    session = get_session()
    
    try:
        cus = session.query(Customer).filter(Customer.id == customer_id).first()
        if not cus:
            await query.edit_message_text("❌ مشتری یافت نشد.")
            return

        # محاسبات آماری مشتری
        final_invoices = [inv for inv in cus.invoices if inv.status == InvoiceStatus.final]
        total_purchases_amount = sum(inv.total_amount for inv in final_invoices)
        total_invoices_count = len(final_invoices)
        
        if final_invoices:
            last_purchase_date = max(inv.created_at for inv in final_invoices).strftime('%Y-%m-%d %H:%M')
        else:
            last_purchase_date = "خریدی ثبت نشده"

        notes = cus.notes if cus.notes else "یادداشتی ثبت نشده است."

        text = f"👤 **پروفایل مشتری**\n"
        text += f"━━━━━━━━━━━━━━\n"
        text += f"نام: `{cus.full_name}`\n"
        text += f"شماره تماس: `{cus.phone}`\n"
        text += f"تاریخ عضویت: `{cus.created_at.strftime('%Y-%m-%d')}`\n"
        text += f"━━━━━━━━━━━━━━\n"
        text += f"🛍 تعداد خریدهای موفق: `{total_invoices_count}` فاکتور\n"
        text += f"💰 جمع کل خریدها: `{total_purchases_amount:,.0f}` تومان\n"
        text += f"🗓 آخرین خرید: `{last_purchase_date}`\n"
        text += f"━━━━━━━━━━━━━━\n"
        text += f"📝 **یادداشت:**\n{notes}"

        keyboard = [
            [InlineKeyboardButton("🧾 تاریخچه فاکتورها", callback_data=f"crm_invs_{cus.id}_1")],
            [InlineKeyboardButton("✏️ ویرایش یادداشت", callback_data=f"crm_note_{cus.id}")],
            [InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="crm_list_1")]
        ]
        
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    finally:
        session.close()


async def customer_invoices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش لیست فاکتورهای مربوط به یک مشتری خاص"""
    query = update.callback_query
    await query.answer()
    
    parts = query.data.split("_")
    customer_id = int(parts[2])
    page = int(parts[3])
    per_page = 5
    offset = (page - 1) * per_page
    
    session = get_session()
    try:
        total_invs = session.query(Invoice).filter(Invoice.customer_id == customer_id).count()
        invoices = session.query(Invoice).filter(Invoice.customer_id == customer_id)\
                          .order_by(Invoice.created_at.desc()).offset(offset).limit(per_page).all()
        
        keyboard = []
        for inv in invoices:
            # از پیشوندهای فاز ۲ برای نمایش فاکتور استفاده می‌کنیم تا تداخل نداشته باشد
            status_emoji = "✅" if inv.status == InvoiceStatus.final else "📝" if inv.status == InvoiceStatus.draft else "❌"
            btn_text = f"{status_emoji} {inv.invoice_number} | {inv.total_amount:,.0f} تومان"
            keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"inv_mgmt_view_{inv.id}")])
            
        nav_buttons = []
        if page > 1:
            nav_buttons.append(InlineKeyboardButton("⬅️", callback_data=f"crm_invs_{customer_id}_{page-1}"))
        if offset + per_page < total_invs:
            nav_buttons.append(InlineKeyboardButton("➡️", callback_data=f"crm_invs_{customer_id}_{page+1}"))
            
        if nav_buttons:
            keyboard.append(nav_buttons)
            
        keyboard.append([InlineKeyboardButton("🔙 بازگشت به پروفایل", callback_data=f"crm_profile_{customer_id}")])
        
        text = f"🧾 **تاریخچه فاکتورهای مشتری** (صفحه {page}):"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    finally:
        session.close()


async def edit_note_init(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """درخواست یادداشت جدید از کاربر"""
    query = update.callback_query
    await query.answer()
    customer_id = int(query.data.split("_")[-1])
    context.user_data['crm_target_customer'] = customer_id
    
    keyboard = [[InlineKeyboardButton("انصراف", callback_data=f"crm_profile_{customer_id}")]]
    await query.edit_message_text(
        "✏️ لطفاً یادداشت جدید (آدرس، ترجیحات خرید و ...) را برای این مشتری وارد کنید:", 
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CRM_EDIT_NOTE


async def edit_note_perform(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ذخیره یادداشت جدید برای مشتری در دیتابیس"""
    new_note = update.message.text
    customer_id = context.user_data.get('crm_target_customer')
    
    session = get_session()
    try:
        cus = session.query(Customer).filter(Customer.id == customer_id).first()
        if cus:
            cus.notes = new_note
            session.commit()
            
        keyboard = [[InlineKeyboardButton("🔙 مشاهده پروفایل", callback_data=f"crm_profile_{customer_id}")]]
        await update.message.reply_text("✅ یادداشت با موفقیت ذخیره شد.", reply_markup=InlineKeyboardMarkup(keyboard))
    finally:
        session.close()
        
    return ConversationHandler.END


async def top_customers_init(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت تعداد N برای رتبه‌بندی مشتریان"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("۵ نفر برتر", callback_data="crm_top_calc_5"), 
         InlineKeyboardButton("۱۰ نفر برتر", callback_data="crm_top_calc_10")],
        [InlineKeyboardButton("انصراف", callback_data="crm_menu")]
    ]
    await query.edit_message_text(
        "🏆 برای مشاهده برترین مشتریان بر اساس مجموع خرید، یکی از گزینه‌ها را انتخاب کنید\nیا تعداد دلخواه خود را تایپ کنید (مثلاً 20):", 
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CRM_TOP_N


async def top_customers_perform(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """محاسبه و نمایش لیست برترین مشتریان بر اساس مبلغ خرید"""
    session = get_session()
    
    try:
        # تشخیص اینکه ورودی از طریق دکمه بوده یا تایپ مستقیم
        if update.callback_query:
            await update.callback_query.answer()
            top_n = int(update.callback_query.data.split("_")[-1])
            message_obj = update.callback_query.message
        else:
            try:
                top_n = int(update.message.text.strip())
                message_obj = update.message
            except ValueError:
                await update.message.reply_text("❌ لطفاً یک عدد معتبر وارد کنید.")
                return CRM_TOP_N

        # استخراج رتبه‌بندی با استفاده از Group By و مجموع فاکتورهای نهایی
        top_customers = session.query(
            Customer,
            func.sum(Invoice.total_amount).label('total_spent')
        ).join(Invoice).filter(
            Invoice.status == InvoiceStatus.final
        ).group_by(Customer.id).order_by(desc('total_spent')).limit(top_n).all()
        
        text = f"🏆 **لیست {top_n} مشتری برتر (براساس مبلغ خرید):**\n\n"
        
        if not top_customers:
            text += "داده‌ای برای نمایش وجود ندارد."
        else:
            for idx, (cus, total_spent) in enumerate(top_customers, 1):
                text += f"{idx}. {cus.full_name} | `{total_spent:,.0f}` تومان\n"
                
        keyboard = [[InlineKeyboardButton("🔙 بازگشت به منو", callback_data="crm_menu")]]
        
        if update.callback_query:
            await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        else:
            await message_obj.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
            
    finally:
        session.close()
        
    return ConversationHandler.END


def register_crm_handlers(application: Application):
    """
    ثبت تمام هندلرهای فاز ۴ (مدیریت مشتریان) در سیستم مرکزی.
    """
    # فراخوانی منوی اصلی CRM
    application.add_handler(CallbackQueryHandler(crm_main_menu, pattern="^crm_menu$"))
    
    # هندلرهای ساده (بدون state)
    application.add_handler(CallbackQueryHandler(list_customers, pattern="^crm_list_"))
    application.add_handler(CallbackQueryHandler(customer_profile, pattern="^crm_profile_"))
    application.add_handler(CallbackQueryHandler(customer_invoices, pattern="^crm_invs_"))

    # هندلر جستجوی مشتری
    search_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(search_init, pattern="^crm_search_init$")],
        states={
            CRM_SEARCH: [MessageHandler(filters.TEXT & ~filters.COMMAND, search_perform)]
        },
        fallbacks=[CallbackQueryHandler(crm_main_menu, pattern="^crm_menu$")],
        map_to_parent={ConversationHandler.END: ConversationHandler.END}
    )
    application.add_handler(search_conv)

    # هندلر ویرایش یادداشت
    note_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_note_init, pattern="^crm_note_")],
        states={
            CRM_EDIT_NOTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_note_perform)]
        },
        fallbacks=[CallbackQueryHandler(crm_main_menu, pattern="^crm_menu$")],
        map_to_parent={ConversationHandler.END: ConversationHandler.END}
    )
    application.add_handler(note_conv)

    # هندلر رتبه‌بندی مشتریان برتر
    top_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(top_customers_init, pattern="^crm_top_init$")],
        states={
            CRM_TOP_N: [
                CallbackQueryHandler(top_customers_perform, pattern="^crm_top_calc_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, top_customers_perform)
            ]
        },
        fallbacks=[CallbackQueryHandler(crm_main_menu, pattern="^crm_menu$")],
        map_to_parent={ConversationHandler.END: ConversationHandler.END}
    )
    application.add_handler(top_conv)