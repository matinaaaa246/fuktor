"""
فاز ۱ - فاکتور جدید (یکپارچه‌شده با فاز ۵ - محصولات و انبار):
  - رنج state های ConversationHandler: 100-199
  - پیشوند callback_data: inv_new_
  - پشتیبانی از افزودن محصولات تعریف‌شده یا ورود دستی اقلام
  - کسر خودکار موجودی انبار هنگام نهایی شدن فاکتور
"""

import logging
from datetime import datetime

from sqlalchemy import or_
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from database.db import get_session
from database.models import Customer, DiscountType, Invoice, InvoiceItem, InvoiceStatus, PaymentStatus
from utils.invoice_file import save_invoice_image_file, save_invoice_text_file

# ارتباط با فاز ۵ برای محصولات و انبار
from handlers.product_handlers import get_product_list, deduct_stock

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ثابت‌ها (اجباری طبق قرارداد مشترک پروژه)
# ---------------------------------------------------------------------------
CB = "inv_new_"  # پیشوند callback_data فاز ۱

(
    CUSTOMER_SEARCH,          # 100
    CUSTOMER_REG_NAME,        # 101
    CUSTOMER_REG_PHONE,       # 102
    CUSTOMER_REG_TELEGRAM_ID,  # 103
    CUSTOMER_SELECT,          # 104
    ITEM_NAME,                # 105 - منتظر نام محصول (یا کلیک از لیست)
    ITEM_QTY,                 # 106
    ITEM_PRICE,               # 107 - منتظر قیمت واحد محصول (یا تایید قیمت سیستم)
    ITEM_MORE,                # 108
    SHIPPING_COST,            # 109
    DISCOUNT_TYPE,            # 110
    DISCOUNT_VALUE,           # 111
    PREVIEW_CONFIRM,          # 112
) = range(100, 113)


# ---------------------------------------------------------------------------
# توابع کمکی
# ---------------------------------------------------------------------------

def _reset_invoice_data(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("inv_customer_id", None)
    context.user_data.pop("inv_items", None)
    context.user_data.pop("inv_shipping_cost", None)
    context.user_data.pop("inv_discount_type", None)
    context.user_data.pop("inv_discount_value", None)
    context.user_data.pop("inv_current_item", None)
    context.user_data.pop("reg_flow", None)
    context.user_data.pop("reg_name", None)
    context.user_data.pop("reg_phone", None)


def _generate_invoice_number(session) -> str:
    today_str = datetime.now().strftime("%Y%m%d")
    prefix = f"INV-{today_str}-"
    count_today = (
        session.query(Invoice)
        .filter(Invoice.invoice_number.like(f"{prefix}%"))
        .count()
    )
    return f"{prefix}{count_today + 1:04d}"


def _format_currency(amount: float) -> str:
    return f"{amount:,.0f} تومان"


def _calc_totals(items: list, shipping_cost: float, discount_type: str | None, discount_value: float):
    subtotal = sum(item["line_total"] for item in items)
    total = subtotal + shipping_cost
    if discount_type == DiscountType.amount.value:
        total -= discount_value
    elif discount_type == DiscountType.percent.value:
        total -= subtotal * (discount_value / 100.0)
    total = max(total, 0)
    return subtotal, total


def _build_preview_text(context: ContextTypes.DEFAULT_TYPE, customer: Customer) -> str:
    items = context.user_data.get("inv_items", [])
    shipping_cost = context.user_data.get("inv_shipping_cost", 0)
    discount_type = context.user_data.get("inv_discount_type")
    discount_value = context.user_data.get("inv_discount_value", 0)

    subtotal, total = _calc_totals(items, shipping_cost, discount_type, discount_value)

    lines = [
        "🧾 پیش‌نمایش فاکتور",
        "━━━━━━━━━━━━━━",
        f"👤 مشتری: {customer.full_name}",
        f"📞 تلفن: {customer.phone}",
        "━━━━━━━━━━━━━━",
        "اقلام:",
    ]
    for idx, item in enumerate(items, start=1):
        lines.append(
            f"{idx}. {item['product_name']} × {item['quantity']} = "
            f"{_format_currency(item['line_total'])}"
        )

    lines.append("━━━━━━━━━━━━━━")
    lines.append(f"جمع جزء: {_format_currency(subtotal)}")
    lines.append(f"هزینه ارسال: {_format_currency(shipping_cost)}")

    if discount_type and discount_value:
        label = f"{discount_value}%" if discount_type == DiscountType.percent.value else _format_currency(discount_value)
        lines.append(f"تخفیف: {label}")

    lines.append(f"💰 مبلغ نهایی: {_format_currency(total)}")

    return "\n".join(lines)


def _get_product_keyboard() -> InlineKeyboardMarkup | None:
    """ساخت کیبورد شیشه‌ای برای لیست محصولات (دریافت شده از فاز ۵)"""
    products = get_product_list()
    if not products:
        return None
        
    keyboard = []
    for p in products:
        btn_text = f"📦 {p['name']} | {_format_currency(p['unit_price'])} (موجودی: {p['stock']})"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"{CB}sel_prod_{p['id']}")])
        
    return InlineKeyboardMarkup(keyboard)

# ---------------------------------------------------------------------------
# منوی اصلی و شروع
# ---------------------------------------------------------------------------

async def open_invoice_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("👤 ثبت مشتری جدید", callback_data=f"{CB}reg_customer_start")],
            [InlineKeyboardButton("🧾 شروع فاکتور جدید", callback_data=f"{CB}start_invoice")],
            [InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")],
        ]
    )
    await query.edit_message_text("بخش فاکتور 🧾\nیک گزینه را انتخاب کنید:", reply_markup=keyboard)


# ---------------------------------------------------------------------------
# ثبت مشتری جدید
# ---------------------------------------------------------------------------

async def reg_customer_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if context.user_data.get("reg_flow") != "invoice":
        context.user_data["reg_flow"] = "standalone"

    await query.edit_message_text("👤 ثبت مشتری جدید\n\nلطفاً نام و نام‌خانوادگی مشتری را وارد کنید:")
    return CUSTOMER_REG_NAME


async def receive_customer_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = (update.message.text or "").strip()
    if not name:
        await update.message.reply_text("نام نمی‌تواند خالی باشد. لطفاً دوباره وارد کنید:")
        return CUSTOMER_REG_NAME

    context.user_data["reg_name"] = name
    await update.message.reply_text("📞 لطفاً شماره تلفن مشتری را وارد کنید:")
    return CUSTOMER_REG_PHONE


async def receive_customer_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    phone = (update.message.text or "").strip()
    if not phone or not any(ch.isdigit() for ch in phone):
        await update.message.reply_text("شماره تلفن نامعتبر است. لطفاً دوباره وارد کنید:")
        return CUSTOMER_REG_PHONE

    context.user_data["reg_phone"] = phone

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("رد شدن (ندارد)", callback_data=f"{CB}skip_telegram_id")]]
    )
    await update.message.reply_text("🆔 آیدی تلگرام مشتری را وارد کنید (اختیاری):", reply_markup=keyboard)
    return CUSTOMER_REG_TELEGRAM_ID


async def _finalize_customer_registration(update_or_query, context: ContextTypes.DEFAULT_TYPE, telegram_id: str | None) -> int:
    session = get_session()
    try:
        customer = Customer(
            full_name=context.user_data.get("reg_name"),
            phone=context.user_data.get("reg_phone"),
            telegram_id=telegram_id,
        )
        session.add(customer)
        session.commit()
        session.refresh(customer)
        customer_id = customer.id
        customer_name = customer.full_name
    finally:
        session.close()

    flow = context.user_data.get("reg_flow")

    if flow == "invoice":
        context.user_data["inv_customer_id"] = customer_id
        context.user_data["inv_items"] = []
        context.user_data.pop("reg_flow", None)
        context.user_data.pop("reg_name", None)
        context.user_data.pop("reg_phone", None)

        text = f"✅ مشتری «{customer_name}» با موفقیت ثبت شد.\n\n📦 نام اولین محصول را وارد کنید یا از لیست زیر انتخاب کنید:"
        kb = _get_product_keyboard()
        
        if isinstance(update_or_query, Update) and update_or_query.message:
            await update_or_query.message.reply_text(text, reply_markup=kb)
        else:
            await update_or_query.edit_message_text(text, reply_markup=kb) if kb else await update_or_query.edit_message_text(text)
        return ITEM_NAME

    context.user_data.pop("reg_flow", None)
    context.user_data.pop("reg_name", None)
    context.user_data.pop("reg_phone", None)

    text = f"✅ مشتری «{customer_name}» با موفقیت ثبت شد."
    if isinstance(update_or_query, Update) and update_or_query.message:
        await update_or_query.message.reply_text(text)
    else:
        await update_or_query.edit_message_text(text)
    return ConversationHandler.END


async def receive_customer_telegram_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    telegram_id = (update.message.text or "").strip() or None
    return await _finalize_customer_registration(update, context, telegram_id)


async def skip_customer_telegram_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    return await _finalize_customer_registration(query, context, None)


# ---------------------------------------------------------------------------
# جستجو/انتخاب مشتری برای فاکتور
# ---------------------------------------------------------------------------

async def start_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    _reset_invoice_data(context)
    context.user_data["inv_items"] = []

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("➕ ثبت مشتری جدید", callback_data=f"{CB}reg_customer_start")]]
    )
    await query.edit_message_text(
        "🔍 نام یا شماره تلفن مشتری را برای جستجو وارد کنید:\n(در صورت مشتری جدید، از دکمه زیر استفاده کنید)",
        reply_markup=keyboard,
    )
    context.user_data["reg_flow"] = "invoice"
    return CUSTOMER_SEARCH


async def receive_customer_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query_text = (update.message.text or "").strip()
    if not query_text:
        await update.message.reply_text("لطفاً یک متن برای جستجو وارد کنید:")
        return CUSTOMER_SEARCH

    session = get_session()
    try:
        results = session.query(Customer).filter(
            or_(Customer.full_name.contains(query_text), Customer.phone.contains(query_text))
        ).limit(10).all()
        buttons = [[InlineKeyboardButton(f"{c.full_name} - {c.phone}", callback_data=f"{CB}select_customer_{c.id}")] for c in results]
    finally:
        session.close()

    buttons.append([InlineKeyboardButton("➕ ثبت مشتری جدید", callback_data=f"{CB}reg_customer_start")])

    if not results:
        await update.message.reply_text(
            "❌ مشتری‌ای با این مشخصات پیدا نشد.\nمی‌توانید دوباره جستجو کنید یا مشتری جدید ثبت کنید:",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return CUSTOMER_SEARCH

    await update.message.reply_text("یکی از مشتریان زیر را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(buttons))
    return CUSTOMER_SELECT


async def select_customer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    customer_id = int(query.data.replace(f"{CB}select_customer_", ""))
    context.user_data["inv_customer_id"] = customer_id
    context.user_data.pop("reg_flow", None)

    kb = _get_product_keyboard()
    text = "✅ مشتری انتخاب شد.\n\n📦 نام محصول اول را وارد کنید یا از لیست زیر انتخاب کنید:"
    if kb:
        await query.edit_message_text(text, reply_markup=kb)
    else:
        await query.edit_message_text(text)
    return ITEM_NAME


# ---------------------------------------------------------------------------
# اقلام فاکتور (یکپارچه با فاز ۵)
# ---------------------------------------------------------------------------

async def select_product_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """مدیریت کلیک روی دکمه‌ی یک محصول از لیست"""
    query = update.callback_query
    await query.answer()
    prod_id = int(query.data.replace(f"{CB}sel_prod_", ""))
    
    products = get_product_list()
    prod = next((p for p in products if p['id'] == prod_id), None)
    
    if prod:
        context.user_data["inv_current_item"] = {
            "product_name": prod['name'],
            "default_price": prod['unit_price']
        }
        await query.edit_message_text(f"✅ محصول «{prod['name']}» انتخاب شد.\n\n🔢 تعداد این محصول را وارد کنید:")
    else:
        await query.edit_message_text("❌ محصول یافت نشد. لطفاً نام محصول را دستی وارد کنید:")
        return ITEM_NAME
        
    return ITEM_QTY

async def receive_item_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """دریافت دستی نام محصول خارج از لیست سیستم"""
    name = (update.message.text or "").strip()
    if not name:
        await update.message.reply_text("نام محصول نمی‌تواند خالی باشد. دوباره وارد کنید:")
        return ITEM_NAME

    context.user_data["inv_current_item"] = {"product_name": name}
    await update.message.reply_text("🔢 تعداد این محصول را وارد کنید:")
    return ITEM_QTY


async def receive_item_qty(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (update.message.text or "").strip()
    if not text.isdigit() or int(text) <= 0:
        await update.message.reply_text("تعداد باید یک عدد صحیح مثبت باشد. دوباره وارد کنید:")
        return ITEM_QTY

    context.user_data["inv_current_item"]["quantity"] = int(text)
    
    current_item = context.user_data["inv_current_item"]
    default_price = current_item.get("default_price")
    
    # اگر محصول از دیتابیس انتخاب شده باشد، قیمت پیش‌فرض را برای تایید پیشنهاد می‌دهیم
    if default_price is not None:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"✅ تایید قیمت سیستم ({_format_currency(default_price)})", callback_data=f"{CB}conf_price_{default_price}")]
        ])
        await update.message.reply_text(
            "💵 قیمت واحد این محصول را به تومان تایپ کنید:\n"
            "(یا برای اعمال قیمت پیش‌فرض سیستم، دکمه زیر را بزنید)", 
            reply_markup=kb
        )
    else:
        await update.message.reply_text("💵 قیمت واحد این محصول را به تومان وارد کنید:")
        
    return ITEM_PRICE

async def confirm_price_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """تایید قیمت پیش‌فرض محصول سیستم با دکمه شیشه‌ای"""
    query = update.callback_query
    await query.answer()
    price = float(query.data.replace(f"{CB}conf_price_", ""))
    return await _process_item_price(update, context, price, is_query=True)


async def receive_item_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """تایید قیمت به‌صورت تایپ دستی (امکان override کردن)"""
    text = (update.message.text or "").strip().replace(",", "")
    try:
        price = float(text)
        if price < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("قیمت نامعتبر است. لطفاً یک عدد وارد کنید:")
        return ITEM_PRICE

    return await _process_item_price(update, context, price, is_query=False)


async def _process_item_price(update: Update, context: ContextTypes.DEFAULT_TYPE, price: float, is_query: bool) -> int:
    current_item = context.user_data["inv_current_item"]
    current_item["unit_price"] = price
    current_item["line_total"] = price * current_item["quantity"]

    context.user_data.setdefault("inv_items", []).append(current_item)
    context.user_data.pop("inv_current_item", None)

    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ افزودن محصول دیگر", callback_data=f"{CB}add_more_item")],
            [InlineKeyboardButton("➡️ ادامه (پایان اقلام)", callback_data=f"{CB}finish_items")],
        ]
    )
    
    text = f"✅ «{current_item['product_name']}» به فاکتور اضافه شد.\nآیا محصول دیگری هم دارید؟"
    if is_query:
        await update.callback_query.edit_message_text(text, reply_markup=keyboard)
    else:
        await update.message.reply_text(text, reply_markup=keyboard)
        
    return ITEM_MORE


async def handle_item_more(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == f"{CB}add_more_item":
        kb = _get_product_keyboard()
        text = "📦 نام محصول بعدی را وارد کنید یا از لیست زیر انتخاب کنید:"
        if kb:
            await query.edit_message_text(text, reply_markup=kb)
        else:
            await query.edit_message_text(text)
        return ITEM_NAME

    # finish_items
    await query.edit_message_text("🚚 هزینه ارسال را به تومان وارد کنید (در صورت نبود، عدد 0 را وارد کنید):")
    return SHIPPING_COST


# ---------------------------------------------------------------------------
# هزینه ارسال و تخفیف
# ---------------------------------------------------------------------------

async def receive_shipping_cost(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (update.message.text or "").strip().replace(",", "")
    try:
        shipping_cost = float(text)
        if shipping_cost < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("مقدار نامعتبر است. لطفاً یک عدد (یا 0) وارد کنید:")
        return SHIPPING_COST

    context.user_data["inv_shipping_cost"] = shipping_cost

    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("بدون تخفیف", callback_data=f"{CB}discount_none")],
            [InlineKeyboardButton("مبلغ ثابت", callback_data=f"{CB}discount_amount")],
            [InlineKeyboardButton("درصدی", callback_data=f"{CB}discount_percent")],
        ]
    )
    await update.message.reply_text("🏷 نوع تخفیف را انتخاب کنید:", reply_markup=keyboard)
    return DISCOUNT_TYPE


async def handle_discount_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == f"{CB}discount_none":
        context.user_data["inv_discount_type"] = None
        context.user_data["inv_discount_value"] = 0
        return await _show_preview(query, context)

    if query.data == f"{CB}discount_amount":
        context.user_data["inv_discount_type"] = DiscountType.amount.value
        await query.edit_message_text("💵 مبلغ تخفیف را به تومان وارد کنید:")
    else:
        context.user_data["inv_discount_type"] = DiscountType.percent.value
        await query.edit_message_text("📊 درصد تخفیف را وارد کنید (عدد بین 0 تا 100):")

    return DISCOUNT_VALUE


async def receive_discount_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (update.message.text or "").strip().replace(",", "")
    try:
        value = float(text)
        if value < 0:
            raise ValueError
        if context.user_data.get("inv_discount_type") == DiscountType.percent.value and value > 100:
            raise ValueError
    except ValueError:
        await update.message.reply_text("مقدار نامعتبر است. دوباره وارد کنید:")
        return DISCOUNT_VALUE

    context.user_data["inv_discount_value"] = value
    return await _show_preview(update, context)


# ---------------------------------------------------------------------------
# پیش‌نمایش نهایی و ثبت
# ---------------------------------------------------------------------------

async def _show_preview(update_or_query, context: ContextTypes.DEFAULT_TYPE) -> int:
    session = get_session()
    try:
        customer = session.query(Customer).get(context.user_data.get("inv_customer_id"))
    finally:
        session.close()

    if customer is None:
        text = "❌ مشتری یافت نشد. عملیات لغو شد."
        if isinstance(update_or_query, Update) and update_or_query.message:
            await update_or_query.message.reply_text(text)
        else:
            await update_or_query.edit_message_text(text)
        _reset_invoice_data(context)
        return ConversationHandler.END

    preview_text = _build_preview_text(context, customer)

    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ تایید و ثبت", callback_data=f"{CB}confirm")],
            [InlineKeyboardButton("❌ انصراف", callback_data=f"{CB}cancel")],
        ]
    )

    if isinstance(update_or_query, Update) and update_or_query.message:
        await update_or_query.message.reply_text(preview_text, reply_markup=keyboard)
    else:
        await update_or_query.edit_message_text(preview_text, reply_markup=keyboard)

    return PREVIEW_CONFIRM


async def handle_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    items = context.user_data.get("inv_items", [])
    shipping_cost = context.user_data.get("inv_shipping_cost", 0)
    discount_type = context.user_data.get("inv_discount_type")
    discount_value = context.user_data.get("inv_discount_value", 0)
    customer_id = context.user_data.get("inv_customer_id")

    if not items or not customer_id:
        await query.edit_message_text("❌ اطلاعات فاکتور ناقص است. عملیات لغو شد.")
        _reset_invoice_data(context)
        return ConversationHandler.END

    subtotal, total = _calc_totals(items, shipping_cost, discount_type, discount_value)

    invoice_id = None
    invoice_number = ""
    
    session = get_session()
    try:
        customer = session.query(Customer).get(customer_id)

        invoice = Invoice(
            invoice_number=_generate_invoice_number(session),
            customer_id=customer_id,
            shipping_cost=shipping_cost,
            discount_type=DiscountType(discount_type) if discount_type else None,
            discount_value=discount_value,
            subtotal=subtotal,
            total_amount=total,
            status=InvoiceStatus.final,
            payment_status=PaymentStatus.unpaid,
        )
        session.add(invoice)
        session.flush()

        for item in items:
            session.add(
                InvoiceItem(
                    invoice_id=invoice.id,
                    product_name=item["product_name"],
                    quantity=item["quantity"],
                    unit_price=item["unit_price"],
                    line_total=item["line_total"],
                )
            )

        session.commit()
        session.refresh(invoice)
        
        invoice_id = invoice.id
        invoice_number = invoice.invoice_number

        invoice_items = session.query(InvoiceItem).filter_by(invoice_id=invoice.id).all()
        text_file_path = save_invoice_text_file(invoice, customer, invoice_items)
        image_file_path = save_invoice_image_file(invoice, customer, invoice_items)
    finally:
        session.close()

    # فراخوانی تابع کسر موجودی از فاز ۵ به محض نهایی شدن تراکنش دیتابیس
    if invoice_id:
        await deduct_stock(invoice_id, context)

    await query.edit_message_text(f"✅ فاکتور «{invoice_number}» با موفقیت ثبت شد.")

    with open(image_file_path, "rb") as img_f:
        await query.message.reply_photo(photo=img_f, caption=f"🧾 فاکتور {invoice_number}")

    with open(text_file_path, "rb") as txt_f:
        await query.message.reply_document(document=txt_f, filename=f"{invoice_number}.txt")

    _reset_invoice_data(context)
    return ConversationHandler.END


async def handle_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    await query.edit_message_text("❌ عملیات ثبت فاکتور لغو شد.")
    _reset_invoice_data(context)
    return ConversationHandler.END


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ عملیات لغو شد.")
    _reset_invoice_data(context)
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# ثبت هندلرها
# ---------------------------------------------------------------------------

def register_invoice_handlers(application: Application) -> None:
    conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(reg_customer_start, pattern=f"^{CB}reg_customer_start$"),
            CallbackQueryHandler(start_invoice, pattern=f"^{CB}start_invoice$"),
        ],
        states={
            CUSTOMER_SEARCH: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_customer_search),
                CallbackQueryHandler(reg_customer_start, pattern=f"^{CB}reg_customer_start$"),
            ],
            CUSTOMER_REG_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_customer_name)],
            CUSTOMER_REG_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_customer_phone)],
            CUSTOMER_REG_TELEGRAM_ID: [
                CallbackQueryHandler(skip_customer_telegram_id, pattern=f"^{CB}skip_telegram_id$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_customer_telegram_id),
            ],
            CUSTOMER_SELECT: [
                CallbackQueryHandler(select_customer, pattern=f"^{CB}select_customer_"),
                CallbackQueryHandler(reg_customer_start, pattern=f"^{CB}reg_customer_start$"),
            ],
            ITEM_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_item_name),
                CallbackQueryHandler(select_product_callback, pattern=f"^{CB}sel_prod_")
            ],
            ITEM_QTY: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_item_qty)],
            ITEM_PRICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_item_price),
                CallbackQueryHandler(confirm_price_callback, pattern=f"^{CB}conf_price_")
            ],
            ITEM_MORE: [
                CallbackQueryHandler(handle_item_more, pattern=f"^{CB}add_more_item$"),
                CallbackQueryHandler(handle_item_more, pattern=f"^{CB}finish_items$"),
            ],
            SHIPPING_COST: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_shipping_cost)],
            DISCOUNT_TYPE: [
                CallbackQueryHandler(handle_discount_type, pattern=f"^{CB}discount_none$"),
                CallbackQueryHandler(handle_discount_type, pattern=f"^{CB}discount_amount$"),
                CallbackQueryHandler(handle_discount_type, pattern=f"^{CB}discount_percent$"),
            ],
            DISCOUNT_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_discount_value)],
            PREVIEW_CONFIRM: [
                CallbackQueryHandler(handle_confirm, pattern=f"^{CB}confirm$"),
                CallbackQueryHandler(handle_cancel, pattern=f"^{CB}cancel$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
        name="invoice_new_conversation",
        persistent=False,
    )

    application.add_handler(CallbackQueryHandler(open_invoice_menu, pattern=f"^{CB}open_menu$"))
    application.add_handler(conv_handler)