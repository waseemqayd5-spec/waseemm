"""
نظام إدارة وكالة البشائر للأدوية والمستلزمات الطبية
نسخة متوافقة مع Render.com (بدون apt-get)
"""

import os
import sys
import gc
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
from flask import (
    Flask, request, jsonify, render_template_string, session,
    redirect, url_for, make_response, send_from_directory, Response, send_file
)
from openpyxl import Workbook
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
import qrcode
from io import BytesIO

# ===== كشف بيئة Render =====
IS_RENDER = os.environ.get('RENDER', False)

if IS_RENDER:
    print("🚀 تشغيل على Render.com (وضع محسن)")
    os.environ['TOKENIZERS_PARALLELISM'] = 'false'
    gc.set_threshold(100, 5, 5)

# ===== تعطيل الميزات الثقيلة إذا كانت المكتبات غير موجودة =====
try:
    import numpy as np
    from sklearn.ensemble import IsolationForest
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics.pairwise import cosine_similarity
    from sklearn.feature_extraction.text import TfidfVectorizer
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    print("⚠️ scikit-learn غير مثبت (سيتم تعطيل بعض الميزات)")

try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMER_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMER_AVAILABLE = False
    print("⚠️ sentence-transformers غير مثبت (سيتم تعطيل RAG)")

# تعطيل OCR على Render (لأنه يحتاج apt-get)
OCR_AVAILABLE = False
print("⚠️ OCR معطل في بيئة Render")

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
        cur.execute("""CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, username VARCHAR(50) UNIQUE NOT NULL, password_hash VARCHAR(200) NOT NULL, role VARCHAR(20) DEFAULT 'cashier', full_name VARCHAR(100), created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS settings (key VARCHAR(100) PRIMARY KEY, value TEXT)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS customers (id SERIAL PRIMARY KEY, phone VARCHAR(20) UNIQUE, name VARCHAR(100), address TEXT, tax_number VARCHAR(50), commercial_register VARCHAR(50), payment_terms VARCHAR(50) DEFAULT 'cash', loyalty_points INTEGER DEFAULT 0, total_spent REAL DEFAULT 0, visits INTEGER DEFAULT 0, last_visit DATE, tier VARCHAR(20) DEFAULT 'عادي', is_active INTEGER DEFAULT 1, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS suppliers (id SERIAL PRIMARY KEY, name VARCHAR(100) NOT NULL, phone VARCHAR(20), address TEXT, email VARCHAR(100), contact_person VARCHAR(100), license_number VARCHAR(50), bank_account TEXT, notes TEXT)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS units (id SERIAL PRIMARY KEY, name VARCHAR(50) UNIQUE NOT NULL, symbol VARCHAR(10), base_unit_id INTEGER REFERENCES units(id), conversion_factor REAL DEFAULT 1.0, is_base BOOLEAN DEFAULT FALSE)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS products (id SERIAL PRIMARY KEY, barcode VARCHAR(50) UNIQUE, name VARCHAR(200) NOT NULL, description TEXT, category VARCHAR(50), unit_id INTEGER REFERENCES units(id), price REAL NOT NULL, cost_price REAL, quantity REAL DEFAULT 0, min_quantity REAL DEFAULT 10, supplier_id INTEGER REFERENCES suppliers(id), expiry_date DATE, added_date DATE, last_updated DATE, image_url TEXT, image_url2 TEXT, is_active INTEGER DEFAULT 1, active_ingredient TEXT, dosage_form TEXT, strength TEXT, manufacturer TEXT, batch_number TEXT, storage_conditions TEXT, prescription_required BOOLEAN DEFAULT FALSE, unit_pack_size INTEGER, dynamic_price REAL, price_updated_at TIMESTAMP, sales_velocity REAL DEFAULT 0, abc_class CHAR(1) DEFAULT 'C', xyz_class CHAR(1) DEFAULT 'Z')""")
        cur.execute("""CREATE TABLE IF NOT EXISTS purchases (id SERIAL PRIMARY KEY, supplier_id INTEGER REFERENCES suppliers(id), invoice_number VARCHAR(50), total_cost REAL, purchase_date DATE, notes TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS purchase_items (id SERIAL PRIMARY KEY, purchase_id INTEGER REFERENCES purchases(id), product_id INTEGER REFERENCES products(id), quantity REAL, cost_price REAL, total REAL, batch_number TEXT, expiry_date DATE)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS offers (id SERIAL PRIMARY KEY, title VARCHAR(200) NOT NULL, description TEXT, code VARCHAR(50), discount_type VARCHAR(20) DEFAULT 'percentage', discount_value REAL, start_date DATE, end_date DATE, is_active INTEGER DEFAULT 1, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS invoices (id SERIAL PRIMARY KEY, invoice_number VARCHAR(50) UNIQUE NOT NULL, customer_id INTEGER REFERENCES customers(id), customer_name VARCHAR(100), customer_phone VARCHAR(20), customer_address TEXT, total REAL NOT NULL, discount REAL DEFAULT 0, final_total REAL NOT NULL, payment_method VARCHAR(50), points_earned INTEGER DEFAULT 0, points_used INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, created_by INTEGER REFERENCES users(id), is_anomaly BOOLEAN DEFAULT FALSE, anomaly_score REAL DEFAULT 0, anomaly_reason TEXT)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS invoice_items (id SERIAL PRIMARY KEY, invoice_id INTEGER REFERENCES invoices(id), product_id INTEGER REFERENCES products(id), product_name VARCHAR(200), quantity REAL NOT NULL, price REAL NOT NULL, total REAL NOT NULL, batch_number TEXT, expiry_date DATE)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS inventory_logs (id SERIAL PRIMARY KEY, product_id INTEGER REFERENCES products(id), product_name TEXT, change_type TEXT, quantity_change REAL, old_quantity REAL, new_quantity REAL, notes TEXT, user_id INTEGER REFERENCES users(id), timestamp TEXT)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS returns (id SERIAL PRIMARY KEY, invoice_id INTEGER REFERENCES invoices(id), product_id INTEGER REFERENCES products(id), product_name VARCHAR(200), quantity REAL, price REAL, total REAL, reason TEXT, return_date DATE, created_by INTEGER REFERENCES users(id))""")
        cur.execute("""CREATE TABLE IF NOT EXISTS alerts (id SERIAL PRIMARY KEY, type VARCHAR(50), product_id INTEGER REFERENCES products(id), message TEXT, is_read BOOLEAN DEFAULT FALSE, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS feedback (id SERIAL PRIMARY KEY, customer_id INTEGER REFERENCES customers(id), customer_name VARCHAR(100), customer_phone VARCHAR(20), rating INTEGER CHECK (rating >= 1 AND rating <= 5), comment TEXT, sentiment_score REAL, sentiment_label VARCHAR(20), created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS price_history (id SERIAL PRIMARY KEY, product_id INTEGER REFERENCES products(id), old_price REAL, new_price REAL, reason TEXT, created_by INTEGER REFERENCES users(id), created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS anomaly_logs (id SERIAL PRIMARY KEY, invoice_id INTEGER REFERENCES invoices(id), anomaly_score REAL, reason TEXT, is_reviewed BOOLEAN DEFAULT FALSE, reviewed_by INTEGER REFERENCES users(id), created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS recommendations (id SERIAL PRIMARY KEY, customer_id INTEGER REFERENCES customers(id), product_id INTEGER REFERENCES products(id), score REAL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS product_similarity (product_id1 INTEGER REFERENCES products(id), product_id2 INTEGER REFERENCES products(id), similarity_score REAL, PRIMARY KEY (product_id1, product_id2))""")
        cur.execute("""CREATE TABLE IF NOT EXISTS payments (id SERIAL PRIMARY KEY, payment_id VARCHAR(50) UNIQUE NOT NULL, invoice_id INTEGER REFERENCES invoices(id), amount REAL NOT NULL, status VARCHAR(20) DEFAULT 'pending', payment_method VARCHAR(50), created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, completed_at TIMESTAMP)""")
    else:
        # SQLite
        cur.execute("""CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, role TEXT DEFAULT 'cashier', full_name TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS customers (id INTEGER PRIMARY KEY AUTOINCREMENT, phone TEXT UNIQUE, name TEXT, address TEXT, tax_number TEXT, commercial_register TEXT, payment_terms TEXT DEFAULT 'cash', loyalty_points INTEGER DEFAULT 0, total_spent REAL DEFAULT 0, visits INTEGER DEFAULT 0, last_visit DATE, tier TEXT DEFAULT 'عادي', is_active INTEGER DEFAULT 1, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS suppliers (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, phone TEXT, address TEXT, email TEXT, contact_person TEXT, license_number TEXT, bank_account TEXT, notes TEXT)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS units (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL, symbol TEXT, base_unit_id INTEGER REFERENCES units(id), conversion_factor REAL DEFAULT 1.0, is_base BOOLEAN DEFAULT FALSE)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY AUTOINCREMENT, barcode TEXT UNIQUE, name TEXT NOT NULL, description TEXT, category TEXT, unit_id INTEGER REFERENCES units(id), price REAL NOT NULL, cost_price REAL, quantity REAL DEFAULT 0, min_quantity REAL DEFAULT 10, supplier_id INTEGER REFERENCES suppliers(id), expiry_date DATE, added_date DATE, last_updated DATE, image_url TEXT, image_url2 TEXT, is_active INTEGER DEFAULT 1, active_ingredient TEXT, dosage_form TEXT, strength TEXT, manufacturer TEXT, batch_number TEXT, storage_conditions TEXT, prescription_required BOOLEAN DEFAULT FALSE, unit_pack_size INTEGER, dynamic_price REAL, price_updated_at TIMESTAMP, sales_velocity REAL DEFAULT 0, abc_class CHAR(1) DEFAULT 'C', xyz_class CHAR(1) DEFAULT 'Z')""")
        cur.execute("""CREATE TABLE IF NOT EXISTS purchases (id INTEGER PRIMARY KEY AUTOINCREMENT, supplier_id INTEGER REFERENCES suppliers(id), invoice_number TEXT, total_cost REAL, purchase_date DATE, notes TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS purchase_items (id INTEGER PRIMARY KEY AUTOINCREMENT, purchase_id INTEGER REFERENCES purchases(id), product_id INTEGER REFERENCES products(id), quantity REAL, cost_price REAL, total REAL, batch_number TEXT, expiry_date DATE)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS offers (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, description TEXT, code TEXT, discount_type TEXT DEFAULT 'percentage', discount_value REAL, start_date DATE, end_date DATE, is_active INTEGER DEFAULT 1, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS invoices (id INTEGER PRIMARY KEY AUTOINCREMENT, invoice_number TEXT UNIQUE NOT NULL, customer_id INTEGER REFERENCES customers(id), customer_name TEXT, customer_phone TEXT, customer_address TEXT, total REAL NOT NULL, discount REAL DEFAULT 0, final_total REAL NOT NULL, payment_method TEXT, points_earned INTEGER DEFAULT 0, points_used INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, created_by INTEGER REFERENCES users(id), is_anomaly BOOLEAN DEFAULT FALSE, anomaly_score REAL DEFAULT 0, anomaly_reason TEXT)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS invoice_items (id INTEGER PRIMARY KEY AUTOINCREMENT, invoice_id INTEGER REFERENCES invoices(id), product_id INTEGER REFERENCES products(id), product_name TEXT, quantity REAL NOT NULL, price REAL NOT NULL, total REAL NOT NULL, batch_number TEXT, expiry_date DATE)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS inventory_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, product_id INTEGER REFERENCES products(id), product_name TEXT, change_type TEXT, quantity_change REAL, old_quantity REAL, new_quantity REAL, notes TEXT, user_id INTEGER REFERENCES users(id), timestamp TEXT)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS returns (id INTEGER PRIMARY KEY AUTOINCREMENT, invoice_id INTEGER REFERENCES invoices(id), product_id INTEGER REFERENCES products(id), product_name TEXT, quantity REAL, price REAL, total REAL, reason TEXT, return_date DATE, created_by INTEGER REFERENCES users(id))""")
        cur.execute("""CREATE TABLE IF NOT EXISTS alerts (id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT, product_id INTEGER REFERENCES products(id), message TEXT, is_read BOOLEAN DEFAULT FALSE, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS feedback (id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER REFERENCES customers(id), customer_name TEXT, customer_phone TEXT, rating INTEGER, comment TEXT, sentiment_score REAL, sentiment_label TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS price_history (id INTEGER PRIMARY KEY AUTOINCREMENT, product_id INTEGER REFERENCES products(id), old_price REAL, new_price REAL, reason TEXT, created_by INTEGER REFERENCES users(id), created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS anomaly_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, invoice_id INTEGER REFERENCES invoices(id), anomaly_score REAL, reason TEXT, is_reviewed BOOLEAN DEFAULT FALSE, reviewed_by INTEGER REFERENCES users(id), created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS recommendations (id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER REFERENCES customers(id), product_id INTEGER REFERENCES products(id), score REAL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS product_similarity (product_id1 INTEGER REFERENCES products(id), product_id2 INTEGER REFERENCES products(id), similarity_score REAL, PRIMARY KEY (product_id1, product_id2))""")
        cur.execute("""CREATE TABLE IF NOT EXISTS payments (id INTEGER PRIMARY KEY AUTOINCREMENT, payment_id TEXT UNIQUE NOT NULL, invoice_id INTEGER REFERENCES invoices(id), amount REAL NOT NULL, status TEXT DEFAULT 'pending', payment_method TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, completed_at TIMESTAMP)""")

    # إدخال البيانات الافتراضية
    cur.execute("SELECT COUNT(*) FROM units")
    if cur.fetchone()[0] == 0:
        units = [('حبة', 'حب', None, 1.0, 1), ('علبة', 'علبة', None, 1.0, 0), ('شريط', 'شريط', None, 1.0, 0), ('كرتونة', 'كرتونة', None, 1.0, 0), ('لتر', 'لتر', None, 1.0, 0), ('ملجم', 'ملجم', None, 1.0, 0), ('جرام', 'جرام', None, 1.0, 0)]
        for unit in units:
            cur.execute("INSERT INTO units (name, symbol, base_unit_id, conversion_factor, is_base) VALUES (?, ?, ?, ?, ?)", unit)

    cur.execute("SELECT COUNT(*) FROM users")
    if cur.fetchone()[0] == 0:
        hashed = generate_password_hash('admin123')
        cur.execute("INSERT INTO users (username, password_hash, role, full_name) VALUES (?, ?, ?, ?)", ('admin', hashed, 'admin', 'مدير النظام'))
        hashed_ph = generate_password_hash('pharma123')
        cur.execute("INSERT INTO users (username, password_hash, role, full_name) VALUES (?, ?, ?, ?)", ('pharmacist', hashed_ph, 'pharmacist', 'صيدلي رئيسي'))
        hashed_cashier = generate_password_hash('cashier123')
        cur.execute("INSERT INTO users (username, password_hash, role, full_name) VALUES (?, ?, ?, ?)", ('cashier', hashed_cashier, 'cashier', 'كاشير'))
        hashed_stock = generate_password_hash('stock123')
        cur.execute("INSERT INTO users (username, password_hash, role, full_name) VALUES (?, ?, ?, ?)", ('stock', hashed_stock, 'store_keeper', 'أمين مخزن'))
        hashed_purch = generate_password_hash('purch123')
        cur.execute("INSERT INTO users (username, password_hash, role, full_name) VALUES (?, ?, ?, ?)", ('purchaser', hashed_purch, 'purchaser', 'مندوب مشتريات'))

    cur.execute("SELECT COUNT(*) FROM settings")
    if cur.fetchone()[0] == 0:
        default_settings = [('company_name', 'وكالة البشائر للأدوية والمستلزمات الطبية'), ('company_logo', '💊'), ('company_address', 'اليمن - صنعاء'), ('company_phone', '967771602370'), ('company_whatsapp', '967771602370'), ('delivery_fee', '0.00'), ('points_per_riyal', '0'), ('points_redeem_rate', '0'), ('currency', 'ريال يمني'), ('tax_rate', '0.00'), ('default_unit', 'حبة')]
        for key, val in default_settings:
            cur.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (key, val))

    cur.execute("SELECT COUNT(*) FROM suppliers")
    if cur.fetchone()[0] == 0:
        cur.execute("INSERT INTO suppliers (name, phone, address, contact_person, license_number) VALUES (?, ?, ?, ?, ?)", ('شركة الحكمة للأدوية', '0500000001', 'صنعاء', 'أحمد القرشي', 'LIC001'))
        cur.execute("INSERT INTO suppliers (name, phone, address, contact_person, license_number) VALUES (?, ?, ?, ?, ?)", ('مستودع الأمان', '0500000002', 'عدن', 'سامي النجار', 'LIC002'))

    cur.execute("SELECT COUNT(*) FROM customers")
    if cur.fetchone()[0] == 0:
        cur.execute("INSERT INTO customers (phone, name, address, tax_number, commercial_register, payment_terms) VALUES (?, ?, ?, ?, ?, ?)", ('0500000000', 'صيدلية الرحمة', 'صنعاء - شارع الستين', 'TAX001', 'CR001', 'credit'))
        cur.execute("INSERT INTO customers (phone, name, address, tax_number, commercial_register, payment_terms) VALUES (?, ?, ?, ?, ?, ?)", ('0500000003', 'مستشفى السلام', 'صنعاء - السبعين', 'TAX002', 'CR002', 'cash'))

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
            ("6281234567890", "باراسيتامول 500 مجم", "مسكن وخافض حرارة", "مسكنات", unit_id, 5.0, 3.5, 200, 20, sup1, (today + datetime.timedelta(days=365)).isoformat(), today.isoformat(), today.isoformat(), None, None, 1, "باراسيتامول", "أقراص", "500 مجم", "شركة الحكمة", "BATCH001", "درجة حرارة الغرفة", False, 10, None, None, 0, 'A', 'X'),
            ("6280987654321", "أموكسيسيلين 500 مجم", "مضاد حيوي", "مضادات حيوية", unit_id, 15.0, 10.0, 100, 15, sup1, (today + datetime.timedelta(days=180)).isoformat(), today.isoformat(), today.isoformat(), None, None, 1, "أموكسيسيلين", "كبسولات", "500 مجم", "جلوبال فارما", "BATCH002", "يحفظ في الثلاجة", True, 20, None, None, 0, 'A', 'X'),
            ("6281122334455", "أوميبرازول 40 مجم", "علاج قرحة المعدة", "جهاز هضمي", unit_id, 8.0, 5.0, 150, 10, sup2, (today + datetime.timedelta(days=200)).isoformat(), today.isoformat(), today.isoformat(), None, None, 1, "أوميبرازول", "أقراص", "40 مجم", "الأمان", "BATCH003", "درجة حرارة الغرفة", False, 14, None, None, 0, 'B', 'Y'),
            ("6289988776655", "سيتالوبريم 20 مجم", "مضاد اكتئاب", "أمراض نفسية", unit_id, 12.0, 8.0, 80, 10, sup2, (today + datetime.timedelta(days=150)).isoformat(), today.isoformat(), today.isoformat(), None, None, 1, "سيتالوبريم", "أقراص", "20 مجم", "الأمان", "BATCH004", "درجة حرارة الغرفة", True, 28, None, None, 0, 'B', 'Z'),
        ]
        for prod in products:
            cur.execute("""INSERT INTO products (barcode, name, description, category, unit_id, price, cost_price, quantity, min_quantity, supplier_id, expiry_date, added_date, last_updated, image_url, image_url2, is_active, active_ingredient, dosage_form, strength, manufacturer, batch_number, storage_conditions, prescription_required, unit_pack_size, dynamic_price, price_updated_at, sales_velocity, abc_class, xyz_class) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", prod)

    conn.commit()
    conn.close()

init_db()

# =============================== نظام الإشعارات ===============================
notification_queue = queue.Queue()

def check_alerts():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name, quantity, min_quantity FROM products WHERE quantity <= min_quantity AND is_active = 1")
    low_stock = cur.fetchall()
    for row in low_stock:
        msg = f"المنتج '{row['name']}' مخزونه منخفض (الكمية: {row['quantity']}، الحد الأدنى: {row['min_quantity']})"
        execute_query("INSERT INTO alerts (type, product_id, message) VALUES (?, ?, ?)", ('low_stock', row['id'], msg), commit=True)
        notification_queue.put({'type': 'low_stock', 'message': msg, 'product_id': row['id']})
    today = datetime.date.today()
    expiry_threshold = today + datetime.timedelta(days=30)
    cur.execute("SELECT id, name, expiry_date FROM products WHERE expiry_date <= ? AND expiry_date >= ? AND is_active = 1", (expiry_threshold, today))
    near_expiry = cur.fetchall()
    for row in near_expiry:
        days_left = (row['expiry_date'] - today).days
        msg = f"المنتج '{row['name']}' سينتهي صلاحيته خلال {days_left} يوم"
        execute_query("INSERT INTO alerts (type, product_id, message) VALUES (?, ?, ?)", ('expiry', row['id'], msg), commit=True)
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

# =============================== التسعير الديناميكي ===============================
def calculate_dynamic_price(product_id):
    product = execute_query("SELECT id, name, price, cost_price, quantity, sales_velocity, expiry_date, category, abc_class FROM products WHERE id = ?", (product_id,), fetch_one=True)
    if not product:
        return None
    base_price = product['price']
    cost = product['cost_price'] or base_price * 0.6
    quantity = product['quantity'] or 0
    velocity = product['sales_velocity'] or 1.0
    expiry = product['expiry_date']
    factors = {'demand': 1.0, 'stock': 1.0, 'expiry': 1.0, 'category': 1.0, 'class': 1.0}
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
    execute_query("UPDATE products SET dynamic_price = ?, price_updated_at = CURRENT_TIMESTAMP WHERE id = ?", (dynamic_price, product_id), commit=True)
    execute_query("INSERT INTO price_history (product_id, old_price, new_price, reason, created_by) VALUES (?, ?, ?, ?, ?)", (product_id, base_price, dynamic_price, 'تحديث تلقائي - تسعير ديناميكي', 1), commit=True)
    return dynamic_price

@app.route('/api/dynamic-price/<int:product_id>', methods=['GET'])
def api_dynamic_price(product_id):
    price = calculate_dynamic_price(product_id)
    if price is None:
        return jsonify({'success': False, 'message': 'المنتج غير موجود'})
    return jsonify({'success': True, 'price': price})

@app.route('/admin/dynamic-pricing')
@admin_required
def dynamic_pricing_page():
    products = execute_query("SELECT id, name, price, dynamic_price, sales_velocity, quantity, expiry_date, price_updated_at, abc_class FROM products WHERE is_active = 1 ORDER BY name", fetch_all=True)
    return render_template_string("""
    <!DOCTYPE html><html dir="rtl"><head><meta charset="UTF-8"><title>التسعير الديناميكي</title>
    <style>:root{--bg:#000;--text:#FFD700;--card-bg:#111;--border:#FFD700;--btn-bg:#FFD700;--btn-text:#000}body.light{--bg:#f5f5f5;--text:#000;--card-bg:#fff;--border:#007bff;--btn-bg:#007bff;--btn-text:#fff}body{background:var(--bg);color:var(--text);padding:20px;font-family:Arial}.container{max-width:1200px;margin:auto}.header{background:var(--card-bg);border:1px solid var(--border);padding:20px;border-radius:10px;margin-bottom:20px}.nav a{color:var(--text);text-decoration:none;margin-left:15px}table{width:100%;border-collapse:collapse;background:var(--card-bg);border:1px solid var(--border)}th,td{padding:10px;border:1px solid var(--border);text-align:center}th{background:var(--border);color:var(--btn-text)}.btn{background:var(--btn-bg);color:var(--btn-text);padding:8px 15px;border:none;border-radius:5px;cursor:pointer}.price-up{color:#4CAF50}.price-down{color:#f44336}.theme-toggle{position:fixed;top:20px;left:20px;background:var(--btn-bg);color:var(--btn-text);border:none;border-radius:50%;width:50px;height:50px;font-size:20px;cursor:pointer;z-index:1000}.chat-float{position:fixed;bottom:20px;left:20px;background:var(--btn-bg);color:var(--btn-text);width:60px;height:60px;border-radius:50%;font-size:30px;display:flex;align-items:center;justify-content:center;cursor:pointer;z-index:999;box-shadow:0 4px 15px rgba(0,0,0,0.5);text-decoration:none}</style>
    </head><body>
    <button class="theme-toggle" onclick="toggleTheme()">🌓</button>
    <a href="/chat" class="chat-float">💬</a>
    <div class="container"><div class="header"><h2>📊 التسعير الديناميكي</h2><div class="nav"><a href="/admin">لوحة المدير</a><a href="/admin/dynamic-pricing">التسعير الديناميكي</a></div><button class="btn" onclick="updateAllPrices()">🔄 تحديث الأسعار</button></div><div id="result"></div>
    <table><thead><tr><th>#</th><th>المنتج</th><th>السعر الحالي</th><th>السعر الديناميكي</th><th>سرعة المبيعات</th><th>المخزون</th><th>التصنيف</th><th>آخر تحديث</th><th>إجراء</th></tr></thead><tbody>
    {% for p in products %}<tr><td>{{ p.id }}</td><td>{{ p.name }}</td><td>{{ p.price }}</td><td class="{% if p.dynamic_price and p.dynamic_price > p.price %}price-up{% elif p.dynamic_price and p.dynamic_price < p.price %}price-down{% endif %}">{{ p.dynamic_price or p.price }}</td><td>{{ "%.1f"|format(p.sales_velocity or 0) }}</td><td>{{ p.quantity }}</td><td>{{ p.abc_class or '-' }}</td><td>{{ p.price_updated_at or 'لم يحدث' }}</td><td><button class="btn" onclick="updatePrice({{ p.id }})">تحديث</button></td></tr>{% endfor %}
    </tbody></table></div>
    <script>function toggleTheme(){document.body.classList.toggle('light');localStorage.setItem('theme',document.body.classList.contains('light')?'light':'dark');}if(localStorage.getItem('theme')==='light')document.body.classList.add('light');function updatePrice(id){fetch(`/api/dynamic-price/${id}`).then(r=>r.json()).then(data=>{if(data.success){document.getElementById('result').innerHTML=`<p style="color:green;">✅ تم التحديث</p>`;setTimeout(()=>location.reload(),1000);}});}function updateAllPrices(){if(!confirm('تحديث جميع الأسعار؟'))return;fetch('/api/update-all-prices',{method:'POST'}).then(r=>r.json()).then(data=>{document.getElementById('result').innerHTML=`<p style="color:green;">✅ ${data.message}</p>`;setTimeout(()=>location.reload(),1500);});}</script>
    </body></html>
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
        items = execute_query("SELECT ii.quantity FROM invoice_items ii JOIN invoices i ON ii.invoice_id = i.id WHERE ii.product_id = ? AND i.created_at >= datetime('now', '-30 days')", (pid,), fetch_all=True)
        if items:
            total_qty = sum(item['quantity'] for item in items)
            velocity = total_qty / 30.0
        else:
            velocity = 0.1
        execute_query("UPDATE products SET sales_velocity = ? WHERE id = ?", (velocity, pid), commit=True)

# =============================== كشف الشذوذ والاحتيال ===============================
def detect_anomaly(invoice_data):
    if not SKLEARN_AVAILABLE:
        return {'is_anomaly': False, 'score': 0, 'reason': 'scikit-learn غير مثبت'}
    try:
        past_invoices = execute_query("SELECT id, total, discount, final_total, (SELECT COUNT(*) FROM invoice_items WHERE invoice_id = invoices.id) as item_count FROM invoices WHERE created_at >= datetime('now', '-30 days') ORDER BY created_at DESC LIMIT 100", fetch_all=True)
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
        return {'is_anomaly': False, 'score': 0, 'reason': f'خطأ: {str(e)}'}

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
    anomalies = execute_query("SELECT i.*, u.username as created_by_name FROM invoices i LEFT JOIN users u ON i.created_by = u.id WHERE i.is_anomaly = 1 ORDER BY i.created_at DESC", fetch_all=True)
    anomaly_logs = execute_query("SELECT al.*, i.invoice_number, i.customer_name FROM anomaly_logs al JOIN invoices i ON al.invoice_id = i.id ORDER BY al.created_at DESC LIMIT 50", fetch_all=True)
    return render_template_string("""
    <!DOCTYPE html><html dir="rtl"><head><meta charset="UTF-8"><title>كشف الشذوذ</title>
    <style>:root{--bg:#000;--text:#FFD700;--card-bg:#111;--border:#FFD700;--btn-bg:#FFD700;--btn-text:#000}body.light{--bg:#f5f5f5;--text:#000;--card-bg:#fff;--border:#007bff;--btn-bg:#007bff;--btn-text:#fff}body{background:var(--bg);color:var(--text);padding:20px;font-family:Arial}.container{max-width:1200px;margin:auto}.header{background:var(--card-bg);border:1px solid var(--border);padding:20px;border-radius:10px;margin-bottom:20px}.nav a{color:var(--text);text-decoration:none;margin-left:15px}table{width:100%;border-collapse:collapse;background:var(--card-bg);border:1px solid var(--border)}th,td{padding:10px;border:1px solid var(--border);text-align:center}th{background:var(--border);color:var(--btn-text)}.btn{background:var(--btn-bg);color:var(--btn-text);padding:8px 15px;border:none;border-radius:5px;cursor:pointer}.high-risk{color:#f44336}.theme-toggle{position:fixed;top:20px;left:20px;background:var(--btn-bg);color:var(--btn-text);border:none;border-radius:50%;width:50px;height:50px;font-size:20px;cursor:pointer;z-index:1000}.chat-float{position:fixed;bottom:20px;left:20px;background:var(--btn-bg);color:var(--btn-text);width:60px;height:60px;border-radius:50%;font-size:30px;display:flex;align-items:center;justify-content:center;cursor:pointer;z-index:999;box-shadow:0 4px 15px rgba(0,0,0,0.5);text-decoration:none}</style>
    </head><body><button class="theme-toggle" onclick="toggleTheme()">🌓</button><a href="/chat" class="chat-float">💬</a>
    <div class="container"><div class="header"><h2>🛡️ كشف الشذوذ</h2><div class="nav"><a href="/admin">لوحة المدير</a><a href="/admin/anomalies">الفواتير الشاذة</a></div></div>
    <h3>🚨 الفواتير الشاذة</h3>
    {% if anomalies %}<table><thead><tr><th>رقم الفاتورة</th><th>العميل</th><th>الإجمالي</th><th>الخصم</th><th>المبلغ النهائي</th><th>طريقة الدفع</th><th>التاريخ</th><th>السبب</th><th>الحالة</th></tr></thead><tbody>
    {% for inv in anomalies %}<tr><td>{{ inv.invoice_number }}</td><td>{{ inv.customer_name or 'غير معروف' }}</td><td>{{ inv.total }}</td><td>{{ inv.discount }}</td><td class="high-risk">{{ inv.final_total }}</td><td>{{ inv.payment_method }}</td><td>{{ inv.created_at }}</td><td>{{ inv.anomaly_reason or 'غير محدد' }}</td><td><button class="btn" onclick="markReviewed({{ inv.id }})">✅ مراجعة</button></td></tr>{% endfor %}
    </tbody></table>{% else %}<p>✅ لا توجد فواتير شاذة</p>{% endif %}
    <h3 style="margin-top:30px;">📋 سجل المراجعة</h3>
    {% if anomaly_logs %}<table><thead><tr><th>الفاتورة</th><th>العميل</th><th>درجة الشذوذ</th><th>السبب</th><th>تمت المراجعة</th><th>التاريخ</th></tr></thead><tbody>
    {% for log in anomaly_logs %}<tr><td>{{ log.invoice_number }}</td><td>{{ log.customer_name or 'غير معروف' }}</td><td>{{ "%.2f"|format(log.anomaly_score) }}</td><td>{{ log.reason }}</td><td>{{ '✅' if log.is_reviewed else '⏳' }}</td><td>{{ log.created_at }}</td></tr>{% endfor %}
    </tbody></table>{% else %}<p>لا توجد سجلات مراجعة</p>{% endif %}</div>
    <script>function toggleTheme(){document.body.classList.toggle('light');localStorage.setItem('theme',document.body.classList.contains('light')?'light':'dark');}if(localStorage.getItem('theme')==='light')document.body.classList.add('light');function markReviewed(id){fetch(`/api/mark-anomaly-reviewed/${id}`,{method:'POST'}).then(r=>r.json()).then(data=>{if(data.success)location.reload();});}</script>
    </body></html>
    """, anomalies=anomalies, anomaly_logs=anomaly_logs)

@app.route('/api/mark-anomaly-reviewed/<int:invoice_id>', methods=['POST'])
@admin_required
def mark_anomaly_reviewed(invoice_id):
    execute_query("UPDATE invoices SET is_anomaly = 0 WHERE id = ?", (invoice_id,), commit=True)
    execute_query("UPDATE anomaly_logs SET is_reviewed = 1, reviewed_by = ? WHERE invoice_id = ?", (session.get('user_id', 1), invoice_id), commit=True)
    return jsonify({'success': True})

# =============================== المساعد الذكي (RAG) ===============================
embedding_model = None
if SENTENCE_TRANSFORMER_AVAILABLE:
    try:
        embedding_model = SentenceTransformer('paraphrase-MiniLM-L3-v2')
    except:
        embedding_model = None

def get_product_embeddings():
    products = execute_query("SELECT id, name, description, active_ingredient, category, manufacturer, price FROM products WHERE is_active = 1", fetch_all=True)
    if not products or embedding_model is None:
        return None, None
    texts = [f"{p['name']} {p['description'] or ''} {p['active_ingredient'] or ''} {p['category'] or ''}" for p in products]
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
        return [{'product': dict(products[idx]), 'similarity': float(similarities[idx])} for idx in top_indices]
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
        context = "المنتجات ذات الصلة:\n" + "\n".join([f"- {r['product']['name']} (السعر: {r['product']['price']} ريال)" for r in rag_results])
    if GEMINI_API_KEY:
        try:
            system_prompt = f"أنت مساعد صيدلاني. معلومات من قاعدة البيانات:\n{context}\nسؤال: {user_message}"
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
            payload = {"contents": [{"role": "user", "parts": [{"text": system_prompt}]}]}
            resp = requests.post(url, json=payload, timeout=15)
            if resp.status_code == 200:
                candidates = resp.json().get("candidates", [])
                if candidates:
                    reply = candidates[0]["content"]["parts"][0]["text"]
                    return jsonify({"success": True, "reply": reply, "rag_results": rag_results})
        except:
            pass
    if rag_results:
        reply = "📋 منتجات ذات صلة:\n" + "\n".join([f"{i+1}. {r['product']['name']} - {r['product']['price']} ريال" for i, r in enumerate(rag_results[:3])])
    else:
        reply = "🔍 لم أجد منتجات تطابق سؤالك"
    return jsonify({"success": True, "reply": reply, "rag_results": rag_results})

# =============================== تحليل المشاعر ===============================
def analyze_sentiment(text):
    if not text:
        return {'label': 'محايد', 'score': 0.0}
    if GEMINI_API_KEY:
        try:
            prompt = f"حلل المشاعر في النص: '{text}' وأخرج JSON: {{'label':'إيجابي|سلبي|محايد','score':0.0-1.0}}"
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
            payload = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                candidates = resp.json().get("candidates", [])
                if candidates:
                    content = candidates[0]["content"]["parts"][0]["text"]
                    json_match = re.search(r'\{.*\}', content)
                    if json_match:
                        result = json.loads(json_match.group())
                        return {'label': result.get('label', 'محايد'), 'score': result.get('score', 0.5)}
        except:
            pass
    positive_words = ['ممتاز', 'رائع', 'جيد', 'مفيد', 'فعال', 'سريع']
    negative_words = ['سيء', 'مضر', 'ضعيف', 'بطيء', 'غير مفيد', 'خطير']
    pos_score = sum(1 for w in positive_words if w in text.lower())
    neg_score = sum(1 for w in negative_words if w in text.lower())
    if pos_score > neg_score:
        return {'label': 'إيجابي', 'score': min(0.5 + (pos_score - neg_score) * 0.1, 1.0)}
    elif neg_score > pos_score:
        return {'label': 'سلبي', 'score': min(0.5 + (neg_score - pos_score) * 0.1, 1.0)}
    return {'label': 'محايد', 'score': 0.5}

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
    execute_query("INSERT INTO feedback (customer_id, customer_name, customer_phone, rating, comment, sentiment_score, sentiment_label) VALUES (?, ?, ?, ?, ?, ?, ?)", (customer_id, customer_name, customer_phone, rating, comment, sentiment['score'], sentiment['label']), commit=True)
    return jsonify({'success': True, 'message': 'شكراً لتقييمك', 'sentiment': sentiment})

@app.route('/admin/feedback')
@admin_required
def feedback_page():
    feedbacks = execute_query("SELECT * FROM feedback ORDER BY created_at DESC LIMIT 100", fetch_all=True)
    stats = execute_query("SELECT COUNT(*) as total, AVG(rating) as avg_rating, SUM(CASE WHEN sentiment_label = 'إيجابي' THEN 1 ELSE 0 END) as positive, SUM(CASE WHEN sentiment_label = 'سلبي' THEN 1 ELSE 0 END) as negative, SUM(CASE WHEN sentiment_label = 'محايد' THEN 1 ELSE 0 END) as neutral FROM feedback", fetch_one=True)
    return render_template_string("""
    <!DOCTYPE html><html dir="rtl"><head><meta charset="UTF-8"><title>تحليل المشاعر</title>
    <style>:root{--bg:#000;--text:#FFD700;--card-bg:#111;--border:#FFD700;--btn-bg:#FFD700;--btn-text:#000}body.light{--bg:#f5f5f5;--text:#000;--card-bg:#fff;--border:#007bff;--btn-bg:#007bff;--btn-text:#fff}body{background:var(--bg);color:var(--text);padding:20px;font-family:Arial}.container{max-width:1200px;margin:auto}.header{background:var(--card-bg);border:1px solid var(--border);padding:20px;border-radius:10px;margin-bottom:20px}.stats{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:15px;margin-bottom:20px}.stat-card{background:var(--card-bg);border:1px solid var(--border);padding:15px;border-radius:10px;text-align:center}.stat-card .num{font-size:24px;font-weight:bold}.feedback-item{background:var(--card-bg);border:1px solid var(--border);padding:15px;border-radius:8px;margin:10px 0}.positive{color:#4CAF50}.negative{color:#f44336}.neutral{color:#FFC107}.theme-toggle{position:fixed;top:20px;left:20px;background:var(--btn-bg);color:var(--btn-text);border:none;border-radius:50%;width:50px;height:50px;font-size:20px;cursor:pointer;z-index:1000}.chat-float{position:fixed;bottom:20px;left:20px;background:var(--btn-bg);color:var(--btn-text);width:60px;height:60px;border-radius:50%;font-size:30px;display:flex;align-items:center;justify-content:center;cursor:pointer;z-index:999;box-shadow:0 4px 15px rgba(0,0,0,0.5);text-decoration:none}</style>
    </head><body><button class="theme-toggle" onclick="toggleTheme()">🌓</button><a href="/chat" class="chat-float">💬</a>
    <div class="container"><div class="header"><h2>📊 تحليل المشاعر</h2><div class="nav"><a href="/admin">لوحة المدير</a><a href="/admin/feedback">التقييمات</a></div></div>
    <div class="stats"><div class="stat-card"><div class="num">{{ stats.total or 0 }}</div>إجمالي التقييمات</div><div class="stat-card"><div class="num">{{ "%.1f"|format(stats.avg_rating or 0) }}</div>متوسط التقييم</div><div class="stat-card positive"><div class="num">{{ stats.positive or 0 }}</div>👍 إيجابي</div><div class="stat-card negative"><div class="num">{{ stats.negative or 0 }}</div>👎 سلبي</div><div class="stat-card neutral"><div class="num">{{ stats.neutral or 0 }}</div>😐 محايد</div></div>
    <h3>📝 التقييمات الأخيرة</h3>
    {% for fb in feedbacks %}<div class="feedback-item"><div style="display:flex;justify-content:space-between;flex-wrap:wrap;"><span><strong>{{ fb.customer_name or 'غير معروف' }}</strong></span><span>⭐ {{ fb.rating }}/5</span><span class="{% if fb.sentiment_label == 'إيجابي' %}positive{% elif fb.sentiment_label == 'سلبي' %}negative{% else %}neutral{% endif %}">{{ fb.sentiment_label or 'محايد' }}</span><span style="font-size:12px;color:#aaa;">{{ fb.created_at }}</span></div><p>{{ fb.comment }}</p></div>{% else %}<p>لا توجد تقييمات</p>{% endfor %}</div>
    <script>function toggleTheme(){document.body.classList.toggle('light');localStorage.setItem('theme',document.body.classList.contains('light')?'light':'dark');}if(localStorage.getItem('theme')==='light')document.body.classList.add('light');</script>
    </body></html>
    """, stats=stats, feedbacks=feedbacks)

# =============================== توصيات العملاء ===============================
def generate_recommendations(customer_id):
    customer_items = execute_query("SELECT DISTINCT ii.product_id FROM invoice_items ii JOIN invoices i ON ii.invoice_id = i.id WHERE i.customer_id = ?", (customer_id,), fetch_all=True)
    if not customer_items:
        top = execute_query("SELECT product_id FROM invoice_items GROUP BY product_id ORDER BY SUM(quantity) DESC LIMIT 5", fetch_all=True)
        return [p['product_id'] for p in top]
    bought_ids = [p['product_id'] for p in customer_items]
    similar = execute_query("SELECT product_id2 as product_id FROM product_similarity WHERE product_id1 IN ({}) ORDER BY similarity_score DESC LIMIT 10".format(','.join('?' * len(bought_ids))), bought_ids, fetch_all=True)
    if similar:
        recs = [p['product_id'] for p in similar if p['product_id'] not in bought_ids]
        if recs:
            return recs[:5]
    return [p['product_id'] for p in customer_items[:5]]

@app.route('/api/recommendations/<int:customer_id>')
def api_recommendations(customer_id):
    recs = generate_recommendations(customer_id)
    if recs:
        products = execute_query(f"SELECT id, name, price FROM products WHERE id IN ({','.join('?' * len(recs))}) AND is_active = 1", recs, fetch_all=True)
    else:
        products = []
    return jsonify({'success': True, 'recommendations': [dict(p) for p in products]})

# =============================== التحليل الذكي ===============================
@app.route('/admin/analytics')
@admin_required
def analytics_page():
    stats = execute_query("SELECT (SELECT COUNT(*) FROM products WHERE is_active=1) as total_products, (SELECT COUNT(*) FROM customers) as total_customers, (SELECT COUNT(*) FROM invoices WHERE DATE(created_at)=DATE('now')) as today_sales, (SELECT IFNULL(SUM(final_total),0) FROM invoices WHERE DATE(created_at)=DATE('now')) as today_revenue, (SELECT IFNULL(SUM(final_total),0) FROM invoices WHERE created_at>=DATE('now','-30 days')) as month_revenue", fetch_one=True)
    top_products = execute_query("SELECT p.name, SUM(ii.quantity) as total_sold FROM invoice_items ii JOIN products p ON ii.product_id = p.id GROUP BY ii.product_id ORDER BY total_sold DESC LIMIT 10", fetch_all=True)
    daily_sales = execute_query("SELECT DATE(created_at) as day, IFNULL(SUM(final_total),0) as total FROM invoices WHERE created_at>=DATE('now','-7 days') GROUP BY DATE(created_at) ORDER BY day", fetch_all=True)
    return render_template_string("""
    <!DOCTYPE html><html dir="rtl"><head><meta charset="UTF-8"><title>التحليل الذكي</title><script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>:root{--bg:#000;--text:#FFD700;--card-bg:#111;--border:#FFD700;--btn-bg:#FFD700;--btn-text:#000}body.light{--bg:#f5f5f5;--text:#000;--card-bg:#fff;--border:#007bff;--btn-bg:#007bff;--btn-text:#fff}body{background:var(--bg);color:var(--text);padding:20px;font-family:Arial}.container{max-width:1400px;margin:auto}.header{background:var(--card-bg);border:1px solid var(--border);padding:20px;border-radius:10px;margin-bottom:20px}.stats-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:15px;margin-bottom:20px}.stat-card{background:var(--card-bg);border:1px solid var(--border);padding:15px;border-radius:10px;text-align:center}.stat-card .num{font-size:28px;font-weight:bold}.chart-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(400px,1fr));gap:20px}.chart-box{background:var(--card-bg);border:1px solid var(--border);padding:15px;border-radius:10px}.chart-box canvas{max-height:300px;width:100% !important}.theme-toggle{position:fixed;top:20px;left:20px;background:var(--btn-bg);color:var(--btn-text);border:none;border-radius:50%;width:50px;height:50px;font-size:20px;cursor:pointer;z-index:1000}.chat-float{position:fixed;bottom:20px;left:20px;background:var(--btn-bg);color:var(--btn-text);width:60px;height:60px;border-radius:50%;font-size:30px;display:flex;align-items:center;justify-content:center;cursor:pointer;z-index:999;box-shadow:0 4px 15px rgba(0,0,0,0.5);text-decoration:none}</style>
    </head><body><button class="theme-toggle" onclick="toggleTheme()">🌓</button><a href="/chat" class="chat-float">💬</a>
    <div class="container"><div class="header"><h2>📊 التحليل الذكي</h2><div class="nav"><a href="/admin">لوحة المدير</a><a href="/admin/analytics">التحليل</a></div></div>
    <div class="stats-grid"><div class="stat-card"><div class="num">{{ stats.total_products or 0 }}</div>المنتجات</div><div class="stat-card"><div class="num">{{ stats.total_customers or 0 }}</div>العملاء</div><div class="stat-card"><div class="num">{{ stats.today_sales or 0 }}</div>مبيعات اليوم</div><div class="stat-card"><div class="num">{{ "%.0f"|format(stats.today_revenue or 0) }}</div>إيرادات اليوم</div><div class="stat-card"><div class="num">{{ "%.0f"|format(stats.month_revenue or 0) }}</div>إيرادات الشهر</div></div>
    <div class="chart-grid"><div class="chart-box"><h4>🏆 أفضل المنتجات</h4><canvas id="topChart"></canvas></div><div class="chart-box"><h4>📈 المبيعات اليومية</h4><canvas id="dailyChart"></canvas></div></div></div>
    <script>function toggleTheme(){document.body.classList.toggle('light');localStorage.setItem('theme',document.body.classList.contains('light')?'light':'dark');}if(localStorage.getItem('theme')==='light')document.body.classList.add('light');
    const topProducts = {{ top_products | tojson }}; const dailySales = {{ daily_sales | tojson }};
    new Chart(document.getElementById('topChart'),{type:'bar',data:{labels:topProducts.map(p=>p.name),datasets:[{label:'الكمية المباعة',data:topProducts.map(p=>p.total_sold),backgroundColor:'rgba(255,215,0,0.6)'}]},options:{responsive:true,plugins:{legend:{labels:{color:'#FFD700'}}},scales:{y:{ticks:{color:'#FFD700'}},x:{ticks:{color:'#FFD700'}}}}});
    new Chart(document.getElementById('dailyChart'),{type:'line',data:{labels:dailySales.map(d=>d.day),datasets:[{label:'الإيرادات',data:dailySales.map(d=>d.total),borderColor:'#FFD700',backgroundColor:'rgba(255,215,0,0.1)',fill:true,tension:0.3}]},options:{responsive:true,plugins:{legend:{labels:{color:'#FFD700'}}},scales:{y:{ticks:{color:'#FFD700'}},x:{ticks:{color:'#FFD700'}}}}});
    </script></body></html>
    """, stats=stats, top_products=top_products, daily_sales=daily_sales)

# =============================== لوحة المدير ===============================
@app.route('/admin')
@login_required
def admin_dashboard():
    if session['role'] != 'admin':
        return redirect(url_for('pos'))
    low_stock_count = execute_query("SELECT COUNT(*) as count FROM products WHERE quantity <= min_quantity AND is_active=1", fetch_one=True)['count'] or 0
    anomalies_count = execute_query("SELECT COUNT(*) as count FROM invoices WHERE is_anomaly = 1", fetch_one=True)['count'] or 0
    feedback_count = execute_query("SELECT COUNT(*) as count FROM feedback WHERE DATE(created_at) = DATE('now')", fetch_one=True)['count'] or 0
    return render_template_string("""
    <!DOCTYPE html><html dir="rtl"><head><title>لوحة الإدارة</title>
    <style>:root{--bg:#000;--text:#FFD700;--card-bg:#111;--border:#FFD700;--btn-bg:#FFD700;--btn-text:#000}body.light{--bg:#f5f5f5;--text:#000;--card-bg:#fff;--border:#007bff;--btn-bg:#007bff;--btn-text:#fff}body{background:var(--bg);color:var(--text);font-family:Arial;padding:20px}.header{background:var(--card-bg);border:1px solid var(--border);padding:20px;border-radius:10px;margin-bottom:20px}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:15px}.card{background:var(--card-bg);border:1px solid var(--border);padding:18px;border-radius:10px;text-align:center;cursor:pointer;transition:0.3s;color:var(--text);text-decoration:none;display:block}.card:hover{transform:translateY(-5px);background:#222}.card .icon{font-size:32px;display:block;margin-bottom:10px}.card .title{font-weight:bold}.card .badge{background:#f44336;color:#fff;border-radius:50%;padding:2px 10px;font-size:12px;margin-right:5px}.logout{position:absolute;top:20px;left:20px;background:var(--btn-bg);color:var(--btn-text);padding:10px;border-radius:5px;text-decoration:none}.alert{background:#8B0000;border:1px solid var(--border);padding:10px;border-radius:5px;margin-bottom:20px;color:#fff}.chat-float{position:fixed;bottom:20px;left:20px;background:var(--btn-bg);color:var(--btn-text);width:60px;height:60px;border-radius:50%;font-size:30px;display:flex;align-items:center;justify-content:center;cursor:pointer;z-index:999;box-shadow:0 4px 15px rgba(0,0,0,0.5);text-decoration:none}.theme-toggle{position:fixed;top:20px;left:70px;background:var(--btn-bg);color:var(--btn-text);border:none;border-radius:50%;width:50px;height:50px;font-size:20px;cursor:pointer;z-index:1000}.section-title{margin:25px 0 15px 0;border-right:4px solid var(--border);padding-right:15px}</style>
    </head><body><button class="theme-toggle" onclick="toggleTheme()">🌓</button><a href="/chat" class="chat-float">💬</a><a href="/logout" class="logout">تسجيل خروج</a>
    <div class="header"><h1>🎛️ لوحة التحكم</h1><p>مرحباً {{ session.username }} (مدير)</p></div>
    {% if low_stock_count > 0 %}<div class="alert">⚠️ يوجد {{ low_stock_count }} منتج مخزونها منخفض!</div>{% endif %}
    {% if anomalies_count > 0 %}<div class="alert" style="background:#8B0000;">🚨 يوجد {{ anomalies_count }} فاتورة شاذة!</div>{% endif %}
    <h3 class="section-title">📋 الإدارة</h3>
    <div class="grid">
        <a href="/admin/products" class="card"><span class="icon">📦</span><span class="title">المنتجات</span></a>
        <a href="/admin/suppliers" class="card"><span class="icon">🏭</span><span class="title">الموردين</span></a>
        <a href="/admin/purchases" class="card"><span class="icon">📥</span><span class="title">المشتريات</span></a>
        <a href="/admin/customers" class="card"><span class="icon">👥</span><span class="title">العملاء</span></a>
        <a href="/admin/invoices" class="card"><span class="icon">📄</span><span class="title">الفواتير</span></a>
        <a href="/admin/reports" class="card"><span class="icon">📊</span><span class="title">التقارير</span></a>
        <a href="/admin/users" class="card"><span class="icon">👤</span><span class="title">المستخدمين</span></a>
        <a href="/admin/returns" class="card"><span class="icon">🔄</span><span class="title">المرتجعات</span></a>
        <a href="/admin/labels" class="card"><span class="icon">🏷️</span><span class="title">طباعة الملصقات</span></a>
        <a href="/admin/backup" class="card"><span class="icon">💾</span><span class="title">النسخ الاحتياطي</span></a>
    </div>
    <h3 class="section-title">🧠 الذكاء الاصطناعي</h3>
    <div class="grid">
        <a href="/admin/dynamic-pricing" class="card"><span class="icon">💰</span><span class="title">التسعير الديناميكي</span></a>
        <a href="/admin/anomalies" class="card"><span class="icon">🛡️</span><span class="title">كشف الشذوذ <span class="badge">{{ anomalies_count }}</span></span></a>
        <a href="/admin/feedback" class="card"><span class="icon">💬</span><span class="title">تحليل المشاعر <span class="badge">{{ feedback_count }}</span></span></a>
        <a href="/admin/analytics" class="card"><span class="icon">📈</span><span class="title">التحليل الذكي</span></a>
        <a href="/customer/recommendations" class="card"><span class="icon">🎯</span><span class="title">توصيات العملاء</span></a>
        <a href="/chat" class="card"><span class="icon">🤖</span><span class="title">المساعد الذكي</span></a>
    </div>
    <h3 class="section-title">🔗 روابط سريعة</h3>
    <div class="grid">
        <a href="/pos" class="card"><span class="icon">🛒</span><span class="title">نقطة البيع</span></a>
        <a href="/cart" class="card"><span class="icon">🛍️</span><span class="title">السلة</span></a>
        <a href="/voice-assistant" class="card"><span class="icon">🎤</span><span class="title">المساعد الصوتي</span></a>
    </div>
    <script>function toggleTheme(){document.body.classList.toggle('light');localStorage.setItem('theme',document.body.classList.contains('light')?'light':'dark');}if(localStorage.getItem('theme')==='light')document.body.classList.add('light');</script>
    </body></html>
    """, low_stock_count=low_stock_count, anomalies_count=anomalies_count, feedback_count=feedback_count)

# =============================== تسجيل الدخول ===============================
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
            return redirect(url_for('admin_dashboard' if user['role'] == 'admin' else 'pos'))
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

# =============================== نقطة البيع ===============================
@app.route('/pos')
@login_required
def pos():
    return render_template_string("""
    <!DOCTYPE html><html dir="rtl"><head><title>نقطة البيع</title>
    <style>:root{--bg:#000;--text:#FFD700;--card-bg:#111;--border:#FFD700;--btn-bg:#FFD700;--btn-text:#000}body.light{--bg:#f5f5f5;--text:#000;--card-bg:#fff;--border:#007bff;--btn-bg:#007bff;--btn-text:#fff}body{background:var(--bg);color:var(--text);padding:20px;font-family:Arial}.container{max-width:1200px;margin:auto}.header{background:var(--card-bg);border:1px solid var(--border);padding:20px;border-radius:10px;margin-bottom:20px}.pos-grid{display:grid;grid-template-columns:2fr 1fr;gap:20px}.products-list{max-height:500px;overflow-y:auto;display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px}.product-item{background:var(--card-bg);border:1px solid var(--border);padding:10px;border-radius:8px;text-align:center;cursor:pointer}.product-item:hover{background:#222}.cart-item{background:var(--card-bg);border:1px solid var(--border);padding:8px;border-radius:5px;margin:5px 0;display:flex;justify-content:space-between;align-items:center}.btn{background:var(--btn-bg);color:var(--btn-text);padding:8px 15px;border:none;border-radius:5px;cursor:pointer}.theme-toggle{position:fixed;top:20px;left:20px;background:var(--btn-bg);color:var(--btn-text);border:none;border-radius:50%;width:50px;height:50px;font-size:20px;cursor:pointer;z-index:1000}.chat-float{position:fixed;bottom:20px;left:20px;background:var(--btn-bg);color:var(--btn-text);width:60px;height:60px;border-radius:50%;font-size:30px;display:flex;align-items:center;justify-content:center;cursor:pointer;z-index:999;box-shadow:0 4px 15px rgba(0,0,0,0.5);text-decoration:none}.barcode-input{display:flex;gap:10px;margin-bottom:15px}.barcode-input input{flex:1;padding:8px;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:5px}</style>
    </head><body><button class="theme-toggle" onclick="toggleTheme()">🌓</button><a href="/chat" class="chat-float">💬</a>
    <div class="container"><div class="header"><h2>🛒 نقطة البيع</h2><div class="nav"><a href="/">الرئيسية</a><a href="/pos">نقطة البيع</a><a href="/cart">السلة</a></div></div>
    <div class="barcode-input"><input type="text" id="barcodeInput" placeholder="الباركود" onkeypress="if(event.key==='Enter')scanBarcode()"><button class="btn" onclick="scanBarcode()">🔍 بحث</button></div>
    <div class="pos-grid"><div><h4>📦 المنتجات</h4><div id="productsList" class="products-list"></div></div><div><h4>🛒 السلة</h4><div id="cartList"></div><div style="margin-top:15px;padding:10px;background:var(--card-bg);border:1px solid var(--border);border-radius:8px;"><p><strong>الإجمالي:</strong> <span id="cartTotal">0</span> ريال</p><button class="btn" onclick="checkout()" style="width:100%;">✅ إنهاء الطلب</button><button class="btn" onclick="clearCart()" style="width:100%;margin-top:5px;background:#f44336;color:#fff;">🗑️ تفريغ</button></div></div></div></div>
    <script>let cart=[];function toggleTheme(){document.body.classList.toggle('light');localStorage.setItem('theme',document.body.classList.contains('light')?'light':'dark');}if(localStorage.getItem('theme')==='light')document.body.classList.add('light');
    function loadProducts(){fetch('/api/products?limit=30').then(r=>r.json()).then(data=>{if(data.success){let html='';data.products.forEach(p=>{html+=`<div class="product-item" onclick="addProduct(${p.id},'${p.name.replace(/'/g,"\\'")}',${p.price})"><div>${p.name}</div><div style="color:var(--btn-bg);font-weight:bold;">${p.price} ريال</div></div>`;});document.getElementById('productsList').innerHTML=html;}});}
    function addProduct(id,name,price){let existing=cart.find(i=>i.id===id);if(existing)existing.quantity+=1;else cart.push({id,name,price,quantity:1});renderCart();}
    function renderCart(){let html='',total=0;cart.forEach((item,idx)=>{let t=item.price*item.quantity;total+=t;html+=`<div class="cart-item"><span>${item.name} x${item.quantity}</span><span>${t} ريال</span><button onclick="removeItem(${idx})" style="background:#f44336;color:#fff;border:none;border-radius:3px;padding:2px 8px;">✕</button></div>`;});document.getElementById('cartList').innerHTML=html||'<p>السلة فارغة</p>';document.getElementById('cartTotal').innerText=total;}
    function removeItem(idx){cart.splice(idx,1);renderCart();}function clearCart(){cart=[];renderCart();}
    function scanBarcode(){let barcode=document.getElementById('barcodeInput').value.trim();if(!barcode)return;fetch('/api/scan-barcode',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({barcode})}).then(r=>r.json()).then(data=>{if(data.success){addProduct(data.product.id,data.product.name,data.product.price);document.getElementById('barcodeInput').value='';}else{alert('المنتج غير موجود');}});}
    function checkout(){if(cart.length===0){alert('السلة فارغة');return;}fetch('/api/check-anomaly',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cart:cart,total:cart.reduce((s,i)=>s+i.price*i.quantity,0)})}).then(r=>r.json()).then(anomaly=>{if(anomaly.is_anomaly&&!confirm(`⚠️ شذوذ: ${anomaly.reason}\nالمتابعة؟`))return;fetch('/api/create_invoice',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cart:cart,customer_name:'عميل',payment_method:'cash'})}).then(r=>r.json()).then(data=>{if(data.success){alert(`✅ فاتورة ${data.invoice_number}`);cart=[];renderCart();}else{alert('❌ '+data.message);}});});}
    loadProducts();</script></body></html>
    """)

# =============================== المسارات الأساسية ===============================
@app.route('/api/products')
def api_products():
    limit = request.args.get('limit', 50, type=int)
    search = request.args.get('search', '')
    query = "SELECT p.*, u.name as unit_name FROM products p LEFT JOIN units u ON p.unit_id = u.id WHERE p.is_active = 1"
    params = []
    if search:
        query += " AND p.name LIKE ?"
        params.append(f"%{search}%")
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
    product = execute_query("SELECT p.*, u.name as unit_name FROM products p LEFT JOIN units u ON p.unit_id = u.id WHERE p.barcode = ? AND p.is_active = 1", (barcode,), fetch_one=True)
    if product:
        return jsonify({'success': True, 'product': dict(product)})
    return jsonify({'success': False, 'message': 'المنتج غير موجود'})

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
        payment_method = data.get('payment_method', 'cash')
        total = sum(item['price'] * item['quantity'] for item in cart)
        discount = data.get('discount', 0)
        final_total = total - discount
        invoice_number = f"INV-{int(time.time())}"
        invoice_data = {'total': total, 'discount': discount, 'final_total': final_total, 'item_count': len(cart)}
        anomaly_result = detect_anomaly(invoice_data)
        execute_query("INSERT INTO invoices (invoice_number, customer_name, total, discount, final_total, payment_method, created_by, is_anomaly, anomaly_score, anomaly_reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (invoice_number, customer_name, total, discount, final_total, payment_method, session.get('user_id', 1), anomaly_result['is_anomaly'], anomaly_result['score'], anomaly_result['reason']), commit=True)
        invoice = execute_query("SELECT id FROM invoices WHERE invoice_number = ?", (invoice_number,), fetch_one=True)
        invoice_id = invoice['id']
        if anomaly_result['is_anomaly']:
            execute_query("INSERT INTO anomaly_logs (invoice_id, anomaly_score, reason) VALUES (?, ?, ?)", (invoice_id, anomaly_result['score'], anomaly_result['reason']), commit=True)
        for item in cart:
            execute_query("INSERT INTO invoice_items (invoice_id, product_id, product_name, quantity, price, total) VALUES (?, ?, ?, ?, ?, ?)", (invoice_id, item['id'], item['name'], item['quantity'], item['price'], item['price'] * item['quantity']), commit=True)
            product = execute_query("SELECT quantity FROM products WHERE id = ?", (item['id'],), fetch_one=True)
            if product:
                new_qty = product['quantity'] - item['quantity']
                execute_query("UPDATE products SET quantity = ? WHERE id = ?", (new_qty, item['id']), commit=True)
                log_inventory(item['id'], item['name'], 'sale', -item['quantity'], product['quantity'], new_qty, f"فاتورة {invoice_number}", session.get('user_id', 1))
        return jsonify({'success': True, 'invoice_number': invoice_number, 'is_anomaly': anomaly_result['is_anomaly']})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

# =============================== الصفحات الرئيسية ===============================
@app.route('/')
def home():
    settings = get_settings()
    return render_template_string("""
    <!DOCTYPE html><html dir="rtl"><head><meta charset="UTF-8"><title>وكالة البشائر</title>
    <style>:root{--bg:#000;--text:#FFD700;--card-bg:#111;--border:#FFD700;--btn-bg:#FFD700;--btn-text:#000}body.light{--bg:#f5f5f5;--text:#000;--card-bg:#fff;--border:#007bff;--btn-bg:#007bff;--btn-text:#fff}body{background:var(--bg);color:var(--text);padding:20px;font-family:Arial}.container{max-width:1200px;margin:auto}.header{text-align:center;padding:20px;background:var(--card-bg);border-radius:15px;margin-bottom:30px;border:1px solid var(--border)}.nav{display:flex;gap:15px;justify-content:center;margin-bottom:30px;flex-wrap:wrap}.nav a{background:var(--card-bg);color:var(--text);padding:12px 25px;text-decoration:none;border-radius:8px;border:1px solid var(--border)}.nav a:hover{background:var(--btn-bg);color:var(--btn-text)}.content{background:var(--card-bg);padding:25px;border-radius:15px;border:1px solid var(--border)}h2{border-right:4px solid var(--border);padding-right:15px}.products-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:25px;margin-top:20px}.product-card{background:var(--bg);border:1px solid var(--border);border-radius:12px;padding:15px;text-align:center}.product-name{font-weight:bold;font-size:18px}.product-price{font-size:22px;font-weight:bold}.btn{background:var(--btn-bg);color:var(--btn-text);padding:8px 15px;border:none;border-radius:5px;cursor:pointer}.barcode-scanner{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:20px}.barcode-scanner input{flex:1;padding:8px;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:5px}.chat-float{position:fixed;bottom:20px;left:20px;background:var(--btn-bg);color:var(--btn-text);width:60px;height:60px;border-radius:50%;font-size:30px;display:flex;align-items:center;justify-content:center;cursor:pointer;z-index:999;text-decoration:none}.theme-toggle{position:fixed;top:20px;left:20px;background:var(--btn-bg);color:var(--btn-text);border:none;border-radius:50%;width:50px;height:50px;font-size:20px;cursor:pointer;z-index:1000}</style>
    </head><body><button class="theme-toggle" onclick="toggleTheme()">🌓</button><a href="/chat" class="chat-float">💬</a>
    <div class="container"><div class="header"><h1>💊 وكالة البشائر</h1><p>نظام إدارة الأدوية والمستلزمات الطبية</p></div>
    <div class="nav"><a href="/" class="active">الرئيسية</a><a href="/products">الأدوية</a><a href="/cart">السلة</a><a href="/chat">💬 المساعد</a><a href="/pos">🛒 نقطة البيع</a><a href="/login">دخول الإدارة</a><a href="/voice-assistant">🎤 صوتي</a></div>
    <div class="content"><h2>مرحباً بكم</h2><p>أكبر موزع للأدوية في اليمن</p>
    <div class="barcode-scanner"><input type="text" id="barcode-input" placeholder="الباركود"><button class="btn" onclick="searchByBarcode()">🔍 بحث</button></div>
    <div id="scanned-product" style="margin:10px 0;padding:15px;border:1px solid var(--border);border-radius:8px;"></div>
    <div id="featured-products" class="products-grid"></div></div></div>
    <script>function toggleTheme(){document.body.classList.toggle('light');localStorage.setItem('theme',document.body.classList.contains('light')?'light':'dark');}if(localStorage.getItem('theme')==='light')document.body.classList.add('light');
    let quantities={};function loadProducts(){fetch('/api/products?limit=20').then(r=>r.json()).then(data=>{if(data.success){let html='';data.products.forEach(p=>{if(!quantities[p.id])quantities[p.id]=1;html+=`<div class="product-card"><div class="product-name">${p.name}</div><div class="product-price">${p.price} ريال</div><div>المتبقي: ${p.quantity}</div><button class="btn" onclick="addToCart(${p.id},'${p.name.replace(/'/g,"\\'")}',${p.price})">أضف للسلة</button></div>`;});document.getElementById('featured-products').innerHTML=html;}});}
    function addToCart(id,name,price){let cart=JSON.parse(localStorage.getItem('cart')||'[]');let existing=cart.find(i=>i.id==id);if(existing)existing.quantity+=1;else cart.push({id,name,price,quantity:1});localStorage.setItem('cart',JSON.stringify(cart));alert('تمت الإضافة');}
    function searchByBarcode(){let barcode=document.getElementById('barcode-input').value.trim();if(!barcode)return;fetch('/api/scan-barcode',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({barcode})}).then(r=>r.json()).then(data=>{if(data.success){let p=data.product;document.getElementById('scanned-product').innerHTML=`<div><strong>${p.name}</strong><br>السعر: ${p.price} ريال<br>الكمية: ${p.quantity}</div>`;let cart=JSON.parse(localStorage.getItem('cart')||'[]');let existing=cart.find(i=>i.id==p.id);if(existing)existing.quantity+=1;else cart.push({id:p.id,name:p.name,price:p.price,quantity:1});localStorage.setItem('cart',JSON.stringify(cart));alert('تمت الإضافة');}else{document.getElementById('scanned-product').innerHTML='<p style="color:red;">المنتج غير موجود</p>';}});}
    document.getElementById('barcode-input').addEventListener('keypress',function(e){if(e.key==='Enter')searchByBarcode();});
    loadProducts();</script></body></html>
    """, settings=settings)

@app.route('/products')
def products_page():
    return render_template_string("""
    <!DOCTYPE html><html dir="rtl"><head><meta charset="UTF-8"><title>الأدوية</title>
    <style>:root{--bg:#000;--text:#FFD700;--card-bg:#111;--border:#FFD700;--btn-bg:#FFD700;--btn-text:#000}body.light{--bg:#f5f5f5;--text:#000;--card-bg:#fff;--border:#007bff;--btn-bg:#007bff;--btn-text:#fff}body{background:var(--bg);color:var(--text);padding:20px;font-family:Arial}.container{max-width:1200px;margin:auto}.header{background:var(--card-bg);border:1px solid var(--border);padding:20px;border-radius:10px;margin-bottom:20px}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:20px}.card{background:var(--card-bg);border:1px solid var(--border);border-radius:8px;padding:15px;text-align:center}.btn{background:var(--btn-bg);color:var(--btn-text);padding:8px 15px;border:none;border-radius:5px;cursor:pointer}.theme-toggle{position:fixed;top:20px;left:20px;background:var(--btn-bg);color:var(--btn-text);border:none;border-radius:50%;width:50px;height:50px;font-size:20px;cursor:pointer;z-index:1000}.chat-float{position:fixed;bottom:20px;left:20px;background:var(--btn-bg);color:var(--btn-text);width:60px;height:60px;border-radius:50%;font-size:30px;display:flex;align-items:center;justify-content:center;cursor:pointer;z-index:999;text-decoration:none}</style>
    </head><body><button class="theme-toggle" onclick="toggleTheme()">🌓</button><a href="/chat" class="chat-float">💬</a>
    <div class="container"><div class="header"><h2>📦 الأدوية</h2><a href="/">الرئيسية</a> | <a href="/cart">السلة</a></div><div id="products" class="grid"></div></div>
    <script>function toggleTheme(){document.body.classList.toggle('light');localStorage.setItem('theme',document.body.classList.contains('light')?'light':'dark');}if(localStorage.getItem('theme')==='light')document.body.classList.add('light');
    fetch('/api/products?limit=100').then(r=>r.json()).then(data=>{if(data.success){let html='';data.products.forEach(p=>{html+=`<div class="card"><h4>${p.name}</h4><p>💰 ${p.price} ريال</p><button class="btn" onclick="addToCart(${p.id},'${p.name.replace(/'/g,"\\'")}',${p.price})">أضف للسلة</button></div>`;});document.getElementById('products').innerHTML=html;}});
    function addToCart(id,name,price){let cart=JSON.parse(localStorage.getItem('cart')||'[]');let existing=cart.find(i=>i.id===id);if(existing)existing.quantity+=1;else cart.push({id,name,price,quantity:1});localStorage.setItem('cart',JSON.stringify(cart));alert('تمت الإضافة');}</script></body></html>
    """)

@app.route('/cart')
def cart_page():
    return render_template_string("""
    <!DOCTYPE html><html dir="rtl"><head><meta charset="UTF-8"><title>السلة</title>
    <style>:root{--bg:#000;--text:#FFD700;--card-bg:#111;--border:#FFD700;--btn-bg:#FFD700;--btn-text:#000}body.light{--bg:#f5f5f5;--text:#000;--card-bg:#fff;--border:#007bff;--btn-bg:#007bff;--btn-text:#fff}body{background:var(--bg);color:var(--text);padding:20px;font-family:Arial}.container{max-width:800px;margin:auto}.header{background:var(--card-bg);border:1px solid var(--border);padding:20px;border-radius:10px;margin-bottom:20px}.cart-item{background:var(--card-bg);border:1px solid var(--border);padding:10px;border-radius:5px;display:flex;justify-content:space-between;align-items:center;margin:5px 0}.btn{background:var(--btn-bg);color:var(--btn-text);padding:8px 15px;border:none;border-radius:5px;cursor:pointer}.theme-toggle{position:fixed;top:20px;left:20px;background:var(--btn-bg);color:var(--btn-text);border:none;border-radius:50%;width:50px;height:50px;font-size:20px;cursor:pointer;z-index:1000}.chat-float{position:fixed;bottom:20px;left:20px;background:var(--btn-bg);color:var(--btn-text);width:60px;height:60px;border-radius:50%;font-size:30px;display:flex;align-items:center;justify-content:center;cursor:pointer;z-index:999;text-decoration:none}</style>
    </head><body><button class="theme-toggle" onclick="toggleTheme()">🌓</button><a href="/chat" class="chat-float">💬</a>
    <div class="container"><div class="header"><h2>🛒 السلة</h2><a href="/">الرئيسية</a> | <a href="/pos">نقطة البيع</a></div><div id="cartItems"></div>
    <div style="margin-top:20px;padding:15px;background:var(--card-bg);border:1px solid var(--border);border-radius:8px;"><p><strong>الإجمالي:</strong> <span id="totalPrice">0</span> ريال</p><button class="btn" onclick="checkout()" style="width:100%;">✅ إنهاء الطلب</button><button class="btn" onclick="clearCart()" style="width:100%;margin-top:5px;background:#f44336;color:#fff;">🗑️ تفريغ</button></div></div>
    <script>function toggleTheme(){document.body.classList.toggle('light');localStorage.setItem('theme',document.body.classList.contains('light')?'light':'dark');}if(localStorage.getItem('theme')==='light')document.body.classList.add('light');
    function renderCart(){let cart=JSON.parse(localStorage.getItem('cart')||'[]');let container=document.getElementById('cartItems');let total=0;if(cart.length===0){container.innerHTML='<p>السلة فارغة</p>';document.getElementById('totalPrice').innerText='0';return;}let html='';cart.forEach((item,index)=>{let subtotal=item.price*item.quantity;total+=subtotal;html+=`<div class="cart-item"><span><strong>${item.name}</strong> × ${item.quantity}</span><span>${subtotal} ريال</span><div><button onclick="changeQty(${index},-1)">-</button><button onclick="changeQty(${index},1)">+</button><button onclick="removeItem(${index})" style="background:#f44336;color:#fff;border:none;border-radius:3px;padding:2px 8px;">✕</button></div></div>`;});container.innerHTML=html;document.getElementById('totalPrice').innerText=total;}
    function changeQty(index,delta){let cart=JSON.parse(localStorage.getItem('cart')||'[]');if(!cart[index])return;let newQty=cart[index].quantity+delta;if(newQty<1)newQty=1;cart[index].quantity=newQty;localStorage.setItem('cart',JSON.stringify(cart));renderCart();}
    function removeItem(index){let cart=JSON.parse(localStorage.getItem('cart')||'[]');cart.splice(index,1);localStorage.setItem('cart',JSON.stringify(cart));renderCart();}
    function clearCart(){if(confirm('تفريغ السلة؟')){localStorage.removeItem('cart');renderCart();}}
    function checkout(){let cart=JSON.parse(localStorage.getItem('cart')||'[]');if(cart.length===0){alert('السلة فارغة');return;}let total=cart.reduce((s,i)=>s+i.price*i.quantity,0);fetch('/api/check-anomaly',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cart,total})}).then(r=>r.json()).then(anomaly=>{if(anomaly.is_anomaly&&!confirm(`⚠️ شذوذ: ${anomaly.reason}\nالمتابعة؟`))return;fetch('/api/create_invoice',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cart,customer_name:'عميل',payment_method:'cash'})}).then(r=>r.json()).then(data=>{if(data.success){alert(`✅ فاتورة ${data.invoice_number}`);localStorage.removeItem('cart');renderCart();}else{alert('❌ '+data.message);}});});}
    renderCart();</script></body></html>
    """)

@app.route('/chat')
def chat_page():
    return render_template_string("""
    <!DOCTYPE html><html dir="rtl"><head><meta charset="UTF-8"><title>المساعد الذكي</title>
    <style>:root{--bg:#0a0a0a;--text:#FFD700;--card-bg:rgba(17,17,17,0.9);--border:#FFD700;--btn-bg:#FFD700;--btn-text:#000}body{background:var(--bg);color:var(--text);font-family:Arial;padding:20px;min-height:100vh;display:flex;justify-content:center;align-items:center}.container{max-width:700px;width:100%;background:var(--card-bg);border:1px solid var(--border);border-radius:20px;padding:20px;height:80vh;display:flex;flex-direction:column}.header{text-align:center;padding-bottom:15px;border-bottom:1px solid var(--border)}.messages{flex:1;overflow-y:auto;padding:15px 0}.message{padding:10px 15px;border-radius:10px;margin:8px 0;max-width:85%}.user{background:#1a1a2e;border:1px solid var(--border);align-self:flex-end;margin-left:auto}.bot{background:#2a2a3e;border:1px solid #4CAF50;align-self:flex-start}.input-area{display:flex;gap:10px;padding-top:15px;border-top:1px solid var(--border)}.input-area input{flex:1;padding:10px;background:#000;color:var(--text);border:1px solid var(--border);border-radius:8px}.btn{background:var(--btn-bg);color:var(--btn-text);padding:10px 20px;border:none;border-radius:8px;cursor:pointer}.suggestion{display:inline-block;background:#1a1a2e;border:1px solid var(--border);padding:5px 12px;border-radius:15px;cursor:pointer;margin:3px;font-size:12px}.suggestion:hover{background:var(--border);color:#000}.theme-toggle{position:fixed;top:20px;left:20px;background:var(--btn-bg);color:var(--btn-text);border:none;border-radius:50%;width:50px;height:50px;font-size:20px;cursor:pointer;z-index:1000}</style>
    </head><body><button class="theme-toggle" onclick="toggleTheme()">🌓</button>
    <div class="container"><div class="header"><h2>🤖 المساعد الذكي</h2></div>
    <div id="suggestions" style="display:flex;flex-wrap:wrap;gap:5px;margin-bottom:10px;"></div>
    <div class="messages" id="messages"></div>
    <div class="input-area"><input type="text" id="chatInput" placeholder="اكتب سؤالك..." onkeypress="if(event.key==='Enter')sendMessage()"><button class="btn" onclick="sendMessage()">إرسال</button></div></div>
    <script>function toggleTheme(){document.body.classList.toggle('light');localStorage.setItem('theme',document.body.classList.contains('light')?'light':'dark');}if(localStorage.getItem('theme')==='light')document.body.classList.add('light');
    const suggestions=['ما هو الباراسيتامول؟','أدوية الحساسية','سعر الأموكسيسيلين','تفاعلات الأدوية'];
    document.getElementById('suggestions').innerHTML=suggestions.map(s=>`<span class="suggestion" onclick="sendQuick('${s}')">${s}</span>`).join('');
    function sendQuick(text){document.getElementById('chatInput').value=text;sendMessage();}
    function sendMessage(){const input=document.getElementById('chatInput');const text=input.value.trim();if(!text)return;addMessage(text,'user');input.value='';fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:text})}).then(r=>r.json()).then(data=>{if(data.success){addMessage(data.reply,'bot');}else{addMessage('عذراً، حدث خطأ','bot');}}).catch(err=>addMessage('❌ خطأ في الاتصال','bot'));}
    function addMessage(text,sender){const container=document.getElementById('messages');const div=document.createElement('div');div.className=`message ${sender}`;div.innerHTML=text.replace(/\n/g,'<br>');container.appendChild(div);container.scrollTop=container.scrollHeight;}
    </script></body></html>
    """)

@app.route('/voice-assistant')
def voice_assistant():
    return render_template_string("""
    <!DOCTYPE html><html dir="rtl"><head><meta charset="UTF-8"><title>المساعد الصوتي</title>
    <style>:root{--bg:#0a0a0a;--text:#FFD700;--card-bg:rgba(17,17,17,0.9);--border:#FFD700}body{background:var(--bg);color:var(--text);font-family:Arial;padding:20px;min-height:100vh;display:flex;justify-content:center;align-items:center}.container{max-width:600px;width:100%;background:var(--card-bg);border:1px solid var(--border);border-radius:20px;padding:30px;text-align:center}.mic-btn{width:120px;height:120px;border-radius:50%;border:3px solid var(--border);background:radial-gradient(circle,#1a1a2e,#0a0a0a);color:var(--text);font-size:50px;cursor:pointer;margin:20px auto;display:flex;align-items:center;justify-content:center}.mic-btn.listening{animation:pulseMic 1s infinite;border-color:#ff0000}@keyframes pulseMic{0%,100%{transform:scale(1)}50%{transform:scale(1.05)}}.transcript{background:rgba(0,0,0,0.5);padding:20px;border-radius:10px;margin:20px 0;min-height:80px;border:1px solid var(--border)}.response{background:rgba(255,215,0,0.1);padding:20px;border-radius:10px;margin:20px 0;min-height:60px;border:1px solid var(--border);color:#4CAF50}.commands{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:20px 0}.command-btn{background:var(--card-bg);border:1px solid var(--border);color:var(--text);padding:10px;border-radius:8px;cursor:pointer}.command-btn:hover{background:var(--border);color:#000}.speak-btn{background:#4CAF50;color:#fff;border:none;padding:10px 20px;border-radius:8px;cursor:pointer;margin:5px}.status{font-size:0.9em;opacity:0.7;margin-top:10px}</style>
    </head><body><div class="container"><h2>🎤 المساعد الصوتي</h2><div class="mic-btn" id="micBtn" onclick="toggleListening()">🎙️</div>
    <div class="transcript" id="transcript">اضغط على الميكروفون</div><div class="response" id="response">ستظهر الردود هنا</div>
    <div class="commands"><button class="command-btn" onclick="sendCommand('عرض المنتجات')">📦 المنتجات</button><button class="command-btn" onclick="sendCommand('المبيعات اليوم')">📊 المبيعات</button><button class="command-btn" onclick="sendCommand('أفضل دواء')">🏆 أفضل دواء</button><button class="command-btn" onclick="sendCommand('المخزون المنخفض')">⚠️ المخزون</button></div>
    <div><button class="speak-btn" onclick="speakText(document.getElementById('response').innerText)">🔊 قراءة</button><button class="speak-btn" onclick="stopSpeaking()">⏹️ إيقاف</button></div>
    <div class="status" id="status">⏸️ غير نشط</div></div>
    <script>let recognition=null;let isListening=false;let synth=window.speechSynthesis;if('webkitSpeechRecognition' in window||'SpeechRecognition' in window){const SpeechRecognition=window.SpeechRecognition||window.webkitSpeechRecognition;recognition=new SpeechRecognition();recognition.lang='ar-SA';recognition.continuous=false;recognition.interimResults=true;recognition.onresult=function(event){let transcript='';for(let i=event.resultIndex;i<event.results.length;i++){transcript+=event.results[i][0].transcript;}document.getElementById('transcript').innerHTML='🗣️ '+transcript;if(event.results[event.results.length-1].isFinal){sendCommand(transcript);}};recognition.onend=function(){isListening=false;document.getElementById('micBtn').classList.remove('listening');document.getElementById('micBtn').innerHTML='🎙️';document.getElementById('status').innerHTML='⏸️ غير نشط';};}else{document.getElementById('transcript').innerHTML='❌ المتصفح لا يدعم التعرف الصوتي';}
    function toggleListening(){if(!recognition){alert('غير مدعوم');return;}if(isListening){recognition.stop();isListening=false;document.getElementById('micBtn').classList.remove('listening');document.getElementById('micBtn').innerHTML='🎙️';document.getElementById('status').innerHTML='⏸️ غير نشط';}else{recognition.start();isListening=true;document.getElementById('micBtn').classList.add('listening');document.getElementById('micBtn').innerHTML='🔴';document.getElementById('status').innerHTML='🔴 يستمع...';}}
    function sendCommand(text){document.getElementById('transcript').innerHTML='🗣️ '+text;document.getElementById('status').innerHTML='⏳ جاري المعالجة...';fetch('/api/voice-command',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({command:text})}).then(r=>r.json()).then(data=>{if(data.success){document.getElementById('response').innerHTML='✅ '+data.response;speakText(data.response);}else{document.getElementById('response').innerHTML='❌ '+data.message;}document.getElementById('status').innerHTML='✅ تم';});}
    function speakText(text){if(!synth)return;const utterance=new SpeechSynthesisUtterance(text);utterance.lang='ar-SA';synth.speak(utterance);}
    function stopSpeaking(){if(synth)synth.cancel();}
    </script></body></html>
    """)

@app.route('/api/voice-command', methods=['POST'])
@login_required
def voice_command():
    data = request.json
    command = data.get('command', '').strip().lower()
    if not command:
        return jsonify({'success': False, 'message': 'الأمر فارغ'})
    responses = {'عرض المنتجات': 'جاري عرض جميع المنتجات', 'المبيعات اليوم': 'جاري عرض مبيعات اليوم', 'أفضل دواء': 'جاري عرض أفضل دواء', 'المخزون المنخفض': 'جاري عرض المنتجات منخفضة المخزون'}
    for key, response in responses.items():
        if key in command:
            return jsonify({'success': True, 'response': response})
    return jsonify({'success': True, 'response': f'أمر "{command}" قيد التطوير'})

# =============================== تشغيل التطبيق ===============================
if __name__ == '__main__':
    print("="*70)
    print("🚀 وكالة البشائر للأدوية والمستلزمات الطبية")
    print("📁 قاعدة البيانات: " + ("PostgreSQL" if DATABASE_URL else "SQLite local"))
    print("🧠 الميزات: التسعير الديناميكي، كشف الشذوذ، المساعد الذكي، تحليل المشاعر")
    print("🔐 admin/admin123 | pharmacist/pharma123 | cashier/cashier123")
    print("="*70)
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)
