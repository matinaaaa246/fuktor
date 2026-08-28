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

import config
from database.db import get_session
from database.models import Product, Invoice

# وضعیت‌های ConversationHandler برای فاز ۵ (بازه ۵۰۰ تا ۵۹۹)
PRODUCT_ADD_NAME = 500
PRODUCT_ADD_PRICE = 501
PRODUCT_ADD_STOCK = 502
PRODUCT_EDIT_VALUE = 503

# ==========================================
# توابع کمکی (قابل استفاده در سایر فازها)
# ==========================================

def get_product_list():
    """
    لیست محصولات را برای استفاده در فاز ۱ (ثبت فاکتور) برمی‌گرداند.
    ساختار خروجی اجازه override کردن قیمت را در invoice_items می‌دهد.
    """
    session = get_session()
    try:
        products = session.query(Product).order_by(Product.name).all()
        return [{"id": p.id, "name": p.name, "unit_price": p.unit_price, "stock": p.stock_qty} for p in products]
    finally:
        session.close()

async def deduct_stock(invoice_id: int, context: ContextTypes.DEFAULT_TYPE):
    """
    کسر موجودی و ارسال هشدار در صورت کمبود موجودی.
    این تابع باید هنگام نهایی شدن فاکتور در فاز ۱ صدا زده شود.
    """
    session = get_session()
    try:
        invoice = session.query(Invoice).filter(Invoice.id == invoice_id).first()
        if not invoice:
            return

        for item in invoice.items:
            # جستجو بر اساس نام محصول (چون در invoice_items آیدی محصول ذخیره نمی‌شود)
            product = session.query(Product).filter(Product.name == item.product_name).first()
            if product:
                product.stock_qty -= item.quantity
                
                # بررسی هشدار موجودی کم
                if product.stock_qty <= product.low_stock_threshold:
                    alert_msg = (
                        f"⚠️ **هشدار سیستم انبار** ⚠️\n"
                        f"موجودی محصول `{product.name}` رو به اتمام است!\n"
                        f"موجودی فعلی: `{product.stock_qty}` عدد"
                    )
                    await context.bot.send_message(
                        chat_id=config.ADMIN_ID, 
                        text=alert_msg, 
                        parse_mode='Markdown'
                    )
        session.commit()
    finally:
        session.close()

# ==========================================
# هندلرهای تلگرامی (مدیریت محصولات)
# ==========================================

async def product_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """منوی اصلی بخش محصولات و انبار"""
    keyboard = [
        [InlineKeyboardButton("📦 لیست محصولات", callback_data="product_list_1")],
        [InlineKeyboardButton("➕ افزودن محصول جدید", callback_data="product_add_init")],
        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "📦 **مدیریت محصولات و انبار**\nلطفاً یک گزینه را انتخاب کنید:"
    
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    
    return ConversationHandler.END

async def list_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش صفحه‌بندی‌شده محصولات"""
    query = update.callback_query
    await query.answer()
    
    page = 1
    match = re.match(r"product_list_(\d+)", query.data)
    if match:
        page = int(match.group(1))
        
    per_page = 10
    offset = (page - 1) * per_page
    
    session = get_session()
    try:
        total_products = session.query(Product).count()
        products = session.query(Product).order_by(Product.created_at.desc()).offset(offset).limit(per_page).all()
        
        keyboard = []
        for prod in products:
            status = "🟢" if prod.stock_qty > prod.low_stock_threshold else "🔴"
            btn_text = f"{status} {prod.name} | {prod.stock_qty} عدد"
            keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"product_view_{prod.id}")])
            
        nav_buttons = []
        if page > 1:
            nav_buttons.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"product_list_{page-1}"))
        if offset + per_page < total_products:
            nav_buttons.append(InlineKeyboardButton("بعدی ➡️", callback_data=f"product_list_{page+1}"))
            
        if nav_buttons:
            keyboard.append(nav_buttons)
            
        keyboard.append([InlineKeyboardButton("🔙 بازگشت به منو", callback_data="product_menu")])
        
        text = f"📦 **لیست محصولات انبار** (صفحه {page}):\nبرای مدیریت، روی محصول کلیک کنید."
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    finally:
        session.close()

async def view_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش مشخصات یک محصول"""
    query = update.callback_query
    await query.answer()
    
    product_id = int(query.data.split("_")[-1])
    session = get_session()
    
    try:
        prod = session.query(Product).filter(Product.id == product_id).first()
        if not prod:
            await query.edit_message_text("❌ محصول یافت نشد.")
            return

        text = (
            f"📦 **جزئیات محصول**\n"
            f"━━━━━━━━━━━━━━\n"
            f"🏷 نام: `{prod.name}`\n"
            f"💰 قیمت واحد: `{prod.unit_price:,.0f}` تومان\n"
            f"📊 موجودی انبار: `{prod.stock_qty}` عدد\n"
            f"⚠️ مرز هشدار موجودی: `{prod.low_stock_threshold}` عدد\n"
            f"━━━━━━━━━━━━━━\n"
            f"💡 در هنگام صدور فاکتور می‌توانید قیمت پیش‌فرض را به دلخواه تغییر دهید."
        )

        keyboard = [
            [
                InlineKeyboardButton("✏️ نام", callback_data=f"product_edit_name_{prod.id}"),
                InlineKeyboardButton("✏️ قیمت", callback_data=f"product_edit_price_{prod.id}")
            ],
            [
                InlineKeyboardButton("✏️ موجودی", callback_data=f"product_edit_stock_{prod.id}"),
                InlineKeyboardButton("✏️ مرز هشدار", callback_data=f"product_edit_threshold_{prod.id}")
            ],
            [InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="product_list_1")]
        ]
        
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    finally:
        session.close()

# --- بخش افزودن محصول (Add Product Flow) ---

async def add_product_init(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [[InlineKeyboardButton("انصراف", callback_data="product_menu")]]
    await query.edit_message_text(
        "🏷 لطفاً **نام محصول** جدید را وارد کنید:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return PRODUCT_ADD_NAME

async def add_product_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_product_name'] = update.message.text.strip()
    keyboard = [[InlineKeyboardButton("انصراف", callback_data="product_menu")]]
    await update.message.reply_text(
        "💰 لطفاً **قیمت واحد** (به تومان) را به صورت عدد وارد کنید:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return PRODUCT_ADD_PRICE

async def add_product_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    price_str = update.message.text.replace(",", "").strip()
    if not price_str.isdigit():
        await update.message.reply_text("❌ لطفاً فقط عدد وارد کنید.")
        return PRODUCT_ADD_PRICE
        
    context.user_data['new_product_price'] = float(price_str)
    keyboard = [[InlineKeyboardButton("انصراف", callback_data="product_menu")]]
    await update.message.reply_text(
        "📊 لطفاً **موجودی اولیه** محصول در انبار را وارد کنید:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return PRODUCT_ADD_STOCK

async def add_product_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stock_str = update.message.text.strip()
    if not stock_str.isdigit():
        await update.message.reply_text("❌ لطفاً یک عدد صحیح وارد کنید.")
        return PRODUCT_ADD_STOCK
        
    stock = int(stock_str)
    name = context.user_data.get('new_product_name')
    price = context.user_data.get('new_product_price')
    
    session = get_session()
    try:
        new_prod = Product(name=name, unit_price=price, stock_qty=stock)
        session.add(new_prod)
        session.commit()
        
        keyboard = [[InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="product_list_1")]]
        await update.message.reply_text(
            f"✅ محصول `{name}` با موفقیت به سیستم اضافه شد.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    finally:
        session.close()
        
    # پاکسازی دیتای موقت
    context.user_data.pop('new_product_name', None)
    context.user_data.pop('new_product_price', None)
    return ConversationHandler.END

# --- بخش ویرایش محصول (Edit Product Flow) ---

async def edit_product_init(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    parts = query.data.split("_")
    field = parts[2]
    product_id = int(parts[3])
    
    context.user_data['edit_product_id'] = product_id
    context.user_data['edit_product_field'] = field
    
    field_fa = {
        "name": "نام جدید",
        "price": "قیمت جدید (تومان)",
        "stock": "موجودی جدید انبار",
        "threshold": "مرز هشدار جدید"
    }.get(field, "مقدار جدید")
    
    keyboard = [[InlineKeyboardButton("انصراف", callback_data=f"product_view_{product_id}")]]
    await query.edit_message_text(
        f"✏️ لطفاً {field_fa} را وارد کنید:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return PRODUCT_EDIT_VALUE

async def edit_product_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val_str = update.message.text.replace(",", "").strip()
    product_id = context.user_data.get('edit_product_id')
    field = context.user_data.get('edit_product_field')
    
    session = get_session()
    try:
        prod = session.query(Product).filter(Product.id == product_id).first()
        if not prod:
            await update.message.reply_text("❌ محصول یافت نشد.")
            return ConversationHandler.END
            
        if field == "name":
            prod.name = val_str
        elif field == "price":
            if not val_str.isdigit():
                await update.message.reply_text("❌ لطفاً عدد وارد کنید.")
                return PRODUCT_EDIT_VALUE
            prod.unit_price = float(val_str)
        elif field in ["stock", "threshold"]:
            if not val_str.isdigit():
                await update.message.reply_text("❌ لطفاً عدد صحیح وارد کنید.")
                return PRODUCT_EDIT_VALUE
            if field == "stock":
                prod.stock_qty = int(val_str)
            else:
                prod.low_stock_threshold = int(val_str)
                
        session.commit()
        
        keyboard = [[InlineKeyboardButton("🔙 بازگشت به محصول", callback_data=f"product_view_{product_id}")]]
        await update.message.reply_text("✅ تغییرات با موفقیت ذخیره شد.", reply_markup=InlineKeyboardMarkup(keyboard))
    finally:
        session.close()
        
    return ConversationHandler.END

# ==========================================
# تابع ثبت هندلرها (صدا زده شده در main.py)
# ==========================================

def register_product_handlers(application: Application):
    # منوی اصلی
    application.add_handler(CallbackQueryHandler(product_main_menu, pattern="^product_menu$"))
    
    # لیست و نمایش مشخصات
    application.add_handler(CallbackQueryHandler(list_products, pattern="^product_list_"))
    application.add_handler(CallbackQueryHandler(view_product, pattern="^product_view_"))
    
    # Conversation برای افزودن محصول
    add_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_product_init, pattern="^product_add_init$")],
        states={
            PRODUCT_ADD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_product_name)],
            PRODUCT_ADD_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_product_price)],
            PRODUCT_ADD_STOCK: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_product_stock)],
        },
        fallbacks=[CallbackQueryHandler(product_main_menu, pattern="^product_menu$")],
        map_to_parent={ConversationHandler.END: ConversationHandler.END}
    )
    application.add_handler(add_conv)
    
    # Conversation برای ویرایش مشخصات محصول
    edit_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_product_init, pattern="^product_edit_")],
        states={
            PRODUCT_EDIT_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_product_save)]
        },
        fallbacks=[CallbackQueryHandler(view_product, pattern="^product_view_")], # انصراف برمیگرده به ویوی محصول
        map_to_parent={ConversationHandler.END: ConversationHandler.END}
    )
    application.add_handler(edit_conv)