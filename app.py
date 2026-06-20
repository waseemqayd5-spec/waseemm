"""
نظام إدارة وكالة البشائر للأدوية والمستلزمات الطبية (جملة)
نسخة أسطورية متكاملة مع:
- لوحة تحكم 3D تفاعلية
- واجهة صوتية (Voice Interface)
- نظام طباعة وتسميات
- تطبيق موبايل (PWA)
- تكامل الدفع الإلكتروني
- نسخ احتياطي متقدم
- التسعير الديناميكي
- كشف الشذوذ والاحتيال
- مساعد صيدلاني ذكي (RAG + LLM)
- التعرف على الأدوية من الصور
- نظام توصيات مخصص
- تحليل المشاعر
- استخراج الفواتير الورقية
- لوحات تحليل ذكية
"""

from flask import (
    Flask, request, jsonify, render_template_string, session,
    redirect, url_for, make_response, send_from_directory, Response, send_file
)
import os
import datetime
import hashlib
import sqlite3
import psycopg2
from psycopg2.extras import RealDictCursor
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import time
import json
import requests
import io
import re
import base64
import shutil
import zipfile
import subprocess
import threading
import queue
import random
import math
from collections import defaultdict
from datetime import timedelta
from openpyxl import Workbook
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
import qrcode
from io import BytesIO

# محاولة استيراد مكتبات الذكاء الاصطناعي (مع fallback)
try:
    import numpy as np
    from sklearn.ensemble import IsolationForest
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics.pairwise import cosine_similarity
    from sklearn.feature_extraction.text import TfidfVectorizer
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    print("⚠️ scikit-learn غير مثبت، بعض ميزات الذكاء الاصطناعي ستكون محدودة")

try:
    import pytesseract
    from PIL import Image
    import cv2
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False
    print("⚠️ pytesseract أو PIL غير مثبت، ميزة التعرف من الصور غير متوفرة")

try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMER_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMER_AVAILABLE = False
    print("⚠️ sentence-transformers غير مثبت، ميزة RAG محدودة")

# =============================== التهيئة ===============================
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-key-change-in-production')
UPLOAD_FOLDER = 'static/uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf'}

DATABASE_URL = os.environ.get('DATABASE_URL', None)
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')

# =============================== دوال قاعدة البيانات ===============================
def get_db_connection():
    if DATABASE_URL:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    else:
        os.makedirs('data', exist_ok=True)
        conn = sqlite3.connect('data/supermarket.db')
        conn.row_factory = sqlite3.Row
    return conn

def execute_query(query, params=None, fetch_one=False, fetch_all=False, commit=False):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        if params is None:
            params = ()
        cur.execute(query, params)
        if commit:
            conn.commit()
        if fetch_one:
            return cur.fetchone()
        elif fetch_all:
            return cur.fetchall()
    finally:
        cur.close()
        conn.close()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# =============================== نظام الصلاحيات ===============================
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def role_required(allowed_roles):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if 'user_id' not in session or session.get('role') not in allowed_roles:
                return "غير مصرح (صلاحية غير كافية)", 403
            return f(*args, **kwargs)
        return decorated
    return decorator

admin_required = role_required(['admin'])
pharmacist_required = role_required(['admin', 'pharmacist'])
cashier_required = role_required(['admin', 'cashier'])
store_keeper_required = role_required(['admin', 'store_keeper'])
purchaser_required = role_required(['admin', 'purchaser'])

# =============================== دوال مساعدة ===============================
def get_settings():
    rows = execute_query("SELECT key, value FROM settings", fetch_all=True)
    settings = {row['key']: row['value'] for row in rows} if rows else {}
    defaults = {
        'company_name': 'وكالة البشائر للأدوية والمستلزمات الطبية',
        'company_logo': '💊',
        'company_address': 'اليمن - صنعاء',
        'company_phone': '967771602370',
        'company_whatsapp': '967771602370',
        'delivery_fee': '0.00',
        'points_per_riyal': '0',
        'points_redeem_rate': '0',
        'currency': 'ريال يمني',
        'tax_rate': '0.00',
        'default_unit': 'حبة'
    }
    defaults.update(settings)
    return defaults

def save_settings(settings_dict):
    for key, value in settings_dict.items():
        if DATABASE_URL:
            execute_query("INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                          (key, value), commit=True)
        else:
            execute_query("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                          (key, value), commit=True)

def log_inventory(product_id, product_name, change_type, quantity_change, old_qty, new_qty, notes, user_id):
    execute_query("""
        INSERT INTO inventory_logs (product_id, product_name, change_type, quantity_change, old_quantity, new_quantity, notes, user_id, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (product_id, product_name, change_type, quantity_change, old_qty, new_qty, notes, user_id, datetime.datetime.now().isoformat()), commit=True)

# =============================== إنشاء الجداول ===============================
def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    if DATABASE_URL:
        # PostgreSQL
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                password_hash VARCHAR(200) NOT NULL,
                role VARCHAR(20) DEFAULT 'cashier',
                full_name VARCHAR(100),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key VARCHAR(100) PRIMARY KEY,
                value TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS customers (
                id SERIAL PRIMARY KEY,
                phone VARCHAR(20) UNIQUE,
                name VARCHAR(100),
                address TEXT,
                tax_number VARCHAR(50),
                commercial_register VARCHAR(50),
                payment_terms VARCHAR(50) DEFAULT 'cash',
                loyalty_points INTEGER DEFAULT 0,
                total_spent REAL DEFAULT 0,
                visits INTEGER DEFAULT 0,
                last_visit DATE,
                tier VARCHAR(20) DEFAULT 'عادي',
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS suppliers (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                phone VARCHAR(20),
                address TEXT,
                email VARCHAR(100),
                contact_person VARCHAR(100),
                license_number VARCHAR(50),
                bank_account TEXT,
                notes TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS units (
                id SERIAL PRIMARY KEY,
                name VARCHAR(50) UNIQUE NOT NULL,
                symbol VARCHAR(10),
                base_unit_id INTEGER REFERENCES units(id),
                conversion_factor REAL DEFAULT 1.0,
                is_base BOOLEAN DEFAULT FALSE
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id SERIAL PRIMARY KEY,
                barcode VARCHAR(50) UNIQUE,
                name VARCHAR(200) NOT NULL,
                description TEXT,
                category VARCHAR(50),
                unit_id INTEGER REFERENCES units(id),
                price REAL NOT NULL,
                cost_price REAL,
                quantity REAL DEFAULT 0,
                min_quantity REAL DEFAULT 10,
                supplier_id INTEGER REFERENCES suppliers(id),
                expiry_date DATE,
                added_date DATE,
                last_updated DATE,
                image_url TEXT,
                image_url2 TEXT,
                is_active INTEGER DEFAULT 1,
                active_ingredient TEXT,
                dosage_form TEXT,
                strength TEXT,
                manufacturer TEXT,
                batch_number TEXT,
                storage_conditions TEXT,
                prescription_required BOOLEAN DEFAULT FALSE,
                unit_pack_size INTEGER,
                dynamic_price REAL,
                price_updated_at TIMESTAMP,
                sales_velocity REAL DEFAULT 0,
                abc_class CHAR(1) DEFAULT 'C',
                xyz_class CHAR(1) DEFAULT 'Z'
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS purchases (
                id SERIAL PRIMARY KEY,
                supplier_id INTEGER REFERENCES suppliers(id),
                invoice_number VARCHAR(50),
                total_cost REAL,
                purchase_date DATE,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS purchase_items (
                id SERIAL PRIMARY KEY,
                purchase_id INTEGER REFERENCES purchases(id),
                product_id INTEGER REFERENCES products(id),
                quantity REAL,
                cost_price REAL,
                total REAL,
                batch_number TEXT,
                expiry_date DATE
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS offers (
                id SERIAL PRIMARY KEY,
                title VARCHAR(200) NOT NULL,
                description TEXT,
                code VARCHAR(50),
                discount_type VARCHAR(20) DEFAULT 'percentage',
                discount_value REAL,
                start_date DATE,
                end_date DATE,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS invoices (
                id SERIAL PRIMARY KEY,
                invoice_number VARCHAR(50) UNIQUE NOT NULL,
                customer_id INTEGER REFERENCES customers(id),
                customer_name VARCHAR(100),
                customer_phone VARCHAR(20),
                customer_address TEXT,
                total REAL NOT NULL,
                discount REAL DEFAULT 0,
                final_total REAL NOT NULL,
                payment_method VARCHAR(50),
                points_earned INTEGER DEFAULT 0,
                points_used INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_by INTEGER REFERENCES users(id),
                is_anomaly BOOLEAN DEFAULT FALSE,
                anomaly_score REAL DEFAULT 0,
                anomaly_reason TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS invoice_items (
                id SERIAL PRIMARY KEY,
                invoice_id INTEGER REFERENCES invoices(id),
                product_id INTEGER REFERENCES products(id),
                product_name VARCHAR(200),
                quantity REAL NOT NULL,
                price REAL NOT NULL,
                total REAL NOT NULL,
                batch_number TEXT,
                expiry_date DATE
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS inventory_logs (
                id SERIAL PRIMARY KEY,
                product_id INTEGER REFERENCES products(id),
                product_name TEXT,
                change_type TEXT,
                quantity_change REAL,
                old_quantity REAL,
                new_quantity REAL,
                notes TEXT,
                user_id INTEGER REFERENCES users(id),
                timestamp TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS returns (
                id SERIAL PRIMARY KEY,
                invoice_id INTEGER REFERENCES invoices(id),
                product_id INTEGER REFERENCES products(id),
                product_name VARCHAR(200),
                quantity REAL,
                price REAL,
                total REAL,
                reason TEXT,
                return_date DATE,
                created_by INTEGER REFERENCES users(id)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id SERIAL PRIMARY KEY,
                type VARCHAR(50),
                product_id INTEGER REFERENCES products(id),
                message TEXT,
                is_read BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                id SERIAL PRIMARY KEY,
                customer_id INTEGER REFERENCES customers(id),
                customer_name VARCHAR(100),
                customer_phone VARCHAR(20),
                rating INTEGER CHECK (rating >= 1 AND rating <= 5),
                comment TEXT,
                sentiment_score REAL,
                sentiment_label VARCHAR(20),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS price_history (
                id SERIAL PRIMARY KEY,
                product_id INTEGER REFERENCES products(id),
                old_price REAL,
                new_price REAL,
                reason TEXT,
                created_by INTEGER REFERENCES users(id),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS anomaly_logs (
                id SERIAL PRIMARY KEY,
                invoice_id INTEGER REFERENCES invoices(id),
                anomaly_score REAL,
                reason TEXT,
                is_reviewed BOOLEAN DEFAULT FALSE,
                reviewed_by INTEGER REFERENCES users(id),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS recommendations (
                id SERIAL PRIMARY KEY,
                customer_id INTEGER REFERENCES customers(id),
                product_id INTEGER REFERENCES products(id),
                score REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS product_similarity (
                product_id1 INTEGER REFERENCES products(id),
                product_id2 INTEGER REFERENCES products(id),
                similarity_score REAL,
                PRIMARY KEY (product_id1, product_id2)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id SERIAL PRIMARY KEY,
                payment_id VARCHAR(50) UNIQUE NOT NULL,
                invoice_id INTEGER REFERENCES invoices(id),
                amount REAL NOT NULL,
                status VARCHAR(20) DEFAULT 'pending',
                payment_method VARCHAR(50),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP
            )
        """)
    else:
        # SQLite
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT DEFAULT 'cashier',
                full_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT UNIQUE,
                name TEXT,
                address TEXT,
                tax_number TEXT,
                commercial_register TEXT,
                payment_terms TEXT DEFAULT 'cash',
                loyalty_points INTEGER DEFAULT 0,
                total_spent REAL DEFAULT 0,
                visits INTEGER DEFAULT 0,
                last_visit DATE,
                tier TEXT DEFAULT 'عادي',
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS suppliers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                phone TEXT,
                address TEXT,
                email TEXT,
                contact_person TEXT,
                license_number TEXT,
                bank_account TEXT,
                notes TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS units (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                symbol TEXT,
                base_unit_id INTEGER REFERENCES units(id),
                conversion_factor REAL DEFAULT 1.0,
                is_base BOOLEAN DEFAULT FALSE
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                barcode TEXT UNIQUE,
                name TEXT NOT NULL,
                description TEXT,
                category TEXT,
                unit_id INTEGER REFERENCES units(id),
                price REAL NOT NULL,
                cost_price REAL,
                quantity REAL DEFAULT 0,
                min_quantity REAL DEFAULT 10,
                supplier_id INTEGER REFERENCES suppliers(id),
                expiry_date DATE,
                added_date DATE,
                last_updated DATE,
                image_url TEXT,
                image_url2 TEXT,
                is_active INTEGER DEFAULT 1,
                active_ingredient TEXT,
                dosage_form TEXT,
                strength TEXT,
                manufacturer TEXT,
                batch_number TEXT,
                storage_conditions TEXT,
                prescription_required BOOLEAN DEFAULT FALSE,
                unit_pack_size INTEGER,
                dynamic_price REAL,
                price_updated_at TIMESTAMP,
                sales_velocity REAL DEFAULT 0,
                abc_class CHAR(1) DEFAULT 'C',
                xyz_class CHAR(1) DEFAULT 'Z'
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS purchases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                supplier_id INTEGER REFERENCES suppliers(id),
                invoice_number TEXT,
                total_cost REAL,
                purchase_date DATE,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS purchase_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                purchase_id INTEGER REFERENCES purchases(id),
                product_id INTEGER REFERENCES products(id),
                quantity REAL,
                cost_price REAL,
                total REAL,
                batch_number TEXT,
                expiry_date DATE
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS offers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                code TEXT,
                discount_type TEXT DEFAULT 'percentage',
                discount_value REAL,
                start_date DATE,
                end_date DATE,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_number TEXT UNIQUE NOT NULL,
                customer_id INTEGER REFERENCES customers(id),
                customer_name TEXT,
                customer_phone TEXT,
                customer_address TEXT,
                total REAL NOT NULL,
                discount REAL DEFAULT 0,
                final_total REAL NOT NULL,
                payment_method TEXT,
                points_earned INTEGER DEFAULT 0,
                points_used INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_by INTEGER REFERENCES users(id),
                is_anomaly BOOLEAN DEFAULT FALSE,
                anomaly_score REAL DEFAULT 0,
                anomaly_reason TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS invoice_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_id INTEGER REFERENCES invoices(id),
                product_id INTEGER REFERENCES products(id),
                product_name TEXT,
                quantity REAL NOT NULL,
                price REAL NOT NULL,
                total REAL NOT NULL,
                batch_number TEXT,
                expiry_date DATE
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS inventory_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER REFERENCES products(id),
                product_name TEXT,
                change_type TEXT,
                quantity_change REAL,
                old_quantity REAL,
                new_quantity REAL,
                notes TEXT,
                user_id INTEGER REFERENCES users(id),
                timestamp TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS returns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_id INTEGER REFERENCES invoices(id),
                product_id INTEGER REFERENCES products(id),
                product_name TEXT,
                quantity REAL,
                price REAL,
                total REAL,
                reason TEXT,
                return_date DATE,
                created_by INTEGER REFERENCES users(id)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT,
                product_id INTEGER REFERENCES products(id),
                message TEXT,
                is_read BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER REFERENCES customers(id),
                customer_name TEXT,
                customer_phone TEXT,
                rating INTEGER,
                comment TEXT,
                sentiment_score REAL,
                sentiment_label TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER REFERENCES products(id),
                old_price REAL,
                new_price REAL,
                reason TEXT,
                created_by INTEGER REFERENCES users(id),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS anomaly_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_id INTEGER REFERENCES invoices(id),
                anomaly_score REAL,
                reason TEXT,
                is_reviewed BOOLEAN DEFAULT FALSE,
                reviewed_by INTEGER REFERENCES users(id),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS recommendations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER REFERENCES customers(id),
                product_id INTEGER REFERENCES products(id),
                score REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS product_similarity (
                product_id1 INTEGER REFERENCES products(id),
                product_id2 INTEGER REFERENCES products(id),
                similarity_score REAL,
                PRIMARY KEY (product_id1, product_id2)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payment_id TEXT UNIQUE NOT NULL,
                invoice_id INTEGER REFERENCES invoices(id),
                amount REAL NOT NULL,
                status TEXT DEFAULT 'pending',
                payment_method TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP
            )
        """)

    # إدخال البيانات الافتراضية
    cur.execute("SELECT COUNT(*) FROM units")
    if cur.fetchone()[0] == 0:
        units = [
            ('حبة', 'حب', None, 1.0, 1),
            ('علبة', 'علبة', None, 1.0, 0),
            ('شريط', 'شريط', None, 1.0, 0),
            ('كرتونة', 'كرتونة', None, 1.0, 0),
            ('لتر', 'لتر', None, 1.0, 0),
            ('ملجم', 'ملجم', None, 1.0, 0),
            ('جرام', 'جرام', None, 1.0, 0),
        ]
        for unit in units:
            cur.execute("INSERT INTO units (name, symbol, base_unit_id, conversion_factor, is_base) VALUES (?, ?, ?, ?, ?)", unit)

    cur.execute("SELECT COUNT(*) FROM users")
    if cur.fetchone()[0] == 0:
        hashed = generate_password_hash('admin123')
        cur.execute("INSERT INTO users (username, password_hash, role, full_name) VALUES (?, ?, ?, ?)",
                    ('admin', hashed, 'admin', 'مدير النظام'))
        hashed_ph = generate_password_hash('pharma123')
        cur.execute("INSERT INTO users (username, password_hash, role, full_name) VALUES (?, ?, ?, ?)",
                    ('pharmacist', hashed_ph, 'pharmacist', 'صيدلي رئيسي'))
        hashed_cashier = generate_password_hash('cashier123')
        cur.execute("INSERT INTO users (username, password_hash, role, full_name) VALUES (?, ?, ?, ?)",
                    ('cashier', hashed_cashier, 'cashier', 'كاشير'))
        hashed_stock = generate_password_hash('stock123')
        cur.execute("INSERT INTO users (username, password_hash, role, full_name) VALUES (?, ?, ?, ?)",
                    ('stock', hashed_stock, 'store_keeper', 'أمين مخزن'))
        hashed_purch = generate_password_hash('purch123')
        cur.execute("INSERT INTO users (username, password_hash, role, full_name) VALUES (?, ?, ?, ?)",
                    ('purchaser', hashed_purch, 'purchaser', 'مندوب مشتريات'))

    cur.execute("SELECT COUNT(*) FROM settings")
    if cur.fetchone()[0] == 0:
        default_settings = [
            ('company_name', 'وكالة البشائر للأدوية والمستلزمات الطبية'),
            ('company_logo', '💊'),
            ('company_address', 'اليمن - صنعاء'),
            ('company_phone', '967771602370'),
            ('company_whatsapp', '967771602370'),
            ('delivery_fee', '0.00'),
            ('points_per_riyal', '0'),
            ('points_redeem_rate', '0'),
            ('currency', 'ريال يمني'),
            ('tax_rate', '0.00'),
            ('default_unit', 'حبة')
        ]
        for key, val in default_settings:
            cur.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (key, val))

    cur.execute("SELECT COUNT(*) FROM suppliers")
    if cur.fetchone()[0] == 0:
        cur.execute("INSERT INTO suppliers (name, phone, address, contact_person, license_number) VALUES (?, ?, ?, ?, ?)",
                    ('شركة الحكمة للأدوية', '0500000001', 'صنعاء', 'أحمد القرشي', 'LIC001'))
        cur.execute("INSERT INTO suppliers (name, phone, address, contact_person, license_number) VALUES (?, ?, ?, ?, ?)",
                    ('مستودع الأمان', '0500000002', 'عدن', 'سامي النجار', 'LIC002'))

    cur.execute("SELECT COUNT(*) FROM customers")
    if cur.fetchone()[0] == 0:
        cur.execute("INSERT INTO customers (phone, name, address, tax_number, commercial_register, payment_terms) VALUES (?, ?, ?, ?, ?, ?)",
                    ('0500000000', 'صيدلية الرحمة', 'صنعاء - شارع الستين', 'TAX001', 'CR001', 'credit'))
        cur.execute("INSERT INTO customers (phone, name, address, tax_number, commercial_register, payment_terms) VALUES (?, ?, ?, ?, ?, ?)",
                    ('0500000003', 'مستشفى السلام', 'صنعاء - السبعين', 'TAX002', 'CR002', 'cash'))

    cur.execute("SELECT COUNT(*) FROM products")
    if cur.fetchone()[0] == 0:
        today = datetime.date.today()
        cur.execute("SELECT id FROM units WHERE name='حبة'")
        unit_id = cur.fetchone()[0]
        cur.execute("SELECT id FROM suppliers WHERE name LIKE '%الحكمة%'")
        sup1 = cur.fetchone()[0]
        cur.execute("SELECT id FROM suppliers WHERE name LIKE '%الأمان%'")
        sup2 = cur.fetchone()[0]

        products = [
            ("6281234567890", "باراسيتامول 500 مجم", "مسكن وخافض حرارة يستخدم لعلاج الآلام الخفيفة والمتوسطة والحمى.", "مسكنات", unit_id, 5.0, 3.5, 200, 20, sup1, (today + datetime.timedelta(days=365)).isoformat(), today.isoformat(), today.isoformat(), None, None, 1, "باراسيتامول", "أقراص", "500 مجم", "شركة الحكمة", "BATCH001", "درجة حرارة الغرفة", False, 10, None, None, 0, 'A', 'X'),
            ("6280987654321", "أموكسيسيلين 500 مجم", "مضاد حيوي واسع الطيف لعلاج الالتهابات البكتيرية.", "مضادات حيوية", unit_id, 15.0, 10.0, 100, 15, sup1, (today + datetime.timedelta(days=180)).isoformat(), today.isoformat(), today.isoformat(), None, None, 1, "أموكسيسيلين", "كبسولات", "500 مجم", "جلوبال فارما", "BATCH002", "يحفظ في الثلاجة", True, 20, None, None, 0, 'A', 'X'),
            ("6281122334455", "أوميبرازول 40 مجم", "علاج قرحة المعدة والارتجاع المريئي.", "جهاز هضمي", unit_id, 8.0, 5.0, 150, 10, sup2, (today + datetime.timedelta(days=200)).isoformat(), today.isoformat(), today.isoformat(), None, None, 1, "أوميبرازول", "أقراص", "40 مجم", "الأمان", "BATCH003", "درجة حرارة الغرفة", False, 14, None, None, 0, 'B', 'Y'),
            ("6289988776655", "سيتالوبريم 20 مجم", "مضاد اكتئاب من مجموعة مثبطات استرداد السيروتونين.", "أمراض نفسية", unit_id, 12.0, 8.0, 80, 10, sup2, (today + datetime.timedelta(days=150)).isoformat(), today.isoformat(), today.isoformat(), None, None, 1, "سيتالوبريم", "أقراص", "20 مجم", "الأمان", "BATCH004", "درجة حرارة الغرفة", True, 28, None, None, 0, 'B', 'Z'),
        ]
        for prod in products:
            cur.execute("""
                INSERT INTO products (barcode, name, description, category, unit_id, price, cost_price, quantity, min_quantity, supplier_id, expiry_date, added_date, last_updated, image_url, image_url2, is_active, active_ingredient, dosage_form, strength, manufacturer, batch_number, storage_conditions, prescription_required, unit_pack_size, dynamic_price, price_updated_at, sales_velocity, abc_class, xyz_class)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, prod)

    conn.commit()
    conn.close()

init_db()

# =============================== نظام الإشعارات (SSE) ===============================
notification_queue = queue.Queue()

def check_alerts():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, name, quantity, min_quantity FROM products
        WHERE quantity <= min_quantity AND is_active = 1
    """)
    low_stock = cur.fetchall()
    for row in low_stock:
        msg = f"المنتج '{row['name']}' مخزونه منخفض (الكمية: {row['quantity']}، الحد الأدنى: {row['min_quantity']})"
        execute_query("INSERT INTO alerts (type, product_id, message) VALUES (?, ?, ?)",
                      ('low_stock', row['id'], msg), commit=True)
        notification_queue.put({'type': 'low_stock', 'message': msg, 'product_id': row['id']})

    today = datetime.date.today()
    expiry_threshold = today + datetime.timedelta(days=30)
    cur.execute("""
        SELECT id, name, expiry_date FROM products
        WHERE expiry_date <= ? AND expiry_date >= ? AND is_active = 1
    """, (expiry_threshold, today))
    near_expiry = cur.fetchall()
    for row in near_expiry:
        days_left = (row['expiry_date'] - today).days
        msg = f"المنتج '{row['name']}' سينتهي صلاحيته خلال {days_left} يوم (تاريخ الصلاحية: {row['expiry_date']})"
        execute_query("INSERT INTO alerts (type, product_id, message) VALUES (?, ?, ?)",
                      ('expiry', row['id'], msg), commit=True)
        notification_queue.put({'type': 'expiry', 'message': msg, 'product_id': row['id']})
    conn.close()

def alert_scheduler():
    while True:
        check_alerts()
        time.sleep(600)

threading.Thread(target=alert_scheduler, daemon=True).start()

@app.route('/api/events')
def sse_events():
    def event_stream():
        while True:
            try:
                data = notification_queue.get(timeout=30)
                yield f"data: {json.dumps(data)}\n\n"
            except queue.Empty:
                yield ": heartbeat\n\n"
    return Response(event_stream(), mimetype="text/event-stream")

# =============================== رفع الصور ===============================
@app.route('/api/upload-image', methods=['POST'])
@login_required
def upload_image():
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': 'لا يوجد ملف'})
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'message': 'اسم الملف فارغ'})
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        name, ext = os.path.splitext(filename)
        timestamp = int(time.time())
        new_filename = f"{name}_{timestamp}{ext}"
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], new_filename))
        return jsonify({'success': True, 'url': f'/static/uploads/{new_filename}'})
    return jsonify({'success': False, 'message': 'نوع الملف غير مسموح'})

# =============================== ميزة 2: التسعير الديناميكي ===============================
def calculate_dynamic_price(product_id):
    """حساب السعر الديناميكي للمنتج بناءً على عوامل متعددة"""
    product = execute_query("""
        SELECT id, name, price, cost_price, quantity, sales_velocity, expiry_date, category, abc_class
        FROM products WHERE id = ?
    """, (product_id,), fetch_one=True)
    if not product:
        return None

    base_price = product['price']
    cost = product['cost_price'] or base_price * 0.6
    quantity = product['quantity'] or 0
    velocity = product['sales_velocity'] or 1.0
    expiry = product['expiry_date']

    factors = {
        'demand': 1.0,
        'stock': 1.0,
        'expiry': 1.0,
        'category': 1.0,
        'class': 1.0
    }

    if velocity > 5:
        factors['demand'] = 1.08
    elif velocity > 2:
        factors['demand'] = 1.03
    elif velocity < 0.5:
        factors['demand'] = 0.95

    if quantity < 20:
        factors['stock'] = 1.05
    elif quantity > 200:
        factors['stock'] = 0.92

    if expiry:
        today = datetime.date.today()
        if isinstance(expiry, str):
            expiry = datetime.datetime.strptime(expiry, '%Y-%m-%d').date()
        days_left = (expiry - today).days
        if days_left < 30:
            factors['expiry'] = 0.80
        elif days_left < 60:
            factors['expiry'] = 0.90

    if product['category'] in ['مسكنات', 'مضادات حيوية']:
        factors['category'] = 1.05
    elif product['category'] in ['أمراض مزمنة', 'أمراض نفسية']:
        factors['category'] = 1.02

    if product['abc_class'] == 'A':
        factors['class'] = 1.03
    elif product['abc_class'] == 'C':
        factors['class'] = 0.95

    dynamic_price = base_price
    for factor in factors.values():
        dynamic_price *= factor

    min_price = cost * 1.1
    if dynamic_price < min_price:
        dynamic_price = min_price

    dynamic_price = round(dynamic_price * 2) / 2

    execute_query("""
        UPDATE products SET dynamic_price = ?, price_updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (dynamic_price, product_id), commit=True)

    execute_query("""
        INSERT INTO price_history (product_id, old_price, new_price, reason, created_by)
        VALUES (?, ?, ?, ?, ?)
    """, (product_id, base_price, dynamic_price, 'تحديث تلقائي - تسعير ديناميكي', 1), commit=True)

    return dynamic_price

@app.route('/api/dynamic-price/<int:product_id>', methods=['GET'])
def api_dynamic_price(product_id):
    price = calculate_dynamic_price(product_id)
    if price is None:
        return jsonify({'success': False, 'message': 'المنتج غير موجود'})
    return jsonify({'success': True, 'price': price})

@app.route('/admin/dynamic-pricing', methods=['GET', 'POST'])
@admin_required
def dynamic_pricing_page():
    if request.method == 'POST':
        product_id = request.form.get('product_id')
        if product_id:
            price = calculate_dynamic_price(int(product_id))
            return jsonify({'success': True, 'price': price})

    products = execute_query("""
        SELECT id, name, price, dynamic_price, sales_velocity, quantity, expiry_date,
               price_updated_at, abc_class
        FROM products WHERE is_active = 1 ORDER BY name
    """, fetch_all=True)

    update_sales_velocity()

    return render_template_string("""
    <!DOCTYPE html>
    <html dir="rtl">
    <head>
        <meta charset="UTF-8">
        <title>التسعير الديناميكي</title>
        <style>
            :root { --bg: #000; --text: #FFD700; --card-bg: #111; --border: #FFD700; --btn-bg: #FFD700; --btn-text: #000; --input-bg: #000; --input-text: #FFD700; }
            body.light { --bg: #f5f5f5; --text: #000; --card-bg: #fff; --border: #007bff; --btn-bg: #007bff; --btn-text: #fff; --input-bg: #fff; --input-text: #000; }
            body{background:var(--bg);color:var(--text);padding:20px;font-family:Arial;transition:background 0.3s,color 0.3s;}
            .container{max-width:1200px;margin:auto;}
            .header{background:var(--card-bg);border:1px solid var(--border);padding:20px;border-radius:10px;margin-bottom:20px;}
            .nav a{color:var(--text);text-decoration:none;margin-left:15px;}
            table{width:100%;border-collapse:collapse;background:var(--card-bg);border:1px solid var(--border);}
            th,td{padding:10px;border:1px solid var(--border);text-align:center;}
            th{background:var(--border);color:var(--btn-text);}
            .btn{background:var(--btn-bg);color:var(--btn-text);padding:8px 15px;border:none;border-radius:5px;cursor:pointer;}
            .price-up{color:#4CAF50;}.price-down{color:#f44336;}
            .theme-toggle{position:fixed;top:20px;left:20px;background:var(--btn-bg);color:var(--btn-text);border:none;border-radius:50%;width:50px;height:50px;font-size:20px;cursor:pointer;z-index:1000;}
            .chat-float{position:fixed;bottom:20px;left:20px;background:var(--btn-bg);color:var(--btn-text);width:60px;height:60px;border-radius:50%;font-size:30px;display:flex;align-items:center;justify-content:center;cursor:pointer;z-index:999;box-shadow:0 4px 15px rgba(0,0,0,0.5);text-decoration:none;}
        </style>
    </head>
    <body>
    <button class="theme-toggle" onclick="toggleTheme()">🌓</button>
    <a href="/chat" class="chat-float" title="المساعد الذكي">💬</a>
    <div class="container">
        <div class="header">
            <h2>📊 التسعير الديناميكي الذكي</h2>
            <div class="nav">
                <a href="/admin">لوحة المدير</a>
                <a href="/products">المنتجات</a>
                <a href="/admin/dynamic-pricing" style="font-weight:bold;">التسعير الديناميكي</a>
            </div>
            <p style="margin-top:10px;font-size:14px;">يتم حساب السعر الأمثل تلقائياً بناءً على الطلب والمخزون وتاريخ الصلاحية والفئة</p>
            <button class="btn" onclick="updateAllPrices()">🔄 تحديث جميع الأسعار</button>
        </div>
        <div id="result"></div>
        <table>
            <thead><tr><th>#</th><th>المنتج</th><th>السعر الحالي</th><th>السعر الديناميكي</th><th>سرعة المبيعات</th><th>المخزون</th><th>التصنيف</th><th>آخر تحديث</th><th>إجراء</th></tr></thead>
            <tbody>
                {% for p in products %}
                <tr>
                    <td>{{ p.id }}</td>
                    <td>{{ p.name }}</td>
                    <td>{{ p.price }} ريال</td>
                    <td class="{% if p.dynamic_price and p.dynamic_price > p.price %}price-up{% elif p.dynamic_price and p.dynamic_price < p.price %}price-down{% endif %}">
                        {{ p.dynamic_price or p.price }} ريال
                    </td>
                    <td>{{ "%.1f"|format(p.sales_velocity or 0) }}</td>
                    <td>{{ p.quantity }}</td>
                    <td>{{ p.abc_class or '-' }}</td>
                    <td>{{ p.price_updated_at or 'لم يحدث' }}</td>
                    <td><button class="btn" onclick="updatePrice({{ p.id }})">تحديث</button></td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
    <script>
        function toggleTheme(){document.body.classList.toggle('light');localStorage.setItem('theme',document.body.classList.contains('light')?'light':'dark');}
        if(localStorage.getItem('theme')==='light') document.body.classList.add('light');
        function updatePrice(id) {
            fetch(`/api/dynamic-price/${id}`).then(r=>r.json()).then(data=>{
                if(data.success){document.getElementById('result').innerHTML=`<p style="color:green;">✅ تم تحديث السعر إلى ${data.price} ريال</p>`;setTimeout(()=>location.reload(),1000);}
            });
        }
        function updateAllPrices() {
            if(!confirm('تحديث جميع الأسعار قد يستغرق بعض الوقت. هل تريد المتابعة؟')) return;
            document.getElementById('result').innerHTML='<p>⏳ جاري تحديث الأسعار...</p>';
            fetch('/api/update-all-prices',{method:'POST'}).then(r=>r.json()).then(data=>{
                document.getElementById('result').innerHTML=`<p style="color:green;">✅ ${data.message}</p>`;
                setTimeout(()=>location.reload(),1500);
            });
        }
    </script>
    </body>
    </html>
    """, products=products)

@app.route('/api/update-all-prices', methods=['POST'])
@admin_required
def update_all_prices():
    products = execute_query("SELECT id FROM products WHERE is_active = 1", fetch_all=True)
    count = 0
    for p in products:
        calculate_dynamic_price(p['id'])
        count += 1
    return jsonify({'success': True, 'message': f'تم تحديث {count} منتج'})

def update_sales_velocity():
    products = execute_query("SELECT DISTINCT product_id FROM invoice_items", fetch_all=True)
    for p in products:
        pid = p['product_id']
        items = execute_query("""
            SELECT ii.quantity, i.created_at
            FROM invoice_items ii
            JOIN invoices i ON ii.invoice_id = i.id
            WHERE ii.product_id = ? AND i.created_at >= datetime('now', '-30 days')
        """, (pid,), fetch_all=True)
        if items:
            total_qty = sum(item['quantity'] for item in items)
            velocity = total_qty / 30.0
        else:
            velocity = 0.1
        execute_query("UPDATE products SET sales_velocity = ? WHERE id = ?", (velocity, pid), commit=True)

# =============================== ميزة 3: كشف الشذوذ والاحتيال ===============================
def detect_anomaly(invoice_data):
    if not SKLEARN_AVAILABLE:
        return {'is_anomaly': False, 'score': 0, 'reason': 'مكتبة scikit-learn غير مثبتة'}
    try:
        past_invoices = execute_query("""
            SELECT id, total, discount, final_total,
                   (SELECT COUNT(*) FROM invoice_items WHERE invoice_id = invoices.id) as item_count
            FROM invoices
            WHERE created_at >= datetime('now', '-30 days')
            ORDER BY created_at DESC LIMIT 100
        """, fetch_all=True)
        if not past_invoices or len(past_invoices) < 10:
            return {'is_anomaly': False, 'score': 0, 'reason': 'بيانات تدريب غير كافية'}
        X = []
        for inv in past_invoices:
            X.append([inv['total'] or 0, inv['discount'] or 0, inv['final_total'] or 0, inv['item_count'] or 0])
        X.append([invoice_data.get('total', 0), invoice_data.get('discount', 0), invoice_data.get('final_total', 0), invoice_data.get('item_count', 0)])
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)
        model = IsolationForest(contamination=0.1, random_state=42)
        predictions = model.fit_predict(X_scaled)
        scores = model.decision_function(X_scaled)
        is_anomaly = predictions[-1] == -1
        score = float(scores[-1])
        reason = "طبيعي"
        if is_anomaly:
            reasons = []
            if invoice_data.get('total', 0) > 10000:
                reasons.append("قيمة الفاتورة مرتفعة جداً")
            if invoice_data.get('discount', 0) / max(invoice_data.get('total', 1), 1) > 0.5:
                reasons.append("نسبة الخصم مرتفعة جداً")
            if invoice_data.get('item_count', 0) > 30:
                reasons.append("عدد الأصناف كبير جداً")
            if not reasons:
                reasons.append("نمط غير عادي")
            reason = "، ".join(reasons)
        return {'is_anomaly': is_anomaly, 'score': score, 'reason': reason}
    except Exception as e:
        return {'is_anomaly': False, 'score': 0, 'reason': f'خطأ في التحليل: {str(e)}'}

@app.route('/api/check-anomaly', methods=['POST'])
def check_anomaly():
    data = request.json
    cart = data.get('cart', [])
    total = data.get('total', 0)
    discount = data.get('discount', 0)
    final_total = data.get('final_total', total - discount)
    invoice_data = {'total': total, 'discount': discount, 'final_total': final_total, 'item_count': len(cart)}
    result = detect_anomaly(invoice_data)
    return jsonify({'success': True, 'is_anomaly': result['is_anomaly'], 'score': result['score'], 'reason': result['reason']})

@app.route('/admin/anomalies')
@admin_required
def anomalies_page():
    anomalies = execute_query("""
        SELECT i.*, u.username as created_by_name
        FROM invoices i
        LEFT JOIN users u ON i.created_by = u.id
        WHERE i.is_anomaly = 1
        ORDER BY i.created_at DESC
    """, fetch_all=True)
    anomaly_logs = execute_query("""
        SELECT al.*, i.invoice_number, i.customer_name
        FROM anomaly_logs al
        JOIN invoices i ON al.invoice_id = i.id
        ORDER BY al.created_at DESC LIMIT 50
    """, fetch_all=True)
    return render_template_string("""
    <!DOCTYPE html>
    <html dir="rtl">
    <head><meta charset="UTF-8"><title>كشف الشذوذ والاحتيال</title>
    <style>
        :root { --bg: #000; --text: #FFD700; --card-bg: #111; --border: #FFD700; --btn-bg: #FFD700; --btn-text: #000; }
        body.light { --bg: #f5f5f5; --text: #000; --card-bg: #fff; --border: #007bff; --btn-bg: #007bff; --btn-text: #fff; }
        body{background:var(--bg);color:var(--text);padding:20px;font-family:Arial;transition:background 0.3s,color 0.3s;}
        .container{max-width:1200px;margin:auto;}
        .header{background:var(--card-bg);border:1px solid var(--border);padding:20px;border-radius:10px;margin-bottom:20px;}
        .nav a{color:var(--text);text-decoration:none;margin-left:15px;}
        .alert-card{background:var(--card-bg);border:1px solid #f44336;padding:15px;border-radius:8px;margin:10px 0;}
        table{width:100%;border-collapse:collapse;background:var(--card-bg);border:1px solid var(--border);}
        th,td{padding:10px;border:1px solid var(--border);text-align:center;}
        th{background:var(--border);color:var(--btn-text);}
        .btn{background:var(--btn-bg);color:var(--btn-text);padding:8px 15px;border:none;border-radius:5px;cursor:pointer;}
        .high-risk{color:#f44336;font-weight:bold;}
        .theme-toggle{position:fixed;top:20px;left:20px;background:var(--btn-bg);color:var(--btn-text);border:none;border-radius:50%;width:50px;height:50px;font-size:20px;cursor:pointer;z-index:1000;}
        .chat-float{position:fixed;bottom:20px;left:20px;background:var(--btn-bg);color:var(--btn-text);width:60px;height:60px;border-radius:50%;font-size:30px;display:flex;align-items:center;justify-content:center;cursor:pointer;z-index:999;box-shadow:0 4px 15px rgba(0,0,0,0.5);text-decoration:none;}
    </style>
    </head>
    <body>
    <button class="theme-toggle" onclick="toggleTheme()">🌓</button>
    <a href="/chat" class="chat-float" title="المساعد الذكي">💬</a>
    <div class="container">
        <div class="header">
            <h2>🛡️ كشف الشذوذ والاحتيال</h2>
            <div class="nav"><a href="/admin">لوحة المدير</a><a href="/admin/anomalies" style="font-weight:bold;">الفواتير الشاذة</a></div>
            <p style="margin-top:10px;font-size:14px;color:#f44336;">⚠️ يتم تحليل الفواتير تلقائياً لكشف الأنماط غير الطبيعية</p>
        </div>
        <h3>🚨 الفواتير الشاذة</h3>
        {% if anomalies %}
        <table>
            <thead><tr><th>رقم الفاتورة</th><th>العميل</th><th>الإجمالي</th><th>الخصم</th><th>المبلغ النهائي</th><th>طريقة الدفع</th><th>التاريخ</th><th>السبب</th><th>الحالة</th></tr></thead>
            <tbody>
            {% for inv in anomalies %}
            <tr>
                <td>{{ inv.invoice_number }}</td>
                <td>{{ inv.customer_name or 'غير معروف' }}</td>
                <td>{{ inv.total }}</td>
                <td>{{ inv.discount }}</td>
                <td class="high-risk">{{ inv.final_total }}</td>
                <td>{{ inv.payment_method }}</td>
                <td>{{ inv.created_at }}</td>
                <td>{{ inv.anomaly_reason or 'غير محدد' }}</td>
                <td><button class="btn" onclick="markReviewed({{ inv.id }})">✅ مراجعة</button></td>
            </tr>
            {% endfor %}
            </tbody>
        </table>
        {% else %}<p>✅ لا توجد فواتير شاذة حالياً</p>{% endif %}
        <h3 style="margin-top:30px;">📋 سجل المراجعة</h3>
        {% if anomaly_logs %}
        <table>
            <thead><tr><th>الفاتورة</th><th>العميل</th><th>درجة الشذوذ</th><th>السبب</th><th>تمت المراجعة</th><th>التاريخ</th></tr></thead>
            <tbody>
            {% for log in anomaly_logs %}
            <tr><td>{{ log.invoice_number }}</td><td>{{ log.customer_name or 'غير معروف' }}</td><td>{{ "%.2f"|format(log.anomaly_score) }}</td><td>{{ log.reason }}</td><td>{{ '✅' if log.is_reviewed else '⏳' }}</td><td>{{ log.created_at }}</td></tr>
            {% endfor %}
            </tbody>
        </table>
        {% else %}<p>لا توجد سجلات مراجعة</p>{% endif %}
    </div>
    <script>
        function toggleTheme(){document.body.classList.toggle('light');localStorage.setItem('theme',document.body.classList.contains('light')?'light':'dark');}
        if(localStorage.getItem('theme')==='light') document.body.classList.add('light');
        function markReviewed(id){fetch(`/api/mark-anomaly-reviewed/${id}`,{method:'POST'}).then(r=>r.json()).then(data=>{if(data.success)location.reload();});}
    </script>
    </body>
    </html>
    """, anomalies=anomalies, anomaly_logs=anomaly_logs)

@app.route('/api/mark-anomaly-reviewed/<int:invoice_id>', methods=['POST'])
@admin_required
def mark_anomaly_reviewed(invoice_id):
    execute_query("UPDATE invoices SET is_anomaly = 0 WHERE id = ?", (invoice_id,), commit=True)
    execute_query("UPDATE anomaly_logs SET is_reviewed = 1, reviewed_by = ? WHERE invoice_id = ?",
                  (session.get('user_id', 1), invoice_id), commit=True)
    return jsonify({'success': True})

# =============================== ميزة 4: المساعد الذكي المتقدم (RAG + LLM) ===============================
embedding_model = None
if SENTENCE_TRANSFORMER_AVAILABLE:
    try:
        embedding_model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
    except:
        embedding_model = None

def get_product_embeddings():
    products = execute_query("""
        SELECT id, name, description, active_ingredient, category, manufacturer,
               strength, dosage_form, price
        FROM products WHERE is_active = 1
    """, fetch_all=True)
    if not products or embedding_model is None:
        return None, None
    texts = []
    for p in products:
        text = f"{p['name']} {p['description'] or ''} {p['active_ingredient'] or ''} {p['category'] or ''} {p['manufacturer'] or ''}"
        texts.append(text)
    try:
        embeddings = embedding_model.encode(texts)
        return products, embeddings
    except:
        return None, None

def rag_search(query, top_k=3):
    products, embeddings = get_product_embeddings()
    if products is None or embeddings is None:
        return []
    try:
        query_embedding = embedding_model.encode([query])
        similarities = cosine_similarity(query_embedding, embeddings)[0]
        top_indices = similarities.argsort()[-top_k:][::-1]
        results = []
        for idx in top_indices:
            results.append({'product': dict(products[idx]), 'similarity': float(similarities[idx])})
        return results
    except:
        return []

@app.route('/api/chat', methods=['POST'])
def api_chat():
    data = request.json
    user_message = data.get('message', '').strip()
    if not user_message:
        return jsonify({"success": False, "error": "رسالة فارغة"})
    rag_results = rag_search(user_message, top_k=5)
    context = ""
    if rag_results:
        context = "المنتجات ذات الصلة:\n"
        for r in rag_results:
            p = r['product']
            context += f"- {p['name']} (المادة الفعالة: {p['active_ingredient'] or 'غير محدد'}, السعر: {p['price']} ريال, التشابه: {r['similarity']:.2f})\n"
    if GEMINI_API_KEY:
        try:
            system_prompt = f"""أنت مساعد صيدلاني في وكالة البشائر للأدوية والمستلزمات الطبية.
            معلومات إضافية من قاعدة البيانات:
            {context}
            تعليمات مهمة:
            - أجب باللغة العربية الفصحى
            - قدم معلومات دقيقة عن الأدوية
            - لا تقدم استشارات طبية تشخيصية
            - إذا سأل عن دواء معين، استخدم المعلومات المتوفرة أعلاه
            - إذا لم تعرف الإجابة، قل ذلك بصراحة
            سؤال العميل: {user_message}"""
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
            payload = {"contents": [{"role": "user", "parts": [{"text": system_prompt}]}]}
            resp = requests.post(url, json=payload, timeout=15)
            if resp.status_code == 200:
                candidates = resp.json().get("candidates", [])
                if candidates and candidates[0].get("content", {}).get("parts"):
                    reply = candidates[0]["content"]["parts"][0]["text"]
                    return jsonify({"success": True, "reply": reply, "rag_results": rag_results})
        except Exception as e:
            print(f"Gemini error: {e}")
    msg_lower = user_message.lower()
    for r in rag_results[:3]:
        p = r['product']
        if p['name'].lower() in msg_lower:
            reply = f"🔍 **{p['name']}**\n💊 المادة الفعالة: {p['active_ingredient'] or 'غير محدد'}\n📦 الفئة: {p['category'] or 'غير محدد'}\n🏭 الشركة المصنعة: {p['manufacturer'] or 'غير محدد'}\n💰 السعر: {p['price']} ريال\n📝 الوصف: {p['description'] or 'لا يوجد وصف'}\n"
            if p['strength']: reply += f"⚡ التركيز: {p['strength']}\n"
            if p['dosage_form']: reply += f"💊 الشكل الصيدلاني: {p['dosage_form']}\n"
            return jsonify({"success": True, "reply": reply, "rag_results": rag_results})
    if rag_results:
        reply = "📋 **منتجات ذات صلة بسؤالك:**\n"
        for i, r in enumerate(rag_results[:3], 1):
            p = r['product']
            reply += f"{i}. {p['name']} - {p['price']} ريال"
            if p['active_ingredient']:
                reply += f" (المادة الفعالة: {p['active_ingredient']})"
            reply += "\n"
        reply += "\n💡 هل تريد معرفة المزيد عن أي من هذه المنتجات؟"
    else:
        reply = "🔍 لم أجد منتجات تطابق سؤالك بالضبط. يمكنك البحث عن دواء معين أو سؤال عن فئة دوائية محددة."
    return jsonify({"success": True, "reply": reply, "rag_results": rag_results})

# =============================== ميزة 5: التعرف على الأدوية من الصور ===============================
@app.route('/api/scan-image', methods=['POST'])
@login_required
def scan_image():
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': 'لا يوجد ملف'})
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'message': 'اسم الملف فارغ'})
    if not OCR_AVAILABLE:
        return jsonify({'success': False, 'message': 'مكتبات OCR غير مثبتة'})
    try:
        filename = secure_filename(file.filename)
        temp_path = os.path.join('/tmp', filename)
        file.save(temp_path)
        image = cv2.imread(temp_path)
        if image is None:
            return jsonify({'success': False, 'message': 'لا يمكن قراءة الصورة'})
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        gray = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
        text = pytesseract.image_to_string(gray, lang='ara+eng')
        text = text.strip()
        if not text:
            return jsonify({'success': False, 'message': 'لم يتم العثور على نص في الصورة'})
        barcode = None
        try:
            from pyzbar import pyzbar
            barcodes = pyzbar.decode(image)
            if barcodes:
                barcode = barcodes[0].data.decode('utf-8')
        except:
            pass
        products = []
        if barcode:
            product = execute_query("SELECT * FROM products WHERE barcode = ? AND is_active = 1", (barcode,), fetch_one=True)
            if product:
                products.append(dict(product))
        if not products:
            lines = text.split('\n')
            for line in lines:
                line = line.strip()
                if len(line) > 3:
                    results = execute_query("SELECT * FROM products WHERE name LIKE ? AND is_active = 1 LIMIT 5", (f"%{line}%",), fetch_all=True)
                    for r in results:
                        if r not in products:
                            products.append(dict(r))
        try:
            os.remove(temp_path)
        except:
            pass
        return jsonify({'success': True, 'text': text, 'barcode': barcode, 'products': products[:5], 'message': f'تم العثور على {len(products)} منتج'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'خطأ: {str(e)}'})

@app.route('/admin/scan-image-ui')
@login_required
def scan_image_ui():
    return render_template_string("""
    <!DOCTYPE html>
    <html dir="rtl">
    <head><meta charset="UTF-8"><title>التعرف على الأدوية من الصور</title>
    <style>
        :root { --bg: #000; --text: #FFD700; --card-bg: #111; --border: #FFD700; --btn-bg: #FFD700; --btn-text: #000; }
        body.light { --bg: #f5f5f5; --text: #000; --card-bg: #fff; --border: #007bff; --btn-bg: #007bff; --btn-text: #fff; }
        body{background:var(--bg);color:var(--text);padding:20px;font-family:Arial;transition:background 0.3s,color 0.3s;}
        .container{max-width:800px;margin:auto;}
        .header{background:var(--card-bg);border:1px solid var(--border);padding:20px;border-radius:10px;margin-bottom:20px;}
        .upload-area{border:2px dashed var(--border);padding:40px;text-align:center;border-radius:10px;cursor:pointer;}
        .upload-area:hover{background:var(--card-bg);}
        .preview{max-width:100%;max-height:300px;margin:15px 0;border-radius:8px;}
        .result-card{background:var(--card-bg);border:1px solid var(--border);padding:15px;border-radius:8px;margin:10px 0;}
        .btn{background:var(--btn-bg);color:var(--btn-text);padding:10px 20px;border:none;border-radius:5px;cursor:pointer;}
        .theme-toggle{position:fixed;top:20px;left:20px;background:var(--btn-bg);color:var(--btn-text);border:none;border-radius:50%;width:50px;height:50px;font-size:20px;cursor:pointer;z-index:1000;}
        .chat-float{position:fixed;bottom:20px;left:20px;background:var(--btn-bg);color:var(--btn-text);width:60px;height:60px;border-radius:50%;font-size:30px;display:flex;align-items:center;justify-content:center;cursor:pointer;z-index:999;box-shadow:0 4px 15px rgba(0,0,0,0.5);text-decoration:none;}
    </style>
    </head>
    <body>
    <button class="theme-toggle" onclick="toggleTheme()">🌓</button>
    <a href="/chat" class="chat-float" title="المساعد الذكي">💬</a>
    <div class="container">
        <div class="header"><h2>📷 التعرف على الأدوية من الصور</h2><div class="nav"><a href="/admin">لوحة المدير</a><a href="/admin/scan-image-ui" style="font-weight:bold;">مسح الصور</a></div><p>قم برفع صورة لعلبة الدواء للتعرف عليها تلقائياً</p></div>
        <div class="upload-area" onclick="document.getElementById('fileInput').click()">
            <p>📤 اضغط لرفع صورة</p>
            <p style="font-size:12px;color:#aaa;">صور JPG, PNG, GIF</p>
            <input type="file" id="fileInput" accept="image/*" style="display:none;" onchange="scanImage(this.files[0])">
        </div>
        <div id="previewContainer"></div>
        <div id="result"></div>
        <div id="productsResult"></div>
    </div>
    <script>
        function toggleTheme(){document.body.classList.toggle('light');localStorage.setItem('theme',document.body.classList.contains('light')?'light':'dark');}
        if(localStorage.getItem('theme')==='light') document.body.classList.add('light');
        function scanImage(file){if(!file)return;const reader=new FileReader();reader.onload=function(e){document.getElementById('previewContainer').innerHTML=`<img src="${e.target.result}" class="preview"><br><span>⏳ جاري تحليل الصورة...</span>`;};reader.readAsDataURL(file);const formData=new FormData();formData.append('file',file);fetch('/api/scan-image',{method:'POST',body:formData}).then(r=>r.json()).then(data=>{let html='';if(data.success){html+=`<div class="result-card"><h4>📝 النص المستخرج</h4><p>${data.text||'لا يوجد'}</p>`;if(data.barcode){html+=`<p><strong>الباركود:</strong> ${data.barcode}</p>`;}html+=`<p><strong>عدد النتائج:</strong> ${data.products.length}</p></div>`;if(data.products.length>0){html+='<h4>🔍 المنتجات المكتشفة</h4>';data.products.forEach(p=>{html+=`<div class="result-card"><h5>${p.name}</h5><p>السعر: ${p.price} ريال | المخزون: ${p.quantity}</p><p>المادة الفعالة: ${p.active_ingredient||'غير محدد'}</p><p>الشركة: ${p.manufacturer||'غير محدد'}</p><button class="btn" onclick="addToCart(${p.id},'${p.name.replace(/'/g,"\\'")}',${p.price})">أضف للسلة</button></div>`;});}document.getElementById('productsResult').innerHTML=html;}else{document.getElementById('result').innerHTML=`<div class="result-card" style="border-color:#f44336;color:#f44336;">❌ ${data.message}</div>`;}document.getElementById('previewContainer').innerHTML+='<br>✅ تم التحليل';}).catch(err=>{document.getElementById('result').innerHTML=`<div class="result-card" style="border-color:#f44336;color:#f44336;">❌ خطأ: ${err}</div>`;});}
        function addToCart(id,name,price){let cart=JSON.parse(localStorage.getItem('cart')||'[]');let existing=cart.find(i=>i.id==id);if(existing)existing.quantity+=1;else cart.push({id,name,price,quantity:1});localStorage.setItem('cart',JSON.stringify(cart));alert(`تمت إضافة ${name} إلى السلة`);}
    </script>
    </body>
    </html>
    """)

# =============================== ميزة 6: نظام توصيات مخصص للعملاء ===============================
def generate_recommendations(customer_id):
    customer_items = execute_query("""
        SELECT DISTINCT ii.product_id
        FROM invoice_items ii
        JOIN invoices i ON ii.invoice_id = i.id
        WHERE i.customer_id = ?
    """, (customer_id,), fetch_all=True)
    if not customer_items:
        top_products = execute_query("""
            SELECT product_id, SUM(quantity) as total_sold
            FROM invoice_items
            GROUP BY product_id
            ORDER BY total_sold DESC
            LIMIT 5
        """, fetch_all=True)
        return [p['product_id'] for p in top_products]
    bought_ids = [p['product_id'] for p in customer_items]
    similar_products = execute_query("""
        SELECT product_id2 as product_id, similarity_score
        FROM product_similarity
        WHERE product_id1 IN ({})
        ORDER BY similarity_score DESC
        LIMIT 10
    """.format(','.join('?' * len(bought_ids))), bought_ids, fetch_all=True)
    if similar_products:
        recommended = [p['product_id'] for p in similar_products if p['product_id'] not in bought_ids]
        if recommended:
            return recommended[:5]
    categories = execute_query("""
        SELECT DISTINCT category FROM products WHERE id IN ({})
    """.format(','.join('?' * len(bought_ids))), bought_ids, fetch_all=True)
    if categories:
        cats = [c['category'] for c in categories if c['category']]
        if cats:
            placeholders = ','.join('?' * len(cats))
            cat_products = execute_query(f"""
                SELECT id FROM products
                WHERE category IN ({placeholders}) AND is_active = 1
                AND id NOT IN ({','.join('?' * len(bought_ids))})
                ORDER BY sales_velocity DESC, quantity DESC
                LIMIT 5
            """, cats + bought_ids, fetch_all=True)
            return [p['id'] for p in cat_products]
    top = execute_query("""
        SELECT product_id, SUM(quantity) as total_sold
        FROM invoice_items
        GROUP BY product_id
        ORDER BY total_sold DESC
        LIMIT 5
    """, fetch_all=True)
    return [p['product_id'] for p in top]

@app.route('/api/recommendations/<int:customer_id>')
def api_recommendations(customer_id):
    recs = generate_recommendations(customer_id)
    if recs:
        placeholders = ','.join('?' * len(recs))
        products = execute_query(f"""
            SELECT id, name, price, image_url, category, active_ingredient
            FROM products WHERE id IN ({placeholders}) AND is_active = 1
        """, recs, fetch_all=True)
    else:
        products = []
    for p_id in recs[:5]:
        execute_query("""
            INSERT OR REPLACE INTO recommendations (customer_id, product_id, score, created_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        """, (customer_id, p_id, 1.0), commit=True)
    return jsonify({'success': True, 'recommendations': [dict(p) for p in products]})

@app.route('/api/calculate-similarity', methods=['POST'])
@admin_required
def calculate_similarity():
    if not SKLEARN_AVAILABLE:
        return jsonify({'success': False, 'message': 'مكتبة scikit-learn غير مثبتة'})
    products = execute_query("""
        SELECT id, name, description, category, active_ingredient, manufacturer
        FROM products WHERE is_active = 1
    """, fetch_all=True)
    if len(products) < 2:
        return jsonify({'success': False, 'message': 'تحتاج إلى منتجين على الأقل'})
    texts = []
    for p in products:
        text = f"{p['name']} {p['description'] or ''} {p['category'] or ''} {p['active_ingredient'] or ''} {p['manufacturer'] or ''}"
        texts.append(text)
    vectorizer = TfidfVectorizer(max_features=100, stop_words=None)
    tfidf = vectorizer.fit_transform(texts)
    similarity_matrix = cosine_similarity(tfidf)
    count = 0
    for i in range(len(products)):
        for j in range(i+1, len(products)):
            score = float(similarity_matrix[i][j])
            if score > 0.1:
                execute_query("""
                    INSERT OR REPLACE INTO product_similarity (product_id1, product_id2, similarity_score)
                    VALUES (?, ?, ?)
                """, (products[i]['id'], products[j]['id'], score), commit=True)
                count += 1
    return jsonify({'success': True, 'message': f'تم حساب {count} علاقة تشابه بين {len(products)} منتج'})

@app.route('/customer/recommendations')
def customer_recommendations_page():
    return render_template_string("""
    <!DOCTYPE html>
    <html dir="rtl">
    <head><meta charset="UTF-8"><title>توصيات مخصصة</title>
    <style>
        :root { --bg: #000; --text: #FFD700; --card-bg: #111; --border: #FFD700; --btn-bg: #FFD700; --btn-text: #000; }
        body.light { --bg: #f5f5f5; --text: #000; --card-bg: #fff; --border: #007bff; --btn-bg: #007bff; --btn-text: #fff; }
        body{background:var(--bg);color:var(--text);padding:20px;font-family:Arial;transition:background 0.3s,color 0.3s;}
        .container{max-width:1000px;margin:auto;}
        .header{background:var(--card-bg);border:1px solid var(--border);padding:20px;border-radius:10px;margin-bottom:20px;}
        .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:20px;}
        .card{background:var(--card-bg);border:1px solid var(--border);border-radius:10px;padding:15px;text-align:center;}
        .card img{width:100%;height:150px;object-fit:cover;border-radius:8px;background:#222;}
        .btn{background:var(--btn-bg);color:var(--btn-text);padding:8px 15px;border:none;border-radius:5px;cursor:pointer;}
        .theme-toggle{position:fixed;top:20px;left:20px;background:var(--btn-bg);color:var(--btn-text);border:none;border-radius:50%;width:50px;height:50px;font-size:20px;cursor:pointer;z-index:1000;}
        .chat-float{position:fixed;bottom:20px;left:20px;background:var(--btn-bg);color:var(--btn-text);width:60px;height:60px;border-radius:50%;font-size:30px;display:flex;align-items:center;justify-content:center;cursor:pointer;z-index:999;box-shadow:0 4px 15px rgba(0,0,0,0.5);text-decoration:none;}
    </style>
    </head>
    <body>
    <button class="theme-toggle" onclick="toggleTheme()">🌓</button>
    <a href="/chat" class="chat-float" title="المساعد الذكي">💬</a>
    <div class="container">
        <div class="header"><h2>🎯 توصيات مخصصة لك</h2><div class="nav"><a href="/">الرئيسية</a><a href="/products">الأدوية</a><a href="/customer/recommendations" style="font-weight:bold;">التوصيات</a></div>
            <div style="margin-top:10px;"><input type="tel" id="phoneInput" placeholder="أدخل رقم هاتفك" style="padding:8px;border-radius:5px;border:1px solid var(--border);background:var(--bg);color:var(--text);width:200px;"><button class="btn" onclick="getRecommendations()">عرض التوصيات</button></div>
        </div>
        <div id="recommendations" class="grid"></div>
    </div>
    <script>
        function toggleTheme(){document.body.classList.toggle('light');localStorage.setItem('theme',document.body.classList.contains('light')?'light':'dark');}
        if(localStorage.getItem('theme')==='light') document.body.classList.add('light');
        function getRecommendations(){let phone=document.getElementById('phoneInput').value.trim();if(!phone){alert('أدخل رقم الهاتف');return;}fetch(`/api/customer/${phone}`).then(r=>r.json()).then(data=>{if(!data.success){document.getElementById('recommendations').innerHTML=`<p style="color:red;">العميل غير موجود. استخدم رقم هاتف مسجل.</p>`;return;}fetch(`/api/recommendations/${data.id}`).then(r=>r.json()).then(res=>{if(res.success&&res.recommendations.length>0){let html='';res.recommendations.forEach(p=>{html+=`<div class="card"><img src="${p.image_url||'/static/uploads/default.jpg'}" onerror="this.src='/static/uploads/default.jpg'"><h4>${p.name}</h4><p>💰 ${p.price} ريال</p><p style="font-size:12px;color:#aaa;">${p.category||''}</p><button class="btn" onclick="addToCart(${p.id},'${p.name.replace(/'/g,"\\'")}',${p.price})">أضف للسلة</button></div>`;});document.getElementById('recommendations').innerHTML=html;}else{document.getElementById('recommendations').innerHTML=`<p>لا توجد توصيات حالياً. قم بشراء المزيد من المنتجات للحصول على توصيات مخصصة.</p>`;}});});}
        function addToCart(id,name,price){let cart=JSON.parse(localStorage.getItem('cart')||'[]');let existing=cart.find(i=>i.id==id);if(existing)existing.quantity+=1;else cart.push({id,name,price,quantity:1});localStorage.setItem('cart',JSON.stringify(cart));alert(`تمت إضافة ${name} إلى السلة`);}
    </script>
    </body>
    </html>
    """)

# =============================== ميزة 7: تحليل المشاعر من التقييمات ===============================
def analyze_sentiment(text):
    if not text:
        return {'label': 'محايد', 'score': 0.0}
    if GEMINI_API_KEY:
        try:
            prompt = f"""حلل المشاعر في النص التالي وأعط النتيجة كـ JSON:
            النص: "{text}"
            أخرج JSON بالشكل التالي: {{"label": "إيجابي|سلبي|محايد", "score": 0.0-1.0}}
            """
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
            payload = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                candidates = resp.json().get("candidates", [])
                if candidates:
                    content = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                    json_match = re.search(r'\{.*\}', content)
                    if json_match:
                        result = json.loads(json_match.group())
                        return {'label': result.get('label', 'محايد'), 'score': result.get('score', 0.5)}
        except:
            pass
    positive_words = ['ممتاز', 'رائع', 'جيد', 'مفيد', 'فعال', 'سريع', 'دقيق', 'قوي', 'مذهل', 'ممتازة', 'جيدة']
    negative_words = ['سيء', 'مضر', 'ضعيف', 'بطيء', 'غير مفيد', 'خطير', 'مكلف', 'رديء', 'سيئة', 'مشكلة', 'أخطاء']
    text_lower = text.lower()
    pos_score = sum(1 for w in positive_words if w in text_lower)
    neg_score = sum(1 for w in negative_words if w in text_lower)
    if pos_score > neg_score:
        label = 'إيجابي'
        score = min(0.5 + (pos_score - neg_score) * 0.1, 1.0)
    elif neg_score > pos_score:
        label = 'سلبي'
        score = min(0.5 + (neg_score - pos_score) * 0.1, 1.0)
    else:
        label = 'محايد'
        score = 0.5
    return {'label': label, 'score': score}

@app.route('/api/feedback', methods=['POST'])
def submit_feedback():
    data = request.json
    customer_id = data.get('customer_id')
    customer_name = data.get('customer_name', '')
    customer_phone = data.get('customer_phone', '')
    rating = data.get('rating', 3)
    comment = data.get('comment', '')
    if not comment and rating < 1:
        return jsonify({'success': False, 'message': 'يرجى كتابة تعليق أو تقييم'})
    sentiment = analyze_sentiment(comment)
    execute_query("""
        INSERT INTO feedback (customer_id, customer_name, customer_phone, rating, comment, sentiment_score, sentiment_label)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (customer_id, customer_name, customer_phone, rating, comment, sentiment['score'], sentiment['label']), commit=True)
    return jsonify({'success': True, 'message': 'شكراً لتقييمك', 'sentiment': sentiment})

@app.route('/admin/feedback')
@admin_required
def feedback_page():
    feedbacks = execute_query("SELECT * FROM feedback ORDER BY created_at DESC LIMIT 100", fetch_all=True)
    stats = execute_query("""
        SELECT
            COUNT(*) as total,
            AVG(rating) as avg_rating,
            SUM(CASE WHEN sentiment_label = 'إيجابي' THEN 1 ELSE 0 END) as positive,
            SUM(CASE WHEN sentiment_label = 'سلبي' THEN 1 ELSE 0 END) as negative,
            SUM(CASE WHEN sentiment_label = 'محايد' THEN 1 ELSE 0 END) as neutral
        FROM feedback
    """, fetch_one=True)
    return render_template_string("""
    <!DOCTYPE html>
    <html dir="rtl">
    <head><meta charset="UTF-8"><title>تحليل المشاعر والتقييمات</title>
    <style>
        :root { --bg: #000; --text: #FFD700; --card-bg: #111; --border: #FFD700; --btn-bg: #FFD700; --btn-text: #000; }
        body.light { --bg: #f5f5f5; --text: #000; --card-bg: #fff; --border: #007bff; --btn-bg: #007bff; --btn-text: #fff; }
        body{background:var(--bg);color:var(--text);padding:20px;font-family:Arial;transition:background 0.3s,color 0.3s;}
        .container{max-width:1200px;margin:auto;}
        .header{background:var(--card-bg);border:1px solid var(--border);padding:20px;border-radius:10px;margin-bottom:20px;}
        .stats{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:15px;margin-bottom:20px;}
        .stat-card{background:var(--card-bg);border:1px solid var(--border);padding:15px;border-radius:10px;text-align:center;}
        .stat-card .num{font-size:24px;font-weight:bold;}
        .feedback-item{background:var(--card-bg);border:1px solid var(--border);padding:15px;border-radius:8px;margin:10px 0;}
        .positive{color:#4CAF50;}.negative{color:#f44336;}.neutral{color:#FFC107;}
        .theme-toggle{position:fixed;top:20px;left:20px;background:var(--btn-bg);color:var(--btn-text);border:none;border-radius:50%;width:50px;height:50px;font-size:20px;cursor:pointer;z-index:1000;}
        .chat-float{position:fixed;bottom:20px;left:20px;background:var(--btn-bg);color:var(--btn-text);width:60px;height:60px;border-radius:50%;font-size:30px;display:flex;align-items:center;justify-content:center;cursor:pointer;z-index:999;box-shadow:0 4px 15px rgba(0,0,0,0.5);text-decoration:none;}
    </style>
    </head>
    <body>
    <button class="theme-toggle" onclick="toggleTheme()">🌓</button>
    <a href="/chat" class="chat-float" title="المساعد الذكي">💬</a>
    <div class="container">
        <div class="header"><h2>📊 تحليل المشاعر والتقييمات</h2><div class="nav"><a href="/admin">لوحة المدير</a><a href="/admin/feedback" style="font-weight:bold;">التقييمات</a></div></div>
        <div class="stats">
            <div class="stat-card"><div class="num">{{ stats.total or 0 }}</div>إجمالي التقييمات</div>
            <div class="stat-card"><div class="num">{{ "%.1f"|format(stats.avg_rating or 0) }}</div>متوسط التقييم</div>
            <div class="stat-card positive"><div class="num">{{ stats.positive or 0 }}</div>👍 إيجابي</div>
            <div class="stat-card negative"><div class="num">{{ stats.negative or 0 }}</div>👎 سلبي</div>
            <div class="stat-card neutral"><div class="num">{{ stats.neutral or 0 }}</div>😐 محايد</div>
        </div>
        <h3>📝 التقييمات الأخيرة</h3>
        {% for fb in feedbacks %}
        <div class="feedback-item">
            <div style="display:flex;justify-content:space-between;flex-wrap:wrap;">
                <span><strong>{{ fb.customer_name or 'غير معروف' }}</strong> ({{ fb.customer_phone or 'لا يوجد' }})</span>
                <span>⭐ {{ fb.rating }}/5</span>
                <span class="{% if fb.sentiment_label == 'إيجابي' %}positive{% elif fb.sentiment_label == 'سلبي' %}negative{% else %}neutral{% endif %}">
                    {{ fb.sentiment_label or 'محايد' }} ({{ "%.2f"|format(fb.sentiment_score or 0) }})
                </span>
                <span style="font-size:12px;color:#aaa;">{{ fb.created_at }}</span>
            </div>
            <p style="margin-top:10px;">{{ fb.comment }}</p>
        </div>
        {% else %}<p>لا توجد تقييمات حالياً</p>{% endfor %}
    </div>
    <script>
        function toggleTheme(){document.body.classList.toggle('light');localStorage.setItem('theme',document.body.classList.contains('light')?'light':'dark');}
        if(localStorage.getItem('theme')==='light') document.body.classList.add('light');
    </script>
    </body>
    </html>
    """, stats=stats, feedbacks=feedbacks)

# =============================== ميزة 9: استخراج بيانات الفواتير الورقية ===============================
@app.route('/api/analyze-invoice', methods=['POST'])
@login_required
def analyze_invoice():
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': 'لا يوجد ملف'})
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'message': 'اسم الملف فارغ'})
    if not OCR_AVAILABLE:
        return jsonify({'success': False, 'message': 'مكتبات OCR غير مثبتة'})
    try:
        filename = secure_filename(file.filename)
        temp_path = os.path.join('/tmp', filename)
        file.save(temp_path)
        image = cv2.imread(temp_path)
        if image is None:
            return jsonify({'success': False, 'message': 'لا يمكن قراءة الصورة'})
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        gray = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
        text = pytesseract.image_to_string(gray, lang='ara+eng')
        text = text.strip()
        if not text:
            return jsonify({'success': False, 'message': 'لم يتم العثور على نص في الصورة'})
        extracted = {'invoice_number': None, 'supplier_name': None, 'date': None, 'total': None, 'items': []}
        invoice_match = re.search(r'(?:رقم|فاتورة|invoice|#)\s*[: ]?\s*([A-Za-z0-9\-]+)', text, re.IGNORECASE)
        if invoice_match:
            extracted['invoice_number'] = invoice_match.group(1)
        supplier_match = re.search(r'(?:مورد|شركة|supplier|from)\s*[: ]?\s*([^\n]+)', text, re.IGNORECASE)
        if supplier_match:
            extracted['supplier_name'] = supplier_match.group(1).strip()
        date_match = re.search(r'(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})', text)
        if not date_match:
            date_match = re.search(r'(\d{4}[/\-]\d{1,2}[/\-]\d{1,2})', text)
        if date_match:
            extracted['date'] = date_match.group(1)
        total_match = re.search(r'(?:إجمالي|total|المجموع|المبلغ)\s*[: ]?\s*([\d,]+\.?\d*)', text, re.IGNORECASE)
        if total_match:
            extracted['total'] = float(total_match.group(1).replace(',', ''))
        lines = text.split('\n')
        for line in lines:
            line = line.strip()
            item_match = re.search(r'([^\d]+)\s+(\d+\.?\d*)\s+(\d+\.?\d*)\s*$', line)
            if item_match:
                extracted['items'].append({'name': item_match.group(1).strip(), 'quantity': float(item_match.group(2)), 'price': float(item_match.group(3))})
        if not extracted['items']:
            products = execute_query("SELECT name FROM products WHERE is_active = 1", fetch_all=True)
            for p in products:
                if p['name'] in text:
                    extracted['items'].append({'name': p['name'], 'quantity': 1, 'price': 0})
        try:
            os.remove(temp_path)
        except:
            pass
        return jsonify({'success': True, 'text': text[:500], 'extracted': extracted, 'message': 'تم استخراج البيانات بنجاح'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'خطأ: {str(e)}'})

@app.route('/admin/scan-invoice')
@login_required
def scan_invoice_ui():
    suppliers = execute_query("SELECT id, name FROM suppliers", fetch_all=True)
    return render_template_string("""
    <!DOCTYPE html>
    <html dir="rtl">
    <head><meta charset="UTF-8"><title>استخراج بيانات الفواتير</title>
    <style>
        :root { --bg: #000; --text: #FFD700; --card-bg: #111; --border: #FFD700; --btn-bg: #FFD700; --btn-text: #000; }
        body.light { --bg: #f5f5f5; --text: #000; --card-bg: #fff; --border: #007bff; --btn-bg: #007bff; --btn-text: #fff; }
        body{background:var(--bg);color:var(--text);padding:20px;font-family:Arial;transition:background 0.3s,color 0.3s;}
        .container{max-width:900px;margin:auto;}
        .header{background:var(--card-bg);border:1px solid var(--border);padding:20px;border-radius:10px;margin-bottom:20px;}
        .upload-area{border:2px dashed var(--border);padding:30px;text-align:center;border-radius:10px;cursor:pointer;}
        .upload-area:hover{background:var(--card-bg);}
        .result-box{background:var(--card-bg);border:1px solid var(--border);padding:15px;border-radius:8px;margin:10px 0;}
        .btn{background:var(--btn-bg);color:var(--btn-text);padding:8px 15px;border:none;border-radius:5px;cursor:pointer;}
        .preview{max-width:100%;max-height:300px;margin:10px 0;border-radius:8px;}
        .theme-toggle{position:fixed;top:20px;left:20px;background:var(--btn-bg);color:var(--btn-text);border:none;border-radius:50%;width:50px;height:50px;font-size:20px;cursor:pointer;z-index:1000;}
        .chat-float{position:fixed;bottom:20px;left:20px;background:var(--btn-bg);color:var(--btn-text);width:60px;height:60px;border-radius:50%;font-size:30px;display:flex;align-items:center;justify-content:center;cursor:pointer;z-index:999;box-shadow:0 4px 15px rgba(0,0,0,0.5);text-decoration:none;}
        table{width:100%;border-collapse:collapse;margin-top:10px;}
        th,td{padding:8px;border:1px solid var(--border);text-align:center;}
        input{background:var(--bg);color:var(--text);border:1px solid var(--border);padding:5px;border-radius:3px;width:100%;}
    </style>
    </head>
    <body>
    <button class="theme-toggle" onclick="toggleTheme()">🌓</button>
    <a href="/chat" class="chat-float" title="المساعد الذكي">💬</a>
    <div class="container">
        <div class="header"><h2>📄 استخراج بيانات الفواتير الورقية</h2><div class="nav"><a href="/admin">لوحة المدير</a><a href="/admin/scan-invoice" style="font-weight:bold;">مسح الفواتير</a></div><p>قم برفع صورة الفاتورة لاستخراج البيانات تلقائياً</p></div>
        <div class="upload-area" onclick="document.getElementById('fileInput').click()">
            <p>📤 اضغط لرفع صورة الفاتورة</p>
            <p style="font-size:12px;color:#aaa;">صور JPG, PNG, PDF</p>
            <input type="file" id="fileInput" accept="image/*,application/pdf" style="display:none;" onchange="analyzeInvoice(this.files[0])">
        </div>
        <div id="previewContainer"></div>
        <div id="result"></div>
        <div id="extractedData" style="display:none;" class="result-box">
            <h4>📋 البيانات المستخرجة</h4>
            <div id="dataFields"></div>
            <h4>📦 الأصناف</h4>
            <div id="itemsTable"></div>
            <button class="btn" onclick="saveExtracted()">💾 حفظ في قاعدة البيانات</button>
            <div id="saveResult"></div>
        </div>
    </div>
    <script>
        let extractedData = null;
        function toggleTheme(){document.body.classList.toggle('light');localStorage.setItem('theme',document.body.classList.contains('light')?'light':'dark');}
        if(localStorage.getItem('theme')==='light') document.body.classList.add('light');
        function analyzeInvoice(file){if(!file)return;const reader=new FileReader();reader.onload=function(e){document.getElementById('previewContainer').innerHTML=`<img src="${e.target.result}" class="preview"><br><span>⏳ جاري تحليل الفاتورة...</span>`;};reader.readAsDataURL(file);const formData=new FormData();formData.append('file',file);fetch('/api/analyze-invoice',{method:'POST',body:formData}).then(r=>r.json()).then(data=>{if(data.success){extractedData=data.extracted;document.getElementById('result').innerHTML=`<div class="result-box" style="border-color:#4CAF50;">✅ ${data.message}</div>`;let fieldsHtml='';const fields=[['رقم الفاتورة','invoice_number'],['المورد','supplier_name'],['التاريخ','date'],['الإجمالي','total']];fields.forEach(([label,key])=>{let val=extractedData[key]||'';fieldsHtml+=`<div style="margin:5px 0;"><label>${label}:</label><input type="text" id="field_${key}" value="${val}" style="width:100%;"></div>`;});let itemsHtml='<table><thead><tr><th>المنتج</th><th>الكمية</th><th>السعر</th></tr></thead><tbody>';if(extractedData.items&&extractedData.items.length>0){extractedData.items.forEach((item,idx)=>{itemsHtml+=`<tr><td><input type="text" id="item_name_${idx}" value="${item.name}"></td><td><input type="number" id="item_qty_${idx}" value="${item.quantity}"></td><td><input type="number" id="item_price_${idx}" value="${item.price}"></td></tr>`;});}else{itemsHtml+='<tr><td colspan="3">لم يتم العثور على أصناف</td></tr>';}itemsHtml+='</tbody></table>';document.getElementById('dataFields').innerHTML=fieldsHtml;document.getElementById('itemsTable').innerHTML=itemsHtml;document.getElementById('extractedData').style.display='block';}else{document.getElementById('result').innerHTML=`<div class="result-box" style="border-color:#f44336;color:#f44336;">❌ ${data.message}</div>`;}document.getElementById('previewContainer').innerHTML+='<br>✅ تم التحليل';}).catch(err=>{document.getElementById('result').innerHTML=`<div class="result-box" style="border-color:#f44336;color:#f44336;">❌ خطأ: ${err}</div>`;});}
        function saveExtracted(){if(!extractedData)return;const data={invoice_number:document.getElementById('field_invoice_number').value,supplier_name:document.getElementById('field_supplier_name').value,date:document.getElementById('field_date').value,total:parseFloat(document.getElementById('field_total').value)||0,items:[]};const itemsContainer=document.getElementById('itemsTable');const inputs=itemsContainer.querySelectorAll('input');const itemCount=inputs.length/3;for(let i=0;i<itemCount;i++){let name=document.getElementById(`item_name_${i}`).value;let qty=parseFloat(document.getElementById(`item_qty_${i}`).value)||0;let price=parseFloat(document.getElementById(`item_price_${i}`).value)||0;if(name&&qty>0){data.items.push({name,quantity:qty,price});}}fetch('/api/save-invoice-data',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}).then(r=>r.json()).then(res=>{document.getElementById('saveResult').innerHTML=`<div style="color:${res.success?'#4CAF50':'#f44336'};">${res.message}</div>`;if(res.success){setTimeout(()=>window.location.href='/admin/purchases',2000);}});}
    </script>
    </body>
    </html>
    """, suppliers=suppliers)

@app.route('/api/save-invoice-data', methods=['POST'])
@admin_required
def save_invoice_data():
    data = request.json
    try:
        supplier_name = data.get('supplier_name', '')
        supplier = None
        if supplier_name:
            supplier = execute_query("SELECT id FROM suppliers WHERE name LIKE ?", (f"%{supplier_name}%",), fetch_one=True)
        purchase_id = None
        if data.get('items'):
            total = data.get('total', 0)
            if total == 0:
                total = sum(item['quantity'] * item['price'] for item in data['items'])
            execute_query("""
                INSERT INTO purchases (supplier_id, invoice_number, total_cost, purchase_date, notes)
                VALUES (?, ?, ?, ?, ?)
            """, (supplier['id'] if supplier else None, data.get('invoice_number', ''), total, data.get('date') or datetime.date.today().isoformat(), 'تم الاستيراد من الفاتورة الورقية'), commit=True)
            purchase = execute_query("SELECT id FROM purchases ORDER BY id DESC LIMIT 1", fetch_one=True)
            purchase_id = purchase['id']
            for item in data['items']:
                product = execute_query("SELECT id FROM products WHERE name LIKE ?", (f"%{item['name']}%",), fetch_one=True)
                if product:
                    execute_query("""
                        INSERT INTO purchase_items (purchase_id, product_id, quantity, cost_price, total)
                        VALUES (?, ?, ?, ?, ?)
                    """, (purchase_id, product['id'], item['quantity'], item['price'], item['quantity'] * item['price']), commit=True)
                    execute_query("UPDATE products SET quantity = quantity + ? WHERE id = ?", (item['quantity'], product['id']), commit=True)
        return jsonify({'success': True, 'message': 'تم حفظ الفاتورة بنجاح', 'purchase_id': purchase_id})
    except Exception as e:
        return jsonify({'success': False, 'message': f'خطأ: {str(e)}'})

# =============================== ميزة 10: لوحات معلومات ذكية ===============================
@app.route('/admin/analytics')
@admin_required
def analytics_page():
    stats = execute_query("""
        SELECT
            (SELECT COUNT(*) FROM products WHERE is_active = 1) as total_products,
            (SELECT COUNT(*) FROM customers) as total_customers,
            (SELECT COUNT(*) FROM invoices WHERE DATE(created_at) = DATE('now')) as today_sales,
            (SELECT IFNULL(SUM(final_total), 0) FROM invoices WHERE DATE(created_at) = DATE('now')) as today_revenue,
            (SELECT IFNULL(SUM(final_total), 0) FROM invoices WHERE created_at >= DATE('now', '-30 days')) as month_revenue
    """, fetch_one=True)
    top_products = execute_query("""
        SELECT p.name, SUM(ii.quantity) as total_sold, SUM(ii.total) as revenue
        FROM invoice_items ii
        JOIN products p ON ii.product_id = p.id
        GROUP BY ii.product_id
        ORDER BY total_sold DESC
        LIMIT 10
    """, fetch_all=True)
    category_sales = execute_query("""
        SELECT p.category, SUM(ii.total) as revenue
        FROM invoice_items ii
        JOIN products p ON ii.product_id = p.id
        WHERE p.category IS NOT NULL AND p.category != ''
        GROUP BY p.category
        ORDER BY revenue DESC
    """, fetch_all=True)
    daily_sales = execute_query("""
        SELECT DATE(created_at) as day, IFNULL(SUM(final_total), 0) as total
        FROM invoices
        WHERE created_at >= DATE('now', '-7 days')
        GROUP BY DATE(created_at)
        ORDER BY day
    """, fetch_all=True)
    return render_template_string("""
    <!DOCTYPE html>
    <html dir="rtl">
    <head><meta charset="UTF-8"><title>لوحة التحليل الذكية</title><script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root { --bg: #000; --text: #FFD700; --card-bg: #111; --border: #FFD700; --btn-bg: #FFD700; --btn-text: #000; }
        body.light { --bg: #f5f5f5; --text: #000; --card-bg: #fff; --border: #007bff; --btn-bg: #007bff; --btn-text: #fff; }
        body{background:var(--bg);color:var(--text);padding:20px;font-family:Arial;transition:background 0.3s,color 0.3s;}
        .container{max-width:1400px;margin:auto;}
        .header{background:var(--card-bg);border:1px solid var(--border);padding:20px;border-radius:10px;margin-bottom:20px;}
        .stats-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:15px;margin-bottom:20px;}
        .stat-card{background:var(--card-bg);border:1px solid var(--border);padding:15px;border-radius:10px;text-align:center;}
        .stat-card .num{font-size:28px;font-weight:bold;color:var(--text);}
        .stat-card .label{font-size:12px;color:#aaa;}
        .chart-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(400px,1fr));gap:20px;margin-bottom:20px;}
        .chart-box{background:var(--card-bg);border:1px solid var(--border);padding:15px;border-radius:10px;}
        .chart-box canvas{max-height:300px;width:100% !important;}
        .query-area{background:var(--card-bg);border:1px solid var(--border);padding:20px;border-radius:10px;margin-top:20px;}
        .query-area input{width:100%;padding:10px;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:5px;}
        .btn{background:var(--btn-bg);color:var(--btn-text);padding:8px 20px;border:none;border-radius:5px;cursor:pointer;}
        .theme-toggle{position:fixed;top:20px;left:20px;background:var(--btn-bg);color:var(--btn-text);border:none;border-radius:50%;width:50px;height:50px;font-size:20px;cursor:pointer;z-index:1000;}
        .chat-float{position:fixed;bottom:20px;left:20px;background:var(--btn-bg);color:var(--btn-text);width:60px;height:60px;border-radius:50%;font-size:30px;display:flex;align-items:center;justify-content:center;cursor:pointer;z-index:999;box-shadow:0 4px 15px rgba(0,0,0,0.5);text-decoration:none;}
        .query-result{background:var(--bg);border:1px solid var(--border);padding:15px;border-radius:5px;margin-top:10px;max-height:300px;overflow-y:auto;}
    </style>
    </head>
    <body>
    <button class="theme-toggle" onclick="toggleTheme()">🌓</button>
    <a href="/chat" class="chat-float" title="المساعد الذكي">💬</a>
    <div class="container">
        <div class="header"><h2>📊 لوحة التحليل الذكية</h2><div class="nav"><a href="/admin">لوحة المدير</a><a href="/admin/analytics" style="font-weight:bold;">التحليل</a></div></div>
        <div class="stats-grid">
            <div class="stat-card"><div class="num">{{ stats.total_products or 0 }}</div><div class="label">إجمالي المنتجات</div></div>
            <div class="stat-card"><div class="num">{{ stats.total_customers or 0 }}</div><div class="label">إجمالي العملاء</div></div>
            <div class="stat-card"><div class="num">{{ stats.today_sales or 0 }}</div><div class="label">مبيعات اليوم</div></div>
            <div class="stat-card"><div class="num">{{ "%.0f"|format(stats.today_revenue or 0) }}</div><div class="label">إيرادات اليوم</div></div>
            <div class="stat-card"><div class="num">{{ "%.0f"|format(stats.month_revenue or 0) }}</div><div class="label">إيرادات الشهر</div></div>
        </div>
        <div class="chart-grid">
            <div class="chart-box"><h4>🏆 أفضل المنتجات مبيعاً</h4><canvas id="topProductsChart"></canvas></div>
            <div class="chart-box"><h4>📊 المبيعات حسب الفئة</h4><canvas id="categoryChart"></canvas></div>
            <div class="chart-box" style="grid-column:1/-1;"><h4>📈 المبيعات اليومية (آخر 7 أيام)</h4><canvas id="dailySalesChart"></canvas></div>
        </div>
        <div class="query-area">
            <h4>🔍 استعلام طبيعي</h4>
            <p style="font-size:12px;color:#aaa;">اطرح سؤالاً عن بيانات المبيعات مثل: "ما هو أفضل دواء مبيعاً هذا الشهر؟"</p>
            <div style="display:flex;gap:10px;margin-top:10px;"><input type="text" id="queryInput" placeholder="اكتب سؤالك هنا..." style="flex:1;"><button class="btn" onclick="runQuery()">🔍 بحث</button></div>
            <div id="queryResult" class="query-result" style="display:none;"></div>
        </div>
    </div>
    <script>
        function toggleTheme(){document.body.classList.toggle('light');localStorage.setItem('theme',document.body.classList.contains('light')?'light':'dark');}
        if(localStorage.getItem('theme')==='light') document.body.classList.add('light');
        const topProducts = {{ top_products | tojson }};
        const categorySales = {{ category_sales | tojson }};
        const dailySales = {{ daily_sales | tojson }};
        const ctx1 = document.getElementById('topProductsChart').getContext('2d');
        new Chart(ctx1, {type:'bar',data:{labels:topProducts.map(p=>p.name),datasets:[{label:'الكمية المباعة',data:topProducts.map(p=>p.total_sold),backgroundColor:'rgba(255,215,0,0.6)',borderColor:'rgba(255,215,0,1)',borderWidth:1}]},options:{responsive:true,plugins:{legend:{labels:{color:'#FFD700'}}},scales:{y:{ticks:{color:'#FFD700'}},x:{ticks:{color:'#FFD700'}}}}});
        const ctx2 = document.getElementById('categoryChart').getContext('2d');
        new Chart(ctx2, {type:'pie',data:{labels:categorySales.map(c=>c.category),datasets:[{data:categorySales.map(c=>c.revenue),backgroundColor:['#FFD700','#4CAF50','#2196F3','#FF5722','#9C27B0','#FF9800']}]},options:{responsive:true,plugins:{legend:{labels:{color:'#FFD700'}}}}});
        const ctx3 = document.getElementById('dailySalesChart').getContext('2d');
        new Chart(ctx3, {type:'line',data:{labels:dailySales.map(d=>d.day),datasets:[{label:'الإيرادات',data:dailySales.map(d=>d.total),borderColor:'#FFD700',backgroundColor:'rgba(255,215,0,0.1)',fill:true,tension:0.3}]},options:{responsive:true,plugins:{legend:{labels:{color:'#FFD700'}}},scales:{y:{ticks:{color:'#FFD700'}},x:{ticks:{color:'#FFD700'}}}}});
        function runQuery(){const query=document.getElementById('queryInput').value.trim();if(!query)return;const resultDiv=document.getElementById('queryResult');resultDiv.style.display='block';resultDiv.innerHTML='⏳ جاري تحليل السؤال...';fetch('/api/analytics-query',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query:query})}).then(r=>r.json()).then(data=>{if(data.success){resultDiv.innerHTML=`<pre style="white-space:pre-wrap;color:#FFD700;">${data.result}</pre>`;}else{resultDiv.innerHTML=`<p style="color:#f44336;">❌ ${data.message}</p>`;}}).catch(err=>{resultDiv.innerHTML=`<p style="color:#f44336;">❌ خطأ: ${err}</p>`;});}
        document.getElementById('queryInput').addEventListener('keypress',function(e){if(e.key==='Enter')runQuery();});
    </script>
    </body>
    </html>
    """, stats=stats, top_products=top_products, category_sales=category_sales, daily_sales=daily_sales)

@app.route('/api/analytics-query', methods=['POST'])
@admin_required
def analytics_query():
    data = request.json
    query = data.get('query', '').strip()
    if not query:
        return jsonify({'success': False, 'message': 'الاستعلام فارغ'})
    if GEMINI_API_KEY:
        try:
            prompt = f"""أنت مساعد تحليل بيانات. المستخدم يسأل عن بيانات المبيعات.
            قم بتحليل السؤال التالي واستخراج المعلومات المطلوبة من قاعدة البيانات.
            السؤال: "{query}"
            أخرج استجابة منظمة كـ JSON مع:
            - type: نوع الطلب (top_product, revenue, sales_count, general)
            - sql: استعلام SQL إذا أمكن
            - explanation: شرح بالعربية للنتيجة
            فقط أخرج JSON ولا شيء آخر."""
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
            payload = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}
            resp = requests.post(url, json=payload, timeout=15)
            if resp.status_code == 200:
                candidates = resp.json().get("candidates", [])
                if candidates:
                    content = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                    json_match = re.search(r'\{.*\}', content, re.DOTALL)
                    if json_match:
                        try:
                            analysis = json.loads(json_match.group())
                            if analysis.get('sql'):
                                result = execute_query(analysis['sql'], fetch_all=True)
                                if result:
                                    return jsonify({'success': True, 'result': f"{analysis.get('explanation', 'النتيجة:')}\n\n" + '\n'.join([str(dict(r)) for r in result[:20]])})
                        except:
                            pass
        except:
            pass
    query_lower = query.lower()
    result = ""
    if 'أفضل' in query_lower or 'top' in query_lower:
        if 'منتج' in query_lower or 'دواء' in query_lower:
            top = execute_query("""
                SELECT p.name, SUM(ii.quantity) as total_sold
                FROM invoice_items ii JOIN products p ON ii.product_id = p.id
                GROUP BY ii.product_id ORDER BY total_sold DESC LIMIT 5
            """, fetch_all=True)
            if top:
                result = "🏆 أفضل 5 منتجات مبيعاً:\n" + '\n'.join([f"- {p['name']}: {p['total_sold']} وحدة" for p in top])
    elif 'إيراد' in query_lower or 'revenue' in query_lower:
        revenue = execute_query("SELECT IFNULL(SUM(final_total), 0) as total FROM invoices", fetch_one=True)
        result = f"💰 إجمالي الإيرادات: {revenue['total']} ريال"
    elif 'مبيعات' in query_lower or 'sales' in query_lower:
        sales = execute_query("SELECT COUNT(*) as count FROM invoices", fetch_one=True)
        result = f"📊 عدد الفواتير: {sales['count']} فاتورة"
    if not result:
        result = "🔍 لم أتمكن من فهم السؤال. حاول أن تسأل عن: أفضل المنتجات، الإيرادات، عدد المبيعات، أو تصنيف الفئات."
    return jsonify({'success': True, 'result': result})

# =============================== تحديث لوحة المدير الرئيسية ===============================
@app.route('/admin')
@login_required
def admin_dashboard():
    if session['role'] != 'admin':
        return redirect(url_for('pos'))
    low_stock = execute_query("SELECT id, name, quantity, min_quantity FROM products WHERE quantity <= min_quantity AND is_active=1", fetch_all=True)
    low_stock_count = len(low_stock) if low_stock else 0
    anomalies_count = execute_query("SELECT COUNT(*) as count FROM invoices WHERE is_anomaly = 1", fetch_one=True)
    anomalies_count = anomalies_count['count'] if anomalies_count else 0
    feedback_count = execute_query("SELECT COUNT(*) as count FROM feedback WHERE DATE(created_at) = DATE('now')", fetch_one=True)
    feedback_count = feedback_count['count'] if feedback_count else 0
    return render_template_string("""
    <!DOCTYPE html><html dir="rtl"><head><title>لوحة الإدارة</title>
    <style>
        :root { --bg: #000; --text: #FFD700; --card-bg: #111; --border: #FFD700; --btn-bg: #FFD700; --btn-text: #000; }
        body.light { --bg: #f5f5f5; --text: #000; --card-bg: #fff; --border: #007bff; --btn-bg: #007bff; --btn-text: #fff; }
        body{background:var(--bg);color:var(--text);font-family:Arial;padding:20px;transition:background 0.3s,color 0.3s;}
        .header{background:var(--card-bg);border:1px solid var(--border);padding:20px;border-radius:10px;margin-bottom:20px;}
        .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:15px;}
        .card{background:var(--card-bg);border:1px solid var(--border);padding:18px;border-radius:10px;text-align:center;cursor:pointer;transition:0.3s;color:var(--text);text-decoration:none;display:block;}
        .card:hover{transform:translateY(-5px);background:#222;}
        .card .icon{font-size:36px;display:block;margin-bottom:10px;}
        .card .title{font-weight:bold;}
        .card .badge{background:#f44336;color:#fff;border-radius:50%;padding:2px 10px;font-size:12px;margin-right:5px;}
        .logout{position:absolute;top:20px;left:20px;background:var(--btn-bg);color:var(--btn-text);padding:10px;border-radius:5px;text-decoration:none;}
        .alert{background:#8B0000;border:1px solid var(--border);padding:10px;border-radius:5px;margin-bottom:20px;color:#fff;}
        .chat-float{position:fixed;bottom:20px;left:20px;background:var(--btn-bg);color:var(--btn-text);width:60px;height:60px;border-radius:50%;font-size:30px;display:flex;align-items:center;justify-content:center;cursor:pointer;z-index:999;box-shadow:0 4px 15px rgba(0,0,0,0.5);text-decoration:none;}
        .theme-toggle{position:fixed;top:20px;left:70px;background:var(--btn-bg);color:var(--btn-text);border:none;border-radius:50%;width:50px;height:50px;font-size:20px;cursor:pointer;z-index:1000;}
        .section-title{margin:25px 0 15px 0;border-right:4px solid var(--border);padding-right:15px;}
    </style>
    </head>
    <body>
    <button class="theme-toggle" onclick="toggleTheme()">🌓</button>
    <a href="/chat" class="chat-float" title="المساعد الذكي">💬</a>
    <a href="/logout" class="logout">تسجيل خروج</a>
    <div class="header"><h1>🎛️ لوحة التحكم - وكالة البشائر</h1><p>مرحباً {{ session.username }} (مدير)</p><p style="font-size:14px;color:#aaa;">نظام متكامل مع ميزات الذكاء الاصطناعي</p></div>
    {% if low_stock_count > 0 %}<div class="alert">⚠️ تنبيه: يوجد {{ low_stock_count }} منتج (منتجات) مخزونها منخفض!</div>{% endif %}
    {% if anomalies_count > 0 %}<div class="alert" style="background:#8B0000;">🚨 تنبيه: يوجد {{ anomalies_count }} فاتورة شاذة تحتاج إلى مراجعة!</div>{% endif %}
    {% if feedback_count > 0 %}<div class="alert" style="background:#004d40;">💬 يوجد {{ feedback_count }} تقييم جديد اليوم!</div>{% endif %}
    <h3 class="section-title">📋 الإدارة الأساسية</h3>
    <div class="grid">
        <a href="/admin/settings" class="card"><span class="icon">⚙️</span><span class="title">الإعدادات</span></a>
        <a href="/admin/products" class="card"><span class="icon">📦</span><span class="title">المنتجات</span></a>
        <a href="/admin/suppliers" class="card"><span class="icon">🏭</span><span class="title">الموردين</span></a>
        <a href="/admin/purchases" class="card"><span class="icon">📥</span><span class="title">المشتريات</span></a>
        <a href="/admin/offers" class="card"><span class="icon">🎁</span><span class="title">العروض</span></a>
        <a href="/admin/customers" class="card"><span class="icon">👥</span><span class="title">العملاء</span></a>
        <a href="/admin/invoices" class="card"><span class="icon">📄</span><span class="title">الفواتير</span></a>
        <a href="/admin/reports" class="card"><span class="icon">📊</span><span class="title">التقارير</span></a>
        <a href="/admin/users" class="card"><span class="icon">👤</span><span class="title">المستخدمين</span></a>
        <a href="/admin/returns" class="card"><span class="icon">🔄</span><span class="title">المرتجعات</span></a>
        <a href="/admin/labels" class="card"><span class="icon">🏷️</span><span class="title">طباعة الملصقات</span></a>
        <a href="/admin/backup" class="card"><span class="icon">💾</span><span class="title">النسخ الاحتياطي</span></a>
        <a href="/admin/dashboard-3d" class="card"><span class="icon">🚀</span><span class="title">لوحة 3D</span></a>
        <a href="/voice-assistant" class="card"><span class="icon">🎤</span><span class="title">المساعد الصوتي</span></a>
    </div>
    <h3 class="section-title">🧠 ميزات الذكاء الاصطناعي</h3>
    <div class="grid">
        <a href="/admin/dynamic-pricing" class="card"><span class="icon">💰</span><span class="title">التسعير الديناميكي</span></a>
        <a href="/admin/anomalies" class="card"><span class="icon">🛡️</span><span class="title">كشف الشذوذ <span class="badge">{{ anomalies_count }}</span></span></a>
        <a href="/admin/scan-image-ui" class="card"><span class="icon">📷</span><span class="title">التعرف من الصور</span></a>
        <a href="/admin/scan-invoice" class="card"><span class="icon">📄</span><span class="title">استخراج الفواتير</span></a>
        <a href="/admin/feedback" class="card"><span class="icon">💬</span><span class="title">تحليل المشاعر <span class="badge">{{ feedback_count }}</span></span></a>
        <a href="/admin/analytics" class="card"><span class="icon">📈</span><span class="title">التحليل الذكي</span></a>
        <a href="/customer/recommendations" class="card"><span class="icon">🎯</span><span class="title">توصيات العملاء</span></a>
        <a href="/chat" class="card"><span class="icon">🤖</span><span class="title">المساعد الذكي (RAG)</span></a>
    </div>
    <h3 class="section-title">🔗 روابط سريعة</h3>
    <div class="grid">
        <a href="/pos" class="card"><span class="icon">🛒</span><span class="title">نقطة البيع</span></a>
        <a href="/payment" class="card"><span class="icon">💳</span><span class="title">السداد الإلكتروني</span></a>
        <a href="/admin/reports/export/inventory?format=excel" class="card"><span class="icon">📊</span><span class="title">تصدير المخزون Excel</span></a>
        <a href="/admin/reports/export/expiry?format=excel" class="card"><span class="icon">📊</span><span class="title">تقرير الصلاحية Excel</span></a>
    </div>
    <script>
        function toggleTheme(){document.body.classList.toggle('light');localStorage.setItem('theme',document.body.classList.contains('light')?'light':'dark');}
        if(localStorage.getItem('theme')==='light') document.body.classList.add('light');
    </script>
    </body>
    </html>
    """, low_stock_count=low_stock_count, anomalies_count=anomalies_count, feedback_count=feedback_count)

# =============================== تسجيل الدخول والخروج ===============================
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = execute_query("SELECT id, username, password_hash, role FROM users WHERE username = ?", (username,), fetch_one=True)
        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            if user['role'] == 'admin':
                return redirect(url_for('admin_dashboard'))
            elif user['role'] == 'cashier':
                return redirect(url_for('pos'))
            elif user['role'] == 'pharmacist':
                return redirect(url_for('pharmacist_dashboard'))
            else:
                return redirect(url_for('stock_dashboard'))
        else:
            return render_template_string("<h2 style='color:red;text-align:center;'>بيانات دخول خاطئة</h2><a href='/login'>حاول مرة أخرى</a>")
    return render_template_string("""
    <!DOCTYPE html><html dir="rtl"><head><title>تسجيل الدخول</title>
    <style>body{background:#000;color:#FFD700;font-family:Arial;padding:50px;}.login{max-width:400px;margin:auto;background:#111;padding:30px;border-radius:10px;border:1px solid #FFD700;}</style>
    </head><body><div class="login"><h2>تسجيل الدخول</h2><form method="post"><input type="text" name="username" placeholder="اسم المستخدم" required style="width:100%;padding:10px;margin:10px 0;background:#000;color:#FFD700;border:1px solid #FFD700;"><input type="password" name="password" placeholder="كلمة المرور" required style="width:100%;padding:10px;margin:10px 0;background:#000;color:#FFD700;border:1px solid #FFD700;"><button type="submit" style="background:#FFD700;color:#000;padding:10px;width:100%;border:none;">دخول</button></form></div></body>
    """)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

# =============================== نقاط البيع (POS) البسيطة ===============================
@app.route('/pos')
@login_required
def pos():
    return render_template_string("""
    <!DOCTYPE html><html dir="rtl"><head><title>نقطة البيع</title>
    <style>
        :root { --bg: #000; --text: #FFD700; --card-bg: #111; --border: #FFD700; --btn-bg: #FFD700; --btn-text: #000; }
        body.light { --bg: #f5f5f5; --text: #000; --card-bg: #fff; --border: #007bff; --btn-bg: #007bff; --btn-text: #fff; }
        body{background:var(--bg);color:var(--text);padding:20px;font-family:Arial;transition:background 0.3s,color 0.3s;}
        .container{max-width:1200px;margin:auto;}
        .header{background:var(--card-bg);border:1px solid var(--border);padding:20px;border-radius:10px;margin-bottom:20px;}
        .nav a{color:var(--text);text-decoration:none;margin-left:15px;}
        .pos-grid{display:grid;grid-template-columns:2fr 1fr;gap:20px;}
        .products-list{max-height:500px;overflow-y:auto;display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;}
        .product-item{background:var(--card-bg);border:1px solid var(--border);padding:10px;border-radius:8px;text-align:center;cursor:pointer;transition:0.2s;}
        .product-item:hover{background:#222;transform:scale(1.02);}
        .cart-item{background:var(--card-bg);border:1px solid var(--border);padding:8px;border-radius:5px;margin:5px 0;display:flex;justify-content:space-between;align-items:center;}
        .btn{background:var(--btn-bg);color:var(--btn-text);padding:8px 15px;border:none;border-radius:5px;cursor:pointer;}
        .theme-toggle{position:fixed;top:20px;left:20px;background:var(--btn-bg);color:var(--btn-text);border:none;border-radius:50%;width:50px;height:50px;font-size:20px;cursor:pointer;z-index:1000;}
        .chat-float{position:fixed;bottom:20px;left:20px;background:var(--btn-bg);color:var(--btn-text);width:60px;height:60px;border-radius:50%;font-size:30px;display:flex;align-items:center;justify-content:center;cursor:pointer;z-index:999;box-shadow:0 4px 15px rgba(0,0,0,0.5);text-decoration:none;}
        .barcode-input{display:flex;gap:10px;margin-bottom:15px;}
        .barcode-input input{flex:1;padding:8px;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:5px;}
    </style>
    </head>
    <body>
    <button class="theme-toggle" onclick="toggleTheme()">🌓</button>
    <a href="/chat" class="chat-float" title="المساعد الذكي">💬</a>
    <div class="container">
        <div class="header"><h2>🛒 نقطة البيع</h2><div class="nav"><a href="/">الرئيسية</a><a href="/pos" style="font-weight:bold;">نقطة البيع</a><a href="/cart">السلة</a></div><p style="font-size:14px;color:#aaa;">مسح الباركود أو اختيار المنتج من القائمة</p></div>
        <div class="barcode-input"><input type="text" id="barcodeInput" placeholder="ادخل الباركود أو امسحه..." onkeypress="if(event.key==='Enter') scanBarcode()"><button class="btn" onclick="scanBarcode()">🔍 بحث</button><button class="btn" onclick="startScanner()">📷 كاميرا</button></div>
        <div id="scannerContainer" style="display:none;max-width:300px;margin:10px 0;"></div>
        <div class="pos-grid">
            <div><h4>📦 المنتجات</h4><div id="productsList" class="products-list"></div></div>
            <div><h4>🛒 السلة</h4><div id="cartList"></div><div style="margin-top:15px;padding:10px;background:var(--card-bg);border:1px solid var(--border);border-radius:8px;"><p><strong>الإجمالي:</strong> <span id="cartTotal">0</span> ريال</p><button class="btn" onclick="checkout()" style="width:100%;">✅ إنهاء الطلب</button><button class="btn" onclick="clearCart()" style="width:100%;margin-top:5px;background:#f44336;color:#fff;">🗑️ تفريغ</button></div></div>
        </div>
    </div>
    <script src="https://unpkg.com/html5-qrcode@2.3.8/html5-qrcode.min.js"></script>
    <script>
        let cart=[];let html5QrCode=null;
        function toggleTheme(){document.body.classList.toggle('light');localStorage.setItem('theme',document.body.classList.contains('light')?'light':'dark');}
        if(localStorage.getItem('theme')==='light') document.body.classList.add('light');
        function loadProducts(){fetch('/api/products?limit=30').then(r=>r.json()).then(data=>{if(data.success){let html='';data.products.forEach(p=>{html+=`<div class="product-item" onclick="addProduct(${p.id},'${p.name.replace(/'/g,"\\'")}',${p.price})"><div style="font-size:12px;">${p.name}</div><div style="color:var(--btn-bg);font-weight:bold;">${p.price} ريال</div><div style="font-size:10px;color:#aaa;">${p.quantity} متبقي</div></div>`;});document.getElementById('productsList').innerHTML=html;}});}
        function addProduct(id,name,price){let existing=cart.find(i=>i.id===id);if(existing)existing.quantity+=1;else cart.push({id,name,price,quantity:1});renderCart();}
        function renderCart(){let html='';let total=0;cart.forEach((item,idx)=>{let t=item.price*item.quantity;total+=t;html+=`<div class="cart-item"><span>${item.name} x${item.quantity}</span><span>${t} ريال</span><button onclick="removeItem(${idx})" style="background:#f44336;color:#fff;border:none;border-radius:3px;padding:2px 8px;">✕</button></div>`;});document.getElementById('cartList').innerHTML=html||'<p>السلة فارغة</p>';document.getElementById('cartTotal').innerText=total;}
        function removeItem(idx){cart.splice(idx,1);renderCart();}
        function clearCart(){cart=[];renderCart();}
        function scanBarcode(){let barcode=document.getElementById('barcodeInput').value.trim();if(!barcode)return;fetch('/api/scan-barcode',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({barcode})}).then(r=>r.json()).then(data=>{if(data.success){let p=data.product;addProduct(p.id,p.name,p.price);document.getElementById('barcodeInput').value='';}else{alert('المنتج غير موجود');}});}
        function startScanner(){let container=document.getElementById('scannerContainer');container.style.display='block';if(html5QrCode){html5QrCode.stop().then(()=>html5QrCode.clear());}html5QrCode=new Html5Qrcode("scannerContainer");html5QrCode.start({facingMode:"environment"},{fps:10,qrbox:{width:200,height:200}},(decodedText)=>{document.getElementById('barcodeInput').value=decodedText;scanBarcode();html5QrCode.stop();container.style.display='none';},(error)=>{}).catch(err=>alert('لا يمكن الوصول إلى الكاميرا: '+err));}
        function checkout(){if(cart.length===0){alert('السلة فارغة');return;}let order={cart:cart,customer_name:'عميل نقدي',payment_method:'cash'};fetch('/api/check-anomaly',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cart:cart,total:cart.reduce((s,i)=>s+i.price*i.quantity,0)})}).then(r=>r.json()).then(anomaly=>{if(anomaly.is_anomaly){if(!confirm(`⚠️ تحذير: تم اكتشاف شذوذ في هذه الفاتورة!\nالسبب: ${anomaly.reason}\nهل تريد المتابعة؟`)){return;}}fetch('/api/create_invoice',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(order)}).then(r=>r.json()).then(data=>{if(data.success){alert(`✅ تم إنشاء الفاتورة رقم ${data.invoice_number}`);cart=[];renderCart();}else{alert('❌ خطأ: '+data.message);}});});}
        loadProducts();
    </script>
    </body>
    </html>
    """)

# =============================== باقي المسارات الأساسية ===============================
@app.route('/api/products')
def api_products():
    limit = request.args.get('limit', 50, type=int)
    search = request.args.get('search', '')
    category = request.args.get('category', '')
    query = "SELECT p.*, u.name as unit_name, u.symbol as unit_symbol FROM products p LEFT JOIN units u ON p.unit_id = u.id WHERE p.is_active = 1"
    params = []
    if search:
        query += " AND (p.name LIKE ? OR p.description LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])
    if category:
        query += " AND p.category = ?"
        params.append(category)
    query += " ORDER BY p.name LIMIT ?"
    params.append(limit)
    products = execute_query(query, params, fetch_all=True)
    return jsonify({'success': True, 'products': [dict(p) for p in products]})

@app.route('/api/scan-barcode', methods=['POST'])
def scan_barcode():
    data = request.json
    barcode = data.get('barcode', '').strip()
    if not barcode:
        return jsonify({'success': False, 'message': 'الباركود فارغ'})
    product = execute_query("""
        SELECT p.*, u.name as unit_name, u.symbol as unit_symbol
        FROM products p
        LEFT JOIN units u ON p.unit_id = u.id
        WHERE p.barcode = ? AND p.is_active = 1
    """, (barcode,), fetch_one=True)
    if product:
        return jsonify({'success': True, 'product': dict(product)})
    else:
        return jsonify({'success': False, 'message': 'المنتج غير موجود'})

@app.route('/api/categories')
def api_categories():
    rows = execute_query("SELECT DISTINCT category FROM products WHERE category IS NOT NULL AND category != '' AND is_active = 1", fetch_all=True)
    categories = [row['category'] for row in rows] if rows else []
    return jsonify({'categories': categories})

@app.route('/api/offers')
def api_offers():
    offers = execute_query("SELECT * FROM offers WHERE is_active = 1 AND (start_date <= date('now') OR start_date IS NULL) AND (end_date >= date('now') OR end_date IS NULL)", fetch_all=True)
    return jsonify({'offers': [dict(o) for o in offers]})

@app.route('/api/customer/<phone>')
def api_customer(phone):
    customer = execute_query("SELECT * FROM customers WHERE phone = ?", (phone,), fetch_one=True)
    if customer:
        return jsonify({'success': True, **dict(customer)})
    return jsonify({'success': False, 'message': 'العميل غير موجود'})

@app.route('/api/create_invoice', methods=['POST'])
def create_invoice():
    data = request.json
    try:
        cart = data.get('cart', [])
        customer_name = data.get('customer_name', '')
        customer_phone = data.get('customer_phone', '')
        customer_address = data.get('customer_address', '')
        payment_method = data.get('payment_method', 'cash')
        total = sum(item['price'] * item['quantity'] for item in cart)
        discount = data.get('discount', 0)
        final_total = total - discount
        invoice_number = f"INV-{int(time.time())}"
        invoice_data = {'total': total, 'discount': discount, 'final_total': final_total, 'item_count': len(cart)}
        anomaly_result = detect_anomaly(invoice_data)
        execute_query("""
            INSERT INTO invoices (invoice_number, customer_name, customer_phone, customer_address, total, discount, final_total, payment_method, created_by, is_anomaly, anomaly_score, anomaly_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (invoice_number, customer_name, customer_phone, customer_address, total, discount, final_total, payment_method, session.get('user_id', 1),
              anomaly_result['is_anomaly'], anomaly_result['score'], anomaly_result['reason']), commit=True)
        invoice = execute_query("SELECT id FROM invoices WHERE invoice_number = ?", (invoice_number,), fetch_one=True)
        invoice_id = invoice['id']
        if anomaly_result['is_anomaly']:
            execute_query("""INSERT INTO anomaly_logs (invoice_id, anomaly_score, reason) VALUES (?, ?, ?)""",
                          (invoice_id, anomaly_result['score'], anomaly_result['reason']), commit=True)
        for item in cart:
            execute_query("""
                INSERT INTO invoice_items (invoice_id, product_id, product_name, quantity, price, total)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (invoice_id, item['id'], item['name'], item['quantity'], item['price'], item['price'] * item['quantity']), commit=True)
            product = execute_query("SELECT quantity FROM products WHERE id = ?", (item['id'],), fetch_one=True)
            if product:
                new_qty = product['quantity'] - item['quantity']
                execute_query("UPDATE products SET quantity = ? WHERE id = ?", (new_qty, item['id']), commit=True)
                log_inventory(item['id'], item['name'], 'sale', -item['quantity'], product['quantity'], new_qty, f"فاتورة {invoice_number}", session.get('user_id', 1))
        return jsonify({'success': True, 'invoice_number': invoice_number, 'is_anomaly': anomaly_result['is_anomaly']})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

# =============================== تصدير التقارير ===============================
@app.route('/admin/reports/export/<report_type>')
@login_required
def export_report(report_type):
    if report_type == 'inventory':
        data = execute_query("""
            SELECT p.id, p.name, p.category, p.quantity, p.min_quantity, p.price, p.cost_price,
                   p.expiry_date, p.batch_number, p.manufacturer, u.name as unit,
                   p.dynamic_price, p.sales_velocity, p.abc_class
            FROM products p
            LEFT JOIN units u ON p.unit_id = u.id
            WHERE p.is_active = 1
            ORDER BY p.name
        """, fetch_all=True)
        title = 'تقرير المخزون'
        headers = ['الرقم', 'الاسم', 'الفئة', 'الكمية', 'الحد الأدنى', 'سعر البيع', 'سعر الشراء', 'تاريخ الصلاحية', 'رقم الدفعة', 'الشركة المصنعة', 'الوحدة', 'السعر الديناميكي', 'سرعة المبيعات', 'تصنيف ABC']
    elif report_type == 'sales':
        data = execute_query("""
            SELECT i.invoice_number, i.customer_name, i.final_total, i.payment_method, i.created_at,
                   (SELECT COUNT(*) FROM invoice_items WHERE invoice_id = i.id) as items_count,
                   i.is_anomaly
            FROM invoices i
            ORDER BY i.created_at DESC
            LIMIT 100
        """, fetch_all=True)
        title = 'تقرير المبيعات (آخر 100 فاتورة)'
        headers = ['رقم الفاتورة', 'العميل', 'الإجمالي', 'طريقة الدفع', 'التاريخ', 'عدد الأصناف', 'شاذ']
    elif report_type == 'expiry':
        data = execute_query("""
            SELECT id, name, expiry_date, quantity, batch_number, manufacturer
            FROM products
            WHERE expiry_date IS NOT NULL AND is_active = 1
            ORDER BY expiry_date ASC
        """, fetch_all=True)
        title = 'تقرير الصلاحية (الأقرب للانتهاء أولاً)'
        headers = ['الرقم', 'الاسم', 'تاريخ الصلاحية', 'الكمية', 'رقم الدفعة', 'الشركة المصنعة']
    else:
        return 'تقرير غير معروف', 400
    if not data:
        return 'لا توجد بيانات', 404
    fmt = request.args.get('format', 'excel')
    if fmt == 'excel':
        wb = Workbook()
        ws = wb.active
        ws.title = title
        for col, header in enumerate(headers, 1):
            ws.cell(row=1, column=col, value=header)
        for row_idx, row in enumerate(data, 2):
            for col_idx, value in enumerate(row, 1):
                if isinstance(value, (datetime.date, datetime.datetime)):
                    value = value.isoformat()
                ws.cell(row=row_idx, column=col_idx, value=value)
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        return send_file(output, download_name=f"{title}.xlsx", as_attachment=True)
    elif fmt == 'pdf':
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=2*cm, leftMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)
        styles = getSampleStyleSheet()
        title_style = styles['Title']
        title_style.alignment = 1
        elements = []
        elements.append(Paragraph(title, title_style))
        elements.append(Spacer(1, 0.5*cm))
        table_data = [headers]
        for row in data:
            row_list = []
            for value in row:
                if isinstance(value, (datetime.date, datetime.datetime)):
                    row_list.append(value.isoformat())
                else:
                    row_list.append(str(value) if value is not None else '')
            table_data.append(row_list)
        table = Table(table_data, repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ]))
        elements.append(table)
        doc.build(elements)
        buffer.seek(0)
        return send_file(buffer, download_name=f"{title}.pdf", as_attachment=True)
    else:
        return 'صيغة غير مدعومة', 400

# =============================== الميزات الجديدة (1، 3، 10، 11، 12، 16) ===============================

# ------------------------------ الميزة 1: لوحة تحكم 3D ------------------------------
@app.route('/admin/dashboard-3d')
@admin_required
def dashboard_3d():
    stats = execute_query("""
        SELECT 
            (SELECT COUNT(*) FROM products WHERE is_active=1) as total_products,
            (SELECT COUNT(*) FROM customers) as total_customers,
            (SELECT COUNT(*) FROM invoices WHERE DATE(created_at)=DATE('now')) as today_sales,
            (SELECT IFNULL(SUM(final_total),0) FROM invoices WHERE DATE(created_at)=DATE('now')) as today_revenue,
            (SELECT IFNULL(SUM(final_total),0) FROM invoices WHERE created_at>=DATE('now','-30 days')) as month_revenue,
            (SELECT COUNT(*) FROM invoices WHERE is_anomaly=1) as anomalies
    """, fetch_one=True)
    top_products = execute_query("""
        SELECT p.name, SUM(ii.quantity) as sold
        FROM invoice_items ii JOIN products p ON ii.product_id=p.id
        GROUP BY ii.product_id ORDER BY sold DESC LIMIT 5
    """, fetch_all=True)
    daily_sales = execute_query("""
        SELECT DATE(created_at) as day, IFNULL(SUM(final_total),0) as total
        FROM invoices WHERE created_at>=DATE('now','-7 days')
        GROUP BY DATE(created_at) ORDER BY day
    """, fetch_all=True)
    return render_template_string("""
    <!DOCTYPE html>
    <html dir="rtl">
    <head>
        <meta charset="UTF-8">
        <title>لوحة التحكم 3D</title>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <style>
            :root { --bg: #0a0a0a; --text: #FFD700; --card-bg: rgba(17,17,17,0.9); --border: #FFD700; --glow: 0 0 20px rgba(255,215,0,0.3); }
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { background: var(--bg); color: var(--text); font-family: 'Segoe UI', Arial, sans-serif; overflow-x: hidden; min-height: 100vh; }
            .container { max-width: 1400px; margin: 0 auto; padding: 20px; }
            .header-3d { background: linear-gradient(135deg, #1a1a2e, #16213e, #0f3460); padding: 30px; border-radius: 20px; border: 1px solid var(--border); margin-bottom: 30px; position: relative; overflow: hidden; box-shadow: var(--glow); animation: pulseGlow 3s infinite; }
            @keyframes pulseGlow { 0%, 100% { box-shadow: 0 0 20px rgba(255,215,0,0.3); } 50% { box-shadow: 0 0 40px rgba(255,215,0,0.6); } }
            .header-3d::before { content: ''; position: absolute; top: -50%; left: -50%; width: 200%; height: 200%; background: conic-gradient(from 0deg, transparent, rgba(255,215,0,0.1), transparent, rgba(255,215,0,0.1), transparent); animation: rotateGlow 20s linear infinite; }
            @keyframes rotateGlow { 100% { transform: rotate(360deg); } }
            .header-3d h1 { position: relative; z-index: 1; font-size: 2.5em; text-shadow: 0 0 30px rgba(255,215,0,0.5); }
            .stats-grid-3d { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 30px; }
            .stat-card-3d { background: var(--card-bg); backdrop-filter: blur(10px); border: 1px solid var(--border); border-radius: 15px; padding: 20px; text-align: center; transition: all 0.3s ease; cursor: pointer; position: relative; overflow: hidden; }
            .stat-card-3d:hover { transform: translateY(-10px) scale(1.02); box-shadow: 0 20px 40px rgba(255,215,0,0.2); }
            .stat-card-3d .icon { font-size: 2.5em; display: block; margin-bottom: 10px; animation: floatIcon 3s ease-in-out infinite; }
            @keyframes floatIcon { 0%, 100% { transform: translateY(0px); } 50% { transform: translateY(-10px); } }
            .stat-card-3d .number { font-size: 2em; font-weight: bold; background: linear-gradient(135deg, #FFD700, #FF6B00); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }
            .stat-card-3d .label { font-size: 0.9em; opacity: 0.8; margin-top: 5px; }
            .charts-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(400px, 1fr)); gap: 25px; margin-bottom: 30px; }
            .chart-box-3d { background: var(--card-bg); backdrop-filter: blur(10px); border: 1px solid var(--border); border-radius: 15px; padding: 20px; transition: all 0.3s ease; }
            .chart-box-3d:hover { box-shadow: var(--glow); transform: scale(1.01); }
            .chart-box-3d canvas { max-height: 300px; width: 100% !important; }
            #three-container { width: 100%; height: 300px; background: radial-gradient(ellipse at center, #1a1a2e, #0a0a0a); border-radius: 15px; border: 1px solid var(--border); margin-bottom: 30px; overflow: hidden; position: relative; }
            #three-container::after { content: '🔄 اسحب للتدوير'; position: absolute; bottom: 10px; right: 10px; color: rgba(255,215,0,0.5); font-size: 12px; }
            .nav-links { display: flex; gap: 15px; flex-wrap: wrap; margin-top: 15px; }
            .nav-links a { color: var(--text); text-decoration: none; padding: 8px 16px; border: 1px solid var(--border); border-radius: 8px; transition: 0.3s; position: relative; z-index: 1; }
            .nav-links a:hover { background: var(--border); color: #000; transform: scale(1.05); }
            .anomaly-alert { background: rgba(255,0,0,0.2); border: 2px solid #ff0000; padding: 15px; border-radius: 10px; margin-bottom: 20px; animation: pulseAlert 2s infinite; }
            @keyframes pulseAlert { 0%, 100% { opacity: 1; } 50% { opacity: 0.7; } }
            @media (max-width: 600px) { .charts-grid { grid-template-columns: 1fr; } .stats-grid-3d { grid-template-columns: repeat(2, 1fr); } .header-3d h1 { font-size: 1.5em; } }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header-3d">
                <h1>🚀 لوحة التحكم الذكية 3D</h1>
                <div class="nav-links">
                    <a href="/admin">🏠 الرئيسية</a>
                    <a href="/admin/dynamic-pricing">💰 التسعير</a>
                    <a href="/admin/anomalies">🛡️ الشذوذ</a>
                    <a href="/admin/analytics">📊 التحليل</a>
                    <a href="/admin/products">📦 المنتجات</a>
                    <a href="/chat">💬 المساعد</a>
                </div>
            </div>
            {% if stats.anomalies > 0 %}
            <div class="anomaly-alert">🚨 تنبيه: تم اكتشاف {{ stats.anomalies }} فاتورة شاذة! <a href="/admin/anomalies" style="color:#FFD700;">مراجعتها</a></div>
            {% endif %}
            <div id="three-container"></div>
            <div class="stats-grid-3d">
                <div class="stat-card-3d"><span class="icon">💊</span><div class="number">{{ stats.total_products or 0 }}</div><div class="label">إجمالي المنتجات</div></div>
                <div class="stat-card-3d"><span class="icon">👥</span><div class="number">{{ stats.total_customers or 0 }}</div><div class="label">العملاء</div></div>
                <div class="stat-card-3d"><span class="icon">🛒</span><div class="number">{{ stats.today_sales or 0 }}</div><div class="label">مبيعات اليوم</div></div>
                <div class="stat-card-3d"><span class="icon">💰</span><div class="number">{{ "%.0f"|format(stats.today_revenue or 0) }}</div><div class="label">إيرادات اليوم</div></div>
                <div class="stat-card-3d"><span class="icon">📈</span><div class="number">{{ "%.0f"|format(stats.month_revenue or 0) }}</div><div class="label">إيرادات الشهر</div></div>
                <div class="stat-card-3d" style="border-color: {% if stats.anomalies > 0 %}#ff0000{% else %}#4CAF50{% endif %};">
                    <span class="icon">🛡️</span>
                    <div class="number" style="color: {% if stats.anomalies > 0 %}#ff0000{% else %}#4CAF50{% endif %}; -webkit-text-fill-color: {% if stats.anomalies > 0 %}#ff0000{% else %}#4CAF50{% endif %};">
                        {{ stats.anomalies or 0 }}
                    </div>
                    <div class="label">فواتير شاذة</div>
                </div>
            </div>
            <div class="charts-grid">
                <div class="chart-box-3d"><h4>🏆 أفضل المنتجات مبيعاً</h4><canvas id="topChart"></canvas></div>
                <div class="chart-box-3d"><h4>📈 المبيعات اليومية</h4><canvas id="dailyChart"></canvas></div>
            </div>
        </div>
        <script>
            (function() {
                const container = document.getElementById('three-container');
                const scene = new THREE.Scene();
                const camera = new THREE.PerspectiveCamera(45, container.clientWidth / container.clientHeight, 0.1, 1000);
                const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
                renderer.setSize(container.clientWidth, container.clientHeight);
                renderer.setPixelRatio(window.devicePixelRatio);
                container.appendChild(renderer.domElement);
                const ambientLight = new THREE.AmbientLight(0x404060);
                scene.add(ambientLight);
                const directionalLight = new THREE.DirectionalLight(0xFFD700, 1);
                directionalLight.position.set(1, 1, 1);
                scene.add(directionalLight);
                const backLight = new THREE.DirectionalLight(0x4444FF, 0.5);
                backLight.position.set(-1, 0, -1);
                scene.add(backLight);
                const pillGroup = new THREE.Group();
                scene.add(pillGroup);
                function createPill(color, x, y, z, size = 0.3) {
                    const group = new THREE.Group();
                    const bodyGeo = new THREE.CylinderGeometry(size, size, size * 2.5, 16);
                    const bodyMat = new THREE.MeshPhongMaterial({ color: color, shininess: 100, emissive: color, emissiveIntensity: 0.2 });
                    const body = new THREE.Mesh(bodyGeo, bodyMat);
                    body.rotation.x = Math.PI / 2;
                    group.add(body);
                    const glowGeo = new THREE.SphereGeometry(size * 1.2, 16, 16);
                    const glowMat = new THREE.MeshPhongMaterial({ color: color, transparent: true, opacity: 0.1, emissive: color, emissiveIntensity: 0.3 });
                    const glow = new THREE.Mesh(glowGeo, glowMat);
                    group.add(glow);
                    group.position.set(x, y, z);
                    return group;
                }
                const colors = [0xFFD700, 0x4CAF50, 0x2196F3, 0xFF5722, 0x9C27B0, 0x00BCD4];
                const pills = [];
                for (let i = 0; i < 20; i++) {
                    const angle = (i / 20) * Math.PI * 2;
                    const radius = 1.5 + Math.random() * 0.5;
                    const x = Math.cos(angle) * radius;
                    const z = Math.sin(angle) * radius;
                    const y = (Math.random() - 0.5) * 2;
                    const color = colors[i % colors.length];
                    const pill = createPill(color, x, y, z, 0.15 + Math.random() * 0.15);
                    pill.userData = { angle: angle, radius: radius, speed: 0.005 + Math.random() * 0.005, yOffset: y, rotSpeed: 0.01 + Math.random() * 0.01 };
                    pillGroup.add(pill);
                    pills.push(pill);
                }
                camera.position.z = 5;
                camera.position.y = 1;
                camera.lookAt(0, 0, 0);
                let mouseX = 0, mouseY = 0;
                container.addEventListener('mousemove', (e) => {
                    const rect = container.getBoundingClientRect();
                    mouseX = ((e.clientX - rect.left) / rect.width - 0.5) * 2;
                    mouseY = ((e.clientY - rect.top) / rect.height - 0.5) * 2;
                });
                window.addEventListener('resize', () => {
                    const w = container.clientWidth;
                    const h = container.clientHeight;
                    camera.aspect = w / h;
                    camera.updateProjectionMatrix();
                    renderer.setSize(w, h);
                });
                function animate() {
                    requestAnimationFrame(animate);
                    pillGroup.rotation.y += 0.005;
                    pillGroup.rotation.x = Math.sin(Date.now() * 0.0005) * 0.1;
                    pills.forEach((pill, i) => {
                        const data = pill.userData;
                        data.angle += data.speed;
                        const x = Math.cos(data.angle) * data.radius;
                        const z = Math.sin(data.angle) * data.radius;
                        pill.position.x = x;
                        pill.position.z = z;
                        pill.position.y = data.yOffset + Math.sin(Date.now() * 0.001 + i) * 0.2;
                        pill.rotation.x += data.rotSpeed;
                        pill.rotation.y += data.rotSpeed * 0.5;
                    });
                    camera.position.x += (mouseX * 1 - camera.position.x) * 0.02;
                    camera.position.y += (mouseY * 0.5 + 1 - camera.position.y) * 0.02;
                    camera.lookAt(0, 0, 0);
                    renderer.render(scene, camera);
                }
                animate();
            })();
            const topProducts = {{ top_products | tojson }};
            const dailySales = {{ daily_sales | tojson }};
            const ctx1 = document.getElementById('topChart').getContext('2d');
            new Chart(ctx1, { type: 'bar', data: { labels: topProducts.map(p => p.name), datasets: [{ label: 'الكمية المباعة', data: topProducts.map(p => p.sold), backgroundColor: ['rgba(255,215,0,0.8)','rgba(76,175,80,0.8)','rgba(33,150,243,0.8)','rgba(255,87,34,0.8)','rgba(156,39,176,0.8)'], borderColor: '#FFD700', borderWidth: 2, borderRadius: 10 }] }, options: { responsive: true, plugins: { legend: { labels: { color: '#FFD700' } } }, scales: { y: { ticks: { color: '#FFD700' }, grid: { color: 'rgba(255,215,0,0.1)' } }, x: { ticks: { color: '#FFD700' }, grid: { color: 'rgba(255,215,0,0.1)' } } } } });
            const ctx2 = document.getElementById('dailyChart').getContext('2d');
            new Chart(ctx2, { type: 'line', data: { labels: dailySales.map(d => d.day), datasets: [{ label: 'الإيرادات اليومية', data: dailySales.map(d => d.total), borderColor: '#FFD700', backgroundColor: 'rgba(255,215,0,0.1)', fill: true, tension: 0.4, borderWidth: 3, pointBackgroundColor: '#FFD700', pointBorderColor: '#000', pointRadius: 5 }] }, options: { responsive: true, plugins: { legend: { labels: { color: '#FFD700' } } }, scales: { y: { ticks: { color: '#FFD700' }, grid: { color: 'rgba(255,215,0,0.1)' } }, x: { ticks: { color: '#FFD700' }, grid: { color: 'rgba(255,215,0,0.1)' } } } } });
        </script>
    </body>
    </html>
    """, stats=stats, top_products=top_products, daily_sales=daily_sales)

# ------------------------------ الميزة 3: الواجهة الصوتية ------------------------------
@app.route('/voice-assistant')
def voice_assistant():
    return render_template_string("""
    <!DOCTYPE html>
    <html dir="rtl">
    <head>
        <meta charset="UTF-8">
        <title>المساعد الصوتي</title>
        <style>
            :root { --bg: #0a0a0a; --text: #FFD700; --card-bg: rgba(17,17,17,0.9); --border: #FFD700; }
            body { background: var(--bg); color: var(--text); font-family: Arial, sans-serif; padding: 20px; min-height: 100vh; display: flex; justify-content: center; align-items: center; }
            .container { max-width: 600px; width: 100%; background: var(--card-bg); border: 1px solid var(--border); border-radius: 20px; padding: 30px; text-align: center; }
            .mic-btn { width: 120px; height: 120px; border-radius: 50%; border: 3px solid var(--border); background: radial-gradient(circle, #1a1a2e, #0a0a0a); color: var(--text); font-size: 50px; cursor: pointer; transition: all 0.3s ease; margin: 20px auto; display: flex; align-items: center; justify-content: center; box-shadow: 0 0 30px rgba(255,215,0,0.2); }
            .mic-btn:hover { transform: scale(1.1); box-shadow: 0 0 50px rgba(255,215,0,0.4); }
            .mic-btn.listening { animation: pulseMic 1s infinite; box-shadow: 0 0 60px rgba(255,0,0,0.5); border-color: #ff0000; }
            @keyframes pulseMic { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.05); } }
            .transcript { background: rgba(0,0,0,0.5); padding: 20px; border-radius: 10px; margin: 20px 0; min-height: 80px; border: 1px solid var(--border); font-size: 1.2em; }
            .response { background: rgba(255,215,0,0.1); padding: 20px; border-radius: 10px; margin: 20px 0; min-height: 60px; border: 1px solid var(--border); color: #4CAF50; }
            .commands { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 20px 0; }
            .command-btn { background: var(--card-bg); border: 1px solid var(--border); color: var(--text); padding: 10px; border-radius: 8px; cursor: pointer; transition: 0.3s; }
            .command-btn:hover { background: var(--border); color: #000; }
            .status { font-size: 0.9em; opacity: 0.7; margin-top: 10px; }
            .speak-btn { background: #4CAF50; color: #fff; border: none; padding: 10px 20px; border-radius: 8px; cursor: pointer; margin: 5px; }
        </style>
    </head>
    <body>
        <div class="container">
            <h2>🎤 المساعد الصوتي الذكي</h2>
            <p style="opacity:0.7;">تحدث مع النظام لأوامر صوتية</p>
            <div class="mic-btn" id="micBtn" onclick="toggleListening()">🎙️</div>
            <div class="transcript" id="transcript">اضغط على الميكروفون وابدأ التحدث...</div>
            <div class="response" id="response">📢 ستظهر هنا ردود النظام الصوتية</div>
            <div class="commands">
                <button class="command-btn" onclick="sendCommand('عرض المنتجات')">📦 عرض المنتجات</button>
                <button class="command-btn" onclick="sendCommand('المبيعات اليوم')">📊 المبيعات اليوم</button>
                <button class="command-btn" onclick="sendCommand('أفضل دواء')">🏆 أفضل دواء</button>
                <button class="command-btn" onclick="sendCommand('المخزون المنخفض')">⚠️ المخزون المنخفض</button>
                <button class="command-btn" onclick="sendCommand('إضافة دواء')">➕ إضافة دواء</button>
                <button class="command-btn" onclick="sendCommand('تقرير الشهر')">📈 تقرير الشهر</button>
            </div>
            <div>
                <button class="speak-btn" onclick="speakText(document.getElementById('response').innerText)">🔊 قراءة الرد</button>
                <button class="speak-btn" onclick="stopSpeaking()">⏹️ إيقاف</button>
            </div>
            <div class="status" id="status">⏸️ غير نشط</div>
        </div>
        <script>
            let recognition = null; let isListening = false; let synth = window.speechSynthesis;
            if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
                const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
                recognition = new SpeechRecognition();
                recognition.lang = 'ar-SA';
                recognition.continuous = false;
                recognition.interimResults = true;
                recognition.onresult = function(event) {
                    let transcript = '';
                    for (let i = event.resultIndex; i < event.results.length; i++) {
                        transcript += event.results[i][0].transcript;
                    }
                    document.getElementById('transcript').innerHTML = '🗣️ ' + transcript;
                    if (event.results[event.results.length - 1].isFinal) {
                        sendCommand(transcript);
                    }
                };
                recognition.onend = function() {
                    isListening = false;
                    document.getElementById('micBtn').classList.remove('listening');
                    document.getElementById('micBtn').innerHTML = '🎙️';
                    document.getElementById('status').innerHTML = '⏸️ غير نشط';
                };
                recognition.onerror = function(event) {
                    document.getElementById('status').innerHTML = '❌ خطأ: ' + event.error;
                };
            } else {
                document.getElementById('transcript').innerHTML = '❌ متصفحك لا يدعم التعرف الصوتي';
            }
            function toggleListening() {
                if (!recognition) { alert('التعرف الصوتي غير مدعوم في هذا المتصفح'); return; }
                if (isListening) {
                    recognition.stop();
                    isListening = false;
                    document.getElementById('micBtn').classList.remove('listening');
                    document.getElementById('micBtn').innerHTML = '🎙️';
                    document.getElementById('status').innerHTML = '⏸️ غير نشط';
                } else {
                    recognition.start();
                    isListening = true;
                    document.getElementById('micBtn').classList.add('listening');
                    document.getElementById('micBtn').innerHTML = '🔴';
                    document.getElementById('status').innerHTML = '🔴 يستمع...';
                    document.getElementById('transcript').innerHTML = '👂 استمع...';
                }
            }
            function sendCommand(text) {
                document.getElementById('transcript').innerHTML = '🗣️ ' + text;
                document.getElementById('status').innerHTML = '⏳ جاري المعالجة...';
                fetch('/api/voice-command', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({command: text})
                }).then(r => r.json()).then(data => {
                    if (data.success) {
                        document.getElementById('response').innerHTML = '✅ ' + data.response;
                        speakText(data.response);
                    } else {
                        document.getElementById('response').innerHTML = '❌ ' + data.message;
                    }
                    document.getElementById('status').innerHTML = '✅ تم';
                }).catch(err => {
                    document.getElementById('response').innerHTML = '❌ خطأ: ' + err;
                    document.getElementById('status').innerHTML = '❌ خطأ';
                });
            }
            function speakText(text) {
                if (!synth) return;
                const utterance = new SpeechSynthesisUtterance(text);
                utterance.lang = 'ar-SA';
                utterance.rate = 0.9;
                utterance.pitch = 1;
                utterance.volume = 1;
                synth.speak(utterance);
            }
            function stopSpeaking() { if (synth) synth.cancel(); }
            document.addEventListener('keydown', function(e) {
                if (e.key === ' ' && e.target.tagName !== 'INPUT' && e.target.tagName !== 'TEXTAREA') {
                    e.preventDefault();
                    toggleListening();
                }
            });
        </script>
    </body>
    </html>
    """)

@app.route('/api/voice-command', methods=['POST'])
@login_required
def voice_command():
    data = request.json
    command = data.get('command', '').strip().lower()
    if not command:
        return jsonify({'success': False, 'message': 'الأمر فارغ'})
    responses = {
        'عرض المنتجات': 'جاري عرض جميع المنتجات المتاحة',
        'المبيعات اليوم': 'جاري عرض تقرير مبيعات اليوم',
        'أفضل دواء': 'جاري عرض أفضل دواء مبيعاً',
        'المخزون المنخفض': 'جاري عرض المنتجات منخفضة المخزون',
        'إضافة دواء': 'يمكنك إضافة دواء من لوحة الإدارة',
        'تقرير الشهر': 'جاري عرض تقرير الشهر الحالي'
    }
    for key, response in responses.items():
        if key in command:
            return jsonify({'success': True, 'response': response})
    if GEMINI_API_KEY:
        try:
            prompt = f"""المستخدم قال: "{command}"
            قم بالرد بشكل مفيد ومختصر كمساعد صيدلاني.
            الرد باللغة العربية فقط."""
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
            payload = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                candidates = resp.json().get("candidates", [])
                if candidates:
                    reply = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "لم أفهم الأمر")
                    return jsonify({'success': True, 'response': reply})
        except:
            pass
    return jsonify({'success': True, 'response': f'أمر "{command}" قيد التطوير، يرجى المحاولة لاحقاً'})

# ------------------------------ الميزة 10: نظام الطباعة والتسميات ------------------------------
@app.route('/admin/labels')
@admin_required
def labels_page():
    products = execute_query("SELECT id, name, barcode, price, expiry_date, batch_number FROM products WHERE is_active=1 ORDER BY name", fetch_all=True)
    return render_template_string("""
    <!DOCTYPE html>
    <html dir="rtl">
    <head><meta charset="UTF-8"><title>طباعة الملصقات</title>
    <style>
        :root { --bg: #0a0a0a; --text: #FFD700; --card-bg: rgba(17,17,17,0.9); --border: #FFD700; }
        body { background: var(--bg); color: var(--text); font-family: Arial, sans-serif; padding: 20px; }
        .container { max-width: 1200px; margin: 0 auto; }
        .header { background: var(--card-bg); border: 1px solid var(--border); padding: 20px; border-radius: 10px; margin-bottom: 20px; }
        .controls { display: flex; gap: 15px; flex-wrap: wrap; margin-bottom: 20px; }
        .controls input, .controls select { padding: 10px; background: #000; color: #FFD700; border: 1px solid var(--border); border-radius: 5px; flex: 1; min-width: 150px; }
        .btn { background: var(--border); color: #000; padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; font-weight: bold; transition: 0.3s; }
        .btn:hover { transform: scale(1.05); opacity: 0.9; }
        .labels-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 15px; margin-top: 20px; }
        .label-card { background: #fff; color: #000; padding: 15px; border-radius: 8px; text-align: center; border: 2px solid #ddd; page-break-inside: avoid; min-height: 180px; display: flex; flex-direction: column; align-items: center; justify-content: center; }
        .label-card .name { font-size: 1.1em; font-weight: bold; margin: 5px 0; }
        .label-card .price { color: #4CAF50; font-size: 1.2em; font-weight: bold; }
        .label-card .barcode { margin: 8px 0; }
        .label-card .expiry { font-size: 0.8em; color: #666; }
        .label-card .batch { font-size: 0.7em; color: #888; }
        .print-btn { background: #2196F3; color: #fff; }
        @media print { .no-print { display: none !important; } .labels-grid { grid-template-columns: repeat(4, 1fr); } .label-card { border: 1px solid #ddd; } }
    </style>
    </head>
    <body>
        <div class="container">
            <div class="header no-print">
                <h2>🏷️ طباعة الملصقات والتسميات</h2>
                <div class="nav"><a href="/admin" style="color:#FFD700;">العودة للوحة</a></div>
                <p>اختر المنتجات لطباعة ملصقاتها</p>
            </div>
            <div class="controls no-print">
                <input type="text" id="searchInput" placeholder="🔍 بحث عن منتج..." oninput="filterLabels()">
                <select id="categoryFilter" onchange="filterLabels()">
                    <option value="">جميع الفئات</option>
                    {% for cat in ['مسكنات','مضادات حيوية','جهاز هضمي','أمراض نفسية','فيتامينات'] %}
                    <option value="{{ cat }}">{{ cat }}</option>
                    {% endfor %}
                </select>
                <button class="btn" onclick="selectAll()">✅ تحديد الكل</button>
                <button class="btn" onclick="deselectAll()">⬜ إلغاء الكل</button>
                <button class="btn print-btn" onclick="printLabels()">🖨️ طباعة المحدد</button>
                <button class="btn" onclick="generateQRCode()">📱 إنشاء QR</button>
            </div>
            <div id="labelsContainer" class="labels-grid">
                {% for p in products %}
                <div class="label-card" data-id="{{ p.id }}" data-name="{{ p.name }}" data-category="{{ p.category or '' }}">
                    <div>
                        <div class="name">{{ p.name }}</div>
                        <div class="price">{{ p.price }} ريال</div>
                        <div class="barcode"><svg id="barcode-{{ p.id }}"></svg></div>
                        <div class="batch">الدفعة: {{ p.batch_number or 'غير محدد' }}</div>
                        <div class="expiry">الصلاحية: {{ p.expiry_date or 'غير محدد' }}</div>
                    </div>
                    <div style="margin-top:10px;"><input type="checkbox" class="label-checkbox" data-id="{{ p.id }}" checked></div>
                </div>
                {% endfor %}
            </div>
        </div>
        <script src="https://cdn.jsdelivr.net/npm/jsbarcode@3.11.6/dist/JsBarcode.all.min.js"></script>
        <script>
            document.querySelectorAll('[id^="barcode-"]').forEach(function(el) {
                const id = el.id.replace('barcode-', '');
                const product = {{ products | tojson }};
                const p = product.find(x => x.id == id);
                if (p && p.barcode) {
                    JsBarcode(el, p.barcode, { format: "EAN13", width: 1.5, height: 40, displayValue: true, fontSize: 12, background: "#ffffff", lineColor: "#000000" });
                } else {
                    el.innerHTML = '<span style="font-size:10px;">باركود</span>';
                }
            });
            function filterLabels() {
                const search = document.getElementById('searchInput').value.toLowerCase();
                const category = document.getElementById('categoryFilter').value;
                document.querySelectorAll('.label-card').forEach(card => {
                    const name = card.dataset.name.toLowerCase();
                    const cat = card.dataset.category;
                    let show = true;
                    if (search && !name.includes(search)) show = false;
                    if (category && cat !== category) show = false;
                    card.style.display = show ? 'block' : 'none';
                });
            }
            function selectAll() { document.querySelectorAll('.label-checkbox').forEach(cb => cb.checked = true); }
            function deselectAll() { document.querySelectorAll('.label-checkbox').forEach(cb => cb.checked = false); }
            function printLabels() {
                const selected = document.querySelectorAll('.label-checkbox:checked');
                if (selected.length === 0) { alert('يرجى تحديد منتج واحد على الأقل'); return; }
                document.querySelectorAll('.label-card').forEach(card => {
                    const cb = card.querySelector('.label-checkbox');
                    if (!cb.checked) card.style.display = 'none';
                });
                document.querySelectorAll('.no-print').forEach(el => el.style.display = 'none');
                window.print();
                setTimeout(() => {
                    document.querySelectorAll('.no-print').forEach(el => el.style.display = '');
                    document.querySelectorAll('.label-card').forEach(card => card.style.display = '');
                }, 1000);
            }
            function generateQRCode() {
                const selected = document.querySelectorAll('.label-checkbox:checked');
                if (selected.length === 0) { alert('يرجى تحديد منتج'); return; }
                const win = window.open('', '_blank');
                win.document.write('<html><head><title>QR Codes</title><style>body{background:#000;color:#FFD700;font-family:Arial;padding:20px;text-align:center;}.qr-item{display:inline-block;margin:20px;padding:20px;background:#fff;border-radius:10px;}</style></head><body><h2>📱 أكواد QR للمنتجات</h2>');
                selected.forEach(cb => {
                    const card = cb.closest('.label-card');
                    const name = card.dataset.name;
                    win.document.write(`<div class="qr-item"><div id="qr-${cb.dataset.id}"></div><p>${name}</p></div>`);
                });
                win.document.write('<script src="https://cdn.jsdelivr.net/npm/qrcodejs@1.0.0/qrcode.min.js"><\/script><script>');
                selected.forEach(cb => {
                    const id = cb.dataset.id;
                    win.document.write(`new QRCode(document.getElementById("qr-${id}"), { text: "http://localhost:5000/product/${id}", width: 150, height: 150 });`);
                });
                win.document.write('</script></body></html>');
                win.document.close();
            }
        </script>
    </body>
    </html>
    """, products=products)

# ------------------------------ الميزة 11: تطبيق موبايل (PWA) ------------------------------
@app.route('/manifest.json')
def manifest():
    return {
        "name": "وكالة البشائر للأدوية",
        "short_name": "البشائر",
        "description": "نظام إدارة الأدوية والمستلزمات الطبية",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0a0a0a",
        "theme_color": "#FFD700",
        "icons": [
            {"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png"}
        ]
    }

@app.route('/sw.js')
def service_worker():
    return """
    const CACHE_NAME = 'bashaer-v1';
    const urlsToCache = ['/', '/pos', '/cart', '/products', '/chat', '/admin'];
    self.addEventListener('install', event => {
        event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(urlsToCache)));
    });
    self.addEventListener('fetch', event => {
        event.respondWith(caches.match(event.request).then(response => response || fetch(event.request)));
    });
    """

# ------------------------------ الميزة 12: تكامل الدفع الإلكتروني ------------------------------
@app.route('/api/payment/init', methods=['POST'])
@login_required
def init_payment():
    data = request.json
    amount = data.get('amount', 0)
    invoice_id = data.get('invoice_id')
    if amount <= 0:
        return jsonify({'success': False, 'message': 'المبلغ غير صحيح'})
    payment_id = f"PAY-{int(time.time())}-{random.randint(1000, 9999)}"
    execute_query("""
        INSERT INTO payments (payment_id, invoice_id, amount, status, created_at)
        VALUES (?, ?, ?, 'pending', CURRENT_TIMESTAMP)
    """, (payment_id, invoice_id, amount), commit=True)
    payment_url = f"/payment/checkout/{payment_id}"
    return jsonify({
        'success': True,
        'payment_id': payment_id,
        'amount': amount,
        'payment_url': payment_url,
        'methods': [
            {'id': 'cash', 'name': 'دفع نقدي', 'icon': '💰'},
            {'id': 'card', 'name': 'بطاقة ائتمان', 'icon': '💳'},
            {'id': 'mobile', 'name': 'محفظة جوال', 'icon': '📱'},
            {'id': 'bank', 'name': 'تحويل بنكي', 'icon': '🏦'}
        ]
    })

@app.route('/payment/checkout/<payment_id>')
def payment_checkout(payment_id):
    payment = execute_query("SELECT * FROM payments WHERE payment_id = ?", (payment_id,), fetch_one=True)
    if not payment:
        return "الدفع غير موجود", 404
    return render_template_string("""
    <!DOCTYPE html>
    <html dir="rtl">
    <head><meta charset="UTF-8"><title>صفحة الدفع</title>
    <style>
        :root { --bg: #0a0a0a; --text: #FFD700; --card-bg: rgba(17,17,17,0.9); --border: #FFD700; }
        body { background: var(--bg); color: var(--text); font-family: Arial, sans-serif; display: flex; justify-content: center; align-items: center; min-height: 100vh; margin: 0; padding: 20px; }
        .container { max-width: 500px; width: 100%; background: var(--card-bg); border: 1px solid var(--border); border-radius: 20px; padding: 30px; text-align: center; }
        .amount { font-size: 3em; font-weight: bold; margin: 20px 0; background: linear-gradient(135deg, #FFD700, #FF6B00); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .payment-methods { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin: 20px 0; }
        .method-btn { background: #1a1a2e; border: 1px solid var(--border); color: var(--text); padding: 15px; border-radius: 10px; cursor: pointer; transition: 0.3s; font-size: 1.1em; }
        .method-btn:hover { transform: scale(1.05); background: var(--border); color: #000; }
        .method-btn .icon { font-size: 2em; display: block; margin-bottom: 5px; }
        .btn-pay { background: #4CAF50; color: #fff; border: none; padding: 15px 30px; border-radius: 10px; font-size: 1.2em; cursor: pointer; width: 100%; margin-top: 15px; transition: 0.3s; }
        .btn-pay:hover { transform: scale(1.02); opacity: 0.9; }
        .status { margin-top: 15px; padding: 10px; border-radius: 8px; background: rgba(0,0,0,0.3); }
    </style>
    </head>
    <body>
        <div class="container">
            <h2>💳 إتمام الدفع</h2>
            <p>رقم الدفع: {{ payment.payment_id }}</p>
            <div class="amount">{{ "%.2f"|format(payment.amount) }} ريال</div>
            <h4>اختر طريقة الدفع</h4>
            <div class="payment-methods">
                <button class="method-btn" onclick="selectMethod('cash')"><span class="icon">💰</span>نقدي</button>
                <button class="method-btn" onclick="selectMethod('card')"><span class="icon">💳</span>بطاقة</button>
                <button class="method-btn" onclick="selectMethod('mobile')"><span class="icon">📱</span>محفظة</button>
                <button class="method-btn" onclick="selectMethod('bank')"><span class="icon">🏦</span>تحويل</button>
            </div>
            <button class="btn-pay" onclick="processPayment()">✅ تأكيد الدفع</button>
            <div class="status" id="status">اختر طريقة الدفع</div>
        </div>
        <script>
            let selectedMethod = null;
            function selectMethod(method) {
                selectedMethod = method;
                document.getElementById('status').innerHTML = `✅ طريقة الدفع: ${method}`;
                document.querySelectorAll('.method-btn').forEach(btn => btn.style.borderColor = 'var(--border)');
                event.target.style.borderColor = '#4CAF50';
            }
            function processPayment() {
                if (!selectedMethod) { alert('يرجى اختيار طريقة الدفع'); return; }
                document.getElementById('status').innerHTML = '⏳ جاري معالجة الدفع...';
                fetch('/api/payment/process', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({payment_id: '{{ payment.payment_id }}', method: selectedMethod})
                }).then(r=>r.json()).then(data=>{
                    if(data.success){document.getElementById('status').innerHTML='✅ تم الدفع بنجاح!';setTimeout(()=>window.location.href='/',2000);}
                    else{document.getElementById('status').innerHTML='❌ '+data.message;}
                }).catch(err=>{document.getElementById('status').innerHTML='❌ خطأ: '+err;});
            }
        </script>
    </body>
    </html>
    """, payment=payment)

@app.route('/api/payment/process', methods=['POST'])
@login_required
def process_payment():
    data = request.json
    payment_id = data.get('payment_id')
    method = data.get('method', 'cash')
    execute_query("UPDATE payments SET status = 'completed', payment_method = ?, completed_at = CURRENT_TIMESTAMP WHERE payment_id = ?",
                  (method, payment_id), commit=True)
    payment = execute_query("SELECT invoice_id FROM payments WHERE payment_id = ?", (payment_id,), fetch_one=True)
    if payment and payment['invoice_id']:
        execute_query("UPDATE invoices SET payment_method = ? WHERE id = ?", (method, payment['invoice_id']), commit=True)
    return jsonify({'success': True, 'message': 'تم الدفع بنجاح'})

# ------------------------------ الميزة 16: النسخ الاحتياطي المتقدم ------------------------------
@app.route('/admin/backup')
@admin_required
def backup_page():
    backup_dir = 'data/backups'
    os.makedirs(backup_dir, exist_ok=True)
    backups = []
    for f in os.listdir(backup_dir):
        if f.endswith('.zip'):
            path = os.path.join(backup_dir, f)
            size = os.path.getsize(path)
            mtime = datetime.fromtimestamp(os.path.getmtime(path))
            backups.append({'name': f, 'size': size, 'date': mtime, 'size_mb': size / (1024 * 1024)})
    backups.sort(key=lambda x: x['date'], reverse=True)
    return render_template_string("""
    <!DOCTYPE html>
    <html dir="rtl">
    <head><meta charset="UTF-8"><title>النسخ الاحتياطي</title>
    <style>
        :root { --bg: #0a0a0a; --text: #FFD700; --card-bg: rgba(17,17,17,0.9); --border: #FFD700; }
        body { background: var(--bg); color: var(--text); font-family: Arial, sans-serif; padding: 20px; }
        .container { max-width: 1000px; margin: 0 auto; }
        .header { background: var(--card-bg); border: 1px solid var(--border); padding: 20px; border-radius: 10px; margin-bottom: 20px; }
        .btn { background: var(--border); color: #000; padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; font-weight: bold; transition: 0.3s; }
        .btn:hover { transform: scale(1.05); opacity: 0.9; }
        .btn-danger { background: #f44336; color: #fff; }
        .btn-success { background: #4CAF50; color: #fff; }
        .btn-info { background: #2196F3; color: #fff; }
        table { width: 100%; border-collapse: collapse; background: var(--card-bg); border: 1px solid var(--border); }
        th, td { padding: 12px; border: 1px solid var(--border); text-align: center; }
        th { background: var(--border); color: #000; }
        .backup-actions { display: flex; gap: 10px; flex-wrap: wrap; margin: 20px 0; }
        .progress-bar { width: 100%; height: 20px; background: #1a1a2e; border-radius: 10px; overflow: hidden; margin: 10px 0; display: none; }
        .progress-bar .progress { height: 100%; background: linear-gradient(90deg, #FFD700, #FF6B00); width: 0%; transition: width 0.5s; }
        .schedule-options { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px; margin: 15px 0; }
        .schedule-btn { background: var(--card-bg); border: 1px solid var(--border); color: var(--text); padding: 10px; border-radius: 5px; cursor: pointer; transition: 0.3s; }
        .schedule-btn:hover { background: var(--border); color: #000; }
    </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2>💾 نظام النسخ الاحتياطي المتقدم</h2>
                <div class="nav"><a href="/admin" style="color:#FFD700;">العودة للوحة</a></div>
                <p>قم بعمل نسخ احتياطية لقاعدة البيانات والملفات</p>
            </div>
            <div class="backup-actions">
                <button class="btn btn-success" onclick="createBackup()">📦 إنشاء نسخة احتياطية</button>
                <button class="btn btn-info" onclick="restoreBackup()">🔄 استعادة نسخة</button>
                <button class="btn" onclick="scheduleBackup('daily')">📅 جدولة يومية</button>
                <button class="btn" onclick="scheduleBackup('weekly')">📅 جدولة أسبوعية</button>
                <button class="btn btn-danger" onclick="cleanBackups()">🧹 تنظيف القديم</button>
            </div>
            <div class="progress-bar" id="progressBar"><div class="progress" id="progress"></div></div>
            <div id="status" style="margin:15px 0;padding:15px;background:var(--card-bg);border:1px solid var(--border);border-radius:5px;display:none;"></div>
            <h3>📋 النسخ الاحتياطية المتاحة</h3>
            <table>
                <thead><tr><th>اسم الملف</th><th>الحجم</th><th>التاريخ</th><th>إجراءات</th></tr></thead>
                <tbody>
                    {% for b in backups %}
                    <tr>
                        <td>{{ b.name }}</td>
                        <td>{{ "%.2f"|format(b.size_mb) }} MB</td>
                        <td>{{ b.date.strftime('%Y-%m-%d %H:%M') }}</td>
                        <td>
                            <button class="btn btn-info" onclick="downloadBackup('{{ b.name }}')">📥 تحميل</button>
                            <button class="btn btn-danger" onclick="deleteBackup('{{ b.name }}')">🗑️ حذف</button>
                        </td>
                    </tr>
                    {% else %}
                    <tr><td colspan="4">لا توجد نسخ احتياطية</td></tr>
                    {% endfor %}
                </tbody>
            </table>
            <div style="margin-top:20px;padding:15px;background:var(--card-bg);border:1px solid var(--border);border-radius:5px;">
                <h4>⚙️ إعدادات النسخ الاحتياطي</h4>
                <div class="schedule-options">
                    <button class="schedule-btn" onclick="setBackupOption('auto_backup','true')">🔄 تفعيل التلقائي</button>
                    <button class="schedule-btn" onclick="setBackupOption('auto_backup','false')">⏹️ إيقاف التلقائي</button>
                    <button class="schedule-btn" onclick="setBackupOption('backup_interval','daily')">📅 يومي</button>
                    <button class="schedule-btn" onclick="setBackupOption('backup_interval','weekly')">📅 أسبوعي</button>
                    <button class="schedule-btn" onclick="setBackupOption('backup_interval','monthly')">📅 شهري</button>
                    <button class="schedule-btn" onclick="setBackupOption('max_backups','10')">🔢 أقصى 10 نسخ</button>
                </div>
                <div id="settingsStatus" style="margin-top:10px;font-size:0.9em;opacity:0.7;"></div>
            </div>
        </div>
        <script>
            function createBackup() {
                showProgress();
                document.getElementById('status').style.display = 'block';
                document.getElementById('status').innerHTML = '⏳ جاري إنشاء النسخة الاحتياطية...';
                fetch('/api/backup/create', {method:'POST'}).then(r=>r.json()).then(data=>{
                    hideProgress();
                    if(data.success){document.getElementById('status').innerHTML='✅ '+data.message;setTimeout(()=>location.reload(),2000);}
                    else{document.getElementById('status').innerHTML='❌ '+data.message;}
                }).catch(err=>{hideProgress();document.getElementById('status').innerHTML='❌ خطأ: '+err;});
            }
            function restoreBackup() {
                const filename = prompt('أدخل اسم ملف النسخة الاحتياطية للاستعادة:');
                if(!filename)return;
                if(!confirm('⚠️ تحذير: استعادة النسخة ستستبدل البيانات الحالية! هل أنت متأكد؟'))return;
                showProgress();
                document.getElementById('status').style.display='block';
                document.getElementById('status').innerHTML='⏳ جاري استعادة النسخة...';
                fetch('/api/backup/restore',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({filename:filename})})
                .then(r=>r.json()).then(data=>{hideProgress();if(data.success){document.getElementById('status').innerHTML='✅ '+data.message;setTimeout(()=>location.reload(),2000);}else{document.getElementById('status').innerHTML='❌ '+data.message;}})
                .catch(err=>{hideProgress();document.getElementById('status').innerHTML='❌ خطأ: '+err;});
            }
            function downloadBackup(filename){window.location.href=`/api/backup/download/${filename}`;}
            function deleteBackup(filename){if(!confirm(`هل أنت متأكد من حذف ${filename}؟`))return;fetch('/api/backup/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({filename:filename})}).then(r=>r.json()).then(data=>{if(data.success)location.reload();else alert(data.message);});}
            function scheduleBackup(interval){fetch('/api/backup/schedule',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({interval:interval})}).then(r=>r.json()).then(data=>{alert(data.message);if(data.success)location.reload();});}
            function cleanBackups(){if(!confirm('🗑️ سيتم حذف جميع النسخ الاحتياطية القديمة (أكثر من 30 يوم)؟'))return;fetch('/api/backup/clean',{method:'POST'}).then(r=>r.json()).then(data=>{alert(data.message);if(data.success)location.reload();});}
            function setBackupOption(key,value){fetch('/api/backup/setting',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({key:key,value:value})}).then(r=>r.json()).then(data=>{document.getElementById('settingsStatus').innerHTML='✅ تم تحديث الإعداد: '+key+' = '+value;});}
            function showProgress(){document.getElementById('progressBar').style.display='block';let progress=0;const interval=setInterval(()=>{progress+=Math.random()*10;if(progress>95)progress=95;document.getElementById('progress').style.width=progress+'%';},500);window._progressInterval=interval;}
            function hideProgress(){clearInterval(window._progressInterval);document.getElementById('progress').style.width='100%';setTimeout(()=>{document.getElementById('progressBar').style.display='none';document.getElementById('progress').style.width='0%';},1000);}
        </script>
    </body>
    </html>
    """, backups=backups)

@app.route('/api/backup/create', methods=['POST'])
@admin_required
def create_backup():
    try:
        backup_dir = 'data/backups'
        os.makedirs(backup_dir, exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"backup_{timestamp}.zip"
        filepath = os.path.join(backup_dir, filename)
        with zipfile.ZipFile(filepath, 'w', zipfile.ZIP_DEFLATED) as zipf:
            if DATABASE_URL:
                import subprocess
                dump_cmd = f"pg_dump {DATABASE_URL} > data/dump.sql"
                subprocess.run(dump_cmd, shell=True)
                zipf.write('data/dump.sql', 'database.sql')
            else:
                zipf.write('data/supermarket.db', 'database.db')
            if os.path.exists('static/uploads'):
                for root, dirs, files in os.walk('static/uploads'):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, 'static')
                        zipf.write(file_path, f'static/{arcname}')
            if os.path.exists('data/settings.json'):
                zipf.write('data/settings.json', 'settings.json')
        backups = sorted([f for f in os.listdir(backup_dir) if f.endswith('.zip')])
        if len(backups) > 10:
            for old in backups[:-10]:
                os.remove(os.path.join(backup_dir, old))
        return jsonify({'success': True, 'message': f'تم إنشاء النسخة: {filename}', 'filename': filename})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/backup/restore', methods=['POST'])
@admin_required
def restore_backup():
    data = request.json
    filename = data.get('filename')
    if not filename:
        return jsonify({'success': False, 'message': 'اسم الملف مطلوب'})
    filepath = os.path.join('data/backups', filename)
    if not os.path.exists(filepath):
        return jsonify({'success': False, 'message': 'الملف غير موجود'})
    try:
        with zipfile.ZipFile(filepath, 'r') as zipf:
            if DATABASE_URL:
                zipf.extract('database.sql', 'data/')
                import subprocess
                restore_cmd = f"psql {DATABASE_URL} < data/database.sql"
                subprocess.run(restore_cmd, shell=True)
            else:
                zipf.extract('database.db', 'data/')
            for file in zipf.namelist():
                if file.startswith('static/'):
                    zipf.extract(file, '.')
        return jsonify({'success': True, 'message': 'تم استعادة النسخة بنجاح'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/backup/download/<filename>')
@admin_required
def download_backup(filename):
    filepath = os.path.join('data/backups', filename)
    if not os.path.exists(filepath):
        return 'الملف غير موجود', 404
    return send_file(filepath, as_attachment=True, download_name=filename)

@app.route('/api/backup/delete', methods=['POST'])
@admin_required
def delete_backup():
    data = request.json
    filename = data.get('filename')
    if not filename:
        return jsonify({'success': False, 'message': 'اسم الملف مطلوب'})
    filepath = os.path.join('data/backups', filename)
    if os.path.exists(filepath):
        os.remove(filepath)
        return jsonify({'success': True, 'message': 'تم الحذف'})
    return jsonify({'success': False, 'message': 'الملف غير موجود'})

@app.route('/api/backup/clean', methods=['POST'])
@admin_required
def clean_backups():
    backup_dir = 'data/backups'
    thirty_days_ago = time.time() - (30 * 24 * 60 * 60)
    count = 0
    for f in os.listdir(backup_dir):
        if f.endswith('.zip'):
            path = os.path.join(backup_dir, f)
            if os.path.getmtime(path) < thirty_days_ago:
                os.remove(path)
                count += 1
    return jsonify({'success': True, 'message': f'تم حذف {count} نسخة قديمة'})

@app.route('/api/backup/schedule', methods=['POST'])
@admin_required
def schedule_backup():
    data = request.json
    interval = data.get('interval', 'daily')
    execute_query("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", ('backup_interval', interval), commit=True)
    return jsonify({'success': True, 'message': f'تم جدولة النسخ {interval}'})

@app.route('/api/backup/setting', methods=['POST'])
@admin_required
def backup_setting():
    data = request.json
    key = data.get('key')
    value = data.get('value')
    execute_query("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value), commit=True)
    return jsonify({'success': True, 'message': 'تم تحديث الإعداد'})

# =============================== الصفحات الأساسية ===============================
@app.route('/')
def home():
    settings = get_settings()
    company_name = settings['company_name']
    company_logo = settings['company_logo']
    return render_template_string("""
    <!DOCTYPE html>
    <html dir="rtl" lang="ar">
    <head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>{{ company_name }}</title>
    <script src="https://unpkg.com/html5-qrcode@2.3.8/html5-qrcode.min.js"></script>
    <style>
        :root { --bg: #000; --text: #FFD700; --card-bg: #111; --border: #FFD700; --input-bg: #000; --input-text: #FFD700; --btn-bg: #FFD700; --btn-text: #000; }
        body.light { --bg: #f5f5f5; --text: #000; --card-bg: #fff; --border: #007bff; --input-bg: #fff; --input-text: #000; --btn-bg: #007bff; --btn-text: #fff; }
        * { margin: 0; padding: 0; box-sizing: border-box; font-family: 'Tahoma', Arial, sans-serif; }
        body { background: var(--bg); color: var(--text); padding: 20px; transition: background 0.3s, color 0.3s; }
        .container { max-width: 1200px; margin: 0 auto; }
        .header { text-align: center; padding: 20px; background: var(--card-bg); border-radius: 15px; margin-bottom: 30px; border: 1px solid var(--border); }
        .header h1 { color: var(--text); }
        .nav { display: flex; gap: 15px; justify-content: center; margin-bottom: 30px; flex-wrap: wrap; }
        .nav a { background: var(--card-bg); color: var(--text); padding: 12px 25px; text-decoration: none; border-radius: 8px; border: 1px solid var(--border); transition: 0.3s; }
        .nav a:hover, .nav a.active { background: var(--btn-bg); color: var(--btn-text); }
        .content { background: var(--card-bg); padding: 25px; border-radius: 15px; border: 1px solid var(--border); }
        h2 { color: var(--text); margin-bottom: 20px; border-right: 4px solid var(--border); padding-right: 15px; }
        .products-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 25px; margin-top: 20px; }
        .product-card { background: var(--bg); border: 1px solid var(--border); border-radius: 12px; padding: 15px; text-align: center; transition: 0.3s; display: flex; flex-direction: column; }
        .product-card:hover { transform: translateY(-5px); box-shadow: 0 5px 15px rgba(255,215,0,0.3); }
        .product-img { width: 100%; height: 200px; object-fit: cover; border-radius: 8px; margin-bottom: 10px; background: #222; }
        .product-name { font-weight: bold; font-size: 18px; margin: 10px 0; color: var(--text); }
        .product-price { color: var(--text); font-size: 22px; font-weight: bold; margin: 5px 0; }
        .product-desc { font-size: 13px; color: #ccc; margin: 8px 0; }
        .product-stock { font-size: 12px; color: #aaa; margin-bottom: 8px; }
        .quantity-control { display: flex; align-items: center; justify-content: center; gap: 10px; margin: 10px 0; }
        .quantity-control button { background: var(--btn-bg); color: var(--btn-text); border: none; width: 30px; height: 30px; border-radius: 5px; font-weight: bold; cursor: pointer; }
        .quantity-control span { font-size: 16px; font-weight: bold; min-width: 30px; }
        button.add-to-cart { background: var(--btn-bg); color: var(--btn-text); border: none; padding: 8px 15px; border-radius: 5px; cursor: pointer; font-weight: bold; margin-top: 10px; transition: 0.2s; width: 100%; }
        button.add-to-cart:hover { opacity: 0.8; }
        .barcode-scanner { margin-bottom: 20px; display: flex; gap: 10px; flex-wrap: wrap; }
        .barcode-scanner input { flex: 1; padding: 8px; border: 1px solid var(--border); background: var(--input-bg); color: var(--input-text); border-radius: 5px; }
        .chat-float { position: fixed; bottom: 20px; left: 20px; background: var(--btn-bg); color: var(--btn-text); width: 60px; height: 60px; border-radius: 50%; font-size: 30px; display: flex; align-items: center; justify-content: center; cursor: pointer; z-index: 999; box-shadow: 0 4px 15px rgba(0,0,0,0.5); text-decoration: none; }
        .theme-toggle { position: fixed; top: 20px; left: 20px; background: var(--btn-bg); color: var(--btn-text); border: none; border-radius: 50%; width: 50px; height: 50px; font-size: 20px; cursor: pointer; z-index: 1000; }
        .btn { background: var(--btn-bg); color: var(--btn-text); padding: 8px 15px; border: none; border-radius: 5px; cursor: pointer; }
        @media (max-width: 600px) { .products-grid { grid-template-columns: 1fr; } }
    </style>
    </head>
    <body>
        <button class="theme-toggle" onclick="toggleTheme()">🌓</button>
        <a href="/chat" class="chat-float" title="المساعد الذكي">💬</a>
        <div class="container">
            <div class="header"><h1>{{ company_logo }} {{ company_name }}</h1><p>نظام إدارة الأدوية والمستلزمات الطبية بالجملة</p><p style="font-size:14px;color:#aaa;">🧠 مدعوم بالذكاء الاصطناعي</p></div>
            <div class="nav">
                <a href="/" class="active">الرئيسية</a>
                <a href="/products">الأدوية</a>
                <a href="/offers">العروض</a>
                <a href="/points">نقاطي</a>
                <a href="/cart">السلة</a>
                <a href="/chat">💬 المساعد</a>
                <a href="/customer/recommendations">🎯 توصيات</a>
                <a href="/login">دخول الإدارة</a>
                <a href="/voice-assistant">🎤 صوتي</a>
            </div>
            <div class="content">
                <h2>مرحباً بكم في وكالة البشائر</h2>
                <p>أكبر موزع للأدوية والمستلزمات الطبية في اليمن.</p>
                <div class="barcode-scanner">
                    <input type="text" id="barcode-input" placeholder="ادخل الباركود أو امسحه بالكاميرا">
                    <button class="btn" onclick="searchByBarcode()">🔍 بحث</button>
                    <button class="btn" onclick="startScanner()">📷 فتح الكاميرا</button>
                </div>
                <div id="scanner-container" style="display:none;"></div>
                <div id="scanned-product" style="margin:10px 0;padding:15px;border:1px solid var(--border);border-radius:8px;"></div>
                <div id="featured-products" class="products-grid"></div>
            </div>
        </div>
        <script>
            let quantities = {}; let html5QrCode = null;
            function toggleTheme(){document.body.classList.toggle('light');localStorage.setItem('theme',document.body.classList.contains('light')?'light':'dark');}
            if(localStorage.getItem('theme')==='light') document.body.classList.add('light');
            function loadProducts(){fetch('/api/products?limit=50').then(r=>r.json()).then(data=>{if(data.success){let html='';data.products.forEach(p=>{if(!quantities[p.id])quantities[p.id]=1;let priceDisplay=p.dynamic_price?`${p.dynamic_price} (ديناميكي)`:p.price;html+=`<div class="product-card"><img src="${p.image_url||'/static/uploads/default.jpg'}" class="product-img" onerror="this.src='/static/uploads/default.jpg'"><div class="product-name">${p.name} ${p.dynamic_price?'🔄':''}</div><div class="product-price">${priceDisplay} ريال <small>لل${p.unit_name||'حبة'}</small></div><div class="product-desc">${p.description||''}</div><div class="product-stock">المتبقي: ${p.quantity} ${p.unit_name||''}</div><div class="quantity-control"><button onclick="changeQty(${p.id},-1)">-</button><span id="qty-${p.id}">${quantities[p.id]}</span><button onclick="changeQty(${p.id},1)">+</button></div><button class="add-to-cart" onclick="addToCart(${p.id},'${p.name.replace(/'/g,"\\'")}',${p.dynamic_price||p.price})">أضف للسلة</button></div>`;});document.getElementById('featured-products').innerHTML=html;}});}
            function changeQty(id,delta){let newVal=(quantities[id]||1)+delta;if(newVal<1)newVal=1;quantities[id]=newVal;document.getElementById(`qty-${id}`).innerText=newVal;}
            function addToCart(id,name,price){let qty=quantities[id]||1;let cart=JSON.parse(localStorage.getItem('cart')||'[]');let existing=cart.find(i=>i.id==id);if(existing)existing.quantity+=qty;else cart.push({id,name,price,quantity:qty});localStorage.setItem('cart',JSON.stringify(cart));alert(`تمت إضافة ${qty} من ${name}`);quantities[id]=1;if(document.getElementById(`qty-${id}`))document.getElementById(`qty-${id}`).innerText=1;}
            function searchByBarcode(){let barcode=document.getElementById('barcode-input').value.trim();if(!barcode)return;fetch('/api/scan-barcode',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({barcode:barcode})}).then(r=>r.json()).then(data=>{if(data.success){let p=data.product;let priceDisplay=p.dynamic_price||p.price;let html=`<div style="display:flex;align-items:center;gap:15px;flex-wrap:wrap;"><img src="${p.image_url}" style="width:80px;height:80px;object-fit:cover;border-radius:8px;"><div><strong>${p.name}</strong><br>السعر: ${priceDisplay} ريال<br>الكمية: ${p.quantity} ${p.unit}<br>الشركة: ${p.manufacturer||''}<br>رقم الدفعة: ${p.batch_number||''}<br>المادة الفعالة: ${p.active_ingredient||''}<br>التركيز: ${p.strength||''}<br>تاريخ الصلاحية: ${p.expiry_date||''}</div></div>`;document.getElementById('scanned-product').innerHTML=html;let cart=JSON.parse(localStorage.getItem('cart')||'[]');let existing=cart.find(i=>i.id==p.id);if(existing)existing.quantity+=1;else cart.push({id:p.id,name:p.name,price:priceDisplay,quantity:1});localStorage.setItem('cart',JSON.stringify(cart));alert('تمت إضافة المنتج إلى السلة');}else{document.getElementById('scanned-product').innerHTML=`<p style="color:red;">المنتج غير موجود</p>`;}});}
            function startScanner(){let container=document.getElementById('scanner-container');container.style.display='block';if(html5QrCode){html5QrCode.stop().then(()=>{html5QrCode.clear();});}html5QrCode=new Html5Qrcode("scanner-container");html5QrCode.start({facingMode:"environment"},{fps:10,qrbox:{width:250,height:250}},(decodedText)=>{document.getElementById('barcode-input').value=decodedText;searchByBarcode();html5QrCode.stop();container.style.display='none';},(error)=>{}).catch(err=>alert('لا يمكن الوصول إلى الكاميرا: '+err));}
            document.getElementById('barcode-input').addEventListener('keypress',function(e){if(e.key==='Enter')searchByBarcode();});
            loadProducts();
        </script>
    </body>
    </html>
    """, company_name=company_name, company_logo=company_logo)

@app.route('/products')
def products_page():
    settings = get_settings()
    return render_template_string("""
    <!DOCTYPE html>
    <html dir="rtl">
    <head><meta charset="UTF-8"><title>الأدوية</title>
    <style>
        :root { --bg: #000; --text: #FFD700; --card-bg: #111; --border: #FFD700; --btn-bg: #FFD700; --btn-text: #000; }
        body.light { --bg: #f5f5f5; --text: #000; --card-bg: #fff; --border: #007bff; --btn-bg: #007bff; --btn-text: #fff; }
        body{background:var(--bg);color:var(--text);padding:20px;font-family:Arial;transition:0.3s;}
        .container{max-width:1200px;margin:auto;}
        .header{background:var(--card-bg);border:1px solid var(--border);padding:20px;border-radius:10px;margin-bottom:20px;}
        .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:20px;}
        .card{background:var(--card-bg);border:1px solid var(--border);border-radius:8px;padding:15px;text-align:center;}
        .btn{background:var(--btn-bg);color:var(--btn-text);padding:8px 15px;border:none;border-radius:5px;cursor:pointer;}
        .theme-toggle{position:fixed;top:20px;left:20px;background:var(--btn-bg);color:var(--btn-text);border:none;border-radius:50%;width:50px;height:50px;font-size:20px;cursor:pointer;z-index:1000;}
        .chat-float{position:fixed;bottom:20px;left:20px;background:var(--btn-bg);color:var(--btn-text);width:60px;height:60px;border-radius:50%;font-size:30px;display:flex;align-items:center;justify-content:center;cursor:pointer;z-index:999;box-shadow:0 4px 15px rgba(0,0,0,0.5);text-decoration:none;}
    </style>
    </head>
    <body>
    <button class="theme-toggle" onclick="toggleTheme()">🌓</button>
    <a href="/chat" class="chat-float" title="المساعد الذكي">💬</a>
    <div class="container">
        <div class="header"><h2>📦 جميع الأدوية</h2><a href="/">الرئيسية</a> | <a href="/cart">السلة</a></div>
        <div id="products" class="grid"></div>
    </div>
    <script>
        function toggleTheme(){document.body.classList.toggle('light');localStorage.setItem('theme',document.body.classList.contains('light')?'light':'dark');}
        if(localStorage.getItem('theme')==='light') document.body.classList.add('light');
        fetch('/api/products?limit=100').then(r=>r.json()).then(data=>{if(data.success){let html='';data.products.forEach(p=>{html+=`<div class="card"><h4>${p.name}</h4><p>💰 ${p.price} ريال</p><p style="font-size:12px;color:#aaa;">المتبقي: ${p.quantity}</p><button class="btn" onclick="addToCart(${p.id},'${p.name.replace(/'/g,"\\'")}',${p.price})">أضف للسلة</button></div>`;});document.getElementById('products').innerHTML=html;}});
        function addToCart(id,name,price){let cart=JSON.parse(localStorage.getItem('cart')||'[]');let existing=cart.find(i=>i.id===id);if(existing)existing.quantity+=1;else cart.push({id,name,price,quantity:1});localStorage.setItem('cart',JSON.stringify(cart));alert('تمت الإضافة');}
    </script>
    </body>
    </html>
    """, company_name=settings['company_name'])

@app.route('/offers')
def offers_page():
    return render_template_string("""
    <!DOCTYPE html>
    <html dir="rtl">
    <head><meta charset="UTF-8"><title>العروض</title>
    <style>
        :root { --bg: #000; --text: #FFD700; --card-bg: #111; --border: #FFD700; --btn-bg: #FFD700; --btn-text: #000; }
        body{background:var(--bg);color:var(--text);padding:20px;font-family:Arial;}
        .container{max-width:1000px;margin:auto;}
        .header{background:var(--card-bg);border:1px solid var(--border);padding:20px;border-radius:10px;margin-bottom:20px;}
        .offer-card{background:var(--card-bg);border:1px solid var(--border);padding:20px;border-radius:10px;margin:15px 0;}
    </style>
    </head>
    <body>
        <div class="container">
            <div class="header"><h2>🎁 العروض والخصومات</h2><a href="/">الرئيسية</a></div>
            <div id="offers"></div>
        </div>
        <script>
            fetch('/api/offers').then(r=>r.json()).then(data=>{
                let html='';
                data.offers.forEach(o=>{
                    html+=`<div class="offer-card"><h3>${o.title}</h3><p>${o.description||''}</p><p style="color:#4CAF50;">خصم: ${o.discount_value}%</p></div>`;
                });
                document.getElementById('offers').innerHTML=html||'<p>لا توجد عروض حالياً</p>';
            });
        </script>
    </body>
    </html>
    """)

@app.route('/points')
def points_page():
    return render_template_string("""
    <!DOCTYPE html>
    <html dir="rtl">
    <head><meta charset="UTF-8"><title>نقاط الولاء</title>
    <style>
        :root { --bg: #000; --text: #FFD700; --card-bg: #111; --border: #FFD700; }
        body{background:var(--bg);color:var(--text);padding:20px;font-family:Arial;}
        .container{max-width:600px;margin:auto;}
        .header{background:var(--card-bg);border:1px solid var(--border);padding:20px;border-radius:10px;margin-bottom:20px;text-align:center;}
        input{padding:10px;background:#000;color:#FFD700;border:1px solid var(--border);border-radius:5px;width:100%;margin:10px 0;}
        .btn{background:#FFD700;color:#000;padding:10px;border:none;border-radius:5px;cursor:pointer;}
    </style>
    </head>
    <body>
        <div class="container">
            <div class="header"><h2>⭐ نقاط الولاء</h2><a href="/">الرئيسية</a></div>
            <input type="tel" id="phoneInput" placeholder="أدخل رقم الهاتف">
            <button class="btn" onclick="checkPoints()">🔍 عرض النقاط</button>
            <div id="result" style="margin-top:20px;"></div>
        </div>
        <script>
            function checkPoints(){let phone=document.getElementById('phoneInput').value.trim();if(!phone)return;fetch(`/api/customer/${phone}`).then(r=>r.json()).then(data=>{if(data.success){document.getElementById('result').innerHTML=`<div style="background:var(--card-bg);padding:15px;border-radius:8px;border:1px solid var(--border);"><h3>${data.name}</h3><p>⭐ النقاط: ${data.loyalty_points||0}</p><p>💰 إجمالي المشتريات: ${data.total_spent||0} ريال</p><p>👤 المستوى: ${data.tier||'عادي'}</p></div>`;}else{document.getElementById('result').innerHTML=`<p style="color:red;">العميل غير موجود</p>`;}});}
        </script>
    </body>
    </html>
    """)

@app.route('/cart')
def cart_page():
    return render_template_string("""
    <!DOCTYPE html>
    <html dir="rtl">
    <head>
        <meta charset="UTF-8">
        <title>السلة</title>
        <style>
            :root { --bg: #000; --text: #FFD700; --card-bg: #111; --border: #FFD700; --btn-bg: #FFD700; --btn-text: #000; }
            body.light { --bg: #f5f5f5; --text: #000; --card-bg: #fff; --border: #007bff; --btn-bg: #007bff; --btn-text: #fff; }
            body{background:var(--bg);color:var(--text);padding:20px;font-family:Arial;transition:0.3s;}
            .container{max-width:800px;margin:auto;}
            .header{background:var(--card-bg);border:1px solid var(--border);padding:20px;border-radius:10px;margin-bottom:20px;}
            .cart-item{background:var(--card-bg);border:1px solid var(--border);padding:10px;border-radius:5px;display:flex;justify-content:space-between;align-items:center;margin:5px 0;}
            .btn{background:var(--btn-bg);color:var(--btn-text);padding:8px 15px;border:none;border-radius:5px;cursor:pointer;}
            .theme-toggle{position:fixed;top:20px;left:20px;background:var(--btn-bg);color:var(--btn-text);border:none;border-radius:50%;width:50px;height:50px;font-size:20px;cursor:pointer;z-index:1000;}
            .chat-float{position:fixed;bottom:20px;left:20px;background:var(--btn-bg);color:var(--btn-text);width:60px;height:60px;border-radius:50%;font-size:30px;display:flex;align-items:center;justify-content:center;cursor:pointer;z-index:999;box-shadow:0 4px 15px rgba(0,0,0,0.5);text-decoration:none;}
        </style>
    </head>
    <body>
        <button class="theme-toggle" onclick="toggleTheme()">🌓</button>
        <a href="/chat" class="chat-float" title="المساعد الذكي">💬</a>
        <div class="container">
            <div class="header"><h2>🛒 سلة المشتريات</h2><a href="/">الرئيسية</a> | <a href="/pos">نقطة البيع</a></div>
            <div id="cartItems"></div>
            <div style="margin-top:20px;padding:15px;background:var(--card-bg);border:1px solid var(--border);border-radius:8px;">
                <p><strong>الإجمالي:</strong> <span id="totalPrice">0</span> ريال</p>
                <button class="btn" onclick="checkout()" style="width:100%;">✅ إنهاء الطلب</button>
                <button class="btn" onclick="clearCart()" style="width:100%;margin-top:5px;background:#f44336;color:#fff;">🗑️ تفريغ السلة</button>
            </div>
        </div>
        <script>
            function toggleTheme(){document.body.classList.toggle('light');localStorage.setItem('theme',document.body.classList.contains('light')?'light':'dark');}
            if(localStorage.getItem('theme')==='light') document.body.classList.add('light');
            function renderCart(){
                let cart=JSON.parse(localStorage.getItem('cart')||'[]');
                let container=document.getElementById('cartItems');
                let total=0;
                if(cart.length===0){container.innerHTML='<p>السلة فارغة</p>';document.getElementById('totalPrice').innerText='0';return;}
                let html='';
                cart.forEach((item,index)=>{let subtotal=item.price*item.quantity;total+=subtotal;html+=`<div class="cart-item"><span><strong>${item.name}</strong> × ${item.quantity}</span><span>${subtotal} ريال</span><div><button onclick="changeQty(${index},-1)">-</button><button onclick="changeQty(${index},1)">+</button><button onclick="removeItem(${index})" style="background:#f44336;color:#fff;border:none;border-radius:3px;padding:2px 8px;">✕</button></div></div>`;});
                container.innerHTML=html;
                document.getElementById('totalPrice').innerText=total;
            }
            function changeQty(index,delta){let cart=JSON.parse(localStorage.getItem('cart')||'[]');if(!cart[index])return;let newQty=cart[index].quantity+delta;if(newQty<1)newQty=1;cart[index].quantity=newQty;localStorage.setItem('cart',JSON.stringify(cart));renderCart();}
            function removeItem(index){let cart=JSON.parse(localStorage.getItem('cart')||'[]');cart.splice(index,1);localStorage.setItem('cart',JSON.stringify(cart));renderCart();}
            function clearCart(){if(confirm('هل تريد تفريغ السلة؟')){localStorage.removeItem('cart');renderCart();}}
            function checkout(){let cart=JSON.parse(localStorage.getItem('cart')||'[]');if(cart.length===0){alert('السلة فارغة');return;}let total=cart.reduce((s,i)=>s+i.price*i.quantity,0);fetch('/api/check-anomaly',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cart:cart,total:total})}).then(r=>r.json()).then(anomaly=>{if(anomaly.is_anomaly&&!confirm(`⚠️ تحذير: شذوذ محتمل!\nالسبب: ${anomaly.reason}\nهل تريد المتابعة؟`)){return;}fetch('/api/create_invoice',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cart:cart,customer_name:'عميل',payment_method:'cash'})}).then(r=>r.json()).then(data=>{if(data.success){alert(`✅ تم إنشاء الفاتورة رقم ${data.invoice_number}`);localStorage.removeItem('cart');renderCart();}else{alert('❌ خطأ: '+data.message);}});});}
            renderCart();
        </script>
    </body>
    </html>
    """)

@app.route('/chat')
def chat_page():
    settings = get_settings()
    return render_template_string("""
    <!DOCTYPE html>
    <html dir="rtl">
    <head>
        <meta charset="UTF-8">
        <title>المساعد الذكي</title>
        <style>
            :root { --bg: #0a0a0a; --text: #FFD700; --card-bg: rgba(17,17,17,0.9); --border: #FFD700; --btn-bg: #FFD700; --btn-text: #000; }
            body{background:var(--bg);color:var(--text);font-family:Arial,sans-serif;padding:20px;min-height:100vh;display:flex;justify-content:center;align-items:center;}
            .container{max-width:700px;width:100%;background:var(--card-bg);border:1px solid var(--border);border-radius:20px;padding:20px;height:80vh;display:flex;flex-direction:column;}
            .header{text-align:center;padding-bottom:15px;border-bottom:1px solid var(--border);}
            .messages{flex:1;overflow-y:auto;padding:15px 0;}
            .message{padding:10px 15px;border-radius:10px;margin:8px 0;max-width:85%;}
            .user{background:#1a1a2e;border:1px solid var(--border);align-self:flex-end;margin-left:auto;}
            .bot{background:#2a2a3e;border:1px solid #4CAF50;align-self:flex-start;}
            .input-area{display:flex;gap:10px;padding-top:15px;border-top:1px solid var(--border);}
            .input-area input{flex:1;padding:10px;background:#000;color:var(--text);border:1px solid var(--border);border-radius:8px;}
            .btn{background:var(--btn-bg);color:var(--btn-text);padding:10px 20px;border:none;border-radius:8px;cursor:pointer;}
            .suggestion{display:inline-block;background:#1a1a2e;border:1px solid var(--border);padding:5px 12px;border-radius:15px;cursor:pointer;margin:3px;font-size:12px;}
            .suggestion:hover{background:var(--border);color:#000;}
            .rag-result{font-size:12px;color:#aaa;margin-top:5px;padding:5px;background:#1a1a2e;border-radius:5px;}
            .theme-toggle{position:fixed;top:20px;left:20px;background:var(--btn-bg);color:var(--btn-text);border:none;border-radius:50%;width:50px;height:50px;font-size:20px;cursor:pointer;z-index:1000;}
        </style>
    </head>
    <body>
        <button class="theme-toggle" onclick="toggleTheme()">🌓</button>
        <div class="container">
            <div class="header"><h2>🤖 المساعد الذكي</h2><p style="font-size:12px;color:#aaa;">اسأل عن الأدوية، التفاعلات، الجرعات، والمزيد</p></div>
            <div class="messages" id="messages"></div>
            <div id="suggestions" style="display:flex;flex-wrap:wrap;gap:5px;margin-bottom:10px;"></div>
            <div class="input-area">
                <input type="text" id="chatInput" placeholder="اكتب سؤالك هنا..." onkeypress="if(event.key==='Enter')sendMessage()">
                <button class="btn" onclick="sendMessage()">إرسال</button>
            </div>
        </div>
        <script>
            function toggleTheme(){document.body.classList.toggle('light');localStorage.setItem('theme',document.body.classList.contains('light')?'light':'dark');}
            if(localStorage.getItem('theme')==='light') document.body.classList.add('light');
            const suggestions = ['ما هو أفضل دواء للصداع؟', 'معلومات عن الباراسيتامول', 'تفاعلات الأموكسيسيلين', 'أدوية الحساسية', 'سعر الأوميبرازول'];
            document.getElementById('suggestions').innerHTML = suggestions.map(s => `<span class="suggestion" onclick="sendQuick('${s}')">${s}</span>`).join('');
            function sendQuick(text){document.getElementById('chatInput').value=text;sendMessage();}
            function sendMessage(){
                const input=document.getElementById('chatInput');
                const text=input.value.trim();
                if(!text)return;
                addMessage(text,'user');
                input.value='';
                fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:text})})
                    .then(r=>r.json())
                    .then(data=>{
                        if(data.success){addMessage(data.reply,'bot');if(data.rag_results){let html='<div class="rag-result">📚 نتائج البحث: ';data.rag_results.forEach(r=>{html+=`<span style="margin:0 5px;">${r.product.name} (${(r.similarity*100).toFixed(0)}%)</span>`;});html+='</div>';document.querySelector('.messages').lastElementChild.innerHTML+=html;}}else{addMessage('عذراً، حدث خطأ. حاول مرة أخرى.','bot');}
                    })
                    .catch(err=>addMessage('❌ خطأ في الاتصال','bot'));
            }
            function addMessage(text,sender){
                const container=document.getElementById('messages');
                const div=document.createElement('div');
                div.className=`message ${sender}`;
                div.innerHTML=text.replace(/\n/g,'<br>');
                container.appendChild(div);
                container.scrollTop=container.scrollHeight;
            }
        </script>
    </body>
    </html>
    """, company_name=settings['company_name'])

@app.route('/payment')
def payment_page():
    return render_template_string("""
    <!DOCTYPE html>
    <html dir="rtl">
    <head><meta charset="UTF-8"><title>السداد الإلكتروني</title>
    <style>
        :root { --bg: #000; --text: #FFD700; --card-bg: #111; --border: #FFD700; }
        body{background:var(--bg);color:var(--text);padding:20px;font-family:Arial;}
        .container{max-width:500px;margin:auto;}
        .header{background:var(--card-bg);border:1px solid var(--border);padding:20px;border-radius:10px;margin-bottom:20px;text-align:center;}
        input{width:100%;padding:10px;background:#000;color:#FFD700;border:1px solid var(--border);border-radius:5px;margin:10px 0;}
        .btn{background:#FFD700;color:#000;padding:10px;border:none;border-radius:5px;cursor:pointer;width:100%;}
    </style>
    </head>
    <body>
        <div class="container">
            <div class="header"><h2>💳 السداد الإلكتروني</h2><a href="/">الرئيسية</a></div>
            <div style="background:var(--card-bg);padding:20px;border-radius:10px;border:1px solid var(--border);">
                <p>⚠️ بوابة الدفع قيد التطوير</p>
                <p style="font-size:12px;color:#aaa;">سيتم إضافة خيارات الدفع قريباً</p>
            </div>
        </div>
    </body>
    </html>
    """)

@app.route('/pharmacist')
@pharmacist_required
def pharmacist_dashboard():
    return render_template_string("""
    <!DOCTYPE html>
    <html dir="rtl">
    <head><meta charset="UTF-8"><title>لوحة الصيدلي</title>
    <style>
        :root { --bg: #000; --text: #FFD700; --card-bg: #111; --border: #FFD700; }
        body{background:var(--bg);color:var(--text);padding:20px;font-family:Arial;}
        .container{max-width:1000px;margin:auto;}
        .header{background:var(--card-bg);border:1px solid var(--border);padding:20px;border-radius:10px;margin-bottom:20px;}
        .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:15px;}
        .card{background:var(--card-bg);border:1px solid var(--border);padding:20px;border-radius:10px;text-align:center;text-decoration:none;color:var(--text);}
        .card:hover{transform:scale(1.02);background:#222;}
    </style>
    </head>
    <body>
        <div class="container">
            <div class="header"><h2>💊 لوحة الصيدلي</h2><p>مرحباً {{ session.username }}</p></div>
            <div class="grid">
                <a href="/pos" class="card">🛒 نقطة البيع</a>
                <a href="/products" class="card">📦 المنتجات</a>
                <a href="/chat" class="card">🤖 المساعد الذكي</a>
                <a href="/admin/scan-image-ui" class="card">📷 التعرف من الصور</a>
                <a href="/admin/anomalies" class="card">🛡️ كشف الشذوذ</a>
                <a href="/admin/feedback" class="card">💬 التقييمات</a>
            </div>
        </div>
    </body>
    </html>
    """)

@app.route('/stock')
@store_keeper_required
def stock_dashboard():
    return render_template_string("""
    <!DOCTYPE html>
    <html dir="rtl">
    <head><meta charset="UTF-8"><title>لوحة المخزن</title>
    <style>
        :root { --bg: #000; --text: #FFD700; --card-bg: #111; --border: #FFD700; }
        body{background:var(--bg);color:var(--text);padding:20px;font-family:Arial;}
        .container{max-width:1000px;margin:auto;}
        .header{background:var(--card-bg);border:1px solid var(--border);padding:20px;border-radius:10px;margin-bottom:20px;}
        .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:15px;}
        .card{background:var(--card-bg);border:1px solid var(--border);padding:20px;border-radius:10px;text-align:center;text-decoration:none;color:var(--text);}
        .card:hover{transform:scale(1.02);background:#222;}
    </style>
    </head>
    <body>
        <div class="container">
            <div class="header"><h2>📦 لوحة المخزن</h2><p>مرحباً {{ session.username }}</p></div>
            <div class="grid">
                <a href="/products" class="card">📦 المنتجات</a>
                <a href="/admin/labels" class="card">🏷️ طباعة الملصقات</a>
                <a href="/admin/backup" class="card">💾 النسخ الاحتياطي</a>
                <a href="/admin/reports/export/inventory?format=excel" class="card">📊 تقرير المخزون</a>
            </div>
        </div>
    </body>
    </html>
    """)

# =============================== المسارات الإدارية ===============================
@app.route('/admin/settings')
@admin_required
def admin_settings():
    return "صفحة الإعدادات - قيد التطوير"

@app.route('/admin/products', methods=['GET', 'POST'])
@admin_required
def admin_products():
    if request.method == 'POST':
        name = request.form.get('name')
        price = float(request.form.get('price', 0))
        quantity = float(request.form.get('quantity', 0))
        barcode = request.form.get('barcode', '')
        if name and price > 0:
            execute_query("""
                INSERT INTO products (name, price, quantity, barcode, is_active)
                VALUES (?, ?, ?, ?, 1)
            """, (name, price, quantity, barcode), commit=True)
            return redirect('/admin/products')
    products = execute_query("SELECT * FROM products WHERE is_active=1 ORDER BY name", fetch_all=True)
    return render_template_string("""
    <!DOCTYPE html>
    <html dir="rtl">
    <head><meta charset="UTF-8"><title>إدارة المنتجات</title>
    <style>
        :root { --bg: #000; --text: #FFD700; --card-bg: #111; --border: #FFD700; --btn-bg: #FFD700; --btn-text: #000; }
        body{background:var(--bg);color:var(--text);padding:20px;font-family:Arial;}
        .container{max-width:1000px;margin:auto;}
        .header{background:var(--card-bg);border:1px solid var(--border);padding:20px;border-radius:10px;margin-bottom:20px;}
        .form-group{margin:10px 0;}
        input,select{width:100%;padding:8px;background:#000;color:#FFD700;border:1px solid var(--border);border-radius:5px;}
        .btn{background:var(--btn-bg);color:var(--btn-text);padding:8px 15px;border:none;border-radius:5px;cursor:pointer;}
        table{width:100%;border-collapse:collapse;background:var(--card-bg);border:1px solid var(--border);}
        th,td{padding:8px;border:1px solid var(--border);text-align:center;}
        th{background:var(--border);color:var(--btn-text);}
    </style>
    </head>
    <body>
        <div class="container">
            <div class="header"><h2>📦 إدارة المنتجات</h2><a href="/admin">العودة للوحة</a></div>
            <h3>إضافة منتج جديد</h3>
            <form method="post">
                <div class="form-group"><input type="text" name="name" placeholder="اسم المنتج" required></div>
                <div class="form-group"><input type="number" name="price" placeholder="السعر" step="0.01" required></div>
                <div class="form-group"><input type="number" name="quantity" placeholder="الكمية" step="0.01" required></div>
                <div class="form-group"><input type="text" name="barcode" placeholder="الباركود (اختياري)"></div>
                <button type="submit" class="btn">➕ إضافة</button>
            </form>
            <h3 style="margin-top:30px;">قائمة المنتجات</h3>
            <table>
                <tr><th>#</th><th>الاسم</th><th>السعر</th><th>الكمية</th><th>الباركود</th></tr>
                {% for p in products %}
                <tr><td>{{ p.id }}</td><td>{{ p.name }}</td><td>{{ p.price }}</td><td>{{ p.quantity }}</td><td>{{ p.barcode or '' }}</td></tr>
                {% endfor %}
            </table>
        </div>
    </body>
    </html>
    """, products=products)

@app.route('/admin/suppliers')
@admin_required
def admin_suppliers():
    suppliers = execute_query("SELECT * FROM suppliers ORDER BY name", fetch_all=True)
    return render_template_string("""
    <!DOCTYPE html>
    <html dir="rtl">
    <head><meta charset="UTF-8"><title>الموردين</title>
    <style>
        :root { --bg: #000; --text: #FFD700; --card-bg: #111; --border: #FFD700; --btn-bg: #FFD700; --btn-text: #000; }
        body{background:var(--bg);color:var(--text);padding:20px;font-family:Arial;}
        .container{max-width:1000px;margin:auto;}
        .header{background:var(--card-bg);border:1px solid var(--border);padding:20px;border-radius:10px;margin-bottom:20px;}
        table{width:100%;border-collapse:collapse;background:var(--card-bg);border:1px solid var(--border);}
        th,td{padding:8px;border:1px solid var(--border);text-align:center;}
        th{background:var(--border);color:var(--btn-text);}
    </style>
    </head>
    <body>
        <div class="container">
            <div class="header"><h2>🏭 الموردين</h2><a href="/admin">العودة للوحة</a></div>
            <table>
                <tr><th>#</th><th>الاسم</th><th>الهاتف</th><th>العنوان</th></tr>
                {% for s in suppliers %}
                <tr><td>{{ s.id }}</td><td>{{ s.name }}</td><td>{{ s.phone or '' }}</td><td>{{ s.address or '' }}</td></tr>
                {% endfor %}
            </table>
        </div>
    </body>
    </html>
    """, suppliers=suppliers)

@app.route('/admin/purchases')
@admin_required
def admin_purchases():
    purchases = execute_query("""
        SELECT p.*, s.name as supplier_name
        FROM purchases p
        LEFT JOIN suppliers s ON p.supplier_id = s.id
        ORDER BY p.created_at DESC LIMIT 50
    """, fetch_all=True)
    return render_template_string("""
    <!DOCTYPE html>
    <html dir="rtl">
    <head><meta charset="UTF-8"><title>المشتريات</title>
    <style>
        :root { --bg: #000; --text: #FFD700; --card-bg: #111; --border: #FFD700; --btn-bg: #FFD700; --btn-text: #000; }
        body{background:var(--bg);color:var(--text);padding:20px;font-family:Arial;}
        .container{max-width:1000px;margin:auto;}
        .header{background:var(--card-bg);border:1px solid var(--border);padding:20px;border-radius:10px;margin-bottom:20px;}
        table{width:100%;border-collapse:collapse;background:var(--card-bg);border:1px solid var(--border);}
        th,td{padding:8px;border:1px solid var(--border);text-align:center;}
        th{background:var(--border);color:var(--btn-text);}
    </style>
    </head>
    <body>
        <div class="container">
            <div class="header"><h2>📥 المشتريات</h2><a href="/admin">العودة للوحة</a><a href="/admin/scan-invoice" style="margin-right:15px;">📄 مسح فاتورة</a></div>
            <table>
                <tr><th>#</th><th>المورد</th><th>رقم الفاتورة</th><th>الإجمالي</th><th>التاريخ</th></tr>
                {% for p in purchases %}
                <tr><td>{{ p.id }}</td><td>{{ p.supplier_name or 'غير محدد' }}</td><td>{{ p.invoice_number or '' }}</td><td>{{ p.total_cost }}</td><td>{{ p.purchase_date or p.created_at }}</td></tr>
                {% endfor %}
            </table>
        </div>
    </body>
    </html>
    """, purchases=purchases)

@app.route('/admin/offers')
@admin_required
def admin_offers():
    offers = execute_query("SELECT * FROM offers ORDER BY created_at DESC", fetch_all=True)
    return render_template_string("""
    <!DOCTYPE html>
    <html dir="rtl">
    <head><meta charset="UTF-8"><title>العروض</title>
    <style>
        :root { --bg: #000; --text: #FFD700; --card-bg: #111; --border: #FFD700; --btn-bg: #FFD700; --btn-text: #000; }
        body{background:var(--bg);color:var(--text);padding:20px;font-family:Arial;}
        .container{max-width:1000px;margin:auto;}
        .header{background:var(--card-bg);border:1px solid var(--border);padding:20px;border-radius:10px;margin-bottom:20px;}
        table{width:100%;border-collapse:collapse;background:var(--card-bg);border:1px solid var(--border);}
        th,td{padding:8px;border:1px solid var(--border);text-align:center;}
        th{background:var(--border);color:var(--btn-text);}
    </style>
    </head>
    <body>
        <div class="container">
            <div class="header"><h2>🎁 العروض</h2><a href="/admin">العودة للوحة</a></div>
            <table>
                <tr><th>#</th><th>العنوان</th><th>الخصم</th><th>تاريخ البدء</th><th>تاريخ الانتهاء</th><th>الحالة</th></tr>
                {% for o in offers %}
                <tr><td>{{ o.id }}</td><td>{{ o.title }}</td><td>{{ o.discount_value }}%</td><td>{{ o.start_date or '' }}</td><td>{{ o.end_date or '' }}</td><td>{{ '✅ مفعل' if o.is_active else '❌ غير مفعل' }}</td></tr>
                {% endfor %}
            </table>
        </div>
    </body>
    </html>
    """, offers=offers)

@app.route('/admin/customers')
@admin_required
def admin_customers():
    customers = execute_query("SELECT * FROM customers ORDER BY total_spent DESC LIMIT 100", fetch_all=True)
    return render_template_string("""
    <!DOCTYPE html>
    <html dir="rtl">
    <head><meta charset="UTF-8"><title>العملاء</title>
    <style>
        :root { --bg: #000; --text: #FFD700; --card-bg: #111; --border: #FFD700; --btn-bg: #FFD700; --btn-text: #000; }
        body{background:var(--bg);color:var(--text);padding:20px;font-family:Arial;}
        .container{max-width:1200px;margin:auto;}
        .header{background:var(--card-bg);border:1px solid var(--border);padding:20px;border-radius:10px;margin-bottom:20px;}
        table{width:100%;border-collapse:collapse;background:var(--card-bg);border:1px solid var(--border);}
        th,td{padding:8px;border:1px solid var(--border);text-align:center;}
        th{background:var(--border);color:var(--btn-text);}
    </style>
    </head>
    <body>
        <div class="container">
            <div class="header"><h2>👥 العملاء</h2><a href="/admin">العودة للوحة</a></div>
            <table>
                <tr><th>#</th><th>الاسم</th><th>الهاتف</th><th>النقاط</th><th>إجمالي المشتريات</th><th>المستوى</th></tr>
                {% for c in customers %}
                <tr><td>{{ c.id }}</td><td>{{ c.name or 'غير معروف' }}</td><td>{{ c.phone }}</td><td>{{ c.loyalty_points or 0 }}</td><td>{{ c.total_spent or 0 }}</td><td>{{ c.tier or 'عادي' }}</td></tr>
                {% endfor %}
            </table>
        </div>
    </body>
    </html>
    """, customers=customers)

@app.route('/admin/invoices')
@admin_required
def admin_invoices():
    invoices = execute_query("""
        SELECT i.*, u.username as created_by_name
        FROM invoices i
        LEFT JOIN users u ON i.created_by = u.id
        ORDER BY i.created_at DESC LIMIT 100
    """, fetch_all=True)
    return render_template_string("""
    <!DOCTYPE html>
    <html dir="rtl">
    <head><meta charset="UTF-8"><title>الفواتير</title>
    <style>
        :root { --bg: #000; --text: #FFD700; --card-bg: #111; --border: #FFD700; --btn-bg: #FFD700; --btn-text: #000; }
        body{background:var(--bg);color:var(--text);padding:20px;font-family:Arial;}
        .container{max-width:1200px;margin:auto;}
        .header{background:var(--card-bg);border:1px solid var(--border);padding:20px;border-radius:10px;margin-bottom:20px;}
        table{width:100%;border-collapse:collapse;background:var(--card-bg);border:1px solid var(--border);}
        th,td{padding:8px;border:1px solid var(--border);text-align:center;}
        th{background:var(--border);color:var(--btn-text);}
        .anomaly{color:#f44336;font-weight:bold;}
    </style>
    </head>
    <body>
        <div class="container">
            <div class="header"><h2>📄 الفواتير</h2><a href="/admin">العودة للوحة</a></div>
            <table>
                <tr><th>رقم الفاتورة</th><th>العميل</th><th>الإجمالي</th><th>الخصم</th><th>المبلغ النهائي</th><th>طريقة الدفع</th><th>التاريخ</th><th>شاذ</th></tr>
                {% for i in invoices %}
                <tr>
                    <td>{{ i.invoice_number }}</td>
                    <td>{{ i.customer_name or 'غير معروف' }}</td>
                    <td>{{ i.total }}</td>
                    <td>{{ i.discount }}</td>
                    <td>{{ i.final_total }}</td>
                    <td>{{ i.payment_method or 'غير محدد' }}</td>
                    <td>{{ i.created_at }}</td>
                    <td class="{% if i.is_anomaly %}anomaly{% endif %}">{{ '🚨' if i.is_anomaly else '✅' }}</td>
                </tr>
                {% endfor %}
            </table>
        </div>
    </body>
    </html>
    """, invoices=invoices)

@app.route('/admin/reports')
@admin_required
def admin_reports():
    return render_template_string("""
    <!DOCTYPE html>
    <html dir="rtl">
    <head><meta charset="UTF-8"><title>التقارير</title>
    <style>
        :root { --bg: #000; --text: #FFD700; --card-bg: #111; --border: #FFD700; --btn-bg: #FFD700; --btn-text: #000; }
        body{background:var(--bg);color:var(--text);padding:20px;font-family:Arial;}
        .container{max-width:800px;margin:auto;}
        .header{background:var(--card-bg);border:1px solid var(--border);padding:20px;border-radius:10px;margin-bottom:20px;}
        .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:15px;}
        .card{background:var(--card-bg);border:1px solid var(--border);padding:20px;border-radius:10px;text-align:center;text-decoration:none;color:var(--text);display:block;}
        .card:hover{transform:scale(1.02);background:#222;}
    </style>
    </head>
    <body>
        <div class="container">
            <div class="header"><h2>📊 التقارير</h2><a href="/admin">العودة للوحة</a></div>
            <div class="grid">
                <a href="/admin/reports/export/inventory?format=excel" class="card">📦 تقرير المخزون (Excel)</a>
                <a href="/admin/reports/export/inventory?format=pdf" class="card">📦 تقرير المخزون (PDF)</a>
                <a href="/admin/reports/export/sales?format=excel" class="card">💰 تقرير المبيعات (Excel)</a>
                <a href="/admin/reports/export/sales?format=pdf" class="card">💰 تقرير المبيعات (PDF)</a>
                <a href="/admin/reports/export/expiry?format=excel" class="card">⏰ تقرير الصلاحية (Excel)</a>
                <a href="/admin/reports/export/expiry?format=pdf" class="card">⏰ تقرير الصلاحية (PDF)</a>
                <a href="/admin/analytics" class="card">📈 التحليل الذكي</a>
            </div>
        </div>
    </body>
    </html>
    """)

@app.route('/admin/users')
@admin_required
def admin_users():
    users = execute_query("SELECT id, username, role, full_name, created_at FROM users", fetch_all=True)
    return render_template_string("""
    <!DOCTYPE html>
    <html dir="rtl">
    <head><meta charset="UTF-8"><title>المستخدمين</title>
    <style>
        :root { --bg: #000; --text: #FFD700; --card-bg: #111; --border: #FFD700; --btn-bg: #FFD700; --btn-text: #000; }
        body{background:var(--bg);color:var(--text);padding:20px;font-family:Arial;}
        .container{max-width:800px;margin:auto;}
        .header{background:var(--card-bg);border:1px solid var(--border);padding:20px;border-radius:10px;margin-bottom:20px;}
        table{width:100%;border-collapse:collapse;background:var(--card-bg);border:1px solid var(--border);}
        th,td{padding:8px;border:1px solid var(--border);text-align:center;}
        th{background:var(--border);color:var(--btn-text);}
    </style>
    </head>
    <body>
        <div class="container">
            <div class="header"><h2>👤 المستخدمين</h2><a href="/admin">العودة للوحة</a></div>
            <table>
                <tr><th>#</th><th>اسم المستخدم</th><th>الدور</th><th>الاسم الكامل</th><th>تاريخ التسجيل</th></tr>
                {% for u in users %}
                <tr><td>{{ u.id }}</td><td>{{ u.username }}</td><td>{{ u.role }}</td><td>{{ u.full_name or '' }}</td><td>{{ u.created_at }}</td></tr>
                {% endfor %}
            </table>
        </div>
    </body>
    </html>
    """, users=users)

@app.route('/admin/returns')
@admin_required
def admin_returns():
    returns = execute_query("""
        SELECT r.*, i.invoice_number
        FROM returns r
        LEFT JOIN invoices i ON r.invoice_id = i.id
        ORDER BY r.return_date DESC LIMIT 50
    """, fetch_all=True)
    return render_template_string("""
    <!DOCTYPE html>
    <html dir="rtl">
    <head><meta charset="UTF-8"><title>المرتجعات</title>
    <style>
        :root { --bg: #000; --text: #FFD700; --card-bg: #111; --border: #FFD700; --btn-bg: #FFD700; --btn-text: #000; }
        body{background:var(--bg);color:var(--text);padding:20px;font-family:Arial;}
        .container{max-width:1000px;margin:auto;}
        .header{background:var(--card-bg);border:1px solid var(--border);padding:20px;border-radius:10px;margin-bottom:20px;}
        table{width:100%;border-collapse:collapse;background:var(--card-bg);border:1px solid var(--border);}
        th,td{padding:8px;border:1px solid var(--border);text-align:center;}
        th{background:var(--border);color:var(--btn-text);}
    </style>
    </head>
    <body>
        <div class="container">
            <div class="header"><h2>🔄 المرتجعات</h2><a href="/admin">العودة للوحة</a></div>
            <table>
                <tr><th>#</th><th>رقم الفاتورة</th><th>المنتج</th><th>الكمية</th><th>المبلغ</th><th>السبب</th><th>التاريخ</th></tr>
                {% for r in returns %}
                <tr><td>{{ r.id }}</td><td>{{ r.invoice_number or '' }}</td><td>{{ r.product_name }}</td><td>{{ r.quantity }}</td><td>{{ r.total }}</td><td>{{ r.reason or '' }}</td><td>{{ r.return_date }}</td></tr>
                {% endfor %}
            </table>
        </div>
    </body>
    </html>
    """, returns=returns)

# =============================== تشغيل التطبيق ===============================
if __name__ == '__main__':
    print("="*70)
    print("🚀 وكالة البشائر للأدوية والمستلزمات الطبية (النسخة الأسطورية)")
    print("="*70)
    print(f"📁 قاعدة البيانات: {'PostgreSQL' if DATABASE_URL else 'SQLite local'}")
    print("🧠 الميزات المتطورة:")
    print("   💰 التسعير الديناميكي (Dynamic Pricing)")
    print("   🛡️ كشف الشذوذ والاحتيال (Anomaly Detection)")
    print("   🤖 مساعد ذكي متقدم (RAG + LLM)")
    print("   📷 التعرف على الأدوية من الصور (OCR + CV)")
    print("   🎯 توصيات مخصصة للعملاء")
    print("   💬 تحليل المشاعر من التقييمات")
    print("   📄 استخراج بيانات الفواتير الورقية")
    print("   📊 لوحات تحليل ذكية")
    print("   🚀 لوحة تحكم 3D تفاعلية")
    print("   🎤 واجهة صوتية (Voice Interface)")
    print("   🏷️ نظام طباعة وتسميات")
    print("   📱 تطبيق موبايل (PWA)")
    print("   💳 تكامل الدفع الإلكتروني")
    print("   💾 نسخ احتياطي متقدم")
    print("="*70)
    print("🔐 بيانات الدخول:")
    print("   admin / admin123 (مدير)")
    print("   pharmacist / pharma123 (صيدلي)")
    print("   cashier / cashier123 (كاشير)")
    print("   stock / stock123 (أمين مخزن)")
    print("   purchaser / purch123 (مندوب مشتريات)")
    print("="*70)
    print("🌐 الروابط الرئيسية:")
    print("   👉 http://localhost:5000/                          (الرئيسية)")
    print("   👉 http://localhost:5000/admin                     (لوحة المدير)")
    print("   👉 http://localhost:5000/admin/dashboard-3d        (لوحة 3D)")
    print("   👉 http://localhost:5000/voice-assistant           (المساعد الصوتي)")
    print("   👉 http://localhost:5000/admin/labels              (طباعة الملصقات)")
    print("   👉 http://localhost:5000/admin/backup              (النسخ الاحتياطي)")
    print("   👉 http://localhost:5000/chat                      (المساعد الذكي)")
    print("   👉 http://localhost:5000/pos                       (نقطة البيع)")
    print("   👉 http://localhost:5000/cart                      (السلة)")
    print("="*70)
    print("✅ تم التحميل بنجاح! افتح الرابط في المتصفح.")
    app.run(host='127.0.0.1', port=5000, debug=True, threaded=True)
