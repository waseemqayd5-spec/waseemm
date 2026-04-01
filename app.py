"""
تطبيق ويب لنظام نقاط العملاء وإدارة البضائع - سوبر ماركت اولاد قايد محمد
يدعم قواعد البيانات SQLite (للتطوير المحلي) و PostgreSQL (للإنتاج على Render)
الألوان المعدلة: أسود وذهبي
"""

# =============================== الاستيرادات ===============================
from flask import Flask, request, jsonify, render_template_string
import os
import datetime
import psycopg2
from psycopg2.extras import RealDictCursor
import sqlite3

# =============================== التهيئة ===============================
app = Flask(__name__)

# تحديد رابط قاعدة البيانات من متغير البيئة (سيكون موجوداً في Render)
DATABASE_URL = os.environ.get('DATABASE_URL', None)


def get_db_connection():
    """
    تقوم بإنشاء اتصال بقاعدة البيانات المناسبة:
    - إذا كان DATABASE_URL موجوداً => PostgreSQL
    - وإلا => SQLite محلي
    """
    if DATABASE_URL:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    else:
        # التأكد من وجود مجلد data
        if not os.path.exists('data'):
            os.makedirs('data')
        conn = sqlite3.connect('data/supermarket.db')
        conn.row_factory = sqlite3.Row   # لإرجاع الصفوف كقاموس
    return conn


def execute_query(query, params=None, fetch_one=False, fetch_all=False, commit=False):
    """
    دالة مساعدة لتنفيذ الاستعلامات مع التعامل مع الفروقات بين SQLite و PostgreSQL
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        if params is None:
            params = ()
        cur.execute(query, params)
        if commit:
            conn.commit()
        if fetch_one:
            result = cur.fetchone()
            return result
        elif fetch_all:
            result = cur.fetchall()
            return result
        else:
            return None
    finally:
        cur.close()
        conn.close()


# =============================== إنشاء الجداول والبيانات الافتراضية ===============================
def init_db():
    """إنشاء الجداول وإضافة بيانات افتراضية إذا كانت قاعدة البيانات فارغة"""
    conn = get_db_connection()
    cur = conn.cursor()

    if DATABASE_URL:
        # PostgreSQL
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
                category VARCHAR(50),
                price REAL NOT NULL,
                cost_price REAL,
                quantity INTEGER DEFAULT 0,
                min_quantity INTEGER DEFAULT 10,
                unit VARCHAR(20) DEFAULT 'قطعة',
                supplier VARCHAR(100),
                expiry_date VARCHAR(10),
                added_date VARCHAR(10),
                last_updated VARCHAR(10),
                is_active INTEGER DEFAULT 1
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS inventory_logs (
                id SERIAL PRIMARY KEY,
                product_id INTEGER,
                product_name TEXT,
                change_type TEXT,
                quantity_change INTEGER,
                old_quantity INTEGER,
                new_quantity INTEGER,
                notes TEXT,
                user TEXT,
                timestamp TEXT,
                FOREIGN KEY (product_id) REFERENCES products (id)
            )
        """)

        # التحقق من وجود بيانات افتراضية
        cur.execute("SELECT COUNT(*) FROM customers")
        if cur.fetchone()[0] == 0:
            # إضافة عميل تجريبي
            cur.execute("""
                INSERT INTO customers (phone, name, loyalty_points, total_spent, visits, last_visit)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, ("0500000000", "عميل تجريبي", 50, 200.0, 5, datetime.date.today().isoformat()))

        cur.execute("SELECT COUNT(*) FROM products")
        if cur.fetchone()[0] == 0:
            today = datetime.date.today()
            future_date = today + datetime.timedelta(days=180)

            default_products = [
                ("8801234567890", "أرز بسمتي", "مواد غذائية", 25.0, 18.0, 50, 10, "كيلو", "مورد الأرز",
                 future_date.isoformat()),
                ("8809876543210", "سكر", "مواد غذائية", 15.0, 11.0, 100, 20, "كيلو", "مورد السكر",
                 future_date.isoformat()),
                ("8801122334455", "زيت دوار الشمس", "مواد غذائية", 35.0, 28.0, 30, 10, "لتر", "مورد الزيوت",
                 future_date.isoformat()),
                ("8805566778899", "حليب طازج", "مبردات", 8.0, 6.0, 40, 15, "لتر", "شركة الألبان",
                 (today + datetime.timedelta(days=14)).isoformat()),
                ("8809988776655", "شاي", "مواد غذائية", 20.0, 15.0, 60, 15, "علبة", "مورد الشاي",
                 future_date.isoformat()),
            ]

            for prod in default_products:
                cur.execute("""
                    INSERT INTO products (barcode, name, category, price, cost_price, quantity, min_quantity,
                                          unit, supplier, expiry_date, added_date, last_updated)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (*prod, today.isoformat(), today.isoformat()))
    else:
        # SQLite
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
                category TEXT,
                price REAL NOT NULL,
                cost_price REAL,
                quantity INTEGER DEFAULT 0,
                min_quantity INTEGER DEFAULT 10,
                unit TEXT DEFAULT 'قطعة',
                supplier TEXT,
                expiry_date TEXT,
                added_date TEXT,
                last_updated TEXT,
                is_active INTEGER DEFAULT 1
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
                FOREIGN KEY (product_id) REFERENCES products (id)
            )
        """)

        # التحقق من وجود بيانات افتراضية
        cur.execute("SELECT COUNT(*) FROM customers")
        if cur.fetchone()[0] == 0:
            cur.execute("""
                INSERT INTO customers (phone, name, loyalty_points, total_spent, visits, last_visit)
                VALUES (?, ?, ?, ?, ?, ?)
            """, ("0500000000", "عميل تجريبي", 50, 200.0, 5, datetime.date.today().isoformat()))

        cur.execute("SELECT COUNT(*) FROM products")
        if cur.fetchone()[0] == 0:
            today = datetime.date.today()
            future_date = today + datetime.timedelta(days=180)

            default_products = [
                ("8801234567890", "أرز بسمتي", "مواد غذائية", 25.0, 18.0, 50, 10, "كيلو", "مورد الأرز",
                 future_date.isoformat()),
                ("8809876543210", "سكر", "مواد غذائية", 15.0, 11.0, 100, 20, "كيلو", "مورد السكر",
                 future_date.isoformat()),
                ("8801122334455", "زيت دوار الشمس", "مواد غذائية", 35.0, 28.0, 30, 10, "لتر", "مورد الزيوت",
                 future_date.isoformat()),
                ("8805566778899", "حليب طازج", "مبردات", 8.0, 6.0, 40, 15, "لتر", "شركة الألبان",
                 (today + datetime.timedelta(days=14)).isoformat()),
                ("8809988776655", "شاي", "مواد غذائية", 20.0, 15.0, 60, 15, "علبة", "مورد الشاي",
                 future_date.isoformat()),
            ]

            for prod in default_products:
                cur.execute("""
                    INSERT INTO products (barcode, name, category, price, cost_price, quantity, min_quantity,
                                          unit, supplier, expiry_date, added_date, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (*prod, today.isoformat(), today.isoformat()))

    conn.commit()
    conn.close()


# تهيئة قاعدة البيانات عند بدء التطبيق (تضمن إنشاء الجداول في بيئة الإنتاج)
init_db()


# =============================== واجهات العملاء (المعدلة مع رقم واتساب) ===============================
@app.route('/')
def home():
    return render_template_string('''
    <!DOCTYPE html>
    <html dir="rtl" lang="ar">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>نظام نقاط العملاء - سوبر ماركت اولاد قايد محمد</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; font-family: 'Segoe UI', Tahoma, Arial, sans-serif; }
            body { background: #000; min-height: 100vh; padding: 20px; }
            .container { max-width: 1400px; margin: 0 auto; display: grid; grid-template-columns: 1fr 350px; gap: 20px; }
            @media (max-width: 768px) { .container { grid-template-columns: 1fr; } }
            .main-content { background: rgba(255,215,0,0.1); border-radius: 20px; padding: 20px; backdrop-filter: blur(10px); border: 1px solid #FFD700; }
            .cart-sidebar { background: #111; border-radius: 20px; padding: 20px; box-shadow: 0 10px 30px rgba(255,215,0,0.2); height: fit-content; position: sticky; top: 20px; border: 1px solid #FFD700; color: #FFD700; }
            h1 { color: #FFD700; text-align: center; margin-bottom: 20px; font-size: 2em; text-shadow: 2px 2px 4px #000; }
            .nav { display: flex; gap: 10px; margin-bottom: 25px; flex-wrap: wrap; }
            .nav button { flex: 1; padding: 15px; background: #111; color: #FFD700; border: 1px solid #FFD700; border-radius: 12px; cursor: pointer; font-size: 18px; font-weight: bold; transition: 0.3s; min-width: 120px; }
            .nav button.active { background: #FFD700; color: #000; box-shadow: 0 5px 15px rgba(255,215,0,0.4); }
            .nav button:hover { transform: translateY(-2px); background: #FFD700; color: #000; }
            .section { display: none; }
            .section.active { display: block; }
            .filters { display: flex; gap: 15px; margin-bottom: 25px; flex-wrap: wrap; }
            .filters select, .filters input { flex: 1; padding: 15px; border: none; border-radius: 12px; font-size: 16px; background: #111; color: #FFD700; border: 1px solid #FFD700; box-shadow: 0 3px 10px rgba(255,215,0,0.1); }
            .products-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 20px; }
            .product-card { background: #111; border-radius: 15px; padding: 20px; text-align: center; box-shadow: 0 5px 15px rgba(255,215,0,0.2); transition: 0.3s; border: 1px solid #FFD700; color: #FFD700; }
            .product-card:hover { transform: translateY(-5px); box-shadow: 0 10px 25px rgba(255,215,0,0.4); }
            .product-icon { font-size: 50px; margin-bottom: 10px; }
            .product-name { font-weight: bold; font-size: 18px; color: #FFD700; margin-bottom: 5px; }
            .product-price { color: #FFD700; font-size: 22px; font-weight: bold; margin: 10px 0; }
            .product-stock { color: #FFD700; font-size: 14px; margin-bottom: 15px; opacity: 0.8; }
            .add-to-cart-btn { background: #FFD700; color: #000; border: none; padding: 12px; border-radius: 8px; width: 100%; font-size: 16px; cursor: pointer; transition: 0.3s; display: flex; align-items: center; justify-content: center; gap: 5px; font-weight: bold; }
            .add-to-cart-btn:hover { background: #e6c200; }
            .cart-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; padding-bottom: 15px; border-bottom: 2px solid #FFD700; }
            .cart-header h3 { color: #FFD700; }
            .cart-items { max-height: 400px; overflow-y: auto; margin-bottom: 20px; }
            .cart-item { display: flex; justify-content: space-between; align-items: center; padding: 10px; background: #000; border-radius: 8px; margin-bottom: 10px; border: 1px solid #FFD700; color: #FFD700; }
            .cart-item-info { flex: 1; }
            .cart-item-name { font-weight: bold; color: #FFD700; }
            .cart-item-price { color: #FFD700; font-size: 14px; opacity: 0.8; }
            .cart-item-actions { display: flex; gap: 5px; }
            .cart-item-actions button { background: none; border: none; cursor: pointer; font-size: 18px; padding: 5px; color: #FFD700; }
            .cart-total { background: #FFD700; color: #000; padding: 15px; border-radius: 10px; text-align: center; font-size: 20px; font-weight: bold; margin-top: 20px; }
            .whatsapp-btn { background: #25D366; color: white; border: none; padding: 15px; border-radius: 10px; width: 100%; font-size: 18px; font-weight: bold; cursor: pointer; margin-top: 15px; display: flex; align-items: center; justify-content: center; gap: 10px; transition: 0.3s; }
            .whatsapp-btn:hover { background: #128C7E; }
            .clear-cart-btn { background: #FFD700; color: #000; border: none; padding: 10px; border-radius: 5px; cursor: pointer; font-size: 14px; font-weight: bold; }
            .offer-card { background: #111; border-radius: 15px; padding: 20px; margin-bottom: 15px; text-align: center; border: 1px solid #FFD700; color: #FFD700; }
            .offer-code { background: #FFD700; color: #000; padding: 5px 10px; border-radius: 5px; display: inline-block; margin-top: 10px; font-weight: bold; }
        </style>
    </head>
    <body>
        <h1>🛒 سوبر ماركت اولاد قايد محمد</h1>

        <div style="color:#FFD700; text-align:center; margin-bottom:10px;">إعداد وتصميم  《 م/وسيم الحميدي 》</div>
        <div style="color:#FFD700; text-align:center; margin-bottom:20px;">للتواصل  والاستفسار  《967770295876》</div>
        <div class="container">
            <!-- القسم الرئيسي -->
            <div class="main-content">
                <div class="nav">
                    <button class="active" onclick="showSection('points')">⭐ نقاطي</button>
                    <button onclick="showSection('products')">📦 المنتجات</button>
                    <button onclick="showSection('offers')">🎁 العروض</button>
                </div>

                <!-- قسم النقاط -->
                <div id="points-section" class="section active">
                    <div style="background: #111; border-radius: 15px; padding: 25px; border: 1px solid #FFD700;">
                        <input type="tel" id="phone" placeholder="📱 أدخل رقم الهاتف" style="width:100%; padding:15px; border:2px solid #FFD700; border-radius:10px; margin-bottom:15px; background:#000; color:#FFD700;">
                        <button onclick="checkPoints()" style="background:#FFD700; color:#000; border:none; padding:15px; width:100%; border-radius:10px; font-size:18px; font-weight:bold;">🔍 استعلام عن النقاط</button>
                        <div id="points-result" style="margin-top:20px;"></div>
                    </div>
                </div>

                <!-- قسم المنتجات -->
                <div id="products-section" class="section">
                    <div class="filters">
                        <select id="category-filter" onchange="loadProducts()">
                            <option value="">جميع الفئات</option>
                            <option value="مواد غذائية">مواد غذائية</option>
                            <option value="مبردات">مبردات</option>
                            <option value="معلبات">معلبات</option>
                            <option value="منظفات">منظفات</option>
                        </select>
                        <input type="text" id="search-product" placeholder="🔍 ابحث عن منتج..." onkeyup="loadProducts()">
                    </div>
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
                    <button class="clear-cart-btn" onclick="clearCart()">تفريغ السلة</button>
                </div>
                <div id="cart-items" class="cart-items">
                    <p style="text-align:center; color:#FFD700;">السلة فارغة</p>
                </div>
                <div id="cart-total" class="cart-total">الإجمالي: 0 ريال</div>
                <button class="whatsapp-btn" onclick="sendWhatsApp()">
                    <img src="https://img.icons8.com/color/24/000000/whatsapp--v1.png" style="vertical-align:middle;"> إرسال الطلب عبر واتساب
                </button>
            </div>
        </div>

        <script>
            // متغيرات السلة
            let cart = [];

            // تبديل الأقسام
            function showSection(sectionId) {
                document.querySelectorAll('.nav button').forEach(btn => btn.classList.remove('active'));
                event.target.classList.add('active');
                document.querySelectorAll('.section').forEach(sec => sec.classList.remove('active'));
                document.getElementById(sectionId + '-section').classList.add('active');
                if (sectionId === 'products') loadProducts();
                if (sectionId === 'offers') loadOffers();
            }

            // دالة عرض النقاط
            function checkPoints() {
                const phone = document.getElementById('phone').value;
                const resultDiv = document.getElementById('points-result');
                if (!phone) {
                    resultDiv.innerHTML = '<div style="background:#ffebee; color:#c62828; padding:15px; border-radius:10px;">⚠ يرجى إدخال رقم الهاتف</div>';
                    return;
                }
                resultDiv.innerHTML = '<p style="color:#FFD700;">جاري البحث...</p>';
                fetch('/check_points', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({phone: phone})
                })
                .then(r => r.json())
                .then(data => {
                    if (data.success) {
                        const c = data.customer;
                        resultDiv.innerHTML = `
                            <div style="background:#FFD700; color:#000; padding:20px; border-radius:10px;">
                                <h3>👤 ${c.name}</h3>
                                <h1 style="font-size:48px;">${c.points} ⭐</h1>
                                <p>💰 الإنفاق: ${c.total_spent} ريال</p>
                                <p>🛒 الزيارات: ${c.visits}</p>
                                <p>📅 آخر زيارة: ${c.last_visit}</p>
                                <p>🏆 المستوى: ${c.tier}</p>
                            </div>
                        `;
                    } else {
                        resultDiv.innerHTML = `<div style="background:#ffebee; color:#c62828; padding:15px; border-radius:10px;">❌ ${data.message}</div>`;
                    }
                });
            }

            // تحميل المنتجات مع أزرار الإضافة
            function loadProducts() {
                const category = document.getElementById('category-filter').value;
                const search = document.getElementById('search-product').value;
                const resultDiv = document.getElementById('products-result');
                resultDiv.innerHTML = '<p style="color:#FFD700;">جاري تحميل المنتجات...</p>';
                fetch(`/products?category=${encodeURIComponent(category)}&search=${encodeURIComponent(search)}`)
                    .then(r => r.json())
                    .then(data => {
                        if (data.success) {
                            let html = '';
                            data.products.forEach(product => {
                                html += `
                                    <div class="product-card">
                                        <div class="product-icon">📦</div>
                                        <div class="product-name">${product.name}</div>
                                        <div class="product-price">${product.price} ريال</div>
                                        <div class="product-stock">${product.quantity} ${product.unit}</div>
                                        <button class="add-to-cart-btn" onclick="addToCart(${product.id}, '${product.name}', ${product.price})">
                                            ➕ أضف إلى السلة
                                        </button>
                                    </div>
                                `;
                            });
                            resultDiv.innerHTML = html || '<p style="color:#FFD700;">لا توجد منتجات</p>';
                        } else {
                            resultDiv.innerHTML = `<p style="color:#FFD700;">❌ ${data.message}</p>`;
                        }
                    });
            }

            // تحميل العروض
            function loadOffers() {
                fetch('/offers')
                    .then(r => r.json())
                    .then(data => {
                        let html = '';
                        data.offers.forEach(offer => {
                            html += `
                                <div class="offer-card">
                                    <h3>${offer.title}</h3>
                                    <p>${offer.description}</p>
                                    <div class="offer-code">🏷️ كود: ${offer.code}</div>
                                </div>
                            `;
                        });
                        document.getElementById('offers-result').innerHTML = html;
                    });
            }

            // دوال السلة
            function addToCart(id, name, price) {
                const existing = cart.find(item => item.id === id);
                if (existing) {
                    existing.quantity++;
                } else {
                    cart.push({ id, name, price, quantity: 1 });
                }
                updateCartDisplay();
                saveCart();
            }

            function removeFromCart(id) {
                cart = cart.filter(item => item.id !== id);
                updateCartDisplay();
                saveCart();
            }

            function updateCartDisplay() {
                const cartDiv = document.getElementById('cart-items');
                const totalDiv = document.getElementById('cart-total');
                if (cart.length === 0) {
                    cartDiv.innerHTML = '<p style="text-align:center; color:#FFD700;">السلة فارغة</p>';
                    totalDiv.innerText = 'الإجمالي: 0 ريال';
                    return;
                }
                let html = '';
                let total = 0;
                cart.forEach(item => {
                    const itemTotal = item.price * item.quantity;
                    total += itemTotal;
                    html += `
                        <div class="cart-item">
                            <div class="cart-item-info">
                                <div class="cart-item-name">${item.name}</div>
                                <div class="cart-item-price">${item.price} ريال × ${item.quantity} = ${itemTotal} ريال</div>
                            </div>
                            <div class="cart-item-actions">
                                <button onclick="removeFromCart(${item.id})">🗑️</button>
                            </div>
                        </div>
                    `;
                });
                cartDiv.innerHTML = html;
                totalDiv.innerText = `الإجمالي: ${total} ريال`;
            }

            function clearCart() {
                cart = [];
                updateCartDisplay();
                saveCart();
            }

            function saveCart() {
                localStorage.setItem('cart', JSON.stringify(cart));
            }

            function loadCart() {
                const saved = localStorage.getItem('cart');
                if (saved) {
                    cart = JSON.parse(saved);
                    updateCartDisplay();
                }
            }

            // إرسال الطلب عبر واتساب (معدل برقم المتجر)
            function sendWhatsApp() {
                if (cart.length === 0) {
                    alert('السلة فارغة، أضف منتجات أولاً');
                    return;
                }
                let message = '*طلب جديد من سوبر ماركت اولاد قايد محمد للتجاره العامة*%0A';
                let total = 0;
                cart.forEach(item => {
                    const itemTotal = item.price * item.quantity;
                    message += `- ${item.name} (${item.price} ريال) × ${item.quantity} = ${itemTotal} ريال%0A`;
                    total += itemTotal;
                });
                message += `%0A*الإجمالي: ${total} ريال*`;
                // الرقم المطلوب: 967771602370
                window.open(`https://wa.me/967771602370?text=${message}`, '_blank');
            }

            // التحميل الأولي
            window.onload = function() {
                loadCart();
                loadProducts();
                loadOffers();
            };
        </script>
    </body>
    </html>
    ''')


# =============================== واجهات API للعملاء ===============================
@app.route('/check_points', methods=['POST'])
def check_points():
    """API للتحقق من نقاط العميل"""
    try:
        phone = request.json.get('phone')

        if not phone:
            return jsonify({"success": False, "message": "رقم الهاتف مطلوب"})

        conn = get_db_connection()
        cur = conn.cursor()

        if DATABASE_URL:
            cur.execute("""
                SELECT name, loyalty_points, total_spent, visits, last_visit, customer_tier
                FROM customers WHERE phone = %s AND is_active = 1
            """, (phone,))
        else:
            cur.execute("""
                SELECT name, loyalty_points, total_spent, visits, last_visit, customer_tier
                FROM customers WHERE phone = ? AND is_active = 1
            """, (phone,))

        customer = cur.fetchone()
        cur.close()
        conn.close()

        if customer:
            return jsonify({
                "success": True,
                "customer": {
                    "name": customer[0],
                    "points": customer[1],
                    "total_spent": customer[2],
                    "visits": customer[3],
                    "last_visit": customer[4],
                    "tier": customer[5]
                }
            })
        else:
            return jsonify({
                "success": False,
                "message": "رقم الهاتف غير مسجل"
            })

    except Exception as e:
        return jsonify({"success": False, "message": f"خطأ: {str(e)}"})


@app.route('/products')
def get_products():
    """API للحصول على البضائع مع id"""
    try:
        category = request.args.get('category', '')
        search = request.args.get('search', '')

        conn = get_db_connection()
        cur = conn.cursor()

        if DATABASE_URL:
            query = "SELECT id, name, price, quantity, unit, category FROM products WHERE is_active = 1"
            params = []
            if category:
                query += " AND category = %s"
                params.append(category)
            if search:
                query += " AND (name LIKE %s OR barcode LIKE %s)"
                params.append(f'%{search}%')
                params.append(f'%{search}%')
            query += " ORDER BY name"
            cur.execute(query, params)
        else:
            query = "SELECT id, name, price, quantity, unit, category FROM products WHERE is_active = 1"
            params = []
            if category:
                query += " AND category = ?"
                params.append(category)
            if search:
                query += " AND (name LIKE ? OR barcode LIKE ?)"
                params.append(f'%{search}%')
                params.append(f'%{search}%')
            query += " ORDER BY name"
            cur.execute(query, params)

        products = cur.fetchall()
        cur.close()
        conn.close()

        products_list = []
        for product in products:
            products_list.append({
                "id": product[0],
                "name": product[1],
                "price": product[2],
                "quantity": product[3],
                "unit": product[4],
                "category": product[5]
            })

        return jsonify({
            "success": True,
            "count": len(products_list),
            "products": products_list
        })

    except Exception as e:
        return jsonify({"success": False, "message": f"خطأ: {str(e)}"})


@app.route('/offers')
def get_offers():
    """API للحصول على العروض"""
    offers = [
        {"title": "خصم 5%", "description": "على مشترياتك القادمة", "code": "DISCOUNT10"},
        {"title": "توصيل مجاني", "description": "للطلبات فوق 25000 الف", "code": "FREESHIP"},
        {"title": "هدية مجانية", "description": "مع كل شراء 10 قطع بسعر  10000 الف ", "code": "FREE_GIFT"},
        {"title": "نقاط مضاعفة", "description": "في نهاية الأسبوع", "code": "DOUBLE_POINTS"}
    ]
    return jsonify({"success": True, "offers": offers})


# =============================== واجهات إدارة البضائع ===============================
@app.route('/admin/products')
def admin_products():
    return render_template_string('''
    <!DOCTYPE html>
    <html dir="rtl" lang="ar">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>إدارة البضائع</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; font-family: 'Segoe UI', Arial; }
            body { background: #000; padding: 20px; }
            .header { background: #111; color: #FFD700; padding: 25px; border-radius: 15px; margin-bottom: 25px; box-shadow: 0 5px 15px rgba(255,215,0,0.2); border: 1px solid #FFD700; }
            .tabs { display: flex; background: #111; border-radius: 10px; overflow: hidden; margin-bottom: 20px; box-shadow: 0 3px 10px rgba(255,215,0,0.1); border: 1px solid #FFD700; }
            .tab { flex: 1; padding: 15px; text-align: center; cursor: pointer; border-bottom: 3px solid transparent; color: #FFD700; }
            .tab.active { background: #FFD700; color: #000; border-bottom: 3px solid #e6c200; }
            .content { display: none; background: #111; padding: 25px; border-radius: 15px; box-shadow: 0 5px 15px rgba(255,215,0,0.2); border: 1px solid #FFD700; color: #FFD700; }
            .content.active { display: block; }
            .form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 20px; margin-bottom: 30px; }
            .form-group { margin-bottom: 20px; }
            label { display: block; margin-bottom: 8px; color: #FFD700; font-weight: 600; }
            input, select, textarea { width: 100%; padding: 12px; border: 2px solid #FFD700; border-radius: 8px; font-size: 16px; transition: border 0.3s; background: #000; color: #FFD700; }
            input:focus, select:focus, textarea:focus { border-color: #FFD700; outline: none; }
            button { background: #FFD700; color: #000; border: none; padding: 14px 28px; border-radius: 8px; font-size: 16px; cursor: pointer; transition: transform 0.2s, box-shadow 0.2s; font-weight: bold; }
            button:hover { transform: translateY(-2px); box-shadow: 0 5px 15px rgba(255,215,0,0.4); }
            button.secondary { background: #000; color: #FFD700; border: 1px solid #FFD700; }
            button.danger { background: #FFD700; color: #000; }
            .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin: 25px 0; }
            .stat-card { background: #000; padding: 20px; border-radius: 12px; box-shadow: 0 3px 10px rgba(255,215,0,0.2); text-align: center; border-top: 4px solid #FFD700; border: 1px solid #FFD700; color: #FFD700; }
            .stat-number { font-size: 32px; font-weight: bold; color: #FFD700; margin: 10px 0; }
            table { width: 100%; border-collapse: collapse; background: #000; border-radius: 10px; overflow: hidden; box-shadow: 0 3px 10px rgba(255,215,0,0.2); border: 1px solid #FFD700; }
            th { background: #FFD700; color: #000; padding: 18px; text-align: right; font-weight: 600; }
            td { padding: 16px; border-bottom: 1px solid #FFD700; color: #FFD700; }
            tr:hover { background: #111; }
            .low-stock { background: #332d00; border-left: 4px solid #FFD700; }
            .out-of-stock { background: #4d0000; border-left: 4px solid #ff4d4d; }
            .search-box { margin: 20px 0; padding: 15px; background: #111; border-radius: 10px; box-shadow: 0 3px 10px rgba(255,215,0,0.1); border: 1px solid #FFD700; }
            .alert { padding: 15px; border-radius: 8px; margin: 15px 0; }
            .alert-success { background: #FFD700; color: #000; border: 1px solid #e6c200; }
            .alert-error { background: #4d0000; color: #ff4d4d; border: 1px solid #ff4d4d; }
            .modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.8); z-index: 1000; }
            .modal-content { background: #111; width: 90%; max-width: 500px; margin: 50px auto; padding: 30px; border-radius: 15px; border: 2px solid #FFD700; color: #FFD700; }
        </style>
    </head>
    <body>
        <div class="header">
            <h1>📦 إدارة البضائع والمخزون</h1>
            <p>سوبر ماركت اولاد قايد محمد - نظام إدارة كامل</p>
        </div>

        <div class="tabs">
            <div class="tab active" onclick="showTab('dashboard')">📊 لوحة التحكم</div>
            <div class="tab" onclick="showTab('products')">🛍️ البضائع</div>
            <div class="tab" onclick="showTab('add')">➕ إضافة منتج</div>
            <div class="tab" onclick="showTab('inventory')">📦 حركات المخزون</div>
        </div>

        <!-- لوحة التحكم -->
        <div id="dashboard" class="content active">
            <h2>📊 إحصائيات المخزون</h2>
            <div id="stats" class="stats-grid"></div>

            <h2 style="margin-top: 30px;">📈 المنتجات المنخفضة في المخزون</h2>
            <div id="low-stock-alert"></div>
        </div>

        <!-- قائمة البضائع -->
        <div id="products" class="content">
            <div class="search-box">
                <input type="text" id="search" placeholder="🔍 ابحث بالاسم أو الباركود..." onkeyup="loadProducts()" style="width: 300px; display: inline-block; margin-right: 10px; background:#000; color:#FFD700; border:1px solid #FFD700;">
                <select id="filter-category" onchange="loadProducts()" style="width: 200px; display: inline-block; background:#000; color:#FFD700; border:1px solid #FFD700;">
                    <option value="">جميع الفئات</option>
                </select>
            </div>
            <div id="products-list"></div>
        </div>

        <!-- إضافة منتج -->
        <div id="add" class="content">
            <h2>➕ إضافة منتج جديد</h2>
            <form id="add-product-form" onsubmit="return addProduct(event)">
                <div class="form-grid">
                    <div class="form-group">
                        <label>الباركود *</label>
                        <input type="text" id="barcode" required placeholder="1234567890123">
                    </div>
                    <div class="form-group">
                        <label>اسم المنتج *</label>
                        <input type="text" id="name" required placeholder="أرز بسمتي">
                    </div>
                    <div class="form-group">
                        <label>الفئة</label>
                        <select id="category">
                            <option value="مواد غذائية">مواد غذائية</option>
                            <option value="مبردات">مبردات</option>
                            <option value="معلبات">معلبات</option>
                            <option value="منظفات">منظفات</option>
                            <option value="مشروبات">مشروبات</option>
                            <option value="حلويات">حلويات</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>سعر البيع (ريال) *</label>
                        <input type="number" id="price" step="0.01" required min="0">
                    </div>
                    <div class="form-group">
                        <label>سعر التكلفة (ريال)</label>
                        <input type="number" id="cost_price" step="0.01" min="0">
                    </div>
                    <div class="form-group">
                        <label>الكمية *</label>
                        <input type="number" id="quantity" required min="0">
                    </div>
                    <div class="form-group">
                        <label>الحد الأدنى للكمية</label>
                        <input type="number" id="min_quantity" value="10" min="0">
                    </div>
                    <div class="form-group">
                        <label>الوحدة</label>
                        <select id="unit">
                            <option value="قطعة">قطعة</option>
                            <option value="كيلو">كيلو</option>
                            <option value="لتر">لتر</option>
                            <option value="علبة">علبة</option>
                            <option value="كرتون">كرتون</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>المورد</label>
                        <input type="text" id="supplier" placeholder="اسم المورد">
                    </div>
                    <div class="form-group">
                        <label>تاريخ الانتهاء</label>
                        <input type="date" id="expiry_date">
                    </div>
                </div>
                <div style="text-align: left; margin-top: 20px;">
                    <button type="submit">💾 حفظ المنتج</button>
                    <button type="button" class="secondary" onclick="resetForm()">🔄 مسح النموذج</button>
                </div>
            </form>
        </div>

        <!-- حركات المخزون -->
        <div id="inventory" class="content">
            <h2>📦 سجل حركات المخزون</h2>
            <div id="inventory-logs"></div>
        </div>

        <!-- Modal للتعديل -->
        <div id="editModal" class="modal">
            <div class="modal-content">
                <h3>✏️ تعديل المنتج</h3>
                <form id="edit-product-form">
                    <input type="hidden" id="edit-id">
                    <div class="form-grid">
                        <div class="form-group">
                            <label>اسم المنتج</label>
                            <input type="text" id="edit-name" required>
                        </div>
                        <div class="form-group">
                            <label>السعر</label>
                            <input type="number" id="edit-price" step="0.01" required>
                        </div>
                        <div class="form-group">
                            <label>الكمية</label>
                            <input type="number" id="edit-quantity" required>
                        </div>
                    </div>
                    <div style="text-align: left; margin-top: 20px;">
                        <button type="submit">💾 حفظ التغييرات</button>
                        <button type="button" class="secondary" onclick="closeModal()">إلغاء</button>
                    </div>
                </form>
            </div>
        </div>

        <script>
            let currentTab = 'dashboard';

            function showTab(tabName) {
                currentTab = tabName;
                document.querySelectorAll('.tab').forEach(tab => {
                    tab.classList.remove('active');
                });
                event.target.classList.add('active');

                document.querySelectorAll('.content').forEach(content => {
                    content.classList.remove('active');
                });
                document.getElementById(tabName).classList.add('active');

                if (tabName === 'dashboard') loadDashboard();
                if (tabName === 'products') loadProducts();
                if (tabName === 'inventory') loadInventoryLogs();
            }

            function loadDashboard() {
                fetch('/admin/products/stats')
                    .then(r => r.json())
                    .then(data => {
                        if (data.success) {
                            document.getElementById('stats').innerHTML = `
                                <div class="stat-card">
                                    <div>🛍️</div>
                                    <div class="stat-number">${data.total_products}</div>
                                    <div>إجمالي المنتجات</div>
                                </div>
                                <div class="stat-card">
                                    <div>💰</div>
                                    <div class="stat-number">${data.total_value.toFixed(2)}</div>
                                    <div>قيمة المخزون</div>
                                </div>
                                <div class="stat-card">
                                    <div>⚠️</div>
                                    <div class="stat-number">${data.low_stock}</div>
                                    <div>منخفضة المخزون</div>
                                </div>
                                <div class="stat-card">
                                    <div>📈</div>
                                    <div class="stat-number">${data.categories}</div>
                                    <div>الفئات</div>
                                </div>
                            `;

                            let lowStockHTML = '';
                            if (data.low_stock_products.length > 0) {
                                lowStockHTML = '<table>';
                                lowStockHTML += '<thead><tr><th>المنتج</th><th>الكمية</th><th>الحد الأدنى</th><th></th></tr></thead><tbody>';
                                data.low_stock_products.forEach(product => {
                                    lowStockHTML += `
                                        <tr class="low-stock">
                                            <td>${product.name}</td>
                                            <td>${product.quantity} ${product.unit}</td>
                                            <td>${product.min_quantity}</td>
                                            <td><button class="secondary" onclick="editProduct(${product.id})">تعديل</button></td>
                                        </tr>
                                    `;
                                });
                                lowStockHTML += '</tbody></table>';
                            } else {
                                lowStockHTML = '<div class="alert alert-success">جميع المنتجات في مستوى جيد ✓</div>';
                            }
                            document.getElementById('low-stock-alert').innerHTML = lowStockHTML;
                        }
                    });
            }

            function loadProducts() {
                const search = document.getElementById('search')?.value || '';
                const category = document.getElementById('filter-category')?.value || '';

                fetch(`/admin/products/list?search=${encodeURIComponent(search)}&category=${encodeURIComponent(category)}`)
                    .then(r => r.json())
                    .then(data => {
                        if (data.success) {
                            let html = '<table>';
                            html += `
                                <thead>
                                    <tr>
                                        <th>الباركود</th>
                                        <th>الاسم</th>
                                        <th>الفئة</th>
                                        <th>السعر</th>
                                        <th>المخزون</th>
                                        <th>القيمة</th>
                                        <th>الإجراءات</th>
                                    </tr>
                                </thead>
                                <tbody>
                            `;

                            data.products.forEach(product => {
                                const value = product.price * product.quantity;
                                const rowClass = product.quantity === 0 ? 'out-of-stock' : 
                                                product.quantity <= product.min_quantity ? 'low-stock' : '';

                                html += `
                                    <tr class="${rowClass}">
                                        <td>${product.barcode}</td>
                                        <td>${product.name}</td>
                                        <td>${product.category}</td>
                                        <td>${product.price.toFixed(2)} ر.س</td>
                                        <td>${product.quantity} ${product.unit}</td>
                                        <td>${value.toFixed(2)} ر.س</td>
                                        <td>
                                            <button class="secondary" onclick="editProduct(${product.id})">✏️</button>
                                            <button class="danger" onclick="deleteProduct(${product.id})">🗑️</button>
                                        </td>
                                    </tr>
                                `;
                            });

                            html += '</tbody></table>';
                            document.getElementById('products-list').innerHTML = html;
                        }
                    });
            }

            function addProduct(e) {
                e.preventDefault();

                const product = {
                    barcode: document.getElementById('barcode').value,
                    name: document.getElementById('name').value,
                    category: document.getElementById('category').value,
                    price: parseFloat(document.getElementById('price').value),
                    cost_price: parseFloat(document.getElementById('cost_price').value) || 0,
                    quantity: parseInt(document.getElementById('quantity').value),
                    min_quantity: parseInt(document.getElementById('min_quantity').value) || 10,
                    unit: document.getElementById('unit').value,
                    supplier: document.getElementById('supplier').value,
                    expiry_date: document.getElementById('expiry_date').value
                };

                fetch('/admin/products/add', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(product)
                })
                .then(r => r.json())
                .then(data => {
                    if (data.success) {
                        alert('✅ تم إضافة المنتج بنجاح');
                        resetForm();
                        loadProducts();
                        showTab('products');
                    } else {
                        alert('❌ ' + data.message);
                    }
                });
            }

            function resetForm() {
                document.getElementById('add-product-form').reset();
            }

            function editProduct(id) {
                fetch(`/admin/products/${id}`)
                    .then(r => r.json())
                    .then(data => {
                        if (data.success) {
                            document.getElementById('edit-id').value = data.product.id;
                            document.getElementById('edit-name').value = data.product.name;
                            document.getElementById('edit-price').value = data.product.price;
                            document.getElementById('edit-quantity').value = data.product.quantity;
                            document.getElementById('editModal').style.display = 'block';
                        }
                    });
            }

            document.getElementById('edit-product-form').onsubmit = function(e) {
                e.preventDefault();

                const product = {
                    id: document.getElementById('edit-id').value,
                    name: document.getElementById('edit-name').value,
                    price: parseFloat(document.getElementById('edit-price').value),
                    quantity: parseInt(document.getElementById('edit-quantity').value)
                };

                fetch('/admin/products/update', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(product)
                })
                .then(r => r.json())
                .then(data => {
                    if (data.success) {
                        alert('✅ تم تحديث المنتج بنجاح');
                        closeModal();
                        loadProducts();
                        loadDashboard();
                    } else {
                        alert('❌ ' + data.message);
                    }
                });
            };

            function deleteProduct(id) {
                if (confirm('هل أنت متأكد من حذف هذا المنتج؟')) {
                    fetch(`/admin/products/delete/${id}`, {
                        method: 'DELETE'
                    })
                    .then(r => r.json())
                    .then(data => {
                        if (data.success) {
                            alert('✅ تم حذف المنتج بنجاح');
                            loadProducts();
                            loadDashboard();
                        } else {
                            alert('❌ ' + data.message);
                        }
                    });
                }
            }

            function loadInventoryLogs() {
                fetch('/admin/products/logs')
                    .then(r => r.json())
                    .then(data => {
                        if (data.success) {
                            let html = '<table>';
                            html += `
                                <thead>
                                    <tr>
                                        <th>التاريخ</th>
                                        <th>المنتج</th>
                                        <th>نوع الحركة</th>
                                        <th>الكمية</th>
                                        <th>الملاحظات</th>
                                        <th>المستخدم</th>
                                    </tr>
                                </thead>
                                <tbody>
                            `;

                            data.logs.forEach(log => {
                                html += `
                                    <tr>
                                        <td>${log.timestamp}</td>
                                        <td>${log.product_name}</td>
                                        <td>${log.change_type}</td>
                                        <td>${log.quantity_change > 0 ? '+' : ''}${log.quantity_change}</td>
                                        <td>${log.notes || '-'}</td>
                                        <td>${log.user || 'نظام'}</td>
                                    </tr>
                                `;
                            });

                            html += '</tbody></table>';
                            document.getElementById('inventory-logs').innerHTML = html;
                        }
                    });
            }

            function closeModal() {
                document.getElementById('editModal').style.display = 'none';
            }

            // تحميل لوحة التحكم عند البدء
            document.addEventListener('DOMContentLoaded', function() {
                loadDashboard();
                // تحميل الفئات للتصفية
                fetch('/admin/products/categories')
                    .then(r => r.json())
                    .then(data => {
                        if (data.success) {
                            const select = document.getElementById('filter-category');
                            data.categories.forEach(cat => {
                                const option = document.createElement('option');
                                option.value = cat;
                                option.textContent = cat;
                                select.appendChild(option);
                            });
                        }
                    });
            });

            // إغلاق المودال عند النقر خارجها
            window.onclick = function(event) {
                const modal = document.getElementById('editModal');
                if (event.target == modal) {
                    closeModal();
                }
            };
        </script>
    </body>
    </html>
    ''')


# =============================== واجهات API لإدارة البضائع ===============================
@app.route('/admin/products/stats')
def products_stats():
    """إحصائيات البضائع"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        if DATABASE_URL:
            cur.execute("SELECT COUNT(*) FROM products WHERE is_active = 1")
            total_products = cur.fetchone()[0] or 0

            cur.execute("SELECT SUM(price * quantity) FROM products WHERE is_active = 1")
            total_value = cur.fetchone()[0] or 0

            cur.execute("""
                SELECT COUNT(*) FROM products 
                WHERE quantity <= min_quantity AND quantity > 0 AND is_active = 1
            """)
            low_stock = cur.fetchone()[0] or 0

            cur.execute("SELECT COUNT(DISTINCT category) FROM products WHERE is_active = 1")
            categories = cur.fetchone()[0] or 0

            cur.execute("""
                SELECT id, name, quantity, min_quantity, unit 
                FROM products 
                WHERE quantity <= min_quantity AND is_active = 1 
                ORDER BY quantity ASC LIMIT 10
            """)
            low_stock_products = []
            for row in cur.fetchall():
                low_stock_products.append({
                    "id": row[0],
                    "name": row[1],
                    "quantity": row[2],
                    "min_quantity": row[3],
                    "unit": row[4]
                })
        else:
            cur.execute("SELECT COUNT(*) FROM products WHERE is_active = 1")
            total_products = cur.fetchone()[0] or 0

            cur.execute("SELECT SUM(price * quantity) FROM products WHERE is_active = 1")
            total_value = cur.fetchone()[0] or 0

            cur.execute("""
                SELECT COUNT(*) FROM products 
                WHERE quantity <= min_quantity AND quantity > 0 AND is_active = 1
            """)
            low_stock = cur.fetchone()[0] or 0

            cur.execute("SELECT COUNT(DISTINCT category) FROM products WHERE is_active = 1")
            categories = cur.fetchone()[0] or 0

            cur.execute("""
                SELECT id, name, quantity, min_quantity, unit 
                FROM products 
                WHERE quantity <= min_quantity AND is_active = 1 
                ORDER BY quantity ASC LIMIT 10
            """)
            low_stock_products = []
            for row in cur.fetchall():
                low_stock_products.append({
                    "id": row[0],
                    "name": row[1],
                    "quantity": row[2],
                    "min_quantity": row[3],
                    "unit": row[4]
                })

        cur.close()
        conn.close()

        return jsonify({
            "success": True,
            "total_products": total_products,
            "total_value": total_value,
            "low_stock": low_stock,
            "categories": categories,
            "low_stock_products": low_stock_products
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@app.route('/admin/products/list')
def admin_products_list():
    """قائمة البضائع للإدارة"""
    try:
        search = request.args.get('search', '')
        category = request.args.get('category', '')

        conn = get_db_connection()
        cur = conn.cursor()

        if DATABASE_URL:
            query = """
                SELECT id, barcode, name, category, price, cost_price, quantity, 
                       min_quantity, unit, supplier, expiry_date, added_date 
                FROM products WHERE is_active = 1
            """
            params = []
            if search:
                query += " AND (name LIKE %s OR barcode LIKE %s)"
                params.append(f'%{search}%')
                params.append(f'%{search}%')
            if category:
                query += " AND category = %s"
                params.append(category)
            query += " ORDER BY name"
            cur.execute(query, params)
        else:
            query = """
                SELECT id, barcode, name, category, price, cost_price, quantity, 
                       min_quantity, unit, supplier, expiry_date, added_date 
                FROM products WHERE is_active = 1
            """
            params = []
            if search:
                query += " AND (name LIKE ? OR barcode LIKE ?)"
                params.append(f'%{search}%')
                params.append(f'%{search}%')
            if category:
                query += " AND category = ?"
                params.append(category)
            query += " ORDER BY name"
            cur.execute(query, params)

        products = []
        for row in cur.fetchall():
            products.append({
                "id": row[0],
                "barcode": row[1],
                "name": row[2],
                "category": row[3],
                "price": row[4],
                "cost_price": row[5],
                "quantity": row[6],
                "min_quantity": row[7],
                "unit": row[8],
                "supplier": row[9],
                "expiry_date": row[10],
                "added_date": row[11]
            })

        cur.close()
        conn.close()
        return jsonify({"success": True, "products": products})

    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@app.route('/admin/products/categories')
def product_categories():
    """الحصول على قائمة الفئات"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        if DATABASE_URL:
            cur.execute("SELECT DISTINCT category FROM products WHERE is_active = 1 ORDER BY category")
        else:
            cur.execute("SELECT DISTINCT category FROM products WHERE is_active = 1 ORDER BY category")

        categories = [row[0] for row in cur.fetchall() if row[0]]
        cur.close()
        conn.close()
        return jsonify({"success": True, "categories": categories})

    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@app.route('/admin/products/add', methods=['POST'])
def add_product():
    """إضافة منتج جديد"""
    try:
        data = request.json

        required_fields = ['barcode', 'name', 'price', 'quantity']
        for field in required_fields:
            if not data.get(field):
                return jsonify({"success": False, "message": f"حقل {field} مطلوب"})

        conn = get_db_connection()
        cur = conn.cursor()

        # التحقق من عدم تكرار الباركود
        if DATABASE_URL:
            cur.execute("SELECT id FROM products WHERE barcode = %s", (data['barcode'],))
        else:
            cur.execute("SELECT id FROM products WHERE barcode = ?", (data['barcode'],))

        if cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({"success": False, "message": "الباركود مسجل مسبقاً"})

        today = datetime.date.today().isoformat()

        if DATABASE_URL:
            cur.execute("""
                INSERT INTO products (
                    barcode, name, category, price, cost_price, quantity, 
                    min_quantity, unit, supplier, expiry_date, added_date, last_updated
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                data['barcode'],
                data['name'],
                data.get('category', 'مواد غذائية'),
                float(data['price']),
                float(data.get('cost_price', 0)),
                int(data['quantity']),
                int(data.get('min_quantity', 10)),
                data.get('unit', 'قطعة'),
                data.get('supplier', ''),
                data.get('expiry_date', ''),
                today,
                today
            ))
            product_id = cur.fetchone()[0]
        else:
            cur.execute("""
                INSERT INTO products (
                    barcode, name, category, price, cost_price, quantity, 
                    min_quantity, unit, supplier, expiry_date, added_date, last_updated
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data['barcode'],
                data['name'],
                data.get('category', 'مواد غذائية'),
                float(data['price']),
                float(data.get('cost_price', 0)),
                int(data['quantity']),
                int(data.get('min_quantity', 10)),
                data.get('unit', 'قطعة'),
                data.get('supplier', ''),
                data.get('expiry_date', ''),
                today,
                today
            ))
            product_id = cur.lastrowid

        # تسجيل حركة المخزون
        if DATABASE_URL:
            cur.execute("""
                INSERT INTO inventory_logs (
                    product_id, product_name, change_type, quantity_change,
                    old_quantity, new_quantity, notes, user, timestamp
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                product_id,
                data['name'],
                'إضافة',
                int(data['quantity']),
                0,
                int(data['quantity']),
                'إضافة منتج جديد',
                'admin',
                datetime.datetime.now().isoformat()
            ))
        else:
            cur.execute("""
                INSERT INTO inventory_logs (
                    product_id, product_name, change_type, quantity_change,
                    old_quantity, new_quantity, notes, user, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                product_id,
                data['name'],
                'إضافة',
                int(data['quantity']),
                0,
                int(data['quantity']),
                'إضافة منتج جديد',
                'admin',
                datetime.datetime.now().isoformat()
            ))

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"success": True, "message": "تم إضافة المنتج بنجاح"})

    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@app.route('/admin/products/<int:product_id>')
def get_product(product_id):
    """الحصول على بيانات منتج محدد"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        if DATABASE_URL:
            cur.execute("""
                SELECT id, name, price, quantity, category, barcode, unit, min_quantity
                FROM products WHERE id = %s AND is_active = 1
            """, (product_id,))
        else:
            cur.execute("""
                SELECT id, name, price, quantity, category, barcode, unit, min_quantity
                FROM products WHERE id = ? AND is_active = 1
            """, (product_id,))

        row = cur.fetchone()
        cur.close()
        conn.close()

        if row:
            return jsonify({
                "success": True,
                "product": {
                    "id": row[0],
                    "name": row[1],
                    "price": row[2],
                    "quantity": row[3],
                    "category": row[4],
                    "barcode": row[5],
                    "unit": row[6],
                    "min_quantity": row[7]
                }
            })
        else:
            return jsonify({"success": False, "message": "المنتج غير موجود"})

    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@app.route('/admin/products/update', methods=['POST'])
def update_product():
    """تحديث بيانات منتج"""
    try:
        data = request.json

        if not data.get('id'):
            return jsonify({"success": False, "message": "معرف المنتج مطلوب"})

        conn = get_db_connection()
        cur = conn.cursor()

        # الحصول على البيانات الحالية
        if DATABASE_URL:
            cur.execute("SELECT quantity, name FROM products WHERE id = %s", (data['id'],))
        else:
            cur.execute("SELECT quantity, name FROM products WHERE id = ?", (data['id'],))

        current = cur.fetchone()

        if not current:
            cur.close()
            conn.close()
            return jsonify({"success": False, "message": "المنتج غير موجود"})

        old_quantity = current[0]
        product_name = current[1]
        new_quantity = int(data.get('quantity', old_quantity))
        quantity_change = new_quantity - old_quantity

        # تحديث المنتج
        if DATABASE_URL:
            cur.execute("""
                UPDATE products 
                SET name = %s, price = %s, quantity = %s, last_updated = %s
                WHERE id = %s
            """, (
                data['name'],
                float(data['price']),
                new_quantity,
                datetime.date.today().isoformat(),
                data['id']
            ))
        else:
            cur.execute("""
                UPDATE products 
                SET name = ?, price = ?, quantity = ?, last_updated = ?
                WHERE id = ?
            """, (
                data['name'],
                float(data['price']),
                new_quantity,
                datetime.date.today().isoformat(),
                data['id']
            ))

        # تسجيل حركة المخزون إذا تغيرت الكمية
        if quantity_change != 0:
            if DATABASE_URL:
                cur.execute("""
                    INSERT INTO inventory_logs (
                        product_id, product_name, change_type, quantity_change,
                        old_quantity, new_quantity, notes, user, timestamp
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    data['id'],
                    product_name,
                    'تعديل',
                    quantity_change,
                    old_quantity,
                    new_quantity,
                    'تعديل المنتج',
                    'admin',
                    datetime.datetime.now().isoformat()
                ))
            else:
                cur.execute("""
                    INSERT INTO inventory_logs (
                        product_id, product_name, change_type, quantity_change,
                        old_quantity, new_quantity, notes, user, timestamp
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    data['id'],
                    product_name,
                    'تعديل',
                    quantity_change,
                    old_quantity,
                    new_quantity,
                    'تعديل المنتج',
                    'admin',
                    datetime.datetime.now().isoformat()
                ))

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"success": True, "message": "تم تحديث المنتج بنجاح"})

    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@app.route('/admin/products/delete/<int:product_id>', methods=['DELETE'])
def delete_product(product_id):
    """حذف منتج"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # الحصول على بيانات المنتج قبل الحذف
        if DATABASE_URL:
            cur.execute("SELECT name, quantity FROM products WHERE id = %s", (product_id,))
        else:
            cur.execute("SELECT name, quantity FROM products WHERE id = ?", (product_id,))

        product = cur.fetchone()

        if not product:
            cur.close()
            conn.close()
            return jsonify({"success": False, "message": "المنتج غير موجود"})

        # حذف منطقي (تغيير الحالة)
        if DATABASE_URL:
            cur.execute("UPDATE products SET is_active = 0 WHERE id = %s", (product_id,))
        else:
            cur.execute("UPDATE products SET is_active = 0 WHERE id = ?", (product_id,))

        # تسجيل حركة المخزون
        if DATABASE_URL:
            cur.execute("""
                INSERT INTO inventory_logs (
                    product_id, product_name, change_type, quantity_change,
                    old_quantity, new_quantity, notes, user, timestamp
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                product_id,
                product[0],
                'حذف',
                -product[1],
                product[1],
                0,
                'حذف المنتج',
                'admin',
                datetime.datetime.now().isoformat()
            ))
        else:
            cur.execute("""
                INSERT INTO inventory_logs (
                    product_id, product_name, change_type, quantity_change,
                    old_quantity, new_quantity, notes, user, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                product_id,
                product[0],
                'حذف',
                -product[1],
                product[1],
                0,
                'حذف المنتج',
                'admin',
                datetime.datetime.now().isoformat()
            ))

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"success": True, "message": "تم حذف المنتج بنجاح"})

    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@app.route('/admin/products/logs')
def inventory_logs():
    """سجل حركات المخزون"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        if DATABASE_URL:
            cur.execute("""
                SELECT product_name, change_type, quantity_change, 
                       old_quantity, new_quantity, notes, user, timestamp
                FROM inventory_logs 
                ORDER BY timestamp DESC 
                LIMIT 50
            """)
        else:
            cur.execute("""
                SELECT product_name, change_type, quantity_change, 
                       old_quantity, new_quantity, notes, user, timestamp
                FROM inventory_logs 
                ORDER BY timestamp DESC 
                LIMIT 50
            """)

        logs = []
        for row in cur.fetchall():
            logs.append({
                "product_name": row[0],
                "change_type": row[1],
                "quantity_change": row[2],
                "old_quantity": row[3],
                "new_quantity": row[4],
                "notes": row[5],
                "user": row[6],
                "timestamp": row[7]
            })

        cur.close()
        conn.close()
        return jsonify({"success": True, "logs": logs})

    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


# =============================== واجهات الإدارة الأصلية ===============================
@app.route('/admin')
def admin_dashboard():
    return render_template_string('''
    <!DOCTYPE html>
    <html dir="rtl" lang="ar">
    <head>
        <meta charset="UTF-8">
        <title>لوحة التحكم الرئيسية</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { background: #000; padding: 20px; font-family: Arial; }
            .header { background: #111; color: #FFD700; padding: 20px; border-radius: 10px; margin-bottom: 20px; text-align: center; border: 1px solid #FFD700; }
            .dashboard-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; }
            .dashboard-card { background: #111; padding: 30px; border-radius: 15px; box-shadow: 0 5px 15px rgba(255,215,0,0.2); text-align: center; cursor: pointer; transition: transform 0.3s; border: 1px solid #FFD700; color: #FFD700; }
            .dashboard-card:hover { transform: translateY(-5px); }
            .card-icon { font-size: 48px; margin-bottom: 15px; }
            h2 { color: #FFD700; margin-bottom: 10px; }
            .card-description { color: #FFD700; opacity: 0.8; }
            .products { border-top: 4px solid #FFD700; }
            .customers { border-top: 4px solid #FFD700; }
            .stats { border-top: 4px solid #FFD700; }
            .add { border-top: 4px solid #FFD700; }
        </style>
    </head>
    <body>
        <div class="header">
            <h1>🎛️ لوحة تحكم الإدارة - سوبر ماركت اولاد قايد محمد</h1>
            <p>إدارة كاملة للنظام</p>
            <p>تحت اشراف  م/ وسيم العامري</p>
        </div>
        
        <div style="background: #111; padding: 20px; border-radius: 10px; margin-bottom: 20px; border: 1px solid #FFD700; color: #FFD700;">
            <h3>المميزات:</h3>
            <ul style="list-style: none; padding-right: 20px;">
                <li>• إدارة كاملة للبضائع (إضافة/تعديل/حذف)</li>
                <li>• متابعة المخزون والتنبيهات</li>
                <li>• حركات المخزون وتتبع التغيرات</li>
                <li>• عرض البضائع للعملاء</li>
                <li>• نظام كامل لإدارة المتجر</li>
            </ul>
        </div>

        <div class="dashboard-grid">
            <div class="dashboard-card products" onclick="location.href='/admin/products'">
                <div class="card-icon">📦</div>
                <h2>إدارة البضائع</h2>
                <p class="card-description">إضافة، تعديل، وحذف المنتجات، وإدارة المخزون</p>
            </div>

            <div class="dashboard-card customers" onclick="location.href='/admin/customers'">
                <div class="card-icon">👥</div>
                <h2>إدارة العملاء</h2>
                <p class="card-description">عرض العملاء، النقاط، والزيارات</p>
            </div>

            <div class="dashboard-card stats" onclick="location.href='/stats'">
                <div class="card-icon">📊</div>
                <h2>الإحصائيات</h2>
                <p class="card-description">إحصائيات المبيعات والعملاء</p>
            </div>

            <div class="dashboard-card add" onclick="location.href='/add'">
                <div class="card-icon">➕</div>
                <h2>إضافة عميل</h2>
                <p class="card-description">إضافة عميل جديد للنظام</p>
            </div>
        </div>
    </body>
    </html>
    ''')


@app.route('/stats')
def stats():
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        if DATABASE_URL:
            cur.execute("SELECT COUNT(*) FROM customers")
            total_customers = cur.fetchone()[0] or 0

            cur.execute("SELECT COUNT(*) FROM customers WHERE is_active = 1")
            active_customers = cur.fetchone()[0] or 0

            cur.execute("SELECT SUM(total_spent) FROM customers")
            total_spent = cur.fetchone()[0] or 0

            cur.execute("SELECT SUM(loyalty_points) FROM customers")
            total_points = cur.fetchone()[0] or 0

            cur.execute("SELECT COUNT(*) FROM products WHERE is_active = 1")
            total_products = cur.fetchone()[0] or 0

            cur.execute("SELECT SUM(price * quantity) FROM products WHERE is_active = 1")
            inventory_value = cur.fetchone()[0] or 0
        else:
            cur.execute("SELECT COUNT(*) FROM customers")
            total_customers = cur.fetchone()[0] or 0

            cur.execute("SELECT COUNT(*) FROM customers WHERE is_active = 1")
            active_customers = cur.fetchone()[0] or 0

            cur.execute("SELECT SUM(total_spent) FROM customers")
            total_spent = cur.fetchone()[0] or 0

            cur.execute("SELECT SUM(loyalty_points) FROM customers")
            total_points = cur.fetchone()[0] or 0

            cur.execute("SELECT COUNT(*) FROM products WHERE is_active = 1")
            total_products = cur.fetchone()[0] or 0

            cur.execute("SELECT SUM(price * quantity) FROM products WHERE is_active = 1")
            inventory_value = cur.fetchone()[0] or 0

        cur.close()
        conn.close()

        return f'''
        <!DOCTYPE html>
        <html dir="rtl" lang="ar">
        <head>
            <meta charset="UTF-8">
            <title>الإحصائيات</title>
            <style>
                * {{ margin: 0; padding: 0; box-sizing: border-box; }}
                body {{ background: #000; padding: 20px; font-family: Arial; }}
                .header {{ background: #111; color: #FFD700; padding: 20px; border-radius: 10px; margin-bottom: 20px; border: 1px solid #FFD700; }}
                .stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 20px; }}
                .stat-card {{ background: #111; padding: 25px; border-radius: 10px; box-shadow: 0 5px 15px rgba(255,215,0,0.2); text-align: center; border: 1px solid #FFD700; color: #FFD700; }}
                .stat-number {{ font-size: 36px; font-weight: bold; color: #FFD700; margin: 10px 0; }}
                .stat-label {{ color: #FFD700; font-size: 18px; opacity: 0.8; }}
                .back-btn {{ display: block; width: 200px; margin: 30px auto; padding: 15px; background: #FFD700; color: #000; text-align: center; text-decoration: none; border-radius: 8px; font-weight: bold; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>📊 الإحصائيات الشاملة</h1>
                <p>نظرة عامة على أداء المتجر</p>
            </div>

            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-number">{total_customers}</div>
                    <div class="stat-label">👥 إجمالي العملاء</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{active_customers}</div>
                    <div class="stat-label">✅ عملاء نشطين</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{total_spent:.2f} ر.س</div>
                    <div class="stat-label">💰 إجمالي المبيعات</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{total_points}</div>
                    <div class="stat-label">⭐ إجمالي النقاط</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{total_products}</div>
                    <div class="stat-label">📦 المنتجات</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{inventory_value:.2f} ر.س</div>
                    <div class="stat-label">🏪 قيمة المخزون</div>
                </div>
            </div>

            <a href="/admin" class="back-btn">← العودة للوحة التحكم</a>
        </body>
        </html>
        '''
    except Exception as e:
        return f"خطأ: {str(e)}"


@app.route('/admin/customers')
def admin_customers_list():
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        if DATABASE_URL:
            cur.execute("""
                SELECT phone, name, loyalty_points, total_spent, visits, last_visit, customer_tier
                FROM customers WHERE is_active = 1 ORDER BY total_spent DESC
            """)
        else:
            cur.execute("""
                SELECT phone, name, loyalty_points, total_spent, visits, last_visit, customer_tier
                FROM customers WHERE is_active = 1 ORDER BY total_spent DESC
            """)

        customers_list = cur.fetchall()
        cur.close()
        conn.close()

        html = '''
        <!DOCTYPE html>
        <html dir="rtl" lang="ar">
        <head>
            <meta charset="UTF-8">
            <title>قائمة العملاء</title>
            <style>
                * { margin: 0; padding: 0; box-sizing: border-box; }
                body { background: #000; padding: 20px; font-family: Arial; }
                .header { background: #111; color: #FFD700; padding: 20px; border-radius: 10px; margin-bottom: 20px; border: 1px solid #FFD700; }
                table { width: 100%; background: #111; border-radius: 10px; overflow: hidden; box-shadow: 0 5px 15px rgba(255,215,0,0.2); border: 1px solid #FFD700; }
                th { background: #FFD700; color: #000; padding: 15px; text-align: right; }
                td { padding: 12px; border-bottom: 1px solid #FFD700; color: #FFD700; }
                .back-btn { display: block; width: 200px; margin: 30px auto; padding: 15px; background: #FFD700; color: #000; text-align: center; text-decoration: none; border-radius: 8px; font-weight: bold; }
            </style>
        </head>
        <body>
            <div class="header">
                <h1>👥 قائمة العملاء</h1>
                <p>عرض جميع العملاء المسجلين في النظام</p>
            </div>
            <table>
                <thead>
                    <tr>
                        <th>الاسم</th><th>الهاتف</th><th>النقاط</th><th>الإنفاق</th><th>الزيارات</th><th>آخر زيارة</th><th>المستوى</th>
                    </tr>
                </thead>
                <tbody>
        '''

        for customer in customers_list:
            html += f'''
                <tr>
                    <td>{customer[1]}</td>
                    <td>{customer[0]}</td>
                    <td>{customer[2]}</td>
                    <td>{customer[3]:.2f} ريال</td>
                    <td>{customer[4]}</td>
                    <td>{customer[5]}</td>
                    <td>{customer[6] or 'عادي'}</td>
                </tr>
            '''

        html += '''
                </tbody>
            </table>
            <a href="/admin" class="back-btn">← العودة للوحة التحكم</a>
        </body>
        </html>
        '''

        return html
    except Exception as e:
        return f"خطأ: {str(e)}"


@app.route('/add')
def add_page():
    return '''
    <!DOCTYPE html>
    <html dir="rtl" lang="ar">
    <head>
        <meta charset="UTF-8">
        <title>إضافة عميل</title>
        <style>
            body { padding: 40px; font-family: Arial; background: #000; }
            .container { max-width: 400px; margin: auto; background: #111; padding: 30px; border-radius: 10px; box-shadow: 0 5px 15px rgba(255,215,0,0.2); border: 1px solid #FFD700; }
            h2 { color: #FFD700; margin-bottom: 20px; }
            input { display:block; margin:15px 0; padding:12px; width:100%; border:2px solid #FFD700; border-radius:8px; font-size:16px; background: #000; color: #FFD700; }
            button { background: #FFD700; color: #000; border: none; padding: 15px; width:100%; border-radius:8px; font-size:18px; cursor:pointer; font-weight: bold; }
            .back { background: #000; color: #FFD700; border: 1px solid #FFD700; margin-top: 10px; }
            #msg { color: #FFD700; margin-top:15px; }
        </style>
    </head>
    <body>
        <div class="container">
            <h2>➕ إضافة عميل جديد</h2>
            <input id="name" placeholder="الاسم الكامل" required>
            <input id="phone" placeholder="رقم الهاتف" required>
            <button onclick="addCustomer()">حفظ العميل</button>
            <button class="back" onclick="location.href='/admin'">العودة للوحة التحكم</button>
            <p id="msg" style="margin-top:15px;"></p>
        </div>
        <script>
            function addCustomer() {
                const name = document.getElementById('name').value.trim();
                const phone = document.getElementById('phone').value.trim();
                if (!name || !phone) {
                    document.getElementById('msg').innerText = '⚠ جميع الحقول مطلوبة';
                    return;
                }
                fetch('/add_customer', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ name, phone })
                })
                .then(r => r.json())
                .then(data => { 
                    document.getElementById('msg').innerText = data.message;
                    if (data.success) {
                        document.getElementById('name').value = '';
                        document.getElementById('phone').value = '';
                    }
                });
            }
        </script>
    </body>
    </html>
    '''


@app.route('/add_customer', methods=['POST'])
def add_customer():
    try:
        data = request.json
        phone = data.get('phone')
        name = data.get('name')

        if not phone or not name:
            return jsonify({"success": False, "message": "الاسم والهاتف مطلوبان"})

        conn = get_db_connection()
        cur = conn.cursor()

        try:
            if DATABASE_URL:
                cur.execute("""
                    INSERT INTO customers (phone, name, last_visit)
                    VALUES (%s, %s, %s)
                """, (phone, name, datetime.date.today().isoformat()))
            else:
                cur.execute("""
                    INSERT INTO customers (phone, name, last_visit)
                    VALUES (?, ?, ?)
                """, (phone, name, datetime.date.today().isoformat()))

            conn.commit()
            cur.close()
            conn.close()
            return jsonify({"success": True, "message": "✅ تم إضافة العميل بنجاح"})
        except Exception as e:
            if "unique" in str(e).lower() or "duplicate" in str(e).lower():
                return jsonify({"success": False, "message": "⚠ رقم الهاتف مسجل مسبقاً"})
            else:
                raise
    except Exception as e:
        return jsonify({"success": False, "message": f"خطأ: {str(e)}"})


# =============================== أفكار تطوير النظام ===============================
# 1. إضافة نظام تسجيل دخول للمديرين (Admin Login) مع صلاحيات مختلفة.
# 2. إضافة نظام فواتير (Invoicing) بحيث يمكن طباعة فاتورة بعد كل عملية بيع.
# 3. إضافة تقارير متقدمة (مبيعات يومية/شهرية، أفضل المنتجات مبيعاً، العملاء الأكثر إنفاقاً).
# 4. إمكانية مسح الباركود باستخدام كاميرا الهاتف (من واجهة العملاء).
# 5. إضافة نظام تنبيهات عند انخفاض المخزون (إشعارات داخلية أو عبر البريد الإلكتروني).
# 6. دعم متعدد اللغات (عربي/إنجليزي).
# 7. إضافة نظام خصومات (Coupons) يمكن للعملاء استخدامها.
# 8. تحسين أداء البحث وإضافة Pagination للقوائم الطويلة.
# 9. إضافة إمكانية رفع صور للمنتجات.
# 10. عمل تطبيق جوال (PWA) ليتم تثبيته على الهواتف.

# =============================== التشغيل الرئيسي ===============================
if __name__ == '__main__':
    print("=" * 70)
    print("🚀 نظام نقاط العملاء وإدارة البضائع - سوبر ماركت اولاد قايد محمد")
    print("=" * 70)
    print("📁 قاعدة البيانات: " + ("PostgreSQL" if DATABASE_URL else "SQLite local"))
    print("🌐 الروابط المتاحة:")
    print("   👉 http://localhost:5000/            (للعملاء - الرئيسية)")
    print("   👉 http://localhost:5000/admin       (للإدارة - لوحة التحكم)")
    print("   👉 http://localhost:5000/admin/products (إدارة البضائع)")
    print("   👉 http://localhost:5000/stats       (الإحصائيات)")
    print("   👉 http://localhost:5000/add         (إضافة عميل)")
    print("   👉 http://localhost:5000/admin/customers (قائمة العملاء)")
    print("=" * 70)
    print("📦 المميزات المضافة:")
    print("   • إدارة كاملة للبضائع (إضافة/تعديل/حذف)")
    print("   • متابعة المخزون والتنبيهات")
    print("   • حركات المخزون وتتبع التغيرات")
    print("   • عرض البضائع للعملاء مع إضافة إلى السلة")
    print("   • إرسال الطلب عبر واتساب إلى رقم المتجر: 967770295876")
    print("   • نظام كامل لإدارة المتجر")
    print("=" * 70)
    print("🎨 تم تغيير ألوان الواجهات إلى الأسود والذهبي.")
    print("💡 أفكار للتطوير موجودة في نهاية الكود.")
    print("=" * 70)
    print("⏳ جاري التشغيل...")
    app.run(host='127.0.0.1', port=5000, debug=True)
