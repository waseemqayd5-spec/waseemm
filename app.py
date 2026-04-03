"""
نظام إدارة سوبر ماركت متكامل - سوبر ماركت اولاد قايد محمد
يدعم SQLite و PostgreSQL، ألوان أسود/ذهبي/أبيض، صور منتجات، باركود، مرتجعات، مشتريات، إحصائيات.
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

# =============================== التهيئة ===============================
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-key-change-in-production')
UPLOAD_FOLDER = 'static/uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

DATABASE_URL = os.environ.get('DATABASE_URL', None)

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
    # تحديث المستوى
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
            @media (max-width: 600px) { .products-grid { grid-template-columns: 1fr; } }
        </style>
    </head>
    <body>
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
                            alert(`المنتج: ${data.name}\nالسعر: ${data.price} ريال`);
                            // إضافة مباشرة للسلة
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
    </style>
    </head>
    <body><div class="container">
    <div class="header"><h1>{{ company_name }} - المنتجات</h1><div class="nav"><a href="/">الرئيسية</a><a href="/products">المنتجات</a><a href="/offers">العروض</a><a href="/points">نقاطي</a><a href="/cart">السلة</a></div></div>
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
    </style>
    </head>
    <body><div class="container"><h1>🛒 سلة المشتريات</h1>
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
    <style>body{background:#000;color:#fff;padding:20px;}.offer{background:#111;border:1px solid #FFD700;border-radius:10px;padding:20px;margin:15px 0;color:#FFD700;}</style>
    </head>
    <body><h1>🎁 العروض الحالية</h1><div id="offers"></div>
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
    <style>body{background:#000;color:#fff;padding:20px;}.card{background:#111;border:1px solid #FFD700;border-radius:10px;padding:20px;max-width:400px;margin:auto;text-align:center;color:#FFD700;}</style>
    </head>
    <body><div class="card"><h2>🏅 استعلام عن النقاط</h2><input type="tel" id="phone" placeholder="رقم الهاتف" style="width:100%;padding:8px;margin:10px 0;"><button onclick="check()">استعلام</button><div id="result"></div></div>
    <script>
        function check(){let phone=document.getElementById('phone').value;if(!phone){alert('أدخل رقم الهاتف');return;}fetch('/api/customer/'+phone).then(r=>r.json()).then(data=>{if(data.success){document.getElementById('result').innerHTML=`<p>الاسم: ${data.name}</p><p>النقاط: ${data.loyalty_points}</p><p>الإنفاق: ${data.total_spent}</p><p>المستوى: ${data.tier}</p>`;}else{document.getElementById('result').innerHTML='<p>لم يتم العثور على العميل</p>';}});}
    </script>
    </body>
    """)

# =============================== واجهات تسجيل الدخول ===============================
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

# =============================== واجهات الإدارة ===============================
@app.route('/admin')
@login_required
def admin_dashboard():
    if session['role'] != 'admin':
        return redirect(url_for('pos'))
    # إحصائيات سريعة وتنبيهات المخزون المنخفض
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
    </style>
    </head>
    <body><a href="/logout" class="logout">تسجيل خروج</a>
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
    </div>
    </body>
    """, low_stock_count=low_stock_count)

@app.route('/admin/settings', methods=['GET', 'POST'])
@admin_required
def admin_settings():
    settings = get_settings()
    if request.method == 'POST':
        new_settings = {}
        for key in settings.keys():
            new_settings[key] = request.form.get(key, '')
        save_settings(new_settings)
        return redirect(url_for('admin_settings'))
    return render_template_string("""
    <!DOCTYPE html>
    <html dir="rtl">
    <head><title>إعدادات المتجر</title>
    <style>body{background:#000;color:#FFD700;font-family:Arial;padding:20px;}.form{max-width:600px;margin:auto;background:#111;border:1px solid #FFD700;padding:20px;border-radius:10px;}</style>
    </head>
    <body><div class="form"><h2>⚙️ إعدادات المتجر</h2>
    <form method="post">
        {% for key,val in settings.items() %}
        <div><label>{{ key }}</label><input type="text" name="{{ key }}" value="{{ val }}" style="width:100%;padding:5px;margin:5px 0;background:#000;color:#FFD700;border:1px solid #FFD700;"></div>
        {% endfor %}
        <button type="submit">حفظ</button>
    </form>
    <a href="/admin">العودة</a></div></body>
    """, settings=settings)

@app.route('/admin/products')
@stock_keeper_required
def admin_products():
    return render_template_string("""
    <!DOCTYPE html>
    <html dir="rtl">
    <head><title>إدارة المنتجات</title>
    <style>body{background:#000;color:#FFD700;padding:20px;}.btn{background:#FFD700;color:#000;padding:8px 15px;border:none;border-radius:5px;cursor:pointer;}.table{width:100%;border-collapse:collapse;}.table th,.table td{border:1px solid #FFD700;padding:8px;text-align:right;}.form-group{margin-bottom:10px;}</style>
    </head>
    <body><h1>📦 إدارة المنتجات</h1>
    <button class="btn" onclick="showAddForm()">➕ إضافة منتج</button>
    <div id="products-list"></div>
    <div id="add-form" style="display:none; margin-top:20px; background:#111; padding:20px; border-radius:10px;">
        <h2>إضافة منتج</h2>
        <form id="productForm" enctype="multipart/form-data">
            <div class="form-group"><label>الباركود</label><input type="text" name="barcode" required></div>
            <div class="form-group"><label>الاسم</label><input type="text" name="name" required></div>
            <div class="form-group"><label>الوصف</label><textarea name="description"></textarea></div>
            <div class="form-group"><label>الفئة</label><input type="text" name="category"></div>
            <div class="form-group"><label>السعر</label><input type="number" step="0.01" name="price" required></div>
            <div class="form-group"><label>سعر التكلفة</label><input type="number" step="0.01" name="cost_price"></div>
            <div class="form-group"><label>الكمية</label><input type="number" name="quantity" required></div>
            <div class="form-group"><label>الحد الأدنى</label><input type="number" name="min_quantity" value="10"></div>
            <div class="form-group"><label>الوحدة</label><input type="text" name="unit" value="قطعة"></div>
            <div class="form-group"><label>المورد</label><select name="supplier_id" id="supplier_select"></select></div>
            <div class="form-group"><label>تاريخ الانتهاء</label><input type="date" name="expiry_date"></div>
            <div class="form-group"><label>الصورة الرئيسية</label><input type="file" name="image"></div>
            <div class="form-group"><label>صورة إضافية</label><input type="file" name="image2"></div>
            <button type="submit" class="btn">حفظ</button>
            <button type="button" class="btn" onclick="hideAddForm()">إلغاء</button>
        </form>
    </div>
    <script>
        function loadProducts(){
            fetch('/api/products/admin').then(r=>r.json()).then(data=>{
                let html='<table class="table"><tr><th>الباركود</th><th>الاسم</th><th>السعر</th><th>الكمية</th><th>الإجراءات</th></tr>';
                data.products.forEach(p=>{
                    html+=`<tr><td>${p.barcode}</td><td>${p.name}</td><td>${p.price}</td><td>${p.quantity}</td><td><button onclick="editProduct(${p.id})">تعديل</button><button onclick="deleteProduct(${p.id})">حذف</button></td></tr>`;
                });
                html+='</table>';
                document.getElementById('products-list').innerHTML=html;
            });
        }
        function loadSuppliers(){
            fetch('/api/suppliers').then(r=>r.json()).then(data=>{
                let sel=document.getElementById('supplier_select');
                data.suppliers.forEach(s=>{let opt=document.createElement('option');opt.value=s.id;opt.textContent=s.name;sel.appendChild(opt);});
            });
        }
        function showAddForm(){document.getElementById('add-form').style.display='block';}
        function hideAddForm(){document.getElementById('add-form').style.display='none';}
        document.getElementById('productForm').onsubmit=function(e){
            e.preventDefault();
            let formData=new FormData(this);
            fetch('/api/products/add',{method:'POST',body:formData}).then(r=>r.json()).then(data=>{
                alert(data.message);
                if(data.success){hideAddForm();loadProducts();}
            });
        };
        function deleteProduct(id){
            if(confirm('هل أنت متأكد؟')) fetch('/api/products/delete/'+id,{method:'DELETE'}).then(r=>r.json()).then(data=>{alert(data.message);loadProducts();});
        }
        loadProducts(); loadSuppliers();
    </script>
    </body>
    """)

@app.route('/api/products/admin')
@login_required
def api_products_admin():
    rows = execute_query("SELECT id, barcode, name, price, quantity, category FROM products WHERE is_active=1 ORDER BY name", fetch_all=True)
    return jsonify({"success": True, "products": [dict(r) for r in rows] if rows else []})

@app.route('/api/products/add', methods=['POST'])
@stock_keeper_required
def api_add_product():
    try:
        barcode = request.form.get('barcode')
        name = request.form.get('name')
        description = request.form.get('description', '')
        price = float(request.form.get('price'))
        cost_price = request.form.get('cost_price')
        cost_price = float(cost_price) if cost_price else 0
        quantity = int(request.form.get('quantity'))
        min_quantity = int(request.form.get('min_quantity', 10))
        unit = request.form.get('unit', 'قطعة')
        category = request.form.get('category', '')
        supplier_id = request.form.get('supplier_id')
        expiry_date = request.form.get('expiry_date')
        image = request.files.get('image')
        image2 = request.files.get('image2')
        image_url = ''
        image_url2 = ''
        if image and allowed_file(image.filename):
            filename = secure_filename(image.filename)
            filename = f"{int(time.time())}_{filename}"
            image.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            image_url = f"/static/uploads/{filename}"
        if image2 and allowed_file(image2.filename):
            filename2 = secure_filename(image2.filename)
            filename2 = f"{int(time.time())}_{filename2}"
            image2.save(os.path.join(app.config['UPLOAD_FOLDER'], filename2))
            image_url2 = f"/static/uploads/{filename2}"
        exists = execute_query("SELECT id FROM products WHERE barcode = ?", (barcode,), fetch_one=True)
        if exists:
            return jsonify({"success": False, "message": "الباركود موجود مسبقاً"})
        today = datetime.date.today().isoformat()
        execute_query("""
            INSERT INTO products (barcode, name, description, category, price, cost_price, quantity, min_quantity, unit, supplier_id, expiry_date, added_date, last_updated, image_url, image_url2)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (barcode, name, description, category, price, cost_price, quantity, min_quantity, unit, supplier_id, expiry_date, today, today, image_url, image_url2), commit=True)
        return jsonify({"success": True, "message": "تمت الإضافة"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/products/delete/<int:pid>', methods=['DELETE'])
@stock_keeper_required
def api_delete_product(pid):
    execute_query("UPDATE products SET is_active=0 WHERE id=?", (pid,), commit=True)
    return jsonify({"success": True, "message": "تم الحذف"})

@app.route('/api/product/by-barcode/<barcode>')
def api_product_by_barcode(barcode):
    row = execute_query("SELECT id, name, price, image_url FROM products WHERE barcode = ? AND is_active=1", (barcode,), fetch_one=True)
    if row:
        return jsonify({"success": True, "id": row['id'], "name": row['name'], "price": row['price'], "image_url": row['image_url']})
    return jsonify({"success": False, "message": "المنتج غير موجود"}), 404

# =============================== الموردين ===============================
@app.route('/admin/suppliers')
@admin_required
def admin_suppliers():
    return render_template_string("""
    <!DOCTYPE html>
    <html dir="rtl">
    <head><title>الموردين</title>
    <style>body{background:#000;color:#FFD700;padding:20px;}</style>
    </head>
    <body><h1>🏭 الموردين</h1>
    <button onclick="showAdd()">➕ إضافة مورد</button>
    <div id="list"></div>
    <div id="addForm" style="display:none;"><form id="supplierForm"><input name="name" placeholder="الاسم"><input name="phone" placeholder="الهاتف"><input name="address" placeholder="العنوان"><button type="submit">حفظ</button></form></div>
    <script>
        function loadSuppliers(){fetch('/api/suppliers').then(r=>r.json()).then(data=>{let html='<table border="1"><tr><th>الاسم</th><th>الهاتف</th><th>العنوان</th></tr>';data.suppliers.forEach(s=>{html+=`<tr><td>${s.name}</td><td>${s.phone}</td><td>${s.address}</td></tr>`;});html+='</table>';document.getElementById('list').innerHTML=html;});}
        function showAdd(){document.getElementById('addForm').style.display='block';}
        document.getElementById('supplierForm').onsubmit=function(e){e.preventDefault();let formData=new FormData(this);fetch('/api/suppliers/add',{method:'POST',body:JSON.stringify(Object.fromEntries(formData)),headers:{'Content-Type':'application/json'}}).then(r=>r.json()).then(data=>{alert(data.message);if(data.success){loadSuppliers();document.getElementById('addForm').style.display='none';}});};
        loadSuppliers();
    </script>
    </body>
    """)

@app.route('/api/suppliers')
def api_suppliers():
    rows = execute_query("SELECT id, name, phone, address FROM suppliers", fetch_all=True)
    return jsonify({"success": True, "suppliers": [dict(r) for r in rows] if rows else []})

@app.route('/api/suppliers/add', methods=['POST'])
@admin_required
def api_add_supplier():
    data = request.json
    execute_query("INSERT INTO suppliers (name, phone, address) VALUES (?, ?, ?)", (data['name'], data['phone'], data['address']), commit=True)
    return jsonify({"success": True, "message": "تمت الإضافة"})

# =============================== المشتريات ===============================
@app.route('/admin/purchases')
@admin_required
def admin_purchases():
    return render_template_string("""
    <!DOCTYPE html>
    <html dir="rtl">
    <head><title>المشتريات</title>
    <style>body{background:#000;color:#FFD700;padding:20px;}</style>
    </head>
    <body><h1>📥 المشتريات</h1>
    <button onclick="showAdd()">➕ إضافة شراء</button>
    <div id="list"></div>
    <div id="addForm" style="display:none;"><form id="purchaseForm"><select name="supplier_id" id="supplier_select"></select><input name="invoice_number" placeholder="رقم الفاتورة"><input name="total_cost" placeholder="الإجمالي"><button type="submit">حفظ</button></form></div>
    <script>
        function loadPurchases(){fetch('/api/purchases').then(r=>r.json()).then(data=>{let html='<table border="1"><tr><th>المورد</th><th>رقم الفاتورة</th><th>الإجمالي</th><th>التاريخ</th></tr>';data.purchases.forEach(p=>{html+=`<tr><td>${p.supplier_name}</td><td>${p.invoice_number}</td><td>${p.total_cost}</td><td>${p.purchase_date}</td></tr>`;});html+='</table>';document.getElementById('list').innerHTML=html;});}
        function loadSuppliers(){fetch('/api/suppliers').then(r=>r.json()).then(data=>{let sel=document.getElementById('supplier_select');data.suppliers.forEach(s=>{let opt=document.createElement('option');opt.value=s.id;opt.textContent=s.name;sel.appendChild(opt);});});}
        function showAdd(){document.getElementById('addForm').style.display='block';}
        document.getElementById('purchaseForm').onsubmit=function(e){e.preventDefault();let formData=new FormData(this);fetch('/api/purchases/add',{method:'POST',body:JSON.stringify(Object.fromEntries(formData)),headers:{'Content-Type':'application/json'}}).then(r=>r.json()).then(data=>{alert(data.message);if(data.success){loadPurchases();document.getElementById('addForm').style.display='none';}});};
        loadPurchases();loadSuppliers();
    </script>
    </body>
    """)

@app.route('/api/purchases')
def api_purchases():
    rows = execute_query("""
        SELECT p.*, s.name as supplier_name 
        FROM purchases p LEFT JOIN suppliers s ON p.supplier_id = s.id 
        ORDER BY p.purchase_date DESC
    """, fetch_all=True)
    return jsonify({"success": True, "purchases": [dict(r) for r in rows] if rows else []})

@app.route('/api/purchases/add', methods=['POST'])
@admin_required
def api_add_purchase():
    data = request.json
    supplier_id = data.get('supplier_id')
    invoice_number = data.get('invoice_number')
    total_cost = float(data.get('total_cost', 0))
    purchase_date = datetime.date.today().isoformat()
    execute_query("""
        INSERT INTO purchases (supplier_id, invoice_number, total_cost, purchase_date)
        VALUES (?, ?, ?, ?)
    """, (supplier_id, invoice_number, total_cost, purchase_date), commit=True)
    return jsonify({"success": True, "message": "تمت إضافة الشراء"})

# =============================== العروض ===============================
@app.route('/admin/offers')
@admin_required
def admin_offers():
    return render_template_string("""
    <!DOCTYPE html>
    <html dir="rtl">
    <head><title>العروض</title>
    <style>body{background:#000;color:#FFD700;padding:20px;}</style>
    </head>
    <body><h1>🎁 العروض</h1>
    <button onclick="showAdd()">➕ إضافة عرض</button>
    <div id="list"></div>
    <div id="addForm" style="display:none;"><form id="offerForm"><input name="title" placeholder="العنوان"><input name="description" placeholder="الوصف"><input name="code" placeholder="الكود"><select name="discount_type"><option value="percentage">نسبة</option><option value="fixed">قيمة ثابتة</option></select><input name="discount_value" placeholder="قيمة الخصم" type="number"><input name="start_date" type="date"><input name="end_date" type="date"><button type="submit">حفظ</button></form></div>
    <script>
        function loadOffers(){fetch('/api/offers').then(r=>r.json()).then(data=>{let html='<table border="1"><tr><th>العنوان</th><th>الكود</th><th>الخصم</th><th>الفترة</th></tr>';data.offers.forEach(o=>{html+=`<tr><td>${o.title}</td><td>${o.code}</td><td>${o.discount_value} ${o.discount_type=='percentage'?'%':'ريال'}</td><td>${o.start_date||''} - ${o.end_date||''}</td></tr>`;});html+='</table>';document.getElementById('list').innerHTML=html;});}
        function showAdd(){document.getElementById('addForm').style.display='block';}
        document.getElementById('offerForm').onsubmit=function(e){e.preventDefault();let formData=new FormData(this);fetch('/api/offers/add',{method:'POST',body:JSON.stringify(Object.fromEntries(formData)),headers:{'Content-Type':'application/json'}}).then(r=>r.json()).then(data=>{alert(data.message);if(data.success){loadOffers();document.getElementById('addForm').style.display='none';}});};
        loadOffers();
    </script>
    </body>
    """)

@app.route('/api/offers')
def api_offers():
    today = datetime.date.today().isoformat()
    rows = execute_query("SELECT * FROM offers WHERE is_active=1 AND (start_date IS NULL OR start_date <= ?) AND (end_date IS NULL OR end_date >= ?)", (today, today), fetch_all=True)
    return jsonify({"success": True, "offers": [dict(r) for r in rows] if rows else []})

@app.route('/api/offers/add', methods=['POST'])
@admin_required
def api_add_offer():
    data = request.json
    execute_query("""
        INSERT INTO offers (title, description, code, discount_type, discount_value, start_date, end_date)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (data['title'], data['description'], data['code'], data['discount_type'], data['discount_value'], data.get('start_date'), data.get('end_date')), commit=True)
    return jsonify({"success": True, "message": "تمت الإضافة"})

# =============================== العملاء ===============================
@app.route('/admin/customers')
@admin_required
def admin_customers():
    rows = execute_query("SELECT id, name, phone, address, loyalty_points, total_spent, visits, last_visit, tier FROM customers WHERE is_active=1 ORDER BY total_spent DESC", fetch_all=True)
    html = '<!DOCTYPE html><html dir="rtl"><head><title>العملاء</title><style>body{background:#000;color:#FFD700;padding:20px;}table{border-collapse:collapse;}td,th{border:1px solid #FFD700;padding:8px;}</style></head><body><h1>👥 العملاء</h1><a href="/admin/customers/add">➕ إضافة عميل</a><br><br><table border="1"><tr><th>الاسم</th><th>الهاتف</th><th>العنوان</th><th>النقاط</th><th>الإنفاق</th><th>الزيارات</th><th>آخر زيارة</th><th>المستوى</th></tr>'
    for r in rows:
        html += f"<tr><td>{r['name']}</td><td>{r['phone']}</td><td>{r['address'] or ''}</td><td>{r['loyalty_points']}</td><td>{r['total_spent']}</td><td>{r['visits']}</td><td>{r['last_visit']}</td><td>{r['tier']}</td></tr>"
    html += '</table><a href="/admin">العودة</a></body></html>'
    return html

@app.route('/admin/customers/add', methods=['GET', 'POST'])
@admin_required
def add_customer():
    if request.method == 'POST':
        name = request.form.get('name')
        phone = request.form.get('phone')
        address = request.form.get('address')
        if not name or not phone:
            return "الاسم والهاتف مطلوبان", 400
        try:
            execute_query("INSERT INTO customers (name, phone, address, loyalty_points, total_spent, visits, last_visit, tier) VALUES (?, ?, ?, 0, 0, 0, ?, 'عادي')",
                          (name, phone, address, datetime.date.today().isoformat()), commit=True)
            return redirect(url_for('admin_customers'))
        except Exception as e:
            return f"خطأ: الهاتف موجود مسبقاً أو {e}", 400
    return render_template_string("""
    <!DOCTYPE html>
    <html dir="rtl">
    <head><title>إضافة عميل</title>
    <style>body{background:#000;color:#FFD700;padding:20px;}</style>
    </head>
    <body>
        <h2>➕ إضافة عميل جديد</h2>
        <form method="post">
            <label>الاسم: <input type="text" name="name" required></label><br><br>
            <label>رقم الهاتف: <input type="text" name="phone" required></label><br><br>
            <label>العنوان: <input type="text" name="address"></label><br><br>
            <button type="submit">حفظ</button>
            <a href="/admin/customers">إلغاء</a>
        </form>
    </body>
    """)

@app.route('/api/customer/<phone>')
def api_customer(phone):
    row = execute_query("SELECT name, loyalty_points, total_spent, tier FROM customers WHERE phone = ? AND is_active=1", (phone,), fetch_one=True)
    if row:
        return jsonify({"success": True, "name": row['name'], "loyalty_points": row['loyalty_points'], "total_spent": row['total_spent'], "tier": row['tier']})
    return jsonify({"success": False, "message": "لم يتم العثور على العميل"}), 404

# =============================== الفواتير ===============================
@app.route('/admin/invoices')
@admin_required
def admin_invoices():
    rows = execute_query("SELECT id, invoice_number, customer_name, customer_phone, total, final_total, created_at FROM invoices ORDER BY created_at DESC", fetch_all=True)
    html = '<!DOCTYPE html><html dir="rtl"><head><title>الفواتير</title><style>body{background:#000;color:#FFD700;padding:20px;}</style></head><body><h1>📄 الفواتير</h1><table border="1"><tr><th>رقم الفاتورة</th><th>العميل</th><th>الهاتف</th><th>الإجمالي</th><th>النهائي</th><th>التاريخ</th></tr>'
    for r in rows:
        html += f"<tr><td>{r['invoice_number']}</td><td>{r['customer_name']}</td><td>{r['customer_phone']}</td><td>{r['total']}</td><td>{r['final_total']}</td><td>{r['created_at']}</td></tr>"
    html += '</table><a href="/admin">العودة</a></body></html>'
    return html

# =============================== مرتجعات البضاعة ===============================
@app.route('/admin/returns')
@admin_required
def admin_returns():
    return render_template_string("""
    <!DOCTYPE html>
    <html dir="rtl">
    <head><title>مرتجعات البضاعة</title>
    <style>body{background:#000;color:#FFD700;padding:20px;}.btn{background:#FFD700;color:#000;padding:8px;border:none;border-radius:5px;}</style>
    </head>
    <body><h1>🔄 مرتجعات البضاعة</h1>
    <form id="returnForm">
        <select id="product_id" required><option value="">اختر المنتج</option></select>
        <input type="number" id="quantity" placeholder="الكمية المرتجعة" required>
        <input type="text" id="reason" placeholder="سبب الإرجاع">
        <input type="text" id="invoice_number" placeholder="رقم الفاتورة (اختياري)">
        <button type="submit" class="btn">تسجيل إرجاع</button>
    </form>
    <div id="returns-list"></div>
    <script>
        function loadProducts(){
            fetch('/api/products/admin').then(r=>r.json()).then(data=>{
                let sel=document.getElementById('product_id');
                data.products.forEach(p=>{
                    let opt=document.createElement('option');
                    opt.value=p.id;
                    opt.textContent=`${p.name} (المتبقي: ${p.quantity})`;
                    sel.appendChild(opt);
                });
            });
        }
        function loadReturns(){
            fetch('/api/returns').then(r=>r.json()).then(data=>{
                let html='<h3>المرتجعات السابقة</h3><table border="1"><tr><th>المنتج</th><th>الكمية</th><th>السعر</th><th>الإجمالي</th><th>السبب</th><th>التاريخ</th></tr>';
                data.returns.forEach(r=>{
                    html+=`<tr><td>${r.product_name}</td><td>${r.quantity}</td><td>${r.price}</td><td>${r.total}</td><td>${r.reason}</td><td>${r.return_date}</td></tr>`;
                });
                html+='</table>';
                document.getElementById('returns-list').innerHTML=html;
            });
        }
        document.getElementById('returnForm').onsubmit=function(e){
            e.preventDefault();
            let product_id=document.getElementById('product_id').value;
            let quantity=parseInt(document.getElementById('quantity').value);
            let reason=document.getElementById('reason').value;
            let invoice_number=document.getElementById('invoice_number').value;
            fetch('/api/returns/add',{
                method:'POST',
                headers:{'Content-Type':'application/json'},
                body:JSON.stringify({product_id,quantity,reason,invoice_number})
            }).then(r=>r.json()).then(data=>{
                alert(data.message);
                if(data.success){loadReturns();document.getElementById('returnForm').reset();loadProducts();}
            });
        };
        loadProducts(); loadReturns();
    </script>
    </body>
    """)

@app.route('/api/returns')
def api_returns():
    rows = execute_query("SELECT * FROM returns ORDER BY return_date DESC", fetch_all=True)
    return jsonify({"success": True, "returns": [dict(r) for r in rows] if rows else []})

@app.route('/api/returns/add', methods=['POST'])
@admin_required
def api_add_return():
    data = request.json
    product_id = data.get('product_id')
    quantity = int(data.get('quantity'))
    reason = data.get('reason', '')
    invoice_number = data.get('invoice_number', '')
    # جلب المنتج
    product = execute_query("SELECT name, price, quantity FROM products WHERE id = ?", (product_id,), fetch_one=True)
    if not product:
        return jsonify({"success": False, "message": "المنتج غير موجود"})
    if product['quantity'] < quantity:
        return jsonify({"success": False, "message": "الكمية المرتجعة أكبر من المتوفر في المخزون"})
    total = product['price'] * quantity
    # تحديث المخزون (إضافة الكمية المرتجعة)
    new_qty = product['quantity'] + quantity
    execute_query("UPDATE products SET quantity = ? WHERE id = ?", (new_qty, product_id), commit=True)
    log_inventory(product_id, product['name'], 'مرتجع', quantity, product['quantity'], new_qty, f"إرجاع - {reason}", session['user_id'])
    # تسجيل الإرجاع
    execute_query("""
        INSERT INTO returns (product_id, product_name, quantity, price, total, reason, return_date, created_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (product_id, product['name'], quantity, product['price'], total, reason, datetime.date.today().isoformat(), session['user_id']), commit=True)
    return jsonify({"success": True, "message": "تم تسجيل الإرجاع وتحديث المخزون"})

# =============================== التقارير ===============================
@app.route('/admin/reports')
@admin_required
def admin_reports():
    total_invoices = execute_query("SELECT COUNT(*) FROM invoices", fetch_one=True)[0]
    total_revenue = execute_query("SELECT COALESCE(SUM(final_total),0) FROM invoices", fetch_one=True)[0] or 0
    # حساب الربح الصافي
    cost_query = """
        SELECT COALESCE(SUM(ii.quantity * p.cost_price), 0) as total_cost
        FROM invoice_items ii
        JOIN products p ON ii.product_id = p.id
    """
    total_cost = execute_query(cost_query, fetch_one=True)[0] or 0
    net_profit = total_revenue - total_cost
    profit_margin = (net_profit / total_revenue * 100) if total_revenue > 0 else 0
    total_customers = execute_query("SELECT COUNT(*) FROM customers", fetch_one=True)[0]
    total_points = execute_query("SELECT COALESCE(SUM(loyalty_points),0) FROM customers", fetch_one=True)[0] or 0
    # أفضل المنتجات مبيعاً
    top_products = execute_query("""
        SELECT product_name, SUM(quantity) as qty, SUM(total) as revenue
        FROM invoice_items
        GROUP BY product_name
        ORDER BY qty DESC
        LIMIT 10
    """, fetch_all=True)
    # تنبيهات المخزون المنخفض
    low_stock = execute_query("SELECT id, name, quantity, min_quantity FROM products WHERE quantity <= min_quantity AND is_active=1", fetch_all=True)
    html = '<!DOCTYPE html><html dir="rtl"><head><title>التقارير</title><style>body{background:#000;color:#FFD700;padding:20px;}table{border-collapse:collapse;}td,th{border:1px solid #FFD700;padding:8px;}</style></head><body><h1>📊 التقارير</h1>'
    html += f'<p>عدد الفواتير: {total_invoices}</p>'
    html += f'<p>إجمالي الإيرادات: {total_revenue:.2f} ريال</p>'
    html += f'<p>إجمالي التكلفة: {total_cost:.2f} ريال</p>'
    html += f'<p><strong>صافي الربح: {net_profit:.2f} ريال</strong> (بنسبة {profit_margin:.2f}%)</p>'
    html += f'<p>إجمالي العملاء: {total_customers}</p>'
    html += f'<p>إجمالي النقاط: {total_points}</p>'
    html += '<h2>🏆 أفضل المنتجات مبيعاً</h2><table border="1"><tr><th>المنتج</th><th>الكمية المباعة</th><th>الإيرادات</th></tr>'
    for p in top_products:
        html += f"<tr><td>{p['product_name']}</td><td>{p['qty']}</td><td>{p['revenue']:.2f}</td></tr>"
    html += '</table>'
    if low_stock:
        html += '<h2>⚠️ منتجات المخزون المنخفض</h2><table border="1"><tr><th>المنتج</th><th>الكمية الحالية</th><th>الحد الأدنى</th></tr>'
        for ls in low_stock:
            html += f"<tr><td>{ls['name']}</td><td>{ls['quantity']}</td><td>{ls['min_quantity']}</td></tr>"
        html += '</table>'
    html += '<a href="/admin">العودة</a></body></html>'
    return html

# =============================== المستخدمين ===============================
@app.route('/admin/users')
@admin_required
def admin_users():
    rows = execute_query("SELECT id, username, role, full_name FROM users", fetch_all=True)
    html = '<!DOCTYPE html><html dir="rtl"><head><title>المستخدمين</title><style>body{background:#000;color:#FFD700;padding:20px;}</style></head><body><h1>👤 المستخدمين</h1><table border="1"><tr><th>اسم المستخدم</th><th>الدور</th><th>الاسم الكامل</th></tr>'
    for r in rows:
        html += f"<tr><td>{r['username']}</td><td>{r['role']}</td><td>{r['full_name']}</td></tr>"
    html += '</table><a href="/admin">العودة</a></body></html>'
    return html

# =============================== نقطة البيع (POS) ===============================
@app.route('/pos')
@cashier_required
def pos():
    return render_template_string("""
    <!DOCTYPE html>
    <html dir="rtl">
    <head><title>نقطة البيع</title>
    <style>
        body{background:#000;color:#FFD700;font-family:Arial;padding:20px;}
        .container{display:grid;grid-template-columns:1fr 350px;gap:20px;}
        .products{background:#111;border:1px solid #FFD700;border-radius:10px;padding:15px;height:70vh;overflow-y:auto;}
        .cart{background:#111;border:1px solid #FFD700;border-radius:10px;padding:15px;}
        .search{width:100%;padding:8px;margin-bottom:10px;background:#000;color:#FFD700;border:1px solid #FFD700;}
        .product-item{background:#000;border:1px solid #FFD700;border-radius:5px;padding:8px;margin-bottom:5px;cursor:pointer;display:flex;justify-content:space-between;}
        .cart-item{display:flex;justify-content:space-between;margin:5px 0;padding:5px;border-bottom:1px solid #FFD700;}
        .total{background:#FFD700;color:#000;padding:10px;border-radius:5px;text-align:center;font-weight:bold;margin:10px 0;}
        .btn{background:#FFD700;color:#000;padding:10px;border:none;border-radius:5px;cursor:pointer;}
    </style>
    </head>
    <body><h1>🛒 نقطة البيع</h1>
    <div class="container">
        <div class="products">
            <input type="text" id="search" placeholder="بحث بالاسم أو باركود" class="search" onkeyup="searchProducts()">
            <div id="product-list"></div>
        </div>
        <div class="cart">
            <h3>السلة</h3>
            <div id="cart-items"></div>
            <div class="total" id="cart-total">الإجمالي: 0 ريال</div>
            <button class="btn" onclick="checkout()">إنهاء الفاتورة</button>
            <div><input type="text" id="customer-phone" placeholder="رقم العميل (اختياري)" class="search"></div>
            <div><input type="text" id="customer-name" placeholder="اسم العميل (لجديد)" class="search"></div>
        </div>
    </div>
    <script>
        let cart = [];
        function searchProducts() {
            let q = document.getElementById('search').value;
            fetch(`/api/products?search=${encodeURIComponent(q)}`)
                .then(r=>r.json())
                .then(data=>{
                    if(data.success){
                        let html='';
                        data.products.forEach(p=>{
                            html+=`<div class="product-item" onclick="addToCart(${p.id},'${p.name.replace(/'/g,"\\'")}',${p.price})"><span>${p.name}</span><span>${p.price} ريال</span><span>${p.quantity}</span></div>`;
                        });
                        document.getElementById('product-list').innerHTML=html;
                    }
                });
        }
        function addToCart(id,name,price){
            let existing = cart.find(i=>i.id==id);
            if(existing) existing.quantity++;
            else cart.push({id,name,price,quantity:1});
            updateCartDisplay();
        }
        function updateCartDisplay(){
            let itemsDiv = document.getElementById('cart-items');
            let total=0;
            let html='';
            cart.forEach((item,i)=>{
                let itemTotal = item.price*item.quantity;
                total+=itemTotal;
                html+=`<div class="cart-item"><span>${item.name} x${item.quantity}</span><span>${itemTotal} ريال</span><button onclick="removeItem(${i})">حذف</button></div>`;
            });
            itemsDiv.innerHTML=html;
            document.getElementById('cart-total').innerText=`الإجمالي: ${total} ريال`;
        }
        function removeItem(idx){
            cart.splice(idx,1);
            updateCartDisplay();
        }
        function checkout(){
            if(cart.length==0){alert('السلة فارغة');return;}
            let customerPhone = document.getElementById('customer-phone').value;
            let customerName = document.getElementById('customer-name').value;
            let order = {cart, customer_phone: customerPhone, customer_name: customerName, payment_method:'cash'};
            fetch('/api/create_invoice',{
                method:'POST',
                headers:{'Content-Type':'application/json'},
                body:JSON.stringify(order)
            }).then(r=>r.json()).then(data=>{
                if(data.success){
                    alert(`تم إنشاء الفاتورة رقم ${data.invoice_number}`);
                    cart=[];
                    updateCartDisplay();
                }else alert('خطأ: '+data.message);
            });
        }
        searchProducts();
    </script>
    </body>
    """)

# =============================== واجهات API إضافية ===============================
@app.route('/api/categories')
def api_categories():
    rows = execute_query("SELECT DISTINCT category FROM products WHERE is_active=1 AND category IS NOT NULL AND category != ''", fetch_all=True)
    categories = [r['category'] for r in rows] if rows else []
    return jsonify({"success": True, "categories": categories})

@app.route('/api/products')
def api_products():
    search = request.args.get('search', '')
    category = request.args.get('category', '')
    limit = request.args.get('limit', 100)
    query = "SELECT id, name, description, price, quantity, unit, image_url, image_url2 FROM products WHERE is_active=1"
    params = []
    if search:
        query += " AND (name LIKE ? OR barcode LIKE ?)"
        params.append(f"%{search}%")
        params.append(f"%{search}%")
    if category:
        query += " AND category = ?"
        params.append(category)
    query += " ORDER BY name LIMIT ?"
    params.append(int(limit))
    rows = execute_query(query, params, fetch_all=True)
    return jsonify({"success": True, "products": [dict(r) for r in rows] if rows else []})

@app.route('/api/create_invoice', methods=['POST'])
@cashier_required
def api_create_invoice():
    data = request.json
    cart = data.get('cart', [])
    customer_phone = data.get('customer_phone')
    customer_name = data.get('customer_name')
    customer_address = data.get('customer_address', '')
    payment_method = data.get('payment_method', 'cash')
    if not cart:
        return jsonify({"success": False, "message": "السلة فارغة"})
    # البحث عن العميل
    customer = None
    if customer_phone:
        customer = execute_query("SELECT id, name, phone, address FROM customers WHERE phone = ?", (customer_phone,), fetch_one=True)
    if not customer and customer_name:
        # إنشاء عميل جديد
        try:
            execute_query("INSERT INTO customers (name, phone, address, loyalty_points, total_spent, visits, last_visit, tier) VALUES (?, ?, ?, 0, 0, 0, ?, 'عادي')",
                          (customer_name, customer_phone or '', customer_address, datetime.date.today().isoformat()), commit=True)
            customer = execute_query("SELECT id, name, phone, address FROM customers WHERE phone = ?", (customer_phone or '',), fetch_one=True)
        except:
            pass
    if not customer:
        customer = {"id": None, "name": customer_name or "عميل نقدي", "phone": customer_phone or "", "address": customer_address}
    total = sum(item['price'] * item['quantity'] for item in cart)
    discount = 0
    final_total = total - discount
    invoice_number = f"INV-{int(time.time())}"
    # إدراج الفاتورة
    if DATABASE_URL:
        row = execute_query("""
            INSERT INTO invoices (invoice_number, customer_id, customer_name, customer_phone, customer_address, total, discount, final_total, payment_method, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
        """, (invoice_number, customer['id'], customer['name'], customer['phone'], customer['address'], total, discount, final_total, payment_method, session['user_id']), fetch_one=True, commit=True)
        invoice_id = row['id']
    else:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO invoices (invoice_number, customer_id, customer_name, customer_phone, customer_address, total, discount, final_total, payment_method, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (invoice_number, customer['id'], customer['name'], customer['phone'], customer['address'], total, discount, final_total, payment_method, session['user_id']))
        conn.commit()
        invoice_id = cur.lastrowid
        cur.close()
        conn.close()
    # إضافة البنود وتحديث المخزون
    for item in cart:
        product = execute_query("SELECT id, name, quantity FROM products WHERE id = ?", (item['id'],), fetch_one=True)
        if not product:
            continue
        if product['quantity'] < item['quantity']:
            return jsonify({"success": False, "message": f"المنتج {product['name']} غير متوفر بالكمية المطلوبة"})
        execute_query("""
            INSERT INTO invoice_items (invoice_id, product_id, product_name, quantity, price, total)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (invoice_id, product['id'], product['name'], item['quantity'], item['price'], item['price']*item['quantity']), commit=True)
        new_qty = product['quantity'] - item['quantity']
        execute_query("UPDATE products SET quantity = ? WHERE id = ?", (new_qty, product['id']), commit=True)
        log_inventory(product['id'], product['name'], 'بيع', -item['quantity'], product['quantity'], new_qty, f'فاتورة {invoice_number}', session['user_id'])
    if customer['id']:
        update_customer_points(customer['id'], final_total)
    return jsonify({"success": True, "invoice_number": invoice_number})

# =============================== تشغيل التطبيق ===============================
if __name__ == '__main__':
    print("="*70)
    print("🚀 نظام إدارة السوبر ماركت - سوبر ماركت اولاد قايد محمد (الإصدار المتكامل)")
    print("="*70)
    print(f"📁 قاعدة البيانات: {'PostgreSQL' if DATABASE_URL else 'SQLite local'}")
    print("🌐 الروابط:")
    print("   👉 http://localhost:5000/            (الرئيسية)")
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
