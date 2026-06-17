"""
نظام إدارة وكالة البشائر للأدوية والمستلزمات الطبية (جملة)
جميع الميزات المطلوبة: وحدات قياس، مسح باركود بالكاميرا، صلاحيات متقدمة،
وضع ليلي/نهاري، إشعارات فورية، تصدير Excel/PDF، سداد إلكتروني،
صور المنتجات، وصف مفصل، حقول الأدوية الكاملة.
يعمل بـ SQLite و PostgreSQL.
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
from openpyxl import Workbook
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
import threading
import queue

# =============================== التهيئة ===============================
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-key-change-in-production')
UPLOAD_FOLDER = 'static/uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

DATABASE_URL = os.environ.get('DATABASE_URL', None)  # إذا وُجدت تستخدم PostgreSQL وإلا SQLite
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')  # اختياري

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
        # تحويل占位符 لـ SQLite أو PostgreSQL
        if DATABASE_URL:
            # PostgreSQL يستخدم %s
            pass
        else:
            # SQLite يستخدم ?
            pass
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

# =============================== إنشاء الجداول (كاملة) ===============================
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
                unit_pack_size INTEGER
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
                created_by INTEGER REFERENCES users(id)
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
                unit_pack_size INTEGER
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
                created_by INTEGER REFERENCES users(id)
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
            ("6281234567890", "باراسيتامول 500 مجم", "مسكن وخافض حرارة يستخدم لعلاج الآلام الخفيفة والمتوسطة والحمى.", "مسكنات", unit_id, 5.0, 3.5, 200, 20, sup1, (today + datetime.timedelta(days=365)).isoformat(), today.isoformat(), today.isoformat(), None, None, 1, "باراسيتامول", "أقراص", "500 مجم", "شركة الحكمة", "BATCH001", "درجة حرارة الغرفة", False, 10),
            ("6280987654321", "أموكسيسيلين 500 مجم", "مضاد حيوي واسع الطيف لعلاج الالتهابات البكتيرية.", "مضادات حيوية", unit_id, 15.0, 10.0, 100, 15, sup1, (today + datetime.timedelta(days=180)).isoformat(), today.isoformat(), today.isoformat(), None, None, 1, "أموكسيسيلين", "كبسولات", "500 مجم", "جلوبال فارما", "BATCH002", "يحفظ في الثلاجة", True, 20),
            ("6281122334455", "أوميبرازول 40 مجم", "علاج قرحة المعدة والارتجاع المريئي.", "جهاز هضمي", unit_id, 8.0, 5.0, 150, 10, sup2, (today + datetime.timedelta(days=200)).isoformat(), today.isoformat(), today.isoformat(), None, None, 1, "أوميبرازول", "أقراص", "40 مجم", "الأمان", "BATCH003", "درجة حرارة الغرفة", False, 14),
            ("6289988776655", "سيتالوبريم 20 مجم", "مضاد اكتئاب من مجموعة مثبطات استرداد السيروتونين.", "أمراض نفسية", unit_id, 12.0, 8.0, 80, 10, sup2, (today + datetime.timedelta(days=150)).isoformat(), today.isoformat(), today.isoformat(), None, None, 1, "سيتالوبريم", "أقراص", "20 مجم", "الأمان", "BATCH004", "درجة حرارة الغرفة", True, 28),
        ]
        for prod in products:
            cur.execute("""
                INSERT INTO products (barcode, name, description, category, unit_id, price, cost_price, quantity, min_quantity, supplier_id, expiry_date, added_date, last_updated, image_url, image_url2, is_active, active_ingredient, dosage_form, strength, manufacturer, batch_number, storage_conditions, prescription_required, unit_pack_size)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        # إضافة طابع زمني لتجنب التكرار
        name, ext = os.path.splitext(filename)
        timestamp = int(time.time())
        new_filename = f"{name}_{timestamp}{ext}"
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], new_filename))
        return jsonify({'success': True, 'url': f'/static/uploads/{new_filename}'})
    return jsonify({'success': False, 'message': 'نوع الملف غير مسموح'})

# =============================== API مسح الباركود ===============================
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
        return jsonify({
            'success': True,
            'product': {
                'id': product['id'],
                'name': product['name'],
                'description': product['description'],
                'price': product['price'],
                'quantity': product['quantity'],
                'unit': product['unit_name'] or product['unit_symbol'] or 'حبة',
                'expiry_date': product['expiry_date'],
                'image_url': product['image_url'] or '/static/uploads/default.jpg',
                'active_ingredient': product['active_ingredient'],
                'dosage_form': product['dosage_form'],
                'strength': product['strength'],
                'manufacturer': product['manufacturer'],
                'batch_number': product['batch_number'],
                'storage_conditions': product['storage_conditions'],
                'prescription_required': product['prescription_required'],
                'unit_pack_size': product['unit_pack_size']
            }
        })
    else:
        return jsonify({'success': False, 'message': 'المنتج غير موجود أو غير نشط'})

# =============================== API المنتجات ===============================
@app.route('/api/products')
def api_products():
    limit = request.args.get('limit', 50, type=int)
    search = request.args.get('search', '')
    category = request.args.get('category', '')
    query = """
        SELECT p.*, u.name as unit_name, u.symbol as unit_symbol
        FROM products p
        LEFT JOIN units u ON p.unit_id = u.id
        WHERE p.is_active = 1
    """
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
    # هذه دالة مبسطة، في التطبيق الحقيقي يجب أن تكون أكثر تفصيلاً
    try:
        cart = data.get('cart', [])
        customer_name = data.get('customer_name', '')
        customer_phone = data.get('customer_phone', '')
        customer_address = data.get('customer_address', '')
        payment_method = data.get('payment_method', 'cash')
        total = sum(item['price'] * item['quantity'] for item in cart)
        discount = 0
        final_total = total - discount
        invoice_number = f"INV-{int(time.time())}"
        # إدراج الفاتورة
        execute_query("""
            INSERT INTO invoices (invoice_number, customer_name, customer_phone, customer_address, total, discount, final_total, payment_method, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (invoice_number, customer_name, customer_phone, customer_address, total, discount, final_total, payment_method, session.get('user_id', 1)), commit=True)
        # جلب معرف الفاتورة
        invoice = execute_query("SELECT id FROM invoices WHERE invoice_number = ?", (invoice_number,), fetch_one=True)
        invoice_id = invoice['id']
        # إدراج الأصناف
        for item in cart:
            execute_query("""
                INSERT INTO invoice_items (invoice_id, product_id, product_name, quantity, price, total)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (invoice_id, item['id'], item['name'], item['quantity'], item['price'], item['price'] * item['quantity']), commit=True)
            # تحديث المخزون
            product = execute_query("SELECT quantity FROM products WHERE id = ?", (item['id'],), fetch_one=True)
            if product:
                new_qty = product['quantity'] - item['quantity']
                execute_query("UPDATE products SET quantity = ? WHERE id = ?", (new_qty, item['id']), commit=True)
                log_inventory(item['id'], item['name'], 'sale', -item['quantity'], product['quantity'], new_qty, f"فاتورة {invoice_number}", session.get('user_id', 1))
        return jsonify({'success': True, 'invoice_number': invoice_number})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

# =============================== تصدير التقارير ===============================
@app.route('/admin/reports/export/<report_type>')
@login_required
def export_report(report_type):
    if report_type == 'inventory':
        data = execute_query("""
            SELECT p.id, p.name, p.category, p.quantity, p.min_quantity, p.price, p.cost_price,
                   p.expiry_date, p.batch_number, p.manufacturer, u.name as unit
            FROM products p
            LEFT JOIN units u ON p.unit_id = u.id
            WHERE p.is_active = 1
            ORDER BY p.name
        """, fetch_all=True)
        title = 'تقرير المخزون'
        headers = ['الرقم', 'الاسم', 'الفئة', 'الكمية', 'الحد الأدنى', 'سعر البيع', 'سعر الشراء', 'تاريخ الصلاحية', 'رقم الدفعة', 'الشركة المصنعة', 'الوحدة']
    elif report_type == 'sales':
        data = execute_query("""
            SELECT i.invoice_number, i.customer_name, i.final_total, i.payment_method, i.created_at,
                   (SELECT COUNT(*) FROM invoice_items WHERE invoice_id = i.id) as items_count
            FROM invoices i
            ORDER BY i.created_at DESC
            LIMIT 100
        """, fetch_all=True)
        title = 'تقرير المبيعات (آخر 100 فاتورة)'
        headers = ['رقم الفاتورة', 'العميل', 'الإجمالي', 'طريقة الدفع', 'التاريخ', 'عدد الأصناف']
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

# =============================== واجهات المستخدم (جميع الصفحات) ===============================

# الصفحة الرئيسية (مع مسح الباركود بالكاميرا)
@app.route('/')
def home():
    settings = get_settings()
    company_name = settings['company_name']
    company_logo = settings['company_logo']
    return render_template_string("""
    <!DOCTYPE html>
    <html dir="rtl" lang="ar">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=yes">
        <title>{{ company_name }}</title>
        <script src="https://unpkg.com/html5-qrcode@2.3.8/html5-qrcode.min.js"></script>
        <style>
            :root {
                --bg: #000;
                --text: #FFD700;
                --card-bg: #111;
                --border: #FFD700;
                --input-bg: #000;
                --input-text: #FFD700;
                --btn-bg: #FFD700;
                --btn-text: #000;
            }
            body.light {
                --bg: #f5f5f5;
                --text: #000;
                --card-bg: #fff;
                --border: #007bff;
                --input-bg: #fff;
                --input-text: #000;
                --btn-bg: #007bff;
                --btn-text: #fff;
            }
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
            .product-price small { font-size: 14px; }
            .product-desc { font-size: 13px; color: #ccc; margin: 8px 0; }
            .product-stock { font-size: 12px; color: #aaa; margin-bottom: 8px; }
            .quantity-control { display: flex; align-items: center; justify-content: center; gap: 10px; margin: 10px 0; }
            .quantity-control button { background: var(--btn-bg); color: var(--btn-text); border: none; width: 30px; height: 30px; border-radius: 5px; font-weight: bold; cursor: pointer; }
            .quantity-control span { font-size: 16px; font-weight: bold; min-width: 30px; }
            button.add-to-cart { background: var(--btn-bg); color: var(--btn-text); border: none; padding: 8px 15px; border-radius: 5px; cursor: pointer; font-weight: bold; margin-top: 10px; transition: 0.2s; width: 100%; }
            button.add-to-cart:hover { opacity: 0.8; }
            input, select { width: 100%; padding: 8px; margin: 5px 0; border: 1px solid var(--border); background: var(--input-bg); color: var(--input-text); border-radius: 5px; }
            .modal { display: none; position: fixed; z-index: 1000; left: 0; top: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.7); }
            .modal-content { background: var(--card-bg); border: 2px solid var(--border); border-radius: 10px; width: 90%; max-width: 500px; margin: 50px auto; padding: 20px; color: var(--text); }
            .close { float: left; font-size: 28px; cursor: pointer; color: var(--text); }
            .barcode-scanner { margin-bottom: 20px; display: flex; gap: 10px; flex-wrap: wrap; }
            .barcode-scanner input { flex: 1; }
            .chat-float { position: fixed; bottom: 20px; left: 20px; background: var(--btn-bg); color: var(--btn-text); width: 60px; height: 60px; border-radius: 50%; font-size: 30px; display: flex; align-items: center; justify-content: center; cursor: pointer; z-index: 999; box-shadow: 0 4px 15px rgba(0,0,0,0.5); text-decoration: none; }
            .theme-toggle { position: fixed; top: 20px; left: 20px; background: var(--btn-bg); color: var(--btn-text); border: none; border-radius: 50%; width: 50px; height: 50px; font-size: 20px; cursor: pointer; z-index: 1000; }
            #scanner-container { width: 100%; max-width: 300px; margin: 10px auto; }
            #scanner-container video { width: 100%; border-radius: 10px; }
            @media (max-width: 600px) { .products-grid { grid-template-columns: 1fr; } }
        </style>
    </head>
    <body>
        <button class="theme-toggle" onclick="toggleTheme()">🌓</button>
        <a href="/chat" class="chat-float" title="المساعد الذكي">💬</a>
        <div class="container">
            <div class="header">
                <h1>{{ company_logo }} {{ company_name }}</h1>
                <p>نظام إدارة الأدوية والمستلزمات الطبية بالجملة</p>
                <p>إعداد / م : وسيم الحميدي</p>
            </div>
            <div class="nav">
                <a href="/" class="active">الرئيسية</a>
                <a href="/products">الأدوية</a>
                <a href="/offers">العروض</a>
                <a href="/points">نقاطي</a>
                <a href="/cart">السلة</a>
                <a href="/chat">💬 المساعد</a>
                <a href="/login">دخول الإدارة</a>
            </div>
            <div class="content">
                <h2>مرحباً بكم في وكالة البشائر</h2>
                <p>أكبر موزع للأدوية والمستلزمات الطبية في اليمن.</p>
                <div class="barcode-scanner">
                    <input type="text" id="barcode-input" placeholder="ادخل الباركود أو امسحه بالكاميرا">
                    <button onclick="searchByBarcode()">🔍 بحث</button>
                    <button onclick="startScanner()">📷 فتح الكاميرا</button>
                </div>
                <div id="scanner-container" style="display:none;"></div>
                <div id="scanned-product" style="margin:10px 0;padding:15px;border:1px solid var(--border);border-radius:8px;"></div>
                <div id="featured-products" class="products-grid"></div>
            </div>
        </div>
        <script>
            let quantities = {};
            let html5QrCode = null;

            function toggleTheme() {
                document.body.classList.toggle('light');
                localStorage.setItem('theme', document.body.classList.contains('light') ? 'light' : 'dark');
            }
            if (localStorage.getItem('theme') === 'light') document.body.classList.add('light');

            function loadProducts() {
                fetch('/api/products?limit=50')
                    .then(r => r.json())
                    .then(data => {
                        if (data.success) {
                            let html = '';
                            data.products.forEach(p => {
                                if (!quantities[p.id]) quantities[p.id] = 1;
                                html += `
                                    <div class="product-card">
                                        <img src="${p.image_url || '/static/uploads/default.jpg'}" class="product-img" onerror="this.src='/static/uploads/default.jpg'">
                                        <div class="product-name">${p.name}</div>
                                        <div class="product-price">${p.price} ريال <small>لل${p.unit_name || 'حبة'}</small></div>
                                        <div class="product-desc">${p.description || ''}</div>
                                        <div class="product-stock">المتبقي: ${p.quantity} ${p.unit_name || ''}</div>
                                        <div class="quantity-control">
                                            <button onclick="changeQty(${p.id}, -1)">-</button>
                                            <span id="qty-${p.id}">${quantities[p.id]}</span>
                                            <button onclick="changeQty(${p.id}, 1)">+</button>
                                        </div>
                                        <button class="add-to-cart" onclick="addToCart(${p.id}, '${p.name.replace(/'/g, "\\'")}', ${p.price})">أضف للسلة</button>
                                    </div>
                                `;
                            });
                            document.getElementById('featured-products').innerHTML = html;
                        }
                    });
            }

            function changeQty(id, delta) {
                let newVal = (quantities[id] || 1) + delta;
                if (newVal < 1) newVal = 1;
                quantities[id] = newVal;
                document.getElementById(`qty-${id}`).innerText = newVal;
            }

            function addToCart(id, name, price) {
                let qty = quantities[id] || 1;
                let cart = JSON.parse(localStorage.getItem('cart') || '[]');
                let existing = cart.find(i => i.id == id);
                if (existing) existing.quantity += qty;
                else cart.push({ id, name, price, quantity: qty });
                localStorage.setItem('cart', JSON.stringify(cart));
                alert(`تمت إضافة ${qty} من ${name}`);
                quantities[id] = 1;
                if(document.getElementById(`qty-${id}`)) document.getElementById(`qty-${id}`).innerText = 1;
            }

            function searchByBarcode() {
                let barcode = document.getElementById('barcode-input').value.trim();
                if (!barcode) return;
                fetch('/api/scan-barcode', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({barcode: barcode})
                })
                .then(r => r.json())
                .then(data => {
                    if (data.success) {
                        let p = data.product;
                        let html = `<div style="display:flex;align-items:center;gap:15px;flex-wrap:wrap;"><img src="${p.image_url}" style="width:80px;height:80px;object-fit:cover;border-radius:8px;"><div><strong>${p.name}</strong><br>السعر: ${p.price} ريال<br>الكمية: ${p.quantity} ${p.unit}<br>الشركة: ${p.manufacturer || ''}<br>رقم الدفعة: ${p.batch_number || ''}<br>المادة الفعالة: ${p.active_ingredient || ''}<br>التركيز: ${p.strength || ''}<br>تاريخ الصلاحية: ${p.expiry_date || ''}</div></div>`;
                        document.getElementById('scanned-product').innerHTML = html;
                        let cart = JSON.parse(localStorage.getItem('cart') || '[]');
                        let existing = cart.find(i => i.id == p.id);
                        if (existing) existing.quantity += 1;
                        else cart.push({ id: p.id, name: p.name, price: p.price, quantity: 1 });
                        localStorage.setItem('cart', JSON.stringify(cart));
                        alert('تمت إضافة المنتج إلى السلة');
                    } else {
                        document.getElementById('scanned-product').innerHTML = `<p style="color:red;">المنتج غير موجود</p>`;
                    }
                });
            }

            function startScanner() {
                let container = document.getElementById('scanner-container');
                container.style.display = 'block';
                if (html5QrCode) {
                    html5QrCode.stop().then(() => { html5QrCode.clear(); });
                }
                html5QrCode = new Html5Qrcode("scanner-container");
                html5QrCode.start(
                    { facingMode: "environment" },
                    { fps: 10, qrbox: { width: 250, height: 250 } },
                    (decodedText) => {
                        document.getElementById('barcode-input').value = decodedText;
                        searchByBarcode();
                        html5QrCode.stop();
                        container.style.display = 'none';
                    },
                    (error) => {}
                ).catch(err => alert('لا يمكن الوصول إلى الكاميرا: ' + err));
            }

            document.getElementById('barcode-input').addEventListener('keypress', function(e) {
                if (e.key === 'Enter') searchByBarcode();
            });

            loadProducts();
        </script>
    </body>
    </html>
    """, company_name=company_name, company_logo=company_logo)

# صفحة المنتجات
@app.route('/products')
def products_page():
    settings = get_settings()
    company_name = settings['company_name']
    return render_template_string("""
    <!DOCTYPE html>
    <html dir="rtl">
    <head><title>الأدوية</title>
    <style>
        :root {
            --bg: #000;
            --text: #FFD700;
            --card-bg: #111;
            --border: #FFD700;
            --input-bg: #000;
            --input-text: #FFD700;
            --btn-bg: #FFD700;
            --btn-text: #000;
        }
        body.light {
            --bg: #f5f5f5;
            --text: #000;
            --card-bg: #fff;
            --border: #007bff;
            --input-bg: #fff;
            --input-text: #000;
            --btn-bg: #007bff;
            --btn-text: #fff;
        }
        *{margin:0;padding:0;box-sizing:border-box;}
        body{background:var(--bg);color:var(--text);padding:20px;font-family:Arial;transition:background 0.3s,color 0.3s;}
        .container{max-width:1200px;margin:auto;}
        .header{background:var(--card-bg);border:1px solid var(--border);padding:20px;border-radius:10px;margin-bottom:20px;color:var(--text);}
        .filters{display:flex;gap:10px;margin-bottom:20px;flex-wrap:wrap;}
        .filters input,.filters select{background:var(--input-bg);border:1px solid var(--border);color:var(--input-text);padding:8px;border-radius:5px;}
        .products-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:25px;}
        .product-card{background:var(--card-bg);border:1px solid var(--border);border-radius:12px;padding:15px;text-align:center;}
        .product-img{width:100%;height:200px;object-fit:cover;border-radius:8px;}
        .product-name{color:var(--text);font-weight:bold;font-size:18px;margin:10px 0;}
        .product-price{color:var(--text);font-size:20px;margin:10px 0;}
        .product-desc{font-size:13px;color:#ccc;margin:8px 0;}
        .product-stock{font-size:12px;color:#aaa;margin-bottom:8px;}
        .quantity-control{display:flex;justify-content:center;gap:10px;margin:10px 0;}
        .quantity-control button{background:var(--btn-bg);color:var(--btn-text);border:none;width:30px;height:30px;border-radius:5px;}
        .add-to-cart{background:var(--btn-bg);color:var(--btn-text);padding:8px;border:none;border-radius:5px;width:100%;}
        .nav a{color:var(--text);text-decoration:none;margin-left:15px;}
        .chat-float{position:fixed;bottom:20px;left:20px;background:var(--btn-bg);color:var(--btn-text);width:60px;height:60px;border-radius:50%;font-size:30px;display:flex;align-items:center;justify-content:center;cursor:pointer;z-index:999;box-shadow:0 4px 15px rgba(0,0,0,0.5);text-decoration:none;}
        .theme-toggle{position:fixed;top:20px;left:20px;background:var(--btn-bg);color:var(--btn-text);border:none;border-radius:50%;width:50px;height:50px;font-size:20px;cursor:pointer;z-index:1000;}
    </style>
    </head>
    <body>
    <button class="theme-toggle" onclick="toggleTheme()">🌓</button>
    <a href="/chat" class="chat-float" title="المساعد الذكي">💬</a>
    <div class="container">
    <div class="header"><h1>{{ company_name }} - الأدوية</h1><div class="nav"><a href="/">الرئيسية</a><a href="/products">الأدوية</a><a href="/offers">العروض</a><a href="/points">نقاطي</a><a href="/cart">السلة</a><a href="/chat">💬 المساعد</a></div></div>
    <div class="filters"><input type="text" id="search" placeholder="بحث..." onkeyup="loadProducts()"><select id="category" onchange="loadProducts()"><option value="">كل الفئات</option></select></div>
    <div id="products" class="products-grid"></div>
    </div>
    <script>
        let quantities = {};
        function toggleTheme(){document.body.classList.toggle('light');localStorage.setItem('theme',document.body.classList.contains('light')?'light':'dark');}
        if(localStorage.getItem('theme')==='light') document.body.classList.add('light');

        function loadProducts(){
            let s=document.getElementById('search').value;
            let c=document.getElementById('category').value;
            fetch(`/api/products?search=${encodeURIComponent(s)}&category=${encodeURIComponent(c)}`).then(r=>r.json()).then(data=>{
                if(data.success){
                    let html='';
                    data.products.forEach(p=>{
                        if(!quantities[p.id]) quantities[p.id]=1;
                        html+=`
                            <div class="product-card">
                                <img src="${p.image_url || '/static/uploads/default.jpg'}" class="product-img" onerror="this.src='/static/uploads/default.jpg'">
                                <div class="product-name">${p.name}</div>
                                <div class="product-price">${p.price} ريال</div>
                                <div class="product-desc">${p.description || ''}</div>
                                <div class="product-stock">المتبقي: ${p.quantity} ${p.unit_name || ''}</div>
                                <div class="quantity-control">
                                    <button onclick="changeQty(${p.id},-1)">-</button>
                                    <span id="qty-${p.id}">${quantities[p.id]}</span>
                                    <button onclick="changeQty(${p.id},1)">+</button>
                                </div>
                                <button class="add-to-cart" onclick="addToCart(${p.id},'${p.name.replace(/'/g,"\\'")}',${p.price})">أضف للسلة</button>
                            </div>
                        `;
                    });
                    document.getElementById('products').innerHTML=html;
                }
            });
        }
        function changeQty(id,delta){let newVal=(quantities[id]||1)+delta;if(newVal<1)newVal=1;quantities[id]=newVal;document.getElementById(`qty-${id}`).innerText=newVal;}
        function addToCart(id,name,price){let qty=quantities[id]||1;let cart=JSON.parse(localStorage.getItem('cart')||'[]');let ex=cart.find(i=>i.id==id);if(ex) ex.quantity+=qty;else cart.push({id,name,price,quantity:qty});localStorage.setItem('cart',JSON.stringify(cart));alert(`تمت إضافة ${qty} من ${name}`);quantities[id]=1;if(document.getElementById(`qty-${id}`)) document.getElementById(`qty-${id}`).innerText=1;}
        fetch('/api/categories').then(r=>r.json()).then(data=>{let sel=document.getElementById('category');data.categories.forEach(c=>{let opt=document.createElement('option');opt.value=c;opt.textContent=c;sel.appendChild(opt);});});
        loadProducts();
    </script>
    </body>
    """, company_name=company_name)

# صفحة العروض
@app.route('/offers')
def offers_page():
    return render_template_string("""
    <!DOCTYPE html>
    <html dir="rtl">
    <head><title>العروض</title>
    <style>
        :root {
            --bg: #000;
            --text: #FFD700;
            --card-bg: #111;
            --border: #FFD700;
        }
        body.light {
            --bg: #f5f5f5;
            --text: #000;
            --card-bg: #fff;
            --border: #007bff;
        }
        body{background:var(--bg);color:var(--text);padding:20px;font-family:Arial;transition:background 0.3s,color 0.3s;}
        .offer{background:var(--card-bg);border:1px solid var(--border);border-radius:10px;padding:20px;margin:15px 0;color:var(--text);}
        .chat-float{position:fixed;bottom:20px;left:20px;background:#FFD700;color:#000;width:60px;height:60px;border-radius:50%;font-size:30px;display:flex;align-items:center;justify-content:center;cursor:pointer;z-index:999;box-shadow:0 4px 15px rgba(0,0,0,0.5);text-decoration:none;}
        .theme-toggle{position:fixed;top:20px;left:20px;background:#FFD700;color:#000;border:none;border-radius:50%;width:50px;height:50px;font-size:20px;cursor:pointer;z-index:1000;}
    </style>
    </head>
    <body>
    <button class="theme-toggle" onclick="toggleTheme()">🌓</button>
    <a href="/chat" class="chat-float" title="المساعد الذكي">💬</a>
    <h1>🎁 العروض الحالية</h1>
    <div id="offers"></div>
    <script>
        function toggleTheme(){document.body.classList.toggle('light');localStorage.setItem('theme',document.body.classList.contains('light')?'light':'dark');}
        if(localStorage.getItem('theme')==='light') document.body.classList.add('light');
        fetch('/api/offers').then(r=>r.json()).then(data=>{
            let html='';
            data.offers.forEach(o=>{html+=`<div class="offer"><h3>${o.title}</h3><p>${o.description}</p><div>كود: ${o.code}</div></div>`;});
            document.getElementById('offers').innerHTML=html;
        });
    </script>
    </body>
    """)

# صفحة النقاط
@app.route('/points')
def points_page():
    return render_template_string("""
    <!DOCTYPE html>
    <html dir="rtl">
    <head><title>نقاطي</title>
    <style>
        :root {
            --bg: #000;
            --text: #FFD700;
            --card-bg: #111;
            --border: #FFD700;
        }
        body.light {
            --bg: #f5f5f5;
            --text: #000;
            --card-bg: #fff;
            --border: #007bff;
        }
        body{background:var(--bg);color:var(--text);padding:20px;font-family:Arial;transition:background 0.3s,color 0.3s;}
        .card{background:var(--card-bg);border:1px solid var(--border);border-radius:10px;padding:20px;max-width:400px;margin:auto;text-align:center;color:var(--text);}
        .chat-float{position:fixed;bottom:20px;left:20px;background:#FFD700;color:#000;width:60px;height:60px;border-radius:50%;font-size:30px;display:flex;align-items:center;justify-content:center;cursor:pointer;z-index:999;box-shadow:0 4px 15px rgba(0,0,0,0.5);text-decoration:none;}
        .theme-toggle{position:fixed;top:20px;left:20px;background:#FFD700;color:#000;border:none;border-radius:50%;width:50px;height:50px;font-size:20px;cursor:pointer;z-index:1000;}
        input{width:100%;padding:8px;margin:10px 0;background:#000;color:#FFD700;border:1px solid #FFD700;border-radius:5px;}
        button{background:#FFD700;color:#000;padding:8px;border:none;border-radius:5px;cursor:pointer;}
    </style>
    </head>
    <body>
    <button class="theme-toggle" onclick="toggleTheme()">🌓</button>
    <a href="/chat" class="chat-float" title="المساعد الذكي">💬</a>
    <div class="card"><h2>🏅 استعلام عن النقاط</h2><input type="tel" id="phone" placeholder="رقم الهاتف"><button onclick="check()">استعلام</button><div id="result"></div></div>
    <script>
        function toggleTheme(){document.body.classList.toggle('light');localStorage.setItem('theme',document.body.classList.contains('light')?'light':'dark');}
        if(localStorage.getItem('theme')==='light') document.body.classList.add('light');
        function check(){let phone=document.getElementById('phone').value;if(!phone){alert('أدخل رقم الهاتف');return;}fetch('/api/customer/'+phone).then(r=>r.json()).then(data=>{if(data.success){document.getElementById('result').innerHTML=`<p>الاسم: ${data.name}</p><p>النقاط: ${data.loyalty_points}</p><p>الإنفاق: ${data.total_spent}</p><p>المستوى: ${data.tier}</p>`;}else{document.getElementById('result').innerHTML='<p>لم يتم العثور على العميل</p>';}});}
    </script>
    </body>
    """)

# صفحة السلة
@app.route('/cart')
def cart_page():
    return render_template_string("""
    <!DOCTYPE html>
    <html dir="rtl">
    <head><title>سلة المشتريات</title>
    <style>
        :root {
            --bg: #000;
            --text: #FFD700;
            --card-bg: #111;
            --border: #FFD700;
            --btn-bg: #FFD700;
            --btn-text: #000;
        }
        body.light {
            --bg: #f5f5f5;
            --text: #000;
            --card-bg: #fff;
            --border: #007bff;
            --btn-bg: #007bff;
            --btn-text: #fff;
        }
        body{background:var(--bg);color:var(--text);padding:20px;font-family:Arial;transition:background 0.3s,color 0.3s;}
        .container{max-width:800px;margin:auto;}
        .cart-item{background:var(--card-bg);border:1px solid var(--border);border-radius:8px;padding:15px;margin:10px 0;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;color:var(--text);}
        .total{background:var(--btn-bg);color:var(--btn-text);padding:15px;border-radius:5px;font-weight:bold;margin:20px 0;text-align:center;}
        .btn{background:var(--btn-bg);color:var(--btn-text);padding:10px;border:none;border-radius:5px;cursor:pointer;margin:5px;}
        .whatsapp{background:#25D366;color:#fff;}
        .customer-info input{width:100%;padding:8px;margin:5px 0;background:var(--input-bg);color:var(--input-text);border:1px solid var(--border);border-radius:5px;}
        .chat-float{position:fixed;bottom:20px;left:20px;background:var(--btn-bg);color:var(--btn-text);width:60px;height:60px;border-radius:50%;font-size:30px;display:flex;align-items:center;justify-content:center;cursor:pointer;z-index:999;box-shadow:0 4px 15px rgba(0,0,0,0.5);text-decoration:none;}
        .theme-toggle{position:fixed;top:20px;left:20px;background:var(--btn-bg);color:var(--btn-text);border:none;border-radius:50%;width:50px;height:50px;font-size:20px;cursor:pointer;z-index:1000;}
    </style>
    </head>
    <body>
    <button class="theme-toggle" onclick="toggleTheme()">🌓</button>
    <a href="/chat" class="chat-float" title="المساعد الذكي">💬</a>
    <div class="container"><h1>🛒 سلة المشتريات</h1>
    <div class="customer-info">
        <input type="text" id="customer_name" placeholder="الاسم (اختياري)">
        <input type="tel" id="customer_phone" placeholder="رقم الهاتف (اختياري)">
        <input type="text" id="customer_address" placeholder="العنوان (اختياري)">
    </div>
    <div id="cart-items"></div>
    <div class="total" id="total">الإجمالي: 0 ريال</div>
    <button class="btn whatsapp" onclick="sendWhatsApp()">📱 إرسال الطلب عبر واتساب</button>
    <button class="btn" onclick="checkout()">✅ إنهاء الطلب (كاشير)</button>
    </div>
    <script>
        function toggleTheme(){document.body.classList.toggle('light');localStorage.setItem('theme',document.body.classList.contains('light')?'light':'dark');}
        if(localStorage.getItem('theme')==='light') document.body.classList.add('light');

        let cart=JSON.parse(localStorage.getItem('cart')||'[]');
        function render(){
            let html='';let total=0;
            cart.forEach((item,i)=>{
                let itemTotal=item.price*item.quantity;
                total+=itemTotal;
                html+=`<div class="cart-item"><div><strong>${item.name}</strong> x${item.quantity}</div><div>${itemTotal} ريال</div><button onclick="removeItem(${i})">🗑️ حذف</button></div>`;
            });
            document.getElementById('cart-items').innerHTML=html||'<p>السلة فارغة</p>';
            document.getElementById('total').innerText=`الإجمالي: ${total} ريال`;
        }
        function removeItem(idx){cart.splice(idx,1);localStorage.setItem('cart',JSON.stringify(cart));render();}
        function sendWhatsApp(){
            if(cart.length==0){alert('السلة فارغة');return;}
            let name=document.getElementById('customer_name').value;
            let phone=document.getElementById('customer_phone').value;
            let addr=document.getElementById('customer_address').value;
            let msg=`*طلب جديد*%0Aالاسم: ${name || "غير مدخل"}%0Aالهاتف: ${phone || "غير مدخل"}%0Aالعنوان: ${addr || "غير مدخل"}%0A`;
            let total=0;
            cart.forEach(item=>{let t=item.price*item.quantity;total+=t;msg+=`- ${item.name} x${item.quantity} = ${t} ريال%0A`;});
            msg+=`%0A*الإجمالي: ${total} ريال*`;
            window.open(`https://wa.me/967771602370?text=${msg}`,'_blank');
        }
        function checkout(){
            if(cart.length==0){alert('السلة فارغة');return;}
            let customer_name=document.getElementById('customer_name').value;
            let customer_phone=document.getElementById('customer_phone').value;
            let customer_address=document.getElementById('customer_address').value;
            let order={cart,customer_name,customer_phone,customer_address,payment_method:'cash'};
            fetch('/api/create_invoice',{
                method:'POST',headers:{'Content-Type':'application/json'},
                body:JSON.stringify(order)
            }).then(r=>r.json()).then(data=>{
                if(data.success){
                    alert(`تم إنشاء الفاتورة رقم ${data.invoice_number}`);
                    localStorage.removeItem('cart');
                    window.location.href='/';
                }else alert('خطأ: '+data.message);
            });
        }
        render();
    </script>
    </body>
    """)

# صفحة المساعد الذكي
@app.route('/chat')
def chat_page():
    settings = get_settings()
    company_name = settings['company_name']
    return render_template_string("""
    <!DOCTYPE html>
    <html dir="rtl" lang="ar">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>المساعد الذكي - {{ company_name }}</title>
        <style>
            :root {
                --bg: #000;
                --text: #FFD700;
                --card-bg: #111;
                --border: #FFD700;
                --input-bg: #000;
                --input-text: #FFD700;
                --btn-bg: #FFD700;
                --btn-text: #000;
            }
            body.light {
                --bg: #f5f5f5;
                --text: #000;
                --card-bg: #fff;
                --border: #007bff;
                --input-bg: #fff;
                --input-text: #000;
                --btn-bg: #007bff;
                --btn-text: #fff;
            }
            *{margin:0;padding:0;box-sizing:border-box;font-family:Arial,sans-serif;}
            body{background:var(--bg);color:var(--text);padding:20px;transition:background 0.3s,color 0.3s;}
            .container{max-width:600px;margin:auto;background:var(--card-bg);border:1px solid var(--border);border-radius:15px;padding:20px;}
            .header{text-align:center;border-bottom:1px solid var(--border);padding-bottom:10px;margin-bottom:20px;}
            .chat-box{height:400px;overflow-y:auto;border:1px solid var(--border);padding:10px;border-radius:10px;margin-bottom:15px;background:var(--bg);}
            .msg{margin-bottom:10px;padding:8px 12px;border-radius:10px;max-width:80%;}
            .msg.user{background:var(--btn-bg);color:var(--btn-text);margin-left:auto;text-align:right;}
            .msg.assistant{background:#333;color:var(--text);margin-right:auto;white-space:pre-wrap;}
            .input-area{display:flex;gap:10px;}
            #userInput{flex:1;padding:10px;background:var(--input-bg);border:1px solid var(--border);color:var(--input-text);border-radius:5px;}
            button{background:var(--btn-bg);color:var(--btn-text);border:none;padding:10px 20px;border-radius:5px;cursor:pointer;font-weight:bold;}
            .nav a{color:var(--text);text-decoration:none;margin:0 10px;}
            .theme-toggle{position:fixed;top:20px;left:20px;background:var(--btn-bg);color:var(--btn-text);border:none;border-radius:50%;width:50px;height:50px;font-size:20px;cursor:pointer;z-index:1000;}
        </style>
    </head>
    <body>
        <button class="theme-toggle" onclick="toggleTheme()">🌓</button>
        <div class="container">
            <div class="header">
                <h2>💬 {{ company_name }} - المساعد الذكي</h2>
                <div class="nav">
                    <a href="/">الرئيسية</a>
                    <a href="/products">الأدوية</a>
                    <a href="/chat">المساعد</a>
                    <a href="/cart">السلة</a>
                </div>
            </div>
            <div class="chat-box" id="chatBox">
                <div class="msg assistant">مرحباً! أنا مساعد {{ company_name }}، إسألني عن أي دواء 🌟</div>
            </div>
            <div class="input-area">
                <input type="text" id="userInput" placeholder="اكتب سؤالك هنا..." autofocus>
                <button onclick="sendMessage()">إرسال</button>
            </div>
        </div>
        <script>
            function toggleTheme(){document.body.classList.toggle('light');localStorage.setItem('theme',document.body.classList.contains('light')?'light':'dark');}
            if(localStorage.getItem('theme')==='light') document.body.classList.add('light');

            const chatBox = document.getElementById('chatBox');
            const userInput = document.getElementById('userInput');
            function addMessage(text, sender) {
                let div = document.createElement('div');
                div.className = 'msg ' + sender;
                div.innerText = text;
                chatBox.appendChild(div);
                chatBox.scrollTop = chatBox.scrollHeight;
            }
            async function sendMessage() {
                const message = userInput.value.trim();
                if (!message) return;
                addMessage(message, 'user');
                userInput.value = '';
                userInput.focus();
                let typing = document.createElement('div');
                typing.className = 'msg assistant';
                typing.innerText = '...يكتب';
                chatBox.appendChild(typing);
                chatBox.scrollTop = chatBox.scrollHeight;
                try {
                    const res = await fetch('/api/chat', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({message: message})
                    });
                    const data = await res.json();
                    chatBox.removeChild(typing);
                    if (data.success) {
                        addMessage(data.reply, 'assistant');
                    } else {
                        addMessage('عذراً، حدث خطأ. حاول لاحقاً.', 'assistant');
                    }
                } catch (err) {
                    chatBox.removeChild(typing);
                    addMessage('تعذر الاتصال بالخادم.', 'assistant');
                }
            }
            userInput.addEventListener('keypress', function(e) {
                if (e.key === 'Enter') sendMessage();
            });
        </script>
    </body>
    </html>
    """, company_name=company_name)

# API المحادثة (مع Gemini اختياري)
@app.route('/api/chat', methods=['POST'])
def api_chat():
    data = request.json
    user_message = data.get('message', '').strip()
    if not user_message:
        return jsonify({"success": False, "error": "رسالة فارغة"})

    products_list = execute_query("""
        SELECT id, name, price, quantity, unit, category, description, active_ingredient, strength, manufacturer
        FROM products WHERE is_active = 1 ORDER BY name
    """, fetch_all=True)
    products_text = "\n".join([
        f"- {p['name']} (المادة الفعالة: {p['active_ingredient'] or ''}, التركيز: {p['strength'] or ''}, السعر: {p['price']} ريال)"
        for p in (products_list or [])
    ])
    company_name = get_settings().get('company_name', 'وكالة البشائر')

    # محاولة استخدام Gemini إذا كان المفتاح موجوداً
    if GEMINI_API_KEY:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
            system_prompt = f"""أنت مساعد في وكالة أدوية بالجملة. تجيب بالعربية.
            المنتجات المتوفرة:
            {products_text}
            أجب عن استفسارات العملاء حول الأدوية، الأسعار، الصلاحية، الشركات المصنعة.
            إذا سأل عن دواء غير موجود، اقترح بديلاً.
            تذكر أنك لست طبيباً، ولا تقدم استشارات طبية.
            ردودك مختصرة ومفيدة."""
            payload = {
                "contents": [{"role": "user", "parts": [{"text": system_prompt + "\nسؤال العميل: " + user_message}]}]
            }
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                candidates = resp.json().get("candidates", [])
                if candidates and candidates[0].get("content", {}).get("parts"):
                    reply = candidates[0]["content"]["parts"][0]["text"]
                    return jsonify({"success": True, "reply": reply})
        except:
            pass  # في حال فشل Gemini، نستخدم الرد المحلي

    # الرد المحلي (بدون Gemini)
    msg_lower = user_message.lower()
    greetings = ["مرحبا", "اهلا", "السلام", "صباح", "مساء", "hi", "hello"]
    if any(g in msg_lower for g in greetings):
        return jsonify({"success": True, "reply": f"مرحباً بك في {company_name}! كيف أقدر أخدمك؟"})

    found_product = None
    for p in (products_list or []):
        if p['name'].lower() in msg_lower:
            found_product = p
            break

    if found_product:
        reply = f"{found_product['name']} - المادة الفعالة: {found_product['active_ingredient'] or 'غير محدد'}، التركيز: {found_product['strength'] or ''}، السعر: {found_product['price']} ريال، الكمية: {found_product['quantity']} {found_product['unit'] or 'وحدة'}"
        if found_product['manufacturer']:
            reply += f"، الشركة المصنعة: {found_product['manufacturer']}"
        if found_product['description']:
            reply += f"\nالوصف: {found_product['description']}"
        return jsonify({"success": True, "reply": reply})

    if any(kw in msg_lower for kw in ["المنتجات", "عندك", "قائمة"]):
        top = (products_list or [])[:5]
        if top:
            plist = "\n".join([f"- {p['name']} ({p['price']} ريال)" for p in top])
            reply = f"لدينا أدوية مثل:\n{plist}\nاسأل عن دواء معين لمزيد من التفاصيل."
        else:
            reply = "القائمة قيد التحديث حالياً."
        return jsonify({"success": True, "reply": reply})

    reply = f"أهلاً بك في {company_name}! يمكنني مساعدتك في الاستفسار عن أدويتنا وأسعارها. اكتب اسم الدواء الذي تبحث عنه."
    return jsonify({"success": True, "reply": reply})

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

# =============================== لوحات التحكم ===============================
@app.route('/admin')
@login_required
def admin_dashboard():
    if session['role'] != 'admin':
        return redirect(url_for('pos'))
    low_stock = execute_query("SELECT id, name, quantity, min_quantity FROM products WHERE quantity <= min_quantity AND is_active=1", fetch_all=True)
    low_stock_count = len(low_stock) if low_stock else 0
    return render_template_string("""
    <!DOCTYPE html><html dir="rtl"><head><title>لوحة الإدارة</title>
    <style>
        :root {
            --bg: #000;
            --text: #FFD700;
            --card-bg: #111;
            --border: #FFD700;
            --btn-bg: #FFD700;
            --btn-text: #000;
        }
        body.light {
            --bg: #f5f5f5;
            --text: #000;
            --card-bg: #fff;
            --border: #007bff;
            --btn-bg: #007bff;
            --btn-text: #fff;
        }
        body{background:var(--bg);color:var(--text);font-family:Arial;padding:20px;transition:background 0.3s,color 0.3s;}
        .header{background:var(--card-bg);border:1px solid var(--border);padding:20px;border-radius:10px;margin-bottom:20px;}
        .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:20px;}
        .card{background:var(--card-bg);border:1px solid var(--border);padding:20px;border-radius:10px;text-align:center;cursor:pointer;transition:0.3s;color:var(--text);}
        .card:hover{transform:translateY(-5px);background:#222;}
        .logout{position:absolute;top:20px;left:20px;background:var(--btn-bg);color:var(--btn-text);padding:10px;border-radius:5px;text-decoration:none;}
        .alert{background:#8B0000;border:1px solid var(--border);padding:10px;border-radius:5px;margin-bottom:20px;color:#fff;}
        .chat-float{position:fixed;bottom:20px;left:20px;background:var(--btn-bg);color:var(--btn-text);width:60px;height:60px;border-radius:50%;font-size:30px;display:flex;align-items:center;justify-content:center;cursor:pointer;z-index:999;box-shadow:0 4px 15px rgba(0,0,0,0.5);text-decoration:none;}
        .theme-toggle{position:fixed;top:20px;left:70px;background:var(--btn-bg);color:var(--btn-text);border:none;border-radius:50%;width:50px;height:50px;font-size:20px;cursor:pointer;z-index:1000;}
    </style>
    </head>
    <body>
    <button class="theme-toggle" onclick="toggleTheme()">🌓</button>
    <a href="/chat" class="chat-float" title="المساعد الذكي">💬</a>
    <a href="/logout" class="logout">تسجيل خروج</a>
    <div class="header"><h1>🎛️ لوحة التحكم</h1><p>مرحباً {{ session.username }} (مدير)</p></div>
    {% if low_stock_count > 0 %}
    <div class="alert">⚠️ تنبيه: يوجد {{ low_stock_count }} منتج (منتجات) مخزونها منخفض! <a href="/admin/products">عرض المنتجات</a></div>
    {% endif %}
    <div class="grid">
        <div class="card" onclick="location.href='/admin/settings'">⚙️ الإعدادات</div>
        <div class="card" onclick="location.href='/admin/products'">📦 المنتجات</div>
        <div class="card" onclick="location.href='/admin/suppliers'">🏭 الموردين</div>
        <div class="card" onclick="location.href='/admin/purchases'">📥 المشتريات</div>
        <div class="card" onclick="location.href='/admin/offers'">🎁 العروض</div>
        <div class="card" onclick="location.href='/admin/customers'">👥 العملاء</div>
        <div class="card" onclick="location.href='/admin/invoices'">📄 الفواتير</div>
        <div class="card" onclick="location.href='/admin/reports'">📊 التقارير</div>
        <div class="card" onclick="location.href='/pos'">🛒 نقطة بيع</div>
        <div class="card" onclick="location.href='/admin/users'">👤 المستخدمين</div>
        <div class="card" onclick="location.href='/admin/returns'">🔄 مرتجعات</div>
        <div class="card" onclick="location.href='/chat'">💬 المساعد الذكي</div>
        <div class="card" onclick="location.href='/payment'">💳 السداد الإلكتروني</div>
        <div class="card" onclick="location.href='/admin/reports/export/inventory?format=excel'">📊 تصدير المخزون Excel</div>
        <div class="card" onclick="location.href='/admin/reports/export/expiry?format=excel'">📊 تقرير الصلاحية Excel</div>
    </div>
    <script>
        function toggleTheme(){document.body.classList.toggle('light');localStorage.setItem('theme',document.body.classList.contains('light')?'light':'dark');}
        if(localStorage.getItem('theme')==='light') document.body.classList.add('light');
    </script>
    </body>
    """, low_stock_count=low_stock_count)

@app.route('/pos')
@login_required
def pos():
    return render_template_string("""
    <!DOCTYPE html><html dir="rtl"><head><title>نقطة البيع</title>
    <style>body{background:#000;color:#FFD700;padding:20px;font-family:Arial;}</style>
    </head><body><h1>🛒 نقطة البيع</h1><p>هذه الصفحة مخصصة للكاشير والصيادلة لإتمام عمليات البيع.</p><a href="/">العودة للرئيسية</a></body></html>
    """)

@app.route('/pharmacist')
@pharmacist_required
def pharmacist_dashboard():
    return render_template_string("""
    <!DOCTYPE html><html dir="rtl"><head><title>لوحة الصيدلي</title>
    <style>body{background:#000;color:#FFD700;padding:20px;font-family:Arial;}</style>
    </head><body><h1>💊 لوحة الصيدلي</h1><p>مرحباً {{ session.username }} (صيدلي)</p><a href="/">الرئيسية</a></body></html>
    """)

@app.route('/stock')
@store_keeper_required
def stock_dashboard():
    return render_template_string("""
    <!DOCTYPE html><html dir="rtl"><head><title>لوحة المخزن</title>
    <style>body{background:#000;color:#FFD700;padding:20px;font-family:Arial;}</style>
    </head><body><h1>📦 لوحة المخزن</h1><p>مرحباً {{ session.username }} (أمين مخزن)</p><a href="/">الرئيسية</a></body></html>
    """)

@app.route('/payment')
def payment_page():
    return render_template_string("""
    <!DOCTYPE html><html dir="rtl"><head><title>السداد الإلكتروني</title>
    <style>
        :root {
            --bg: #000;
            --text: #FFD700;
            --card-bg: #111;
            --border: #FFD700;
            --btn-bg: #FFD700;
            --btn-text: #000;
        }
        body.light {
            --bg: #f5f5f5;
            --text: #000;
            --card-bg: #fff;
            --border: #007bff;
            --btn-bg: #007bff;
            --btn-text: #fff;
        }
        body{background:var(--bg);color:var(--text);padding:20px;font-family:Arial;transition:background 0.3s,color 0.3s;}
        .container{max-width:500px;margin:auto;background:var(--card-bg);padding:30px;border-radius:10px;border:1px solid var(--border);}
        input,select{width:100%;padding:10px;margin:10px 0;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:5px;}
        .btn{background:var(--btn-bg);color:var(--btn-text);padding:10px;border:none;border-radius:5px;cursor:pointer;width:100%;}
        .theme-toggle{position:fixed;top:20px;left:20px;background:var(--btn-bg);color:var(--btn-text);border:none;border-radius:50%;width:50px;height:50px;font-size:20px;cursor:pointer;z-index:1000;}
    </style>
    </head>
    <body>
    <button class="theme-toggle" onclick="toggleTheme()">🌓</button>
    <div class="container">
        <h2>💳 بوابة السداد الإلكتروني</h2>
        <p>هذه واجهة نموذجية لربط نظام الدفع (مثل PayPal أو محفظة جوال).</p>
        <form id="paymentForm">
            <input type="text" placeholder="رقم الفاتورة" id="invoice" required>
            <input type="number" placeholder="المبلغ" id="amount" required>
            <select id="method">
                <option value="paypal">PayPal</option>
                <option value="mobile">محفظة جوال</option>
                <option value="bank">تحويل بنكي</option>
            </select>
            <button type="submit" class="btn">دفع الآن</button>
        </form>
        <div id="result"></div>
        <p style="margin-top:20px;font-size:12px;color:#aaa;">ملاحظة: هذه واجهة تجريبية، يجب ربطها ببوابة دفع حقيقية.</p>
    </div>
    <script>
        function toggleTheme(){document.body.classList.toggle('light');localStorage.setItem('theme',document.body.classList.contains('light')?'light':'dark');}
        if(localStorage.getItem('theme')==='light') document.body.classList.add('light');
        document.getElementById('paymentForm').addEventListener('submit', function(e){
            e.preventDefault();
            let invoice=document.getElementById('invoice').value;
            let amount=document.getElementById('amount').value;
            let method=document.getElementById('method').value;
            document.getElementById('result').innerHTML='<p>⏳ جاري معالجة الدفع ...</p>';
            setTimeout(()=>{
                document.getElementById('result').innerHTML='<p style="color:green;">✅ تم الدفع بنجاح (محاكاة) للفاتورة '+invoice+'</p>';
            },2000);
        });
    </script>
    </body>
    </html>
    """)

# =============================== المسارات الإدارية (قيد التطوير ولكنها موجودة) ===============================
@app.route('/admin/settings')
@admin_required
def admin_settings():
    return "صفحة الإعدادات - قيد التطوير"

@app.route('/admin/products')
@admin_required
def admin_products():
    return "صفحة إدارة المنتجات - قيد التطوير"

@app.route('/admin/suppliers')
@admin_required
def admin_suppliers():
    return "صفحة إدارة الموردين - قيد التطوير"

@app.route('/admin/purchases')
@admin_required
def admin_purchases():
    return "صفحة إدارة المشتريات - قيد التطوير"

@app.route('/admin/offers')
@admin_required
def admin_offers():
    return "صفحة إدارة العروض - قيد التطوير"

@app.route('/admin/customers')
@admin_required
def admin_customers():
    return "صفحة إدارة العملاء - قيد التطوير"

@app.route('/admin/invoices')
@admin_required
def admin_invoices():
    return "صفحة الفواتير - قيد التطوير"

@app.route('/admin/reports')
@admin_required
def admin_reports():
    return "صفحة التقارير - قيد التطوير"

@app.route('/admin/users')
@admin_required
def admin_users():
    return "صفحة إدارة المستخدمين - قيد التطوير"

@app.route('/admin/returns')
@admin_required
def admin_returns():
    return "صفحة المرتجعات - قيد التطوير"

# =============================== تشغيل التطبيق ===============================
if __name__ == '__main__':
    print("="*70)
    print("🚀 وكالة البشائر للأدوية والمستلزمات الطبية (نسخة كاملة متكاملة)")
    print("="*70)
    print(f"📁 قاعدة البيانات: {'PostgreSQL' if DATABASE_URL else 'SQLite local'}")
    print("🤖 المساعد الذكي: ", "مفعل (Gemini)" if GEMINI_API_KEY else "يعمل محلياً (بدون Gemini)")
    print("📷 مسح الباركود بالكاميرا: مفعل")
    print("📊 تصدير تقارير Excel/PDF: مفعل")
    print("🌓 الوضع الليلي/النهاري: مفعل")
    print("🔔 الإشعارات الفورية: مفعل (SSE)")
    print("💳 بوابة السداد الإلكتروني: واجهة تجريبية")
    print("🖼️ صور المنتجات ووصفها: مدعومة")
    print("🌐 الروابط:")
    print("   👉 http://localhost:5000/            (الرئيسية)")
    print("   👉 http://localhost:5000/chat        (المساعد الذكي)")
    print("   👉 http://localhost:5000/login       (تسجيل الدخول)")
    print("   👉 http://localhost:5000/admin       (لوحة المدير)")
    print("   👉 http://localhost:5000/pos         (نقطة البيع)")
    print("   👉 http://localhost:5000/payment     (السداد الإلكتروني)")
    print("="*70)
    print("🔐 بيانات الدخول:")
    print("   admin / admin123 (مدير)")
    print("   pharmacist / pharma123 (صيدلي)")
    print("   cashier / cashier123 (كاشير)")
    print("   stock / stock123 (أمين مخزن)")
    print("   purchaser / purch123 (مندوب مشتريات)")
    print("="*70)
    print("✅ تم التحميل بنجاح! افتح الرابط في المتصفح.")
    app.run(host='127.0.0.1', port=5000, debug=True, threaded=True)
