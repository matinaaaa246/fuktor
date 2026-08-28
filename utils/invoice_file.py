"""
utils/invoice_file.py
تولید خروجی فاکتور هم به‌صورت تصویر/متن (فاز ۱) و هم به‌صورت PDF (فاز ۲ و ۶).
"""

import os
from datetime import datetime
from textwrap import dedent

# ابزارهای تولید تصویر و متن (فاز ۱)
from PIL import Image, ImageDraw, ImageFont

# ابزارهای تولید PDF (فاز ۲ و ۶)
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import arabic_reshaper
from bidi.algorithm import get_display

import config
from database.db import get_session
from database.models import Invoice, Setting

os.makedirs(config.INVOICE_OUTPUT_DIR, exist_ok=True)

# ==========================================
# بخش اول: توابع فاز ۱ (تولید تصویر و متن)
# ==========================================

def _format_currency(amount: float) -> str:
    return f"{amount:,.0f} تومان"

def build_invoice_text(invoice, customer, items) -> str:
    """متن کامل فاکتور را برای پیش‌نمایش/ذخیره در فایل txt می‌سازد."""
    lines = [
        "🧾 فاکتور فروش",
        "======================",
        f"شماره فاکتور: {invoice.invoice_number}",
        f"تاریخ: {invoice.created_at.strftime('%Y-%m-%d %H:%M') if invoice.created_at else datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"مشتری: {customer.full_name}",
        f"تلفن: {customer.phone}",
        "----------------------",
        "اقلام فاکتور:",
    ]

    for idx, item in enumerate(items, start=1):
        lines.append(
            f"{idx}. {item.product_name} | تعداد: {item.quantity} | "
            f"قیمت واحد: {_format_currency(item.unit_price)} | "
            f"جمع: {_format_currency(item.line_total)}"
        )

    lines.append("----------------------")
    lines.append(f"جمع جزء: {_format_currency(invoice.subtotal)}")
    lines.append(f"هزینه ارسال: {_format_currency(invoice.shipping_cost)}")

    if invoice.discount_type and invoice.discount_value:
        discount_label = (
            f"{invoice.discount_value}%"
            if invoice.discount_type.value == "percent"
            else _format_currency(invoice.discount_value)
        )
        lines.append(f"تخفیف: {discount_label}")

    lines.append(f"مبلغ نهایی قابل پرداخت: {_format_currency(invoice.total_amount)}")
    lines.append("======================")
    lines.append("با تشکر از خرید شما 🌹")

    return "\n".join(lines)


def save_invoice_text_file(invoice, customer, items) -> str:
    """فایل txt فاکتور را می‌سازد و مسیر آن را برمی‌گرداند."""
    text = build_invoice_text(invoice, customer, items)
    file_path = os.path.join(config.INVOICE_OUTPUT_DIR, f"{invoice.invoice_number}.txt")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(text)
    return file_path


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    """
    تلاش برای بارگذاری یک فونت سیستمی؛ در صورت نبود، فونت پیش‌فرض Pillow.
    """
    candidate_paths = [
        os.path.join(config.BASE_DIR, "webapp", "static", "fonts", "Vazirmatn-Regular.ttf"),
        os.path.join(config.BASE_DIR, "assets", "Vazirmatn-Regular.ttf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidate_paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def save_invoice_image_file(invoice, customer, items) -> str:
    """
    یک تصویر ساده (PNG) از فاکتور می‌سازد و مسیر آن را برمی‌گرداند.
    """
    text = build_invoice_text(invoice, customer, items)
    
    # برای رندر درست در Pillow باید متن را راست‌چین و راست‌به‌چپ کنیم
    try:
        reshaped_text = arabic_reshaper.reshape(text)
        bidi_text = get_display(reshaped_text)
        lines = bidi_text.split("\n")
    except:
        lines = text.split("\n")

    font = _load_font(20)
    line_height = 28
    width = 600
    height = line_height * (len(lines) + 2)

    img = Image.new("RGB", (width, height), color=(15, 15, 15))
    draw = ImageDraw.Draw(img)

    y = 20
    for line in lines:
        draw.text((width - 20, y), line, font=font, fill=(240, 240, 240), anchor="ra")
        y += line_height

    file_path = os.path.join(config.INVOICE_OUTPUT_DIR, f"{invoice.invoice_number}.png")
    img.save(file_path)
    return file_path


# ==========================================
# بخش دوم: توابع فاز ۲ (تولید PDF حرفه‌ای)
# ==========================================

def reshape_persian(text):
    if not text:
        return ""
    reshaped = arabic_reshaper.reshape(str(text))
    return get_display(reshaped)

# تابع به حالت async تبدیل شد تا فایل لوگو را بتواند لود کند
async def generate_invoice_pdf(invoice_id: int, bot=None) -> str:
    session = get_session()
    invoice = session.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        session.close()
        return None
    
    filename = f"invoice_{invoice.invoice_number}.pdf"
    filepath = os.path.join(config.INVOICE_OUTPUT_DIR, filename)
    
    c = canvas.Canvas(filepath, pagesize=A4)
    width, height = A4
    
    try:
        font_path = os.path.join(config.BASE_DIR, 'webapp', 'static', 'fonts', 'Vazirmatn-Regular.ttf')
        if os.path.exists(font_path):
            pdfmetrics.registerFont(TTFont('Vazirmatn', font_path))
            font_name = 'Vazirmatn'
        else:
            font_name = 'Helvetica'
    except:
        font_name = 'Helvetica'
    
    shop_name_setting = session.query(Setting).filter(Setting.key == 'shop_name').first()
    shop_name = shop_name_setting.value if shop_name_setting else "سیستم فروشگاهی"
    
    # واکشی و دانلود موقت لوگو در صورت وجود
    logo_setting = session.query(Setting).filter(Setting.key == 'shop_logo').first()
    logo_path = None
    if logo_setting and logo_setting.value and bot:
        try:
            file = await bot.get_file(logo_setting.value)
            logo_path = os.path.join(config.INVOICE_OUTPUT_DIR, f"logo_{logo_setting.value}.jpg")
            if not os.path.exists(logo_path):
                await file.download_to_drive(logo_path)
        except Exception as e:
            print(f"Error downloading logo: {e}")
            logo_path = None

    bg_primary = colors.HexColor("#0B0B10")
    accent_1 = colors.HexColor("#7C5CFF") 
    accent_2 = colors.HexColor("#3B8CFF") 
    text_primary = colors.HexColor("#F2F1F7")
    
    # Header
    c.setFillColor(bg_primary)
    c.rect(0, height - 3.5*cm, width, 3.5*cm, fill=1, stroke=0)
    
    c.setFillColor(accent_1)
    c.rect(0, height - 0.2*cm, width, 0.2*cm, fill=1, stroke=0)
    
    c.setFillColor(text_primary)
    c.setFont(font_name, 22)
    c.drawRightString(width - 2*cm, height - 2*cm, reshape_persian(shop_name))
    
    c.setFillColor(accent_2)
    c.setFont(font_name, 14)
    c.drawString(2*cm, height - 2*cm, reshape_persian(f"فاکتور: {invoice.invoice_number}"))
    
    # رسم تصویر لوگو در هدر
    if logo_path and os.path.exists(logo_path):
        c.drawImage(logo_path, 2*cm, height - 3.2*cm, width=2.5*cm, height=2.5*cm, preserveAspectRatio=True, mask='auto')

    # Customer Info
    c.setFillColor(colors.black)
    c.setFont(font_name, 12)
    c.drawRightString(width - 2*cm, height - 4.5*cm, reshape_persian("اطلاعات مشتری"))
    c.setLineWidth(1)
    c.setStrokeColor(accent_1)
    c.line(width - 2*cm, height - 4.7*cm, width - 6*cm, height - 4.7*cm)
    
    c.setFillColor(colors.darkgrey)
    c.drawRightString(width - 2*cm, height - 5.5*cm, reshape_persian(f"نام مشتری: {invoice.customer.full_name}"))
    c.drawRightString(width - 2*cm, height - 6.2*cm, reshape_persian(f"تلفن تماس: {invoice.customer.phone}"))
    c.drawRightString(width - 2*cm, height - 6.9*cm, reshape_persian(f"تاریخ ثبت: {invoice.created_at.strftime('%Y-%m-%d')}"))
    
    # Table Header
    y_table = height - 8.5*cm
    c.setFillColor(colors.HexColor("#15151C"))
    c.rect(1.5*cm, y_table, width - 3*cm, 1*cm, fill=1, stroke=0)
    
    c.setFillColor(text_primary)
    c.setFont(font_name, 11)
    c.drawRightString(width - 2.5*cm, y_table + 0.3*cm, reshape_persian("ردیف"))
    c.drawRightString(width - 4*cm, y_table + 0.3*cm, reshape_persian("شرح کالا"))
    c.drawString(10*cm, y_table + 0.3*cm, reshape_persian("تعداد"))
    c.drawString(6*cm, y_table + 0.3*cm, reshape_persian("فی (تومان)"))
    c.drawString(2.5*cm, y_table + 0.3*cm, reshape_persian("جمع کل"))
    
    # Items
    y = y_table - 0.8*cm
    c.setFillColor(colors.black)
    c.setFont(font_name, 10)
    
    for i, item in enumerate(invoice.items, 1):
        c.drawRightString(width - 2.5*cm, y, str(i))
        c.drawRightString(width - 4*cm, y, reshape_persian(item.product_name))
        c.drawString(10.5*cm, y, str(item.quantity))
        c.drawString(6*cm, y, f"{item.unit_price:,.0f}")
        c.drawString(2.5*cm, y, f"{item.line_total:,.0f}")
        y -= 0.8*cm
        c.setStrokeColor(colors.lightgrey)
        c.line(2*cm, y + 0.5*cm, width - 2*cm, y + 0.5*cm)
    
    # Totals Area
    y -= 1*cm
    c.setFont(font_name, 12)
    c.setFillColor(colors.darkgrey)
    c.drawRightString(width - 12*cm, y, reshape_persian("جمع مبالغ:"))
    c.drawString(2.5*cm, y, f"{invoice.subtotal:,.0f}")
    y -= 0.8*cm
    
    c.drawRightString(width - 12*cm, y, reshape_persian("تخفیف:"))
    c.drawString(2.5*cm, y, f"{invoice.discount_value:,.0f}")
    y -= 0.8*cm
    
    c.drawRightString(width - 12*cm, y, reshape_persian("هزینه ارسال:"))
    c.drawString(2.5*cm, y, f"{invoice.shipping_cost:,.0f}")
    y -= 1.2*cm
    
    c.setFillColor(colors.HexColor("#1C1C26"))
    c.rect(1.5*cm, y - 0.3*cm, width - 3*cm, 1.2*cm, fill=1, stroke=0)
    c.setFillColor(accent_1)
    c.setFont(font_name, 14)
    c.drawRightString(width - 12*cm, y, reshape_persian("مبلغ نهایی قابل پرداخت:"))
    c.setFont(font_name, 16)
    c.drawString(2.5*cm, y, f"{invoice.total_amount:,.0f}")
    
    c.save()
    session.close()
    return filepath