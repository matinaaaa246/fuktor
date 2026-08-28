"""
مدل‌های SQLAlchemy پروژه (اجباری - ساختار جداول را تغییر ندهید).

تمام فازهای بعدی باید از همین جداول استفاده کنند و جدول جدید نسازند.
"""

import enum

from sqlalchemy import Column, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from database.db import Base


class DiscountType(str, enum.Enum):
    amount = "amount"
    percent = "percent"


class InvoiceStatus(str, enum.Enum):
    draft = "draft"
    final = "final"
    cancelled = "cancelled"


class PaymentStatus(str, enum.Enum):
    paid = "paid"
    partial = "partial"
    unpaid = "unpaid"


class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    full_name = Column(String(255), nullable=False)
    phone = Column(String(20), nullable=False)
    telegram_id = Column(String(50), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    invoices = relationship("Invoice", back_populates="customer")


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    unit_price = Column(Float, nullable=False, default=0)
    stock_qty = Column(Integer, nullable=False, default=0)
    low_stock_threshold = Column(Integer, nullable=False, default=3)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    invoice_number = Column(String(50), unique=True, nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)

    shipping_cost = Column(Float, nullable=False, default=0)
    discount_type = Column(Enum(DiscountType), nullable=True)
    discount_value = Column(Float, nullable=False, default=0)

    subtotal = Column(Float, nullable=False, default=0)
    total_amount = Column(Float, nullable=False, default=0)

    status = Column(Enum(InvoiceStatus), nullable=False, default=InvoiceStatus.draft)
    payment_status = Column(Enum(PaymentStatus), nullable=False, default=PaymentStatus.unpaid)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    customer = relationship("Customer", back_populates="invoices")
    items = relationship("InvoiceItem", back_populates="invoice", cascade="all, delete-orphan")
    payments = relationship("Payment", back_populates="invoice", cascade="all, delete-orphan")


class InvoiceItem(Base):
    __tablename__ = "invoice_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False)
    product_name = Column(String(255), nullable=False)
    quantity = Column(Integer, nullable=False, default=1)
    unit_price = Column(Float, nullable=False, default=0)
    line_total = Column(Float, nullable=False, default=0)

    invoice = relationship("Invoice", back_populates="items")


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False)
    amount = Column(Float, nullable=False)
    paid_at = Column(DateTime(timezone=True), server_default=func.now())
    note = Column(Text, nullable=True)

    invoice = relationship("Invoice", back_populates="payments")


class Setting(Base):
    __tablename__ = "settings"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=True)
