import os
from flask import Flask, redirect, render_template

from sqlalchemy import func

import config
from database.db import get_session
from database.models import Invoice, Customer, Product, InvoiceStatus

app = Flask(__name__, static_folder='static', template_folder='templates')


@app.route('/')
def index():
    return redirect('/dashboard')


@app.route('/dashboard')
def dashboard():
    session = get_session()
    try:
        # محاسبه تعداد مشتریان
        total_customers = session.query(Customer).count()
        
        # محاسبه درآمد کل (فقط فاکتورهای نهایی)
        total_revenue = session.query(func.sum(Invoice.total_amount))\
                               .filter(Invoice.status == InvoiceStatus.final).scalar() or 0
        
        # استخراج محصولات با موجودی کم (هشدار انبار)
        low_stock_products = session.query(Product)\
                                    .filter(Product.stock_qty <= Product.low_stock_threshold).all()
        
        # دریافت ۵ فاکتور اخیر
        recent_invoices = session.query(Invoice)\
                                 .order_by(Invoice.created_at.desc()).limit(5).all()

        return render_template('dashboard.html', 
                               customers=total_customers, 
                               revenue=total_revenue, 
                               low_stock=low_stock_products,
                               recent_invoices=recent_invoices)
    finally:
        session.close()

if __name__ == '__main__':
    # اجرای سرور وب روی یک پورت مجزا (برای تست لوکال یا اجرای مستقل بدون ربات)
    app.run(host='0.0.0.0', port=config.WEBAPP_PORT)