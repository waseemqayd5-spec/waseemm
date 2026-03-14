"""
نظام سوبر ماركت متكامل - اولاد قايد محمد
نسخة كاملة وشاملة مع جميع الميزات المطلوبة:
- واجهة زبون حديثة (أسود وذهبي) مع صور المنتجات ومسح باركود
- إدارة متكاملة: منتجات، فئات، عملاء، فواتير، مصروفات، إحصائيات
- نظام دخول آمن (Flask-Login)
- دفع: نقدي، أجل، القطيبي (رقم حساب 108058)
- تقارير أرباح وتكاليف ومصروفات
"""

# ========================== الاستيرادات ==========================
import os
import datetime
import sqlite3
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, request, jsonify, render_template_string, redirect, url_for, session, send_from_directory
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import json

# ========================== الإعدادات الأساسية ==========================
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'supersecretkey123')

UPLOAD_FOLDER = os.path.join('static', 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

DATABASE_URL = os.environ.get('DATABASE_URL', None)

ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# ========================== دوال مساعدة ==========================
def get_db_connection():
    if DATABASE_URL:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    else:
        if not os.path.exists('data'):
            os.makedirs('data')
        conn = sqlite3.connect('data/supermarket.db')
        conn.row_factory = sqlite3.Row
    return conn

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ========================== نموذج المستخدم ==========================
class User(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username

@login_manager.user_loader
def load_user(user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    if DATABASE_URL:
        cur.execute("SELECT id, username FROM users WHERE id = %s", (user_id,))
    else:
        cur.execute("SELECT id, username FROM users WHERE id = ?", (user_id,))
    user = cur.fetchone()
    cur.close()
    conn.close()
    if user:
        return User(user['id'], user['username'])
    return None

# ========================== تسجيل الأنشطة ==========================
def log_activity(action, entity_type, entity_id=None, details=None):
    if current_user.is_authenticated:
        user = current_user.username
    else:
        user = 'system'
    ip = request.remote_addr or '127.0.0.1'
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        if DATABASE_URL:
            cur.execute("""
                INSERT INTO user_activity (user, action, entity_type, entity_id, details, ip_address, timestamp)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (user, action, entity_type, entity_id, details, ip, datetime.datetime.now().isoformat()))
        else:
            cur.execute("""
                INSERT INTO user_activity (user, action, entity_type, entity_id, details, ip_address, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (user, action, entity_type, entity_id, details, ip, datetime.datetime.now().isoformat()))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Log error: {e}")

# ========================== إنشاء الجداول والبيانات الافتراضية ==========================
def init_db():
    conn = get_db_connection()
    cur = conn.cursor()

    if DATABASE_URL:
        # PostgreSQL
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                password_hash VARCHAR(200) NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL UNIQUE
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS customers (
                id SERIAL PRIMARY KEY,
                phone VARCHAR(20) UNIQUE,
                name VARCHAR(100),
                loyalty_points INTEGER DEFAULT 0,
                total_spent REAL DEFAULT 0,
                visits INTEGER DEFAULT 0,
                last_visit VARCHAR(10),
                customer_tier VARCHAR(20) DEFAULT 'عادي',
                is_active INTEGER DEFAULT 1
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id SERIAL PRIMARY KEY,
                barcode VARCHAR(50) UNIQUE,
                name VARCHAR(200) NOT NULL,
                category_id INTEGER REFERENCES categories(id),
                price REAL NOT NULL,
                cost_price REAL,
                quantity INTEGER DEFAULT 0,
                min_quantity INTEGER DEFAULT 10,
                unit VARCHAR(20) DEFAULT 'قطعة',
                supplier VARCHAR(100),
                expiry_date VARCHAR(10),
                added_date VARCHAR(10),
                last_updated VARCHAR(10),
                image_path VARCHAR(255),
                is_active INTEGER DEFAULT 1
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
                user TEXT,
                timestamp TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sales (
                id SERIAL PRIMARY KEY,
                customer_name VARCHAR(100),
                customer_phone VARCHAR(20),
                customer_address TEXT,
                payment_method VARCHAR(20),
                account_number VARCHAR(50),
                notes TEXT,
                total REAL,
                tax REAL DEFAULT 0,
                discount REAL DEFAULT 0,
                net_total REAL,
                sale_date TEXT,
                user TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sale_items (
                id SERIAL PRIMARY KEY,
                sale_id INTEGER REFERENCES sales(id),
                product_id INTEGER REFERENCES products(id),
                product_name VARCHAR(200),
                price REAL,
                quantity INTEGER,
                total REAL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id SERIAL PRIMARY KEY,
                description TEXT,
                amount REAL,
                expense_date TEXT,
                user TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_activity (
                id SERIAL PRIMARY KEY,
                user VARCHAR(50),
                action VARCHAR(100),
                entity_type VARCHAR(50),
                entity_id INTEGER,
                details TEXT,
                ip_address VARCHAR(45),
                timestamp TEXT
            )
        """)

        # إضافة مستخدم افتراضي
        cur.execute("SELECT COUNT(*) FROM users")
        if cur.fetchone()[0] == 0:
            hashed = generate_password_hash(ADMIN_PASSWORD)
            cur.execute("INSERT INTO users (username, password_hash) VALUES (%s, %s)", (ADMIN_USERNAME, hashed))

        # إضافة فئات افتراضية
        cur.execute("SELECT COUNT(*) FROM categories")
        if cur.fetchone()[0] == 0:
            categories = ['مواد غذائية', 'مبردات', 'معلبات', 'منظفات', 'مشروبات', 'حلويات']
            for cat in categories:
                cur.execute("INSERT INTO categories (name) VALUES (%s)", (cat,))

        # إضافة عميل تجريبي
        cur.execute("SELECT COUNT(*) FROM customers")
        if cur.fetchone()[0] == 0:
            cur.execute("""
                INSERT INTO customers (phone, name, loyalty_points, total_spent, visits, last_visit)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, ("0500000000", "عميل تجريبي", 50, 200.0, 5, datetime.date.today().isoformat()))

        # إضافة منتجات افتراضية
        cur.execute("SELECT COUNT(*) FROM products")
        if cur.fetchone()[0] == 0:
            today = datetime.date.today().isoformat()
            future = (datetime.date.today() + datetime.timedelta(days=180)).isoformat()
            # الحصول على معرفات الفئات
            cur.execute("SELECT id, name FROM categories")
            cats = {row['name']: row['id'] for row in cur.fetchall()}
            default_products = [
                ("8801234567890", "أرز بسمتي", cats['مواد غذائية'], 25.0, 18.0, 50, 10, "كيلو", "مورد الأرز", future, today, today, ''),
                ("8809876543210", "سكر", cats['مواد غذائية'], 15.0, 11.0, 100, 20, "كيلو", "مورد السكر", future, today, today, ''),
                ("8801122334455", "زيت دوار الشمس", cats['مواد غذائية'], 35.0, 28.0, 30, 10, "لتر", "مورد الزيوت", future, today, today, ''),
                ("8805566778899", "حليب طازج", cats['مبردات'], 8.0, 6.0, 40, 15, "لتر", "شركة الألبان",
                 (datetime.date.today() + datetime.timedelta(days=14)).isoformat(), today, today, ''),
                ("8809988776655", "شاي", cats['مواد غذائية'], 20.0, 15.0, 60, 15, "علبة", "مورد الشاي", future, today, today, ''),
            ]
            for prod in default_products:
                cur.execute("""
                    INSERT INTO products (barcode, name, category_id, price, cost_price, quantity, min_quantity,
                                          unit, supplier, expiry_date, added_date, last_updated, image_path)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, prod)

    else:
        # SQLite
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT UNIQUE,
                name TEXT,
                loyalty_points INTEGER DEFAULT 0,
                total_spent REAL DEFAULT 0,
                visits INTEGER DEFAULT 0,
                last_visit TEXT,
                customer_tier TEXT DEFAULT 'عادي',
                is_active INTEGER DEFAULT 1
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                barcode TEXT UNIQUE,
                name TEXT NOT NULL,
                category_id INTEGER,
                price REAL NOT NULL,
                cost_price REAL,
                quantity INTEGER DEFAULT 0,
                min_quantity INTEGER DEFAULT 10,
                unit TEXT DEFAULT 'قطعة',
                supplier TEXT,
                expiry_date TEXT,
                added_date TEXT,
                last_updated TEXT,
                image_path TEXT,
                is_active INTEGER DEFAULT 1,
                FOREIGN KEY (category_id) REFERENCES categories(id)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS inventory_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER,
                product_name TEXT,
                change_type TEXT,
                quantity_change INTEGER,
                old_quantity INTEGER,
                new_quantity INTEGER,
                notes TEXT,
                user TEXT,
                timestamp TEXT,
                FOREIGN KEY (product_id) REFERENCES products(id)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sales (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_name TEXT,
                customer_phone TEXT,
                customer_address TEXT,
                payment_method TEXT,
                account_number TEXT,
                notes TEXT,
                total REAL,
                tax REAL DEFAULT 0,
                discount REAL DEFAULT 0,
                net_total REAL,
                sale_date TEXT,
                user TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sale_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sale_id INTEGER,
                product_id INTEGER,
                product_name TEXT,
                price REAL,
                quantity INTEGER,
                total REAL,
                FOREIGN KEY (sale_id) REFERENCES sales(id)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                description TEXT,
                amount REAL,
                expense_date TEXT,
                user TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user TEXT,
                action TEXT,
                entity_type TEXT,
                entity_id INTEGER,
                details TEXT,
                ip_address TEXT,
                timestamp TEXT
            )
        """)

        # إضافة مستخدم افتراضي
        cur.execute("SELECT COUNT(*) FROM users")
        if cur.fetchone()[0] == 0:
            hashed = generate_password_hash(ADMIN_PASSWORD)
            cur.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (ADMIN_USERNAME, hashed))

        # إضافة فئات افتراضية
        cur.execute("SELECT COUNT(*) FROM categories")
        if cur.fetchone()[0] == 0:
            categories = ['مواد غذائية', 'مبردات', 'معلبات', 'منظفات', 'مشروبات', 'حلويات']
            for cat in categories:
                cur.execute("INSERT INTO categories (name) VALUES (?)", (cat,))

        # إضافة عميل تجريبي
        cur.execute("SELECT COUNT(*) FROM customers")
        if cur.fetchone()[0] == 0:
            cur.execute("""
                INSERT INTO customers (phone, name, loyalty_points, total_spent, visits, last_visit)
                VALUES (?, ?, ?, ?, ?, ?)
            """, ("0500000000", "عميل تجريبي", 50, 200.0, 5, datetime.date.today().isoformat()))

        # إضافة منتجات افتراضية
        cur.execute("SELECT COUNT(*) FROM products")
        if cur.fetchone()[0] == 0:
            today = datetime.date.today().isoformat()
            future = (datetime.date.today() + datetime.timedelta(days=180)).isoformat()
            cur.execute("SELECT id, name FROM categories")
            cats = {row['name']: row['id'] for row in cur.fetchall()}
            default_products = [
                ("8801234567890", "أرز بسمتي", cats['مواد غذائية'], 25.0, 18.0, 50, 10, "كيلو", "مورد الأرز", future, today, today, ''),
                ("8809876543210", "سكر", cats['مواد غذائية'], 15.0, 11.0, 100, 20, "كيلو", "مورد السكر", future, today, today, ''),
                ("8801122334455", "زيت دوار الشمس", cats['مواد غذائية'], 35.0, 28.0, 30, 10, "لتر", "مورد الزيوت", future, today, today, ''),
                ("8805566778899", "حليب طازج", cats['مبردات'], 8.0, 6.0, 40, 15, "لتر", "شركة الألبان",
                 (datetime.date.today() + datetime.timedelta(days=14)).isoformat(), today, today, ''),
                ("8809988776655", "شاي", cats['مواد غذائية'], 20.0, 15.0, 60, 15, "علبة", "مورد الشاي", future, today, today, ''),
            ]
            for prod in default_products:
                cur.execute("""
                    INSERT INTO products (barcode, name, category_id, price, cost_price, quantity, min_quantity,
                                          unit, supplier, expiry_date, added_date, last_updated, image_path)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, prod)

    conn.commit()
    conn.close()

init_db()

# ========================== واجهة العميل (الصفحة الرئيسية) ==========================
@app.route('/')
def home():
    return render_template_string('''
    <!DOCTYPE html>
    <html dir="rtl" lang="ar">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>سوبر ماركت اولاد قايد محمد</title>
        <style>
            * { margin:0; padding:0; box-sizing:border-box; font-family:'Segoe UI',Arial; }
            body { background:#000; padding:20px; }
            .container { max-width:1400px; margin:0 auto; display:grid; grid-template-columns:1fr 350px; gap:20px; }
            @media (max-width:768px) { .container { grid-template-columns:1fr; } }
            .main-content { background:rgba(255,215,0,0.1); border-radius:20px; padding:20px; border:1px solid #FFD700; }
            .cart-sidebar { background:#111; border-radius:20px; padding:20px; border:1px solid #FFD700; color:#FFD700; position:sticky; top:20px; }
            h1 { color:#FFD700; text-align:center; margin-bottom:20px; }
            .nav { display:flex; gap:10px; margin-bottom:25px; flex-wrap:wrap; }
            .nav button { flex:1; padding:15px; background:#111; color:#FFD700; border:1px solid #FFD700; border-radius:12px; cursor:pointer; font-weight:bold; transition:0.3s; min-width:120px; }
            .nav button.active { background:#FFD700; color:#000; }
            .section { display:none; }
            .section.active { display:block; }
            .filters { display:flex; gap:15px; margin-bottom:25px; flex-wrap:wrap; }
            .filters select, .filters input { flex:1; padding:15px; background:#111; color:#FFD700; border:1px solid #FFD700; border-radius:12px; }
            .products-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(200px,1fr)); gap:20px; }
            .product-card { background:#111; border-radius:15px; padding:15px; text-align:center; border:1px solid #FFD700; transition:0.3s; }
            .product-card:hover { transform:translateY(-5px); box-shadow:0 10px 20px rgba(255,215,0,0.3); }
            .product-card img { width:100%; height:150px; object-fit:cover; border-radius:10px; margin-bottom:10px; }
            .product-name { font-size:18px; font-weight:bold; color:#FFD700; margin:10px 0; }
            .product-price { color:#FFD700; font-size:22px; font-weight:bold; }
            .add-to-cart-btn { background:#FFD700; color:#000; border:none; padding:12px; width:100%; border-radius:8px; font-weight:bold; cursor:pointer; }
            .cart-header { display:flex; justify-content:space-between; align-items:center; border-bottom:2px solid #FFD700; padding-bottom:15px; margin-bottom:20px; }
            .cart-item { display:flex; justify-content:space-between; background:#000; border:1px solid #FFD700; border-radius:8px; padding:10px; margin-bottom:10px; }
            .cart-total { background:#FFD700; color:#000; padding:15px; border-radius:10px; text-align:center; font-size:20px; font-weight:bold; margin:20px 0; }
            .whatsapp-btn { background:#25D366; color:white; border:none; padding:15px; width:100%; border-radius:10px; font-weight:bold; cursor:pointer; display:flex; align-items:center; justify-content:center; gap:10px; }
            .clear-cart-btn { background:#FFD700; color:#000; border:none; padding:8px 15px; border-radius:5px; cursor:pointer; }
            .modal { display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.9); align-items:center; justify-content:center; z-index:1000; }
            .modal-content { background:#111; border:2px solid #FFD700; border-radius:15px; padding:25px; width:90%; max-width:400px; color:#FFD700; }
            .modal-content input, .modal-content select, .modal-content textarea { width:100%; padding:12px; margin-bottom:15px; background:#000; border:1px solid #FFD700; color:#FFD700; border-radius:8px; }
            .modal-buttons { display:flex; gap:10px; }
            .modal-buttons button { flex:1; padding:12px; border-radius:8px; font-weight:bold; cursor:pointer; }
            .btn-confirm { background:#FFD700; color:#000; border:none; }
            .btn-cancel { background:#000; color:#FFD700; border:1px solid #FFD700; }
            #scanner-container { width:100%; max-width:400px; margin:20px auto; }
        </style>
        <script src="https://unpkg.com/quagga/dist/quagga.min.js"></script>
    </head>
    <body>
        <h1>🛒 سوبر ماركت اولاد قايد محمد</h1>
        <div class="container">
            <div class="main-content">
                <div class="nav">
                    <button class="active" onclick="showSection('points')">⭐ نقاطي</button>
                    <button onclick="showSection('products')">📦 المنتجات</button>
                    <button onclick="showSection('offers')">🎁 العروض</button>
                </div>

                <!-- قسم النقاط -->
                <div id="points-section" class="section active">
                    <div style="background:#111; padding:25px; border-radius:15px; border:1px solid #FFD700;">
                        <input type="tel" id="phone" placeholder="📱 أدخل رقم الهاتف" style="width:100%; padding:15px; background:#000; border:2px solid #FFD700; border-radius:10px; margin-bottom:15px; color:#FFD700;">
                        <button onclick="checkPoints()" style="background:#FFD700; color:#000; border:none; padding:15px; width:100%; border-radius:10px; font-weight:bold;">🔍 استعلام عن النقاط</button>
                        <div id="points-result" style="margin-top:20px;"></div>
                    </div>
                </div>

                <!-- قسم المنتجات -->
                <div id="products-section" class="section">
                    <div class="filters">
                        <select id="category-filter" onchange="loadProducts()"></select>
                        <input type="text" id="search-product" placeholder="🔍 بحث..." onkeyup="loadProducts()">
                    </div>
                    <div style="margin-bottom:15px;">
                        <button onclick="startScanner()" style="background:#FFD700; color:#000; border:none; padding:12px; border-radius:8px;">📷 مسح باركود</button>
                    </div>
                    <div id="scanner-container" style="display:none;"></div>
                    <div id="products-result" class="products-grid"></div>
                </div>

                <!-- قسم العروض -->
                <div id="offers-section" class="section">
                    <div id="offers-result"></div>
                </div>
            </div>

            <!-- سلة التسوق -->
            <div class="cart-sidebar">
                <div class="cart-header">
                    <h3>🛒 سلة المشتريات</h3>
                    <button class="clear-cart-btn" onclick="clearCart()">تفريغ</button>
                </div>
                <div id="cart-items" class="cart-items"></div>
                <div id="cart-total" class="cart-total">الإجمالي: 0 ريال</div>
                <button class="whatsapp-btn" onclick="openCustomerModal()">
                    <img src="https://img.icons8.com/color/24/whatsapp--v1.png"> إرسال الطلب
                </button>
            </div>
        </div>

        <!-- نافذة بيانات العميل وطرق الدفع -->
        <div id="customerModal" class="modal">
            <div class="modal-content">
                <h3>📋 بيانات العميل والدفع</h3>
                <input type="text" id="customerName" placeholder="الاسم الكامل *" required>
                <input type="tel" id="customerPhone" placeholder="رقم الهاتف *" required>
                <input type="text" id="customerAddress" placeholder="العنوان (اختياري)">
                <select id="paymentMethod">
                    <option value="نقدي">💵 نقدي</option>
                    <option value="أجل">📅 أجل</option>
                    <option value="القطيبي">🏦 القطيبي (رقم 108058)</option>
                </select>
                <input type="text" id="accountNumber" placeholder="رقم الحساب (إذا كان التحويل)" value="">
                <textarea id="notes" placeholder="ملاحظات"></textarea>
                <div class="modal-buttons">
                    <button class="btn-confirm" onclick="submitOrder()">تأكيد</button>
                    <button class="btn-cancel" onclick="closeCustomerModal()">إلغاء</button>
                </div>
            </div>
        </div>

        <script>
            let cart = JSON.parse(localStorage.getItem('cart')) || [];

            function showSection(sectionId) {
                document.querySelectorAll('.nav button').forEach(b=>b.classList.remove('active'));
                event.target.classList.add('active');
                document.querySelectorAll('.section').forEach(s=>s.classList.remove('active'));
                document.getElementById(sectionId+'-section').classList.add('active');
                if(sectionId=='products') loadProducts();
                if(sectionId=='offers') loadOffers();
            }

            function loadCategories() {
                fetch('/categories').then(r=>r.json()).then(data=>{
                    let html = '<option value="">جميع الفئات</option>';
                    data.forEach(c=> html+=`<option value="${c.id}">${c.name}</option>`);
                    document.getElementById('category-filter').innerHTML = html;
                });
            }

            function loadProducts() {
                const cat = document.getElementById('category-filter').value;
                const search = document.getElementById('search-product').value;
                fetch(`/products?category_id=${cat}&search=${encodeURIComponent(search)}`)
                    .then(r=>r.json())
                    .then(data=>{
                        let html='';
                        data.products.forEach(p=>{
                            html+=`
                                <div class="product-card">
                                    <img src="${p.image}" alt="${p.name}">
                                    <div class="product-name">${p.name}</div>
                                    <div class="product-price">${p.price} ريال</div>
                                    <div class="product-stock">${p.quantity} ${p.unit}</div>
                                    <button class="add-to-cart-btn" onclick="addToCart(${p.id}, '${p.name}', ${p.price})">➕ أضف</button>
                                </div>
                            `;
                        });
                        document.getElementById('products-result').innerHTML = html || '<p style="color:#FFD700;">لا توجد منتجات</p>';
                    });
            }

            function addToCart(id, name, price) {
                let found = cart.find(item=>item.id==id);
                if(found) found.quantity++;
                else cart.push({id, name, price, quantity:1});
                updateCart();
            }

            function removeFromCart(id) {
                cart = cart.filter(item=>item.id!=id);
                updateCart();
            }

            function updateCart() {
                let html='', total=0;
                cart.forEach(item=>{
                    let itemTotal = item.price*item.quantity;
                    total+=itemTotal;
                    html+=`
                        <div class="cart-item">
                            <div>${item.name} x${item.quantity}</div>
                            <div>${itemTotal} ريال <button onclick="removeFromCart(${item.id})" style="background:none; border:none; color:#FFD700;">🗑️</button></div>
                        </div>
                    `;
                });
                document.getElementById('cart-items').innerHTML = html || '<p style="color:#FFD700;">السلة فارغة</p>';
                document.getElementById('cart-total').innerText = `الإجمالي: ${total} ريال`;
                localStorage.setItem('cart', JSON.stringify(cart));
            }

            function clearCart() { cart=[]; updateCart(); }

            // مسح الباركود
            function startScanner() {
                document.getElementById('scanner-container').style.display = 'block';
                Quagga.init({
                    inputStream : { name : "Live", type : "LiveStream", target: document.querySelector('#scanner-container') },
                    decoder : { readers : ["ean_reader", "code_128_reader"] }
                }, function(err) {
                    if (err) { console.log(err); return; }
                    Quagga.start();
                });
                Quagga.onDetected(function(data) {
                    let code = data.codeResult.code;
                    Quagga.stop();
                    document.getElementById('scanner-container').style.display = 'none';
                    fetch(`/product_by_barcode/${code}`)
                        .then(r=>r.json())
                        .then(p=>{
                            if(p.success) addToCart(p.id, p.name, p.price);
                            else alert('المنتج غير موجود');
                        });
                });
            }

            function openCustomerModal() {
                if(cart.length==0) { alert('السلة فارغة'); return; }
                document.getElementById('customerModal').style.display = 'flex';
            }
            function closeCustomerModal() { document.getElementById('customerModal').style.display = 'none'; }

            function submitOrder() {
                let name = document.getElementById('customerName').value.trim();
                let phone = document.getElementById('customerPhone').value.trim();
                if(!name || !phone) { alert('الاسم ورقم الهاتف مطلوبان'); return; }
                let address = document.getElementById('customerAddress').value.trim();
                let method = document.getElementById('paymentMethod').value;
                let account = document.getElementById('accountNumber').value.trim();
                let notes = document.getElementById('notes').value.trim();

                let total = cart.reduce((acc,item)=> acc + item.price*item.quantity, 0);
                let message = `*🧾 فاتورة - سوبر ماركت اولاد قايد محمد*%0A`;
                message += `👤 *العميل:* ${name}%0A📱 ${phone}%0A`;
                if(address) message += `📍 ${address}%0A`;
                message += `💳 *طريقة الدفع:* ${method}`;
                if(method=='القطيبي') message += ` (رقم 108058)`;
                message += `%0A📝 ملاحظات: ${notes || '---'}%0A`;
                message += `-----------------------%0A`;
                cart.forEach(item=>{
                    let sub = item.price * item.quantity;
                    message += `${item.name} (${item.price}ريال) ×${item.quantity} = ${sub}ريال%0A`;
                });
                message += `-----------------------%0A*الإجمالي: ${total} ريال*%0Aشكراً لتسوقكم`;

                window.open(`https://wa.me/967771602370?text=${message}`, '_blank');

                // حفظ الفاتورة في قاعدة البيانات
                fetch('/save_sale', {
                    method:'POST',
                    headers:{'Content-Type':'application/json'},
                    body: JSON.stringify({
                        customer_name: name,
                        customer_phone: phone,
                        customer_address: address,
                        payment_method: method,
                        account_number: account,
                        notes: notes,
                        total: total,
                        items: cart
                    })
                }).then(r=>r.json()).then(d=> console.log(d));

                closeCustomerModal();
                clearCart();
            }

            function checkPoints() {
                let phone = document.getElementById('phone').value;
                fetch('/check_points', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({phone}) })
                .then(r=>r.json())
                .then(data=>{
                    if(data.success) {
                        document.getElementById('points-result').innerHTML = `
                            <div style="background:#FFD700; color:#000; padding:20px; border-radius:10px;">
                                <h3>👤 ${data.customer.name}</h3>
                                <h1 style="font-size:48px;">${data.customer.points} ⭐</h1>
                                <p>💰 الإنفاق: ${data.customer.total_spent} ريال</p>
                                <p>🛒 الزيارات: ${data.customer.visits}</p>
                                <p>🏆 المستوى: ${data.customer.tier}</p>
                            </div>
                        `;
                    } else {
                        document.getElementById('points-result').innerHTML = '<p style="color:#ff6b6b;">رقم غير مسجل</p>';
                    }
                });
            }

            function loadOffers() {
                fetch('/offers').then(r=>r.json()).then(data=>{
                    let html='';
                    data.offers.forEach(o=>{
                        html+=`<div class="offer-card" style="background:#111; border:1px solid #FFD700; border-radius:10px; padding:15px; margin-bottom:10px;">${o.title}<br><small>${o.description}</small></div>`;
                    });
                    document.getElementById('offers-result').innerHTML=html;
                });
            }

            window.onload = function() {
                updateCart();
                loadCategories();
                loadProducts();
                loadOffers();
            };
        </script>
    </body>
    </html>
    ''')

# ========================== واجهات API للعميل ==========================
@app.route('/categories')
def get_categories():
    conn = get_db_connection()
    cur = conn.cursor()
    if DATABASE_URL:
        cur.execute("SELECT id, name FROM categories ORDER BY name")
    else:
        cur.execute("SELECT id, name FROM categories ORDER BY name")
    cats = [{'id':r['id'], 'name':r['name']} for r in cur.fetchall()]
    cur.close()
    conn.close()
    return jsonify(cats)

@app.route('/products')
def get_products():
    category_id = request.args.get('category_id', '')
    search = request.args.get('search', '')
    conn = get_db_connection()
    cur = conn.cursor()
    if DATABASE_URL:
        query = "SELECT id, name, price, quantity, unit, image_path FROM products WHERE is_active=1"
        params = []
        if category_id:
            query += " AND category_id = %s"
            params.append(category_id)
        if search:
            query += " AND name ILIKE %s"
            params.append(f'%{search}%')
        query += " ORDER BY name"
        cur.execute(query, params)
    else:
        query = "SELECT id, name, price, quantity, unit, image_path FROM products WHERE is_active=1"
        params = []
        if category_id:
            query += " AND category_id = ?"
            params.append(category_id)
        if search:
            query += " AND name LIKE ?"
            params.append(f'%{search}%')
        query += " ORDER BY name"
        cur.execute(query, params)
    products = []
    for row in cur.fetchall():
        products.append({
            'id': row['id'],
            'name': row['name'],
            'price': row['price'],
            'quantity': row['quantity'],
            'unit': row['unit'],
            'image': url_for('static', filename=f'uploads/{row["image_path"]}') if row['image_path'] else url_for('static', filename='default.png')
        })
    cur.close()
    conn.close()
    return jsonify({'products': products})

@app.route('/product_by_barcode/<barcode>')
def product_by_barcode(barcode):
    conn = get_db_connection()
    cur = conn.cursor()
    if DATABASE_URL:
        cur.execute("SELECT id, name, price FROM products WHERE barcode=%s AND is_active=1", (barcode,))
    else:
        cur.execute("SELECT id, name, price FROM products WHERE barcode=? AND is_active=1", (barcode,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row:
        return jsonify({'success': True, 'id': row['id'], 'name': row['name'], 'price': row['price']})
    else:
        return jsonify({'success': False})

@app.route('/check_points', methods=['POST'])
def check_points():
    phone = request.json.get('phone')
    conn = get_db_connection()
    cur = conn.cursor()
    if DATABASE_URL:
        cur.execute("SELECT name, loyalty_points, total_spent, visits, customer_tier FROM customers WHERE phone=%s AND is_active=1", (phone,))
    else:
        cur.execute("SELECT name, loyalty_points, total_spent, visits, customer_tier FROM customers WHERE phone=? AND is_active=1", (phone,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row:
        return jsonify({'success': True, 'customer': {
            'name': row['name'],
            'points': row['loyalty_points'],
            'total_spent': row['total_spent'],
            'visits': row['visits'],
            'tier': row['customer_tier']
        }})
    else:
        return jsonify({'success': False, 'message': 'رقم غير مسجل'})

@app.route('/offers')
def get_offers():
    offers = [
        {'title': 'خصم 5%', 'description': 'على المشتريات فوق 100 ريال'},
        {'title': 'توصيل مجاني', 'description': 'للطلبات فوق 200 ريال'},
        {'title': 'هدية', 'description': 'مع كل 3 منتجات من القسم نفسه'}
    ]
    return jsonify({'offers': offers})

@app.route('/save_sale', methods=['POST'])
def save_sale():
    data = request.json
    conn = get_db_connection()
    cur = conn.cursor()
    sale_date = datetime.datetime.now().isoformat()
    user = current_user.username if current_user.is_authenticated else 'customer'
    if DATABASE_URL:
        cur.execute("""
            INSERT INTO sales (customer_name, customer_phone, customer_address, payment_method,
            account_number, notes, total, sale_date, user)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
        """, (data['customer_name'], data['customer_phone'], data['customer_address'],
              data['payment_method'], data.get('account_number',''), data.get('notes',''),
              data['total'], sale_date, user))
        sale_id = cur.fetchone()['id']
    else:
        cur.execute("""
            INSERT INTO sales (customer_name, customer_phone, customer_address, payment_method,
            account_number, notes, total, sale_date, user)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (data['customer_name'], data['customer_phone'], data['customer_address'],
              data['payment_method'], data.get('account_number',''), data.get('notes',''),
              data['total'], sale_date, user))
        sale_id = cur.lastrowid
    for item in data['items']:
        if DATABASE_URL:
            cur.execute("""
                INSERT INTO sale_items (sale_id, product_id, product_name, price, quantity, total)
                VALUES (%s,%s,%s,%s,%s,%s)
            """, (sale_id, item['id'], item['name'], item['price'], item['quantity'], item['price']*item['quantity']))
        else:
            cur.execute("""
                INSERT INTO sale_items (sale_id, product_id, product_name, price, quantity, total)
                VALUES (?,?,?,?,?,?)
            """, (sale_id, item['id'], item['name'], item['price'], item['quantity'], item['price']*item['quantity']))
        # تحديث المخزون
        if DATABASE_URL:
            cur.execute("UPDATE products SET quantity = quantity - %s WHERE id = %s", (item['quantity'], item['id']))
        else:
            cur.execute("UPDATE products SET quantity = quantity - ? WHERE id = ?", (item['quantity'], item['id']))
    conn.commit()
    cur.close()
    conn.close()
    log_activity('إضافة فاتورة', 'sale', sale_id, f'فاتورة بمبلغ {data["total"]}')
    return jsonify({'success': True})

# ========================== نظام الدخول ==========================
@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = get_db_connection()
        cur = conn.cursor()
        if DATABASE_URL:
            cur.execute("SELECT id, username, password_hash FROM users WHERE username = %s", (username,))
        else:
            cur.execute("SELECT id, username, password_hash FROM users WHERE username = ?", (username,))
        user = cur.fetchone()
        cur.close()
        conn.close()
        if user and check_password_hash(user['password_hash'], password):
            user_obj = User(user['id'], user['username'])
            login_user(user_obj)
            return redirect(url_for('admin_dashboard'))
        else:
            return render_template_string('''
            <!DOCTYPE html><html dir="rtl"><head><title>تسجيل الدخول</title>
            <style>body{background:#000;display:flex;justify-content:center;align-items:center;height:100vh;}
            .login-box{background:#111;padding:30px;border-radius:15px;border:2px solid #FFD700;color:#FFD700;width:300px;}
            input{width:100%;padding:12px;margin:10px 0;background:#000;border:1px solid #FFD700;color:#FFD700;border-radius:8px;}
            button{width:100%;padding:12px;background:#FFD700;color:#000;border:none;border-radius:8px;font-weight:bold;}
            .error{color:#ff6b6b;text-align:center;}</style></head>
            <body><div class="login-box"><h2>🔐 تسجيل الدخول</h2>
            <form method="POST"><input type="text" name="username" placeholder="اسم المستخدم" required>
            <input type="password" name="password" placeholder="كلمة المرور" required>
            <button type="submit">دخول</button></form><div class="error">بيانات غير صحيحة</div></div></body></html>
            ''')
    return render_template_string('''
    <!DOCTYPE html><html dir="rtl"><head><title>تسجيل الدخول</title>
    <style>body{background:#000;display:flex;justify-content:center;align-items:center;height:100vh;}
    .login-box{background:#111;padding:30px;border-radius:15px;border:2px solid #FFD700;color:#FFD700;width:300px;}
    input{width:100%;padding:12px;margin:10px 0;background:#000;border:1px solid #FFD700;color:#FFD700;border-radius:8px;}
    button{width:100%;padding:12px;background:#FFD700;color:#000;border:none;border-radius:8px;font-weight:bold;}</style></head>
    <body><div class="login-box"><h2>🔐 تسجيل الدخول</h2>
    <form method="POST"><input type="text" name="username" placeholder="اسم المستخدم" required>
    <input type="password" name="password" placeholder="كلمة المرور" required>
    <button type="submit">دخول</button></form></div></body></html>
    ''')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))

# ========================== لوحة تحكم الإدارة (محمية) ==========================
@app.route('/admin')
@login_required
def admin_dashboard():
    return render_template_string('''
    <!DOCTYPE html><html dir="rtl"><head><title>لوحة التحكم</title>
    <style>
        * { margin:0; padding:0; box-sizing:border-box; }
        body { background:#000; padding:20px; font-family:Arial; }
        .header { background:#111; color:#FFD700; padding:20px; border-radius:10px; margin-bottom:20px; border:1px solid #FFD700; display:flex; justify-content:space-between; align-items:center; }
        .dashboard-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(250px,1fr)); gap:20px; }
        .card { background:#111; padding:30px; border-radius:15px; border:1px solid #FFD700; color:#FFD700; text-align:center; cursor:pointer; transition:0.3s; }
        .card:hover { transform:translateY(-5px); box-shadow:0 10px 20px rgba(255,215,0,0.3); }
        .card-icon { font-size:48px; margin-bottom:15px; }
        .logout-btn { background:#FFD700; color:#000; padding:10px 20px; border-radius:8px; text-decoration:none; font-weight:bold; }
    </style>
    </head>
    <body>
        <div class="header">
            <h1>🎛️ لوحة التحكم - مرحباً {{ current_user.username }}</h1>
            <a href="/logout" class="logout-btn">تسجيل خروج</a>
        </div>
        <div class="dashboard-grid">
            <div class="card" onclick="location.href='/admin/products'">
                <div class="card-icon">📦</div>
                <h3>إدارة المنتجات</h3>
            </div>
            <div class="card" onclick="location.href='/admin/categories'">
                <div class="card-icon">🏷️</div>
                <h3>إدارة الفئات</h3>
            </div>
            <div class="card" onclick="location.href='/admin/customers'">
                <div class="card-icon">👥</div>
                <h3>العملاء</h3>
            </div>
            <div class="card" onclick="location.href='/admin/sales'">
                <div class="card-icon">🧾</div>
                <h3>الفواتير</h3>
            </div>
            <div class="card" onclick="location.href='/admin/expenses'">
                <div class="card-icon">💰</div>
                <h3>المصروفات</h3>
            </div>
            <div class="card" onclick="location.href='/admin/stats'">
                <div class="card-icon">📊</div>
                <h3>الإحصائيات</h3>
            </div>
        </div>
    </body></html>
    ''', current_user=current_user)

# ========================== إدارة المنتجات (محمية) ==========================
@app.route('/admin/products')
@login_required
def admin_products():
    conn = get_db_connection()
    cur = conn.cursor()
    if DATABASE_URL:
        cur.execute("""
            SELECT p.*, c.name as category_name FROM products p
            LEFT JOIN categories c ON p.category_id = c.id
            WHERE p.is_active=1 ORDER BY p.name
        """)
    else:
        cur.execute("""
            SELECT p.*, c.name as category_name FROM products p
            LEFT JOIN categories c ON p.category_id = c.id
            WHERE p.is_active=1 ORDER BY p.name
        """)
    products = cur.fetchall()
    cur.close()
    conn.close()
    return render_template_string('''
    <!DOCTYPE html><html dir="rtl"><head><title>إدارة المنتجات</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box;font-family:Arial;}
        body{background:#000;padding:20px;color:#FFD700;}
        .header{background:#111;padding:20px;border-radius:10px;border:1px solid #FFD700;margin-bottom:20px;display:flex;justify-content:space-between;}
        table{width:100%;background:#111;border-radius:10px;border:1px solid #FFD700;border-collapse:collapse;}
        th{background:#FFD700;color:#000;padding:12px;}
        td{padding:10px;border-bottom:1px solid #FFD700;}
        img{width:50px;height:50px;object-fit:cover;border-radius:5px;}
        .btn{background:#FFD700;color:#000;padding:8px 15px;border-radius:5px;text-decoration:none;margin:2px;display:inline-block;}
        .btn-danger{background:#ff4444;color:white;}
        .add-btn{margin-bottom:15px;}
    </style>
    </head>
    <body>
        <div class="header">
            <h1>📦 إدارة المنتجات</h1>
            <a href="/admin" class="btn">العودة</a>
        </div>
        <div class="add-btn">
            <a href="/admin/products/add" class="btn">➕ إضافة منتج جديد</a>
        </div>
        <table>
            <thead><tr><th>الصورة</th><th>الباركود</th><th>الاسم</th><th>الفئة</th><th>السعر</th><th>التكلفة</th><th>الكمية</th><th>الوحدة</th><th>الإجراءات</th></tr></thead>
            <tbody>
                {% for p in products %}
                <tr>
                    <td><img src="{{ url_for('static', filename='uploads/'+p.image_path) if p.image_path else url_for('static', filename='default.png') }}"></td>
                    <td>{{ p.barcode }}</td>
                    <td>{{ p.name }}</td>
                    <td>{{ p.category_name }}</td>
                    <td>{{ p.price }}</td>
                    <td>{{ p.cost_price }}</td>
                    <td>{{ p.quantity }}</td>
                    <td>{{ p.unit }}</td>
                    <td>
                        <a href="/admin/products/edit/{{ p.id }}" class="btn">✏️</a>
                        <a href="/admin/products/delete/{{ p.id }}" class="btn btn-danger" onclick="return confirm('تأكيد الحذف؟')">🗑️</a>
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </body></html>
    ''', products=products)

@app.route('/admin/products/add', methods=['GET','POST'])
@login_required
def admin_add_product():
    if request.method == 'GET':
        conn = get_db_connection()
        cur = conn.cursor()
        if DATABASE_URL:
            cur.execute("SELECT id, name FROM categories ORDER BY name")
        else:
            cur.execute("SELECT id, name FROM categories ORDER BY name")
        cats = cur.fetchall()
        cur.close()
        conn.close()
        return render_template_string('''
        <!DOCTYPE html><html dir="rtl"><head><title>إضافة منتج</title>
        <style>
            *{margin:0;padding:0;box-sizing:border-box;}
            body{background:#000;padding:20px;color:#FFD700;font-family:Arial;}
            .form-container{background:#111;padding:30px;border-radius:15px;border:1px solid #FFD700;max-width:600px;margin:auto;}
            label{display:block;margin-bottom:5px;margin-top:15px;}
            input,select,textarea{width:100%;padding:10px;background:#000;border:1px solid #FFD700;color:#FFD700;border-radius:5px;}
            .btn{background:#FFD700;color:#000;padding:12px 25px;border:none;border-radius:8px;font-weight:bold;cursor:pointer;margin-top:20px;}
        </style>
        </head>
        <body>
            <div class="form-container">
                <h2>➕ إضافة منتج جديد</h2>
                <form method="POST" enctype="multipart/form-data">
                    <label>الباركود</label>
                    <input type="text" name="barcode" required>
                    <label>الاسم</label>
                    <input type="text" name="name" required>
                    <label>الفئة</label>
                    <select name="category_id">
                        {% for c in cats %}
                        <option value="{{ c.id }}">{{ c.name }}</option>
                        {% endfor %}
                    </select>
                    <label>سعر البيع</label>
                    <input type="number" step="0.01" name="price" required>
                    <label>سعر التكلفة</label>
                    <input type="number" step="0.01" name="cost_price" value="0">
                    <label>الكمية</label>
                    <input type="number" name="quantity" required>
                    <label>الحد الأدنى</label>
                    <input type="number" name="min_quantity" value="10">
                    <label>الوحدة</label>
                    <input type="text" name="unit" value="قطعة">
                    <label>المورد</label>
                    <input type="text" name="supplier">
                    <label>تاريخ الانتهاء</label>
                    <input type="date" name="expiry_date">
                    <label>صورة المنتج</label>
                    <input type="file" name="image" accept="image/*">
                    <button type="submit" class="btn">💾 حفظ المنتج</button>
                </form>
                <a href="/admin/products" class="btn" style="display:block;text-align:center;margin-top:10px;">إلغاء</a>
            </div>
        </body></html>
        ''', cats=cats)
    else:
        # معالجة POST
        barcode = request.form['barcode']
        name = request.form['name']
        category_id = request.form['category_id']
        price = float(request.form['price'])
        cost_price = float(request.form.get('cost_price', 0))
        quantity = int(request.form['quantity'])
        min_quantity = int(request.form.get('min_quantity', 10))
        unit = request.form.get('unit', 'قطعة')
        supplier = request.form.get('supplier', '')
        expiry_date = request.form.get('expiry_date', '')
        image = request.files.get('image')
        image_filename = ''
        if image and allowed_file(image.filename):
            filename = secure_filename(image.filename)
            timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            image_filename = f"{timestamp}_{filename}"
            image.save(os.path.join(app.config['UPLOAD_FOLDER'], image_filename))

        today = datetime.date.today().isoformat()
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            if DATABASE_URL:
                cur.execute("""
                    INSERT INTO products (barcode, name, category_id, price, cost_price, quantity, min_quantity,
                                          unit, supplier, expiry_date, added_date, last_updated, image_path)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, (barcode, name, category_id, price, cost_price, quantity, min_quantity,
                      unit, supplier, expiry_date, today, today, image_filename))
            else:
                cur.execute("""
                    INSERT INTO products (barcode, name, category_id, price, cost_price, quantity, min_quantity,
                                          unit, supplier, expiry_date, added_date, last_updated, image_path)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (barcode, name, category_id, price, cost_price, quantity, min_quantity,
                      unit, supplier, expiry_date, today, today, image_filename))
            conn.commit()
            log_activity('إضافة منتج', 'product', cur.lastrowid, name)
        except Exception as e:
            conn.rollback()
            return f"خطأ: {str(e)}"
        finally:
            cur.close()
            conn.close()
        return redirect(url_for('admin_products'))

@app.route('/admin/products/edit/<int:pid>', methods=['GET','POST'])
@login_required
def admin_edit_product(pid):
    conn = get_db_connection()
    cur = conn.cursor()
    if request.method == 'GET':
        if DATABASE_URL:
            cur.execute("SELECT * FROM products WHERE id=%s", (pid,))
        else:
            cur.execute("SELECT * FROM products WHERE id=?", (pid,))
        product = cur.fetchone()
        cur.execute("SELECT id, name FROM categories ORDER BY name")
        cats = cur.fetchall()
        cur.close()
        conn.close()
        if not product:
            return "المنتج غير موجود"
        return render_template_string('''
        <!DOCTYPE html><html dir="rtl"><head><title>تعديل منتج</title>
        <style>
            *{margin:0;padding:0;box-sizing:border-box;}
            body{background:#000;padding:20px;color:#FFD700;font-family:Arial;}
            .form-container{background:#111;padding:30px;border-radius:15px;border:1px solid #FFD700;max-width:600px;margin:auto;}
            label{display:block;margin-bottom:5px;margin-top:15px;}
            input,select,textarea{width:100%;padding:10px;background:#000;border:1px solid #FFD700;color:#FFD700;border-radius:5px;}
            .btn{background:#FFD700;color:#000;padding:12px 25px;border:none;border-radius:8px;font-weight:bold;cursor:pointer;margin-top:20px;}
        </style>
        </head>
        <body>
            <div class="form-container">
                <h2>✏️ تعديل المنتج</h2>
                <form method="POST" enctype="multipart/form-data">
                    <label>الباركود</label>
                    <input type="text" name="barcode" value="{{ product.barcode }}" required>
                    <label>الاسم</label>
                    <input type="text" name="name" value="{{ product.name }}" required>
                    <label>الفئة</label>
                    <select name="category_id">
                        {% for c in cats %}
                        <option value="{{ c.id }}" {% if c.id == product.category_id %}selected{% endif %}>{{ c.name }}</option>
                        {% endfor %}
                    </select>
                    <label>سعر البيع</label>
                    <input type="number" step="0.01" name="price" value="{{ product.price }}" required>
                    <label>سعر التكلفة</label>
                    <input type="number" step="0.01" name="cost_price" value="{{ product.cost_price }}">
                    <label>الكمية</label>
                    <input type="number" name="quantity" value="{{ product.quantity }}" required>
                    <label>الحد الأدنى</label>
                    <input type="number" name="min_quantity" value="{{ product.min_quantity }}">
                    <label>الوحدة</label>
                    <input type="text" name="unit" value="{{ product.unit }}">
                    <label>المورد</label>
                    <input type="text" name="supplier" value="{{ product.supplier }}">
                    <label>تاريخ الانتهاء</label>
                    <input type="date" name="expiry_date" value="{{ product.expiry_date }}">
                    <label>تغيير الصورة (اختياري)</label>
                    <input type="file" name="image" accept="image/*">
                    <button type="submit" class="btn">💾 حفظ التغييرات</button>
                </form>
                <a href="/admin/products" class="btn" style="display:block;text-align:center;margin-top:10px;">إلغاء</a>
            </div>
        </body></html>
        ''', product=product, cats=cats)
    else:
        # POST: تحديث
        barcode = request.form['barcode']
        name = request.form['name']
        category_id = request.form['category_id']
        price = float(request.form['price'])
        cost_price = float(request.form.get('cost_price', 0))
        quantity = int(request.form['quantity'])
        min_quantity = int(request.form.get('min_quantity', 10))
        unit = request.form.get('unit', 'قطعة')
        supplier = request.form.get('supplier', '')
        expiry_date = request.form.get('expiry_date', '')
        image = request.files.get('image')
        today = datetime.date.today().isoformat()

        # الحصول على الصورة القديمة
        if DATABASE_URL:
            cur.execute("SELECT image_path FROM products WHERE id=%s", (pid,))
        else:
            cur.execute("SELECT image_path FROM products WHERE id=?", (pid,))
        old_image = cur.fetchone()['image_path']

        image_filename = old_image
        if image and allowed_file(image.filename):
            filename = secure_filename(image.filename)
            timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            image_filename = f"{timestamp}_{filename}"
            image.save(os.path.join(app.config['UPLOAD_FOLDER'], image_filename))
            # حذف القديم إذا كان موجودًا
            if old_image:
                old_path = os.path.join(app.config['UPLOAD_FOLDER'], old_image)
                if os.path.exists(old_path):
                    os.remove(old_path)

        if DATABASE_URL:
            cur.execute("""
                UPDATE products SET barcode=%s, name=%s, category_id=%s, price=%s, cost_price=%s,
                quantity=%s, min_quantity=%s, unit=%s, supplier=%s, expiry_date=%s,
                last_updated=%s, image_path=%s WHERE id=%s
            """, (barcode, name, category_id, price, cost_price, quantity, min_quantity,
                  unit, supplier, expiry_date, today, image_filename, pid))
        else:
            cur.execute("""
                UPDATE products SET barcode=?, name=?, category_id=?, price=?, cost_price=?,
                quantity=?, min_quantity=?, unit=?, supplier=?, expiry_date=?,
                last_updated=?, image_path=? WHERE id=?
            """, (barcode, name, category_id, price, cost_price, quantity, min_quantity,
                  unit, supplier, expiry_date, today, image_filename, pid))
        conn.commit()
        log_activity('تعديل منتج', 'product', pid, name)
        cur.close()
        conn.close()
        return redirect(url_for('admin_products'))

@app.route('/admin/products/delete/<int:pid>')
@login_required
def admin_delete_product(pid):
    conn = get_db_connection()
    cur = conn.cursor()
    # حذف منطقي (is_active=0) أو حذف الصورة أيضاً
    if DATABASE_URL:
        cur.execute("SELECT image_path, name FROM products WHERE id=%s", (pid,))
    else:
        cur.execute("SELECT image_path, name FROM products WHERE id=?", (pid,))
    prod = cur.fetchone()
    if prod and prod['image_path']:
        img_path = os.path.join(app.config['UPLOAD_FOLDER'], prod['image_path'])
        if os.path.exists(img_path):
            os.remove(img_path)
    if DATABASE_URL:
        cur.execute("UPDATE products SET is_active=0 WHERE id=%s", (pid,))
    else:
        cur.execute("UPDATE products SET is_active=0 WHERE id=?", (pid,))
    conn.commit()
    log_activity('حذف منتج', 'product', pid, prod['name'] if prod else '')
    cur.close()
    conn.close()
    return redirect(url_for('admin_products'))

# ========================== إدارة الفئات ==========================
@app.route('/admin/categories')
@login_required
def admin_categories():
    conn = get_db_connection()
    cur = conn.cursor()
    if DATABASE_URL:
        cur.execute("SELECT * FROM categories ORDER BY name")
    else:
        cur.execute("SELECT * FROM categories ORDER BY name")
    cats = cur.fetchall()
    cur.close()
    conn.close()
    return render_template_string('''
    <!DOCTYPE html><html dir="rtl"><head><title>إدارة الفئات</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box;}
        body{background:#000;padding:20px;color:#FFD700;font-family:Arial;}
        .header{background:#111;padding:20px;border-radius:10px;border:1px solid #FFD700;margin-bottom:20px;display:flex;justify-content:space-between;}
        table{width:100%;background:#111;border-radius:10px;border:1px solid #FFD700;border-collapse:collapse;}
        th{background:#FFD700;color:#000;padding:12px;}
        td{padding:10px;border-bottom:1px solid #FFD700;}
        .btn{background:#FFD700;color:#000;padding:8px 15px;border-radius:5px;text-decoration:none;margin:2px;display:inline-block;}
        .add-btn{margin-bottom:15px;}
        .form-inline{display:flex;gap:10px;margin-bottom:20px;}
        .form-inline input{flex:1;padding:10px;background:#000;border:1px solid #FFD700;color:#FFD700;border-radius:5px;}
    </style>
    </head>
    <body>
        <div class="header">
            <h1>🏷️ إدارة الفئات</h1>
            <a href="/admin" class="btn">العودة</a>
        </div>
        <div class="form-inline">
            <form method="POST" action="/admin/categories/add" style="display:flex; width:100%; gap:10px;">
                <input type="text" name="name" placeholder="اسم الفئة الجديدة" required>
                <button type="submit" class="btn">➕ إضافة</button>
            </form>
        </div>
        <table>
            <thead><tr><th>الرقم</th><th>اسم الفئة</th><th>الإجراءات</th></tr></thead>
            <tbody>
                {% for c in cats %}
                <tr>
                    <td>{{ c.id }}</td>
                    <td>{{ c.name }}</td>
                    <td>
                        <a href="/admin/categories/edit/{{ c.id }}" class="btn">✏️</a>
                        <a href="/admin/categories/delete/{{ c.id }}" class="btn btn-danger" onclick="return confirm('تأكيد الحذف؟')">🗑️</a>
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </body></html>
    ''', cats=cats)

@app.route('/admin/categories/add', methods=['POST'])
@login_required
def admin_add_category():
    name = request.form['name']
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        if DATABASE_URL:
            cur.execute("INSERT INTO categories (name) VALUES (%s)", (name,))
        else:
            cur.execute("INSERT INTO categories (name) VALUES (?)", (name,))
        conn.commit()
        log_activity('إضافة فئة', 'category', cur.lastrowid, name)
    except Exception as e:
        conn.rollback()
    finally:
        cur.close()
        conn.close()
    return redirect(url_for('admin_categories'))

@app.route('/admin/categories/edit/<int:cid>', methods=['GET','POST'])
@login_required
def admin_edit_category(cid):
    conn = get_db_connection()
    cur = conn.cursor()
    if request.method == 'GET':
        if DATABASE_URL:
            cur.execute("SELECT * FROM categories WHERE id=%s", (cid,))
        else:
            cur.execute("SELECT * FROM categories WHERE id=?", (cid,))
        cat = cur.fetchone()
        cur.close()
        conn.close()
        return render_template_string('''
        <!DOCTYPE html><html dir="rtl"><head><title>تعديل فئة</title>
        <style>
            *{margin:0;padding:0;box-sizing:border-box;}
            body{background:#000;padding:20px;color:#FFD700;font-family:Arial;}
            .form-container{background:#111;padding:30px;border-radius:15px;border:1px solid #FFD700;max-width:400px;margin:auto;}
            input{width:100%;padding:10px;margin:10px 0;background:#000;border:1px solid #FFD700;color:#FFD700;border-radius:5px;}
            .btn{background:#FFD700;color:#000;padding:12px 25px;border:none;border-radius:8px;cursor:pointer;}
        </style>
        </head>
        <body>
            <div class="form-container">
                <h2>✏️ تعديل الفئة</h2>
                <form method="POST">
                    <input type="text" name="name" value="{{ cat.name }}" required>
                    <button type="submit" class="btn">💾 حفظ</button>
                </form>
                <a href="/admin/categories" class="btn" style="display:block;text-align:center;margin-top:10px;">إلغاء</a>
            </div>
        </body></html>
        ''', cat=cat)
    else:
        name = request.form['name']
        if DATABASE_URL:
            cur.execute("UPDATE categories SET name=%s WHERE id=%s", (name, cid))
        else:
            cur.execute("UPDATE categories SET name=? WHERE id=?", (name, cid))
        conn.commit()
        log_activity('تعديل فئة', 'category', cid, name)
        cur.close()
        conn.close()
        return redirect(url_for('admin_categories'))

@app.route('/admin/categories/delete/<int:cid>')
@login_required
def admin_delete_category(cid):
    conn = get_db_connection()
    cur = conn.cursor()
    # التحقق من عدم وجود منتجات مرتبطة
    if DATABASE_URL:
        cur.execute("SELECT COUNT(*) FROM products WHERE category_id=%s AND is_active=1", (cid,))
    else:
        cur.execute("SELECT COUNT(*) FROM products WHERE category_id=? AND is_active=1", (cid,))
    count = cur.fetchone()[0]
    if count > 0:
        cur.close()
        conn.close()
        return "لا يمكن حذف الفئة لأنها تحتوي على منتجات. قم بنقل المنتجات أولاً."
    if DATABASE_URL:
        cur.execute("DELETE FROM categories WHERE id=%s", (cid,))
    else:
        cur.execute("DELETE FROM categories WHERE id=?", (cid,))
    conn.commit()
    log_activity('حذف فئة', 'category', cid)
    cur.close()
    conn.close()
    return redirect(url_for('admin_categories'))

# ========================== إدارة العملاء (مختصرة) ==========================
@app.route('/admin/customers')
@login_required
def admin_customers():
    conn = get_db_connection()
    cur = conn.cursor()
    if DATABASE_URL:
        cur.execute("SELECT * FROM customers WHERE is_active=1 ORDER BY total_spent DESC")
    else:
        cur.execute("SELECT * FROM customers WHERE is_active=1 ORDER BY total_spent DESC")
    customers = cur.fetchall()
    cur.close()
    conn.close()
    return render_template_string('''
    <!DOCTYPE html><html dir="rtl"><head><title>العملاء</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box;}
        body{background:#000;padding:20px;color:#FFD700;font-family:Arial;}
        .header{background:#111;padding:20px;border-radius:10px;border:1px solid #FFD700;margin-bottom:20px;display:flex;justify-content:space-between;}
        table{width:100%;background:#111;border-radius:10px;border:1px solid #FFD700;border-collapse:collapse;}
        th{background:#FFD700;color:#000;padding:12px;}
        td{padding:10px;border-bottom:1px solid #FFD700;}
        .btn{background:#FFD700;color:#000;padding:8px 15px;border-radius:5px;text-decoration:none;}
    </style>
    </head>
    <body>
        <div class="header">
            <h1>👥 العملاء</h1>
            <a href="/admin" class="btn">العودة</a>
        </div>
        <table>
            <thead><tr><th>الاسم</th><th>الهاتف</th><th>النقاط</th><th>الإنفاق</th><th>الزيارات</th><th>آخر زيارة</th><th>المستوى</th></tr></thead>
            <tbody>
                {% for c in customers %}
                <tr>
                    <td>{{ c.name }}</td>
                    <td>{{ c.phone }}</td>
                    <td>{{ c.loyalty_points }}</td>
                    <td>{{ c.total_spent }}</td>
                    <td>{{ c.visits }}</td>
                    <td>{{ c.last_visit }}</td>
                    <td>{{ c.customer_tier }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </body></html>
    ''', customers=customers)

# ========================== إدارة الفواتير ==========================
@app.route('/admin/sales')
@login_required
def admin_sales():
    conn = get_db_connection()
    cur = conn.cursor()
    if DATABASE_URL:
        cur.execute("SELECT * FROM sales ORDER BY sale_date DESC LIMIT 100")
    else:
        cur.execute("SELECT * FROM sales ORDER BY sale_date DESC LIMIT 100")
    sales = cur.fetchall()
    cur.close()
    conn.close()
    return render_template_string('''
    <!DOCTYPE html><html dir="rtl"><head><title>الفواتير</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box;}
        body{background:#000;padding:20px;color:#FFD700;font-family:Arial;}
        .header{background:#111;padding:20px;border-radius:10px;border:1px solid #FFD700;margin-bottom:20px;display:flex;justify-content:space-between;}
        table{width:100%;background:#111;border-radius:10px;border:1px solid #FFD700;border-collapse:collapse;}
        th{background:#FFD700;color:#000;padding:12px;}
        td{padding:10px;border-bottom:1px solid #FFD700;}
        .btn{background:#FFD700;color:#000;padding:8px 15px;border-radius:5px;text-decoration:none;}
    </style>
    </head>
    <body>
        <div class="header">
            <h1>🧾 الفواتير</h1>
            <a href="/admin" class="btn">العودة</a>
        </div>
        <table>
            <thead><tr><th>رقم</th><th>العميل</th><th>الهاتف</th><th>طريقة الدفع</th><th>الإجمالي</th><th>التاريخ</th><th>المستخدم</th></tr></thead>
            <tbody>
                {% for s in sales %}
                <tr>
                    <td>{{ s.id }}</td>
                    <td>{{ s.customer_name }}</td>
                    <td>{{ s.customer_phone }}</td>
                    <td>{{ s.payment_method }}</td>
                    <td>{{ s.total }}</td>
                    <td>{{ s.sale_date }}</td>
                    <td>{{ s.user }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </body></html>
    ''', sales=sales)

# ========================== إدارة المصروفات ==========================
@app.route('/admin/expenses')
@login_required
def admin_expenses():
    conn = get_db_connection()
    cur = conn.cursor()
    if DATABASE_URL:
        cur.execute("SELECT * FROM expenses ORDER BY expense_date DESC")
    else:
        cur.execute("SELECT * FROM expenses ORDER BY expense_date DESC")
    expenses = cur.fetchall()
    cur.close()
    conn.close()
    return render_template_string('''
    <!DOCTYPE html><html dir="rtl"><head><title>المصروفات</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box;}
        body{background:#000;padding:20px;color:#FFD700;font-family:Arial;}
        .header{background:#111;padding:20px;border-radius:10px;border:1px solid #FFD700;margin-bottom:20px;display:flex;justify-content:space-between;}
        .form-inline{display:flex;gap:10px;margin-bottom:20px;}
        .form-inline input{flex:1;padding:10px;background:#000;border:1px solid #FFD700;color:#FFD700;border-radius:5px;}
        table{width:100%;background:#111;border-radius:10px;border:1px solid #FFD700;border-collapse:collapse;}
        th{background:#FFD700;color:#000;padding:12px;}
        td{padding:10px;border-bottom:1px solid #FFD700;}
        .btn{background:#FFD700;color:#000;padding:8px 15px;border-radius:5px;text-decoration:none;}
    </style>
    </head>
    <body>
        <div class="header">
            <h1>💰 المصروفات</h1>
            <a href="/admin" class="btn">العودة</a>
        </div>
        <div class="form-inline">
            <form method="POST" action="/admin/expenses/add" style="display:flex; width:100%; gap:10px;">
                <input type="text" name="description" placeholder="وصف المصروف" required>
                <input type="number" step="0.01" name="amount" placeholder="المبلغ" required>
                <input type="date" name="expense_date" value="{{ today }}">
                <button type="submit" class="btn">➕ إضافة</button>
            </form>
        </div>
        <table>
            <thead><tr><th>الوصف</th><th>المبلغ</th><th>التاريخ</th><th>المستخدم</th><th>الإجراءات</th></tr></thead>
            <tbody>
                {% for e in expenses %}
                <tr>
                    <td>{{ e.description }}</td>
                    <td>{{ e.amount }}</td>
                    <td>{{ e.expense_date }}</td>
                    <td>{{ e.user }}</td>
                    <td><a href="/admin/expenses/delete/{{ e.id }}" class="btn" onclick="return confirm('حذف؟')">🗑️</a></td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </body></html>
    ''', expenses=expenses, today=datetime.date.today().isoformat())

@app.route('/admin/expenses/add', methods=['POST'])
@login_required
def admin_add_expense():
    desc = request.form['description']
    amount = float(request.form['amount'])
    exp_date = request.form.get('expense_date', datetime.date.today().isoformat())
    user = current_user.username
    conn = get_db_connection()
    cur = conn.cursor()
    if DATABASE_URL:
        cur.execute("INSERT INTO expenses (description, amount, expense_date, user) VALUES (%s,%s,%s,%s)",
                    (desc, amount, exp_date, user))
    else:
        cur.execute("INSERT INTO expenses (description, amount, expense_date, user) VALUES (?,?,?,?)",
                    (desc, amount, exp_date, user))
    conn.commit()
    log_activity('إضافة مصروف', 'expense', cur.lastrowid, f'{desc}: {amount}')
    cur.close()
    conn.close()
    return redirect(url_for('admin_expenses'))

@app.route('/admin/expenses/delete/<int:eid>')
@login_required
def admin_delete_expense(eid):
    conn = get_db_connection()
    cur = conn.cursor()
    if DATABASE_URL:
        cur.execute("DELETE FROM expenses WHERE id=%s", (eid,))
    else:
        cur.execute("DELETE FROM expenses WHERE id=?", (eid,))
    conn.commit()
    log_activity('حذف مصروف', 'expense', eid)
    cur.close()
    conn.close()
    return redirect(url_for('admin_expenses'))

# ========================== الإحصائيات المتقدمة ==========================
@app.route('/admin/stats')
@login_required
def admin_stats():
    conn = get_db_connection()
    cur = conn.cursor()
    today = datetime.date.today().isoformat()
    month_start = (datetime.date.today().replace(day=1)).isoformat()
    # إجمالي المبيعات
    if DATABASE_URL:
        cur.execute("SELECT COALESCE(SUM(total),0) FROM sales")
    else:
        cur.execute("SELECT COALESCE(SUM(total),0) FROM sales")
    total_sales = cur.fetchone()[0]

    # إجمالي التكلفة
    if DATABASE_URL:
        cur.execute("""
            SELECT COALESCE(SUM(si.quantity * p.cost_price),0)
            FROM sale_items si
            JOIN products p ON si.product_id = p.id
        """)
    else:
        cur.execute("""
            SELECT COALESCE(SUM(si.quantity * p.cost_price),0)
            FROM sale_items si
            JOIN products p ON si.product_id = p.id
        """)
    total_cost = cur.fetchone()[0]

    # إجمالي المصروفات
    if DATABASE_URL:
        cur.execute("SELECT COALESCE(SUM(amount),0) FROM expenses")
    else:
        cur.execute("SELECT COALESCE(SUM(amount),0) FROM expenses")
    total_expenses = cur.fetchone()[0]

    net_profit = total_sales - total_cost - total_expenses

    # مبيعات اليوم
    if DATABASE_URL:
        cur.execute("SELECT COALESCE(SUM(total),0) FROM sales WHERE sale_date LIKE %s", (today+'%',))
    else:
        cur.execute("SELECT COALESCE(SUM(total),0) FROM sales WHERE sale_date LIKE ?", (today+'%',))
    today_sales = cur.fetchone()[0]

    # مبيعات الشهر
    if DATABASE_URL:
        cur.execute("SELECT COALESCE(SUM(total),0) FROM sales WHERE sale_date >= %s", (month_start,))
    else:
        cur.execute("SELECT COALESCE(SUM(total),0) FROM sales WHERE sale_date >= ?", (month_start,))
    month_sales = cur.fetchone()[0]

    # أفضل المنتجات
    if DATABASE_URL:
        cur.execute("""
            SELECT product_name, SUM(quantity) as qty, SUM(total) as total_sales
            FROM sale_items
            GROUP BY product_name
            ORDER BY qty DESC
            LIMIT 5
        """)
    else:
        cur.execute("""
            SELECT product_name, SUM(quantity) as qty, SUM(total) as total_sales
            FROM sale_items
            GROUP BY product_name
            ORDER BY qty DESC
            LIMIT 5
        """)
    top_products = cur.fetchall()

    cur.close()
    conn.close()

    return render_template_string('''
    <!DOCTYPE html><html dir="rtl"><head><title>الإحصائيات</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        *{margin:0;padding:0;box-sizing:border-box;}
        body{background:#000;padding:20px;color:#FFD700;font-family:Arial;}
        .header{background:#111;padding:20px;border-radius:10px;border:1px solid #FFD700;margin-bottom:20px;display:flex;justify-content:space-between;}
        .stats-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:20px;margin-bottom:30px;}
        .stat-card{background:#111;padding:20px;border-radius:10px;border:1px solid #FFD700;text-align:center;}
        .stat-number{font-size:32px;font-weight:bold;color:#FFD700;}
        .btn{background:#FFD700;color:#000;padding:8px 15px;border-radius:5px;text-decoration:none;}
        canvas{max-width:600px;margin:auto;background:#111;border:1px solid #FFD700;border-radius:10px;padding:10px;}
    </style>
    </head>
    <body>
        <div class="header">
            <h1>📊 الإحصائيات</h1>
            <a href="/admin" class="btn">العودة</a>
        </div>
        <div class="stats-grid">
            <div class="stat-card">
                <div>💰 إجمالي المبيعات</div>
                <div class="stat-number">{{ "%.2f"|format(total_sales) }}</div>
            </div>
            <div class="stat-card">
                <div>📦 إجمالي التكلفة</div>
                <div class="stat-number">{{ "%.2f"|format(total_cost) }}</div>
            </div>
            <div class="stat-card">
                <div>💸 المصروفات</div>
                <div class="stat-number">{{ "%.2f"|format(total_expenses) }}</div>
            </div>
            <div class="stat-card">
                <div>📈 صافي الربح</div>
                <div class="stat-number">{{ "%.2f"|format(net_profit) }}</div>
            </div>
            <div class="stat-card">
                <div>📅 مبيعات اليوم</div>
                <div class="stat-number">{{ "%.2f"|format(today_sales) }}</div>
            </div>
            <div class="stat-card">
                <div>🗓️ مبيعات الشهر</div>
                <div class="stat-number">{{ "%.2f"|format(month_sales) }}</div>
            </div>
        </div>

        <h2>أفضل 5 منتجات مبيعاً</h2>
        <canvas id="salesChart"></canvas>
        <script>
            const ctx = document.getElementById('salesChart').getContext('2d');
            new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: [{% for p in top_products %}'{{ p.product_name }}',{% endfor %}],
                    datasets: [{
                        label: 'الكمية المباعة',
                        data: [{% for p in top_products %}{{ p.qty }},{% endfor %}],
                        backgroundColor: '#FFD700'
                    }]
                }
            });
        </script>
    </body></html>
    ''', total_sales=total_sales, total_cost=total_cost, total_expenses=total_expenses,
        net_profit=net_profit, today_sales=today_sales, month_sales=month_sales,
        top_products=top_products)

# ========================== ملفات ثابتة ==========================
@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename)

# ========================== التشغيل ==========================
if __name__ == '__main__':
    print("="*60)
    print("نظام سوبر ماركت متكامل - اولاد قايد محمد")
    print("بيئة:", "PostgreSQL" if DATABASE_URL else "SQLite")
    print("الدخول للإدارة: /login  (admin/admin123)")
    print("="*60)
    app.run(host='127.0.0.1', port=5000, debug=True)
