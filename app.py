"""
نظام إدارة سوبر ماركت متكامل - سوبر ماركت اولاد قايد محمد
يدعم SQLite و PostgreSQL، ألوان أسود/ذهبي/أبيض، صور منتجات، باركود، مرتجعات، مشتريات، إحصائيات.
مع مساعد ذكي (Chatbot) مدمج.
"""

from flask import (
    Flask, request, jsonify, render_template_string, session,
    redirect, url_for, make_response, send_from_directory
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
import requests   # <-- أضف هذا السطر هنا

# اختياري: للذكاء الاصطناعي عبر OpenAI
try:
    import openai
except ImportError:
    openai = None

# =============================== التهيئة ===============================
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-key-change-in-production')
UPLOAD_FOLDER = 'static/uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

DATABASE_URL = os.environ.get('DATABASE_URL', None)

# مفتاح OpenAI – يفضل تعيينه في متغيرات البيئة وليس مباشرة في الكود
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
if OPENAI_API_KEY and openai:
    openai.api_key = OPENAI_API_KEY

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

# =============================== دالة تزيين للصلاحيات ===============================
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session or session.get('role') != 'admin':
            return "غير مصرح", 403
        return f(*args, **kwargs)
    return decorated

def cashier_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session or session.get('role') not in ['admin', 'cashier']:
            return "غير مصرح", 403
        return f(*args, **kwargs)
    return decorated

def stock_keeper_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session or session.get('role') not in ['admin', 'stock_keeper']:
            return "غير مصرح", 403
        return f(*args, **kwargs)
    return decorated

# =============================== دوال مساعدة ===============================
def get_settings():
    rows = execute_query("SELECT key, value FROM settings", fetch_all=True)
    settings = {row['key']: row['value'] for row in rows} if rows else {}
    defaults = {
        'company_name': 'سوبر ماركت اولاد قايد محمد',
        'company_logo': '🛒',
        'company_address': 'اليمن - صنعاء',
        'company_phone': '967771602370',
        'company_whatsapp': '967771602370',
        'delivery_fee': '5.00',
        'points_per_riyal': '1',
        'points_redeem_rate': '100'
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

def update_customer_points(customer_id, total_spent):
    points_per_riyal = float(get_settings().get('points_per_riyal', 1))
    points_earned = int(total_spent * points_per_riyal)
    execute_query("UPDATE customers SET loyalty_points = loyalty_points + ?, total_spent = total_spent + ?, visits = visits + 1, last_visit = ? WHERE id = ?",
                  (points_earned, total_spent, datetime.date.today().isoformat(), customer_id), commit=True)
    row = execute_query("SELECT total_spent FROM customers WHERE id = ?", (customer_id,), fetch_one=True)
    if row:
        spent = row['total_spent']
        if spent >= 5000:
            tier = 'ذهبي'
        elif spent >= 2000:
            tier = 'فضي'
        else:
            tier = 'عادي'
        execute_query("UPDATE customers SET tier = ? WHERE id = ?", (tier, customer_id), commit=True)

# دالة للبحث عن منتج بالكلمات – تستخدم في المساعد المحلي
def search_products_by_name(keywords):
    rows = execute_query("""
        SELECT id, name, price, quantity, description FROM products
        WHERE is_active = 1 AND (name LIKE ? OR description LIKE ?)
        LIMIT 5
    """, (f"%{keywords}%", f"%{keywords}%"), fetch_all=True)
    return rows if rows else []

# =============================== إنشاء الجداول والبيانات الافتراضية ===============================
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
                notes TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id SERIAL PRIMARY KEY,
                barcode VARCHAR(50) UNIQUE,
                name VARCHAR(200) NOT NULL,
                description TEXT,
                category VARCHAR(50),
                price REAL NOT NULL,
                cost_price REAL,
                quantity INTEGER DEFAULT 0,
                min_quantity INTEGER DEFAULT 10,
                unit VARCHAR(20) DEFAULT 'قطعة',
                supplier_id INTEGER REFERENCES suppliers(id),
                expiry_date DATE,
                added_date DATE,
                last_updated DATE,
                image_url TEXT,
                image_url2 TEXT,
                is_active INTEGER DEFAULT 1
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
                quantity INTEGER,
                cost_price REAL,
                total REAL
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
                quantity INTEGER NOT NULL,
                price REAL NOT NULL,
                total REAL NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS inventory_logs (
                id SERIAL PRIMARY KEY,
                product_id INTEGER REFERENCES products(id),
                product_name TEXT,
                change_type TEXT,
                quantity_change INTEGER,
                old_quantity INTEGER,
                new_quantity INTEGER,
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
                quantity INTEGER,
                price REAL,
                total REAL,
                reason TEXT,
                return_date DATE,
                created_by INTEGER REFERENCES users(id)
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
                notes TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                barcode TEXT UNIQUE,
                name TEXT NOT NULL,
                description TEXT,
                category TEXT,
                price REAL NOT NULL,
                cost_price REAL,
                quantity INTEGER DEFAULT 0,
                min_quantity INTEGER DEFAULT 10,
                unit TEXT DEFAULT 'قطعة',
                supplier_id INTEGER REFERENCES suppliers(id),
                expiry_date DATE,
                added_date DATE,
                last_updated DATE,
                image_url TEXT,
                image_url2 TEXT,
                is_active INTEGER DEFAULT 1
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
                quantity INTEGER,
                cost_price REAL,
                total REAL
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
                quantity INTEGER NOT NULL,
                price REAL NOT NULL,
                total REAL NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS inventory_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER REFERENCES products(id),
                product_name TEXT,
                change_type TEXT,
                quantity_change INTEGER,
                old_quantity INTEGER,
                new_quantity INTEGER,
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
                quantity INTEGER,
                price REAL,
                total REAL,
                reason TEXT,
                return_date DATE,
                created_by INTEGER REFERENCES users(id)
            )
        """)

    # بيانات افتراضية
    cur.execute("SELECT COUNT(*) FROM users")
    if cur.fetchone()[0] == 0:
        hashed = generate_password_hash('admin123')
        cur.execute("INSERT INTO users (username, password_hash, role, full_name) VALUES (?, ?, ?, ?)",
                    ('admin', hashed, 'admin', 'مدير النظام'))
        hashed_cashier = generate_password_hash('cashier123')
        cur.execute("INSERT INTO users (username, password_hash, role, full_name) VALUES (?, ?, ?, ?)",
                    ('cashier', hashed_cashier, 'cashier', 'كاشير'))
        hashed_stock = generate_password_hash('stock123')
        cur.execute("INSERT INTO users (username, password_hash, role, full_name) VALUES (?, ?, ?, ?)",
                    ('stock', hashed_stock, 'stock_keeper', 'أمين مخزن'))

    cur.execute("SELECT COUNT(*) FROM settings")
    if cur.fetchone()[0] == 0:
        default_settings = [
            ('company_name', 'سوبر ماركت اولاد قايد محمد'),
            ('company_logo', '🛒'),
            ('company_address', 'اليمن - صنعاء'),
            ('company_phone', '967771602370'),
            ('company_whatsapp', '967771602370'),
            ('delivery_fee', '5.00'),
            ('points_per_riyal', '1'),
            ('points_redeem_rate', '100')
        ]
        for key, val in default_settings:
            cur.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (key, val))

    cur.execute("SELECT COUNT(*) FROM offers")
    if cur.fetchone()[0] == 0:
        offers = [
            ('خصم 10%', 'خصم 10% على كل الطلبات', 'DISCOUNT10', 'percentage', 10, None, None),
            ('توصيل مجاني', 'توصيل مجاني للطلبات فوق 200 ريال', 'FREESHIP', 'fixed', 0, None, None),
            ('نقاط مضاعفة', 'نقاط مضاعفة في نهاية الأسبوع', 'DOUBLE_POINTS', 'percentage', 0, None, None)
        ]
        for offer in offers:
            cur.execute("INSERT INTO offers (title, description, code, discount_type, discount_value, start_date, end_date) VALUES (?, ?, ?, ?, ?, ?, ?)", offer)

    cur.execute("SELECT COUNT(*) FROM customers")
    if cur.fetchone()[0] == 0:
        cur.execute("INSERT INTO customers (phone, name, address, loyalty_points, total_spent, visits, last_visit, tier) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    ("0500000000", "عميل تجريبي", "صنعاء", 100, 200.0, 5, datetime.date.today().isoformat(), "فضي"))

    cur.execute("SELECT COUNT(*) FROM suppliers")
    if cur.fetchone()[0] == 0:
        cur.execute("INSERT INTO suppliers (name, phone, address) VALUES (?, ?, ?)", ("مورد تجريبي", "0500000001", "صنعاء"))

    cur.execute("SELECT COUNT(*) FROM products")
    if cur.fetchone()[0] == 0:
        today = datetime.date.today()
        products = [
            ("8801234567890", "أرز بسمتي", "أرز عالي الجودة", "مواد غذائية", 25.0, 18.0, 50, 10, "كيلو", 1, (today + datetime.timedelta(days=180)).isoformat()),
            ("8809876543210", "سكر", "سكر أبيض ناعم", "مواد غذائية", 15.0, 11.0, 100, 20, "كيلو", 1, (today + datetime.timedelta(days=180)).isoformat()),
            ("8801122334455", "زيت دوار الشمس", "زيت صحي", "مواد غذائية", 35.0, 28.0, 30, 10, "لتر", 1, (today + datetime.timedelta(days=180)).isoformat()),
            ("8805566778899", "حليب طازج", "حليب كامل الدسم", "مبردات", 8.0, 6.0, 40, 15, "لتر", 1, (today + datetime.timedelta(days=14)).isoformat()),
            ("8809988776655", "شاي", "شاي أسود", "مواد غذائية", 20.0, 15.0, 60, 15, "علبة", 1, (today + datetime.timedelta(days=180)).isoformat())
        ]
        for prod in products:
            cur.execute("""
                INSERT INTO products (barcode, name, description, category, price, cost_price, quantity, min_quantity, unit, supplier_id, expiry_date, added_date, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (*prod, today.isoformat(), today.isoformat()))

    conn.commit()
    conn.close()

init_db()

# =============================== واجهات المستخدم العامة ===============================
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
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; font-family: 'Tahoma', Arial, sans-serif; }
            body { background: #000; color: #fff; padding: 20px; }
            .container { max-width: 1200px; margin: 0 auto; }
            .header { text-align: center; padding: 20px; background: #111; border-radius: 15px; margin-bottom: 30px; border: 1px solid #FFD700; color: #FFD700; }
            .header h1 { color: #FFD700; }
            .nav { display: flex; gap: 15px; justify-content: center; margin-bottom: 30px; flex-wrap: wrap; }
            .nav a { background: #111; color: #FFD700; padding: 12px 25px; text-decoration: none; border-radius: 8px; border: 1px solid #FFD700; transition: 0.3s; }
            .nav a:hover, .nav a.active { background: #FFD700; color: #000; }
            .content { background: #111; padding: 25px; border-radius: 15px; border: 1px solid #FFD700; }
            h2 { color: #FFD700; margin-bottom: 20px; border-right: 4px solid #FFD700; padding-right: 15px; }
            .products-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 25px; margin-top: 20px; }
            .product-card { background: #000; border: 1px solid #FFD700; border-radius: 12px; padding: 15px; text-align: center; transition: 0.3s; display: flex; flex-direction: column; }
            .product-card:hover { transform: translateY(-5px); box-shadow: 0 5px 15px rgba(255,215,0,0.3); }
            .product-img { width: 100%; height: 200px; object-fit: cover; border-radius: 8px; margin-bottom: 10px; background: #222; }
            .product-name { font-weight: bold; font-size: 18px; margin: 10px 0; color: #FFD700; }
            .product-price { color: #FFD700; font-size: 22px; font-weight: bold; margin: 5px 0; }
            .product-price small { font-size: 14px; }
            .product-desc { font-size: 13px; color: #ccc; margin: 8px 0; }
            .product-stock { font-size: 12px; color: #aaa; margin-bottom: 8px; }
            .quantity-control { display: flex; align-items: center; justify-content: center; gap: 10px; margin: 10px 0; }
            .quantity-control button { background: #FFD700; color: #000; border: none; width: 30px; height: 30px; border-radius: 5px; font-weight: bold; cursor: pointer; }
            .quantity-control span { font-size: 16px; font-weight: bold; min-width: 30px; }
            button.add-to-cart { background: #FFD700; color: #000; border: none; padding: 8px 15px; border-radius: 5px; cursor: pointer; font-weight: bold; margin-top: 10px; transition: 0.2s; width: 100%; }
            button.add-to-cart:hover { background: #e6c200; }
            input, select { width: 100%; padding: 8px; margin: 5px 0; border: 1px solid #FFD700; background: #000; color: #FFD700; border-radius: 5px; }
            .modal { display: none; position: fixed; z-index: 1000; left: 0; top: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.7); }
            .modal-content { background: #111; border: 2px solid #FFD700; border-radius: 10px; width: 90%; max-width: 500px; margin: 50px auto; padding: 20px; color: #FFD700; }
            .close { float: left; font-size: 28px; cursor: pointer; color: #FFD700; }
            .barcode-scanner { margin-bottom: 20px; display: flex; gap: 10px; }
            .barcode-scanner input { flex: 1; }
            .chat-float { position: fixed; bottom: 20px; left: 20px; background: #FFD700; color: #000; width: 60px; height: 60px; border-radius: 50%; font-size: 30px; display: flex; align-items: center; justify-content: center; cursor: pointer; z-index: 999; box-shadow: 0 4px 15px rgba(0,0,0,0.5); text-decoration: none; }
            @media (max-width: 600px) { .products-grid { grid-template-columns: 1fr; } }
        </style>
    </head>
    <body>
        <a href="/chat" class="chat-float" title="المساعد الذكي">💬</a>
        <div class="container">
            <div class="header">
                <h1>{{ company_logo }} {{ company_name }}</h1>
                <p>نظام نقاط العملاء وإدارة المتجر</p>
                <p>إعداد /م : وسيم الحميدي </p>
            </div>
            <div class="nav">
                <a href="/" class="active">الرئيسية</a>
                <a href="/products">المنتجات</a>
                <a href="/offers">العروض</a>
                <a href="/points">نقاطي</a>
                <a href="/cart">السلة</a>
                <a href="/chat">💬 المساعد</a>
                <a href="/login">دخول الإدارة</a>
            </div>
            <div class="content">
                <h2>مرحباً بكم في متجرنا</h2>
                <p>استمتع بتجربة تسوق مميزة مع نظام النقاط والعروض الحصرية.</p>
                <div class="barcode-scanner">
                    <input type="text" id="barcode-input" placeholder="امسح الباركود أو أدخله">
                    <button onclick="searchByBarcode()">بحث</button>
                </div>
                <div id="featured-products" class="products-grid"></div>
            </div>
        </div>
        <script>
            let quantities = {};
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
                                        <div class="product-price">${p.price} ريال <small>لل${p.unit}</small></div>
                                        <div class="product-desc">${p.description || ''}</div>
                                        <div class="product-stock">المتبقي: ${p.quantity}</div>
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
                fetch(`/api/product/by-barcode/${encodeURIComponent(barcode)}`)
                    .then(r => r.json())
                    .then(data => {
                        if (data.success) {
                            alert(`المنتج: ${data.name}\\nالسعر: ${data.price} ريال`);
                            let cart = JSON.parse(localStorage.getItem('cart') || '[]');
                            let existing = cart.find(i => i.id == data.id);
                            if (existing) existing.quantity++;
                            else cart.push({ id: data.id, name: data.name, price: data.price, quantity: 1 });
                            localStorage.setItem('cart', JSON.stringify(cart));
                            alert('تمت إضافة المنتج إلى السلة');
                        } else {
                            alert('المنتج غير موجود');
                        }
                    });
            }
            loadProducts();
        </script>
    </body>
    </html>
    """, company_name=company_name, company_logo=company_logo)

@app.route('/products')
def products_page():
    settings = get_settings()
    company_name = settings['company_name']
    return render_template_string("""
    <!DOCTYPE html>
    <html dir="rtl">
    <head><title>المنتجات</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box;}
        body{background:#000;color:#fff;padding:20px;font-family:Arial;}
        .container{max-width:1200px;margin:auto;}
        .header{background:#111;border:1px solid #FFD700;padding:20px;border-radius:10px;margin-bottom:20px;color:#FFD700;}
        .filters{display:flex;gap:10px;margin-bottom:20px;flex-wrap:wrap;}
        .filters input,.filters select{background:#000;border:1px solid #FFD700;color:#FFD700;padding:8px;border-radius:5px;}
        .products-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:25px;}
        .product-card{background:#111;border:1px solid #FFD700;border-radius:12px;padding:15px;text-align:center;}
        .product-img{width:100%;height:200px;object-fit:cover;border-radius:8px;}
        .product-name{color:#FFD700;font-weight:bold;font-size:18px;margin:10px 0;}
        .product-price{color:#FFD700;font-size:20px;margin:10px 0;}
        .product-desc{font-size:13px;color:#ccc;}
        .quantity-control{display:flex;justify-content:center;gap:10px;margin:10px 0;}
        .quantity-control button{background:#FFD700;color:#000;border:none;width:30px;height:30px;border-radius:5px;}
        .add-to-cart{background:#FFD700;color:#000;padding:8px;border:none;border-radius:5px;width:100%;}
        .nav a{color:#FFD700;text-decoration:none;margin-left:15px;}
        .chat-float { position: fixed; bottom: 20px; left: 20px; background: #FFD700; color: #000; width: 60px; height: 60px; border-radius: 50%; font-size: 30px; display: flex; align-items: center; justify-content: center; cursor: pointer; z-index: 999; box-shadow: 0 4px 15px rgba(0,0,0,0.5); text-decoration: none; }
    </style>
    </head>
    <body>
    <a href="/chat" class="chat-float" title="المساعد الذكي">💬</a>
    <div class="container">
    <div class="header"><h1>{{ company_name }} - المنتجات</h1><div class="nav"><a href="/">الرئيسية</a><a href="/products">المنتجات</a><a href="/offers">العروض</a><a href="/points">نقاطي</a><a href="/cart">السلة</a><a href="/chat">💬 المساعد</a></div></div>
    <div class="filters"><input type="text" id="search" placeholder="بحث..." onkeyup="loadProducts()"><select id="category" onchange="loadProducts()"><option value="">كل الفئات</option></select></div>
    <div id="products" class="products-grid"></div>
    </div>
    <script>
        let quantities = {};
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
        function changeQty(id,delta){
            let newVal=(quantities[id]||1)+delta;
            if(newVal<1) newVal=1;
            quantities[id]=newVal;
            document.getElementById(`qty-${id}`).innerText=newVal;
        }
        function addToCart(id,name,price){
            let qty=quantities[id]||1;
            let cart=JSON.parse(localStorage.getItem('cart')||'[]');
            let ex=cart.find(i=>i.id==id);
            if(ex) ex.quantity+=qty;
            else cart.push({id,name,price,quantity:qty});
            localStorage.setItem('cart',JSON.stringify(cart));
            alert(`تمت إضافة ${qty} من ${name}`);
            quantities[id]=1;
            if(document.getElementById(`qty-${id}`)) document.getElementById(`qty-${id}`).innerText=1;
        }
        fetch('/api/categories').then(r=>r.json()).then(data=>{
            let sel=document.getElementById('category');
            data.categories.forEach(c=>{let opt=document.createElement('option');opt.value=c;opt.textContent=c;sel.appendChild(opt);});
        });
        loadProducts();
    </script>
    </body>
    """, company_name=company_name)

@app.route('/cart')
def cart_page():
    return render_template_string("""
    <!DOCTYPE html>
    <html dir="rtl">
    <head><title>سلة المشتريات</title>
    <style>
        body{background:#000;color:#fff;padding:20px;font-family:Arial;}
        .container{max-width:800px;margin:auto;}
        .cart-item{background:#111;border:1px solid #FFD700;border-radius:8px;padding:15px;margin:10px 0;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;}
        .total{background:#FFD700;color:#000;padding:15px;border-radius:5px;font-weight:bold;margin:20px 0;text-align:center;}
        .btn{background:#FFD700;color:#000;padding:10px;border:none;border-radius:5px;cursor:pointer;margin:5px;}
        .whatsapp{background:#25D366;}
        .customer-info input{width:100%;padding:8px;margin:5px 0;background:#000;color:#FFD700;border:1px solid #FFD700;border-radius:5px;}
        .chat-float { position: fixed; bottom: 20px; left: 20px; background: #FFD700; color: #000; width: 60px; height: 60px; border-radius: 50%; font-size: 30px; display: flex; align-items: center; justify-content: center; cursor: pointer; z-index: 999; box-shadow: 0 4px 15px rgba(0,0,0,0.5); text-decoration: none; }
    </style>
    </head>
    <body>
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
    <button class="btn checkout" onclick="checkout()">✅ إنهاء الطلب (كاشير)</button>
    </div>
    <script>
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

@app.route('/offers')
def offers_page():
    return render_template_string("""
    <!DOCTYPE html>
    <html dir="rtl">
    <head><title>العروض</title>
    <style>body{background:#000;color:#fff;padding:20px;}.offer{background:#111;border:1px solid #FFD700;border-radius:10px;padding:20px;margin:15px 0;color:#FFD700;}
    .chat-float { position: fixed; bottom: 20px; left: 20px; background: #FFD700; color: #000; width: 60px; height: 60px; border-radius: 50%; font-size: 30px; display: flex; align-items: center; justify-content: center; cursor: pointer; z-index: 999; box-shadow: 0 4px 15px rgba(0,0,0,0.5); text-decoration: none; }
    </style>
    </head>
    <body><a href="/chat" class="chat-float" title="المساعد الذكي">💬</a><h1>🎁 العروض الحالية</h1><div id="offers"></div>
    <script>
        fetch('/api/offers').then(r=>r.json()).then(data=>{
            let html='';data.offers.forEach(o=>{html+=`<div class="offer"><h3>${o.title}</h3><p>${o.description}</p><div>كود: ${o.code}</div></div>`;});
            document.getElementById('offers').innerHTML=html;
        });
    </script>
    </body>
    """)

@app.route('/points')
def points_page():
    return render_template_string("""
    <!DOCTYPE html>
    <html dir="rtl">
    <head><title>نقاطي</title>
    <style>body{background:#000;color:#fff;padding:20px;}.card{background:#111;border:1px solid #FFD700;border-radius:10px;padding:20px;max-width:400px;margin:auto;text-align:center;color:#FFD700;}
    .chat-float { position: fixed; bottom: 20px; left: 20px; background: #FFD700; color: #000; width: 60px; height: 60px; border-radius: 50%; font-size: 30px; display: flex; align-items: center; justify-content: center; cursor: pointer; z-index: 999; box-shadow: 0 4px 15px rgba(0,0,0,0.5); text-decoration: none; }
    </style>
    </head>
    <body><a href="/chat" class="chat-float" title="المساعد الذكي">💬</a><div class="card"><h2>🏅 استعلام عن النقاط</h2><input type="tel" id="phone" placeholder="رقم الهاتف" style="width:100%;padding:8px;margin:10px 0;"><button onclick="check()">استعلام</button><div id="result"></div></div>
    <script>
        function check(){let phone=document.getElementById('phone').value;if(!phone){alert('أدخل رقم الهاتف');return;}fetch('/api/customer/'+phone).then(r=>r.json()).then(data=>{if(data.success){document.getElementById('result').innerHTML=`<p>الاسم: ${data.name}</p><p>النقاط: ${data.loyalty_points}</p><p>الإنفاق: ${data.total_spent}</p><p>المستوى: ${data.tier}</p>`;}else{document.getElementById('result').innerHTML='<p>لم يتم العثور على العميل</p>';}});}
    </script>
    </body>
    """)

# =============================== صفحة المساعد الذكي ===============================
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
            *{margin:0;padding:0;box-sizing:border-box;font-family:Arial,sans-serif;}
            body{background:#000;color:#FFD700;padding:20px;}
            .container{max-width:600px;margin:auto;background:#111;border:1px solid #FFD700;border-radius:15px;padding:20px;}
            .header{text-align:center;border-bottom:1px solid #FFD700;padding-bottom:10px;margin-bottom:20px;}
            .chat-box{height:400px;overflow-y:auto;border:1px solid #FFD700;padding:10px;border-radius:10px;margin-bottom:15px;background:#000;}
            .msg{margin-bottom:10px;padding:8px 12px;border-radius:10px;max-width:80%;}
            .msg.user{background:#FFD700;color:#000;margin-left:auto;text-align:right;}
            .msg.assistant{background:#333;color:#FFD700;margin-right:auto;white-space:pre-wrap;}
            .input-area{display:flex;gap:10px;}
            #userInput{flex:1;padding:10px;background:#000;border:1px solid #FFD700;color:#FFD700;border-radius:5px;}
            button{background:#FFD700;color:#000;border:none;padding:10px 20px;border-radius:5px;cursor:pointer;font-weight:bold;}
            .nav a{color:#FFD700;text-decoration:none;margin:0 10px;}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2>💬 {{ company_name }} - المساعد الذكي</h2>
                <div class="nav">
                    <a href="/">الرئيسية</a>
                    <a href="/products">المنتجات</a>
                    <a href="/chat">المساعد</a>
                    <a href="/cart">السلة</a>
                </div>
            </div>
            <div class="chat-box" id="chatBox">
                <div class="msg assistant">مرحباً! أنا مساعد {{ company_name }}، إسألني عن أي منتج 🌟</div>
            </div>
            <div class="input-area">
                <input type="text" id="userInput" placeholder="اكتب سؤالك هنا..." autofocus>
                <button onclick="sendMessage()">إرسال</button>
            </div>
        </div>
        <script>
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
# أضف هذا الاستيراد في الأعلى


@app.route('/api/chat', methods=['POST'])
def api_chat():
    data = request.json
    user_message = data.get('message', '').strip()
    if not user_message:
        return jsonify({"success": False, "error": "رسالة فارغة"})

    products_list = execute_query("""
        SELECT id, name, price, quantity, unit, category, description FROM products
        WHERE is_active = 1 ORDER BY name
    """, fetch_all=True)
    products_text = "\n".join([
        f"- {p['name']} ({p['category'] or 'عام'}) | السعر: {p['price']} ريال/{p['unit']} | الكمية: {p['quantity']} | الوصف: {p['description'] or ''}"
        for p in (products_list or [])
    ])

    company_name = get_settings().get('company_name', 'سوبر ماركت اولاد قايد محمد')

    # ============== تجربة Google Gemini أولاً (مجاني) ==============
    gemini_key = os.environ.get('GEMINI_API_KEY', '')
    if gemini_key:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={gemini_key}"
            system_prompt = f"""أنت مساعد ودود في متجر '{company_name}'. تجيب بالعربية فقط.
            لديك قائمة المنتجات:
            {products_text}
            أجب عن أي سؤال يخص المنتجات، الأسعار، الفوائد العامة، العروض.
            إذا سأل العميل عن منتج غير موجود، أخبره بلطف واقترح بدائل.
            ردودك قصيرة ومفيدة. وإذا كانت التحية رد عليها بترحيب."""
            payload = {
                "contents": [
                    {"role": "user", "parts": [{"text": system_prompt + "\nسؤال العميل: " + user_message}]}
                ]
            }
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                candidates = resp.json().get("candidates", [])
                if candidates and candidates[0].get("content", {}).get("parts"):
                    reply = candidates[0]["content"]["parts"][0]["text"]
                    return jsonify({"success": True, "reply": reply})
        except Exception as e:
            pass  # إذا فشل Gemini نكمل للمساعد المحلي

    # ============== المساعد المحلي المطوَّر (مجاني للأبد) ==============
    msg_lower = user_message.lower()

    greetings = ["مرحبا", "اهلا", "السلام", "صباح", "مساء", "hi", "hello"]
    if any(g in msg_lower for g in greetings):
        return jsonify({"success": True, "reply": f"مرحباً بك في {company_name}! كيف أقدر أخدمك؟"})

    # البحث عن منتج مذكور في النص
    found_product = None
    for p in (products_list or []):
        if p['name'].lower() in msg_lower:
            found_product = p
            break

    if found_product:
        # إذا كان السؤال عن فوائد
        if any(kw in msg_lower for kw in ["فائدة", "فوائد", "فوايد", "ايش", "ماهو", "ما هو"]):
            desc = found_product['description'] or "منتج عالي الجودة"
            reply = f"بخصوص {found_product['name']}:\n{desc}\nالسعر: {found_product['price']} ريال/{found_product['unit']}\nالكمية المتوفرة: {found_product['quantity']}"
            return jsonify({"success": True, "reply": reply})
        # سعر
        if any(kw in msg_lower for kw in ["سعر", "كم", "بكم"]):
            reply = f"سعر {found_product['name']} هو {found_product['price']} ريال/{found_product['unit']}. الكمية: {found_product['quantity']}"
            return jsonify({"success": True, "reply": reply})
        # عرض عادي
        reply = f"{found_product['name']} متوفر بسعر {found_product['price']} ريال/{found_product['unit']} (الكمية: {found_product['quantity']})"
        return jsonify({"success": True, "reply": reply})

    # أسئلة عامة عن المنتجات
    if any(kw in msg_lower for kw in ["المنتجات", "عندك", "قائمة", "ايش فيه", "ايش في"]):
        top = (products_list or [])[:5]
        if top:
            plist = "\n".join([f"- {p['name']} ({p['price']} ريال)" for p in top])
            reply = f"لدينا منتجات متنوعة مثل:\n{plist}\nاسأل عن أي منتج لمزيد من التفاصيل."
        else:
            reply = "القائمة قيد التحديث حالياً."
        return jsonify({"success": True, "reply": reply})

    # رد افتراضي مفيد
    reply = f"أهلاً بك في {company_name}! يمكنني مساعدتك في:\n- الاستفسار عن منتج معين (مثلاً: سكر، حليب)\n- معرفة الأسعار والكميات\n- أسئلة عامة عن المنتجات\nاكتب اسم المنتج أو استفسارك."
    return jsonify({"success": True, "reply": reply})
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
            if user['role'] == 'admin':
                return redirect(url_for('admin_dashboard'))
            elif user['role'] == 'cashier':
                return redirect(url_for('pos'))
            else:
                return redirect(url_for('stock_dashboard'))
        else:
            return render_template_string("<h2 style='color:red;text-align:center;'>بيانات دخول خاطئة</h2><a href='/login'>حاول مرة أخرى</a>")
    return render_template_string("""
    <!DOCTYPE html>
    <html dir="rtl">
    <head><title>تسجيل الدخول</title>
    <style>body{background:#000;color:#FFD700;font-family:Arial;padding:50px;}.login{max-width:400px;margin:auto;background:#111;padding:30px;border-radius:10px;border:1px solid #FFD700;}</style>
    </head>
    <body><div class="login"><h2>تسجيل الدخول</h2>
    <form method="post"><input type="text" name="username" placeholder="اسم المستخدم" required style="width:100%;padding:10px;margin:10px 0;background:#000;color:#FFD700;border:1px solid #FFD700;"><input type="password" name="password" placeholder="كلمة المرور" required style="width:100%;padding:10px;margin:10px 0;background:#000;color:#FFD700;border:1px solid #FFD700;"><button type="submit" style="background:#FFD700;color:#000;padding:10px;width:100%;border:none;">دخول</button></form></div></body>
    """)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

# =============================== لوحة الإدارة ===============================
@app.route('/admin')
@login_required
def admin_dashboard():
    if session['role'] != 'admin':
        return redirect(url_for('pos'))
    low_stock = execute_query("SELECT id, name, quantity, min_quantity FROM products WHERE quantity <= min_quantity AND is_active=1", fetch_all=True)
    low_stock_count = len(low_stock) if low_stock else 0
    return render_template_string("""
    <!DOCTYPE html>
    <html dir="rtl">
    <head><title>لوحة الإدارة</title>
    <style>
        body{background:#000;color:#FFD700;font-family:Arial;padding:20px;}
        .header{background:#111;border:1px solid #FFD700;padding:20px;border-radius:10px;margin-bottom:20px;}
        .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:20px;}
        .card{background:#111;border:1px solid #FFD700;padding:20px;border-radius:10px;text-align:center;cursor:pointer;transition:0.3s;}
        .card:hover{transform:translateY(-5px);background:#222;}
        .logout{position:absolute;top:20px;left:20px;background:#FFD700;color:#000;padding:10px;border-radius:5px;text-decoration:none;}
        .alert{background:#8B0000;border:1px solid #FFD700;padding:10px;border-radius:5px;margin-bottom:20px;}
        .chat-float { position: fixed; bottom: 20px; left: 20px; background: #FFD700; color: #000; width: 60px; height: 60px; border-radius: 50%; font-size: 30px; display: flex; align-items: center; justify-content: center; cursor: pointer; z-index: 999; box-shadow: 0 4px 15px rgba(0,0,0,0.5); text-decoration: none; }
    </style>
    </head>
    <body>
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
    </div>
    </body>
    """, low_stock_count=low_stock_count)

# ... (باقي المسارات الإدارية تبقى كما هي، مع إمكانية إضافة زر المساعد في القوالب الإدارية إن أردت)

# =============================== تشغيل التطبيق ===============================
if __name__ == '__main__':
    print("="*70)
    print("🚀 نظام إدارة السوبر ماركت - سوبر ماركت اولاد قايد محمد (الإصدار المتكامل)")
    print("="*70)
    print(f"📁 قاعدة البيانات: {'PostgreSQL' if DATABASE_URL else 'SQLite local'}")
    print("🤖 المساعد الذكي: ", "مفعل (OpenAI)" if OPENAI_API_KEY else "يعمل محلياً")
    print("🌐 الروابط:")
    print("   👉 http://localhost:5000/            (الرئيسية)")
    print("   👉 http://localhost:5000/chat        (المساعد الذكي)")
    print("   👉 http://localhost:5000/login       (تسجيل الدخول)")
    print("   👉 http://localhost:5000/admin       (لوحة المدير)")
    print("   👉 http://localhost:5000/pos         (نقطة البيع)")
    print("="*70)
    print("🔐 بيانات الدخول:")
    print("   admin / admin123 (مدير)")
    print("   cashier / cashier123 (كاشير)")
    print("   stock / stock123 (أمين مخزن)")
    print("="*70)
    app.run(host='127.0.0.1', port=5000, debug=True)
