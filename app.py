"""
تطبيق ويب لنظام نقاط العملاء وإدارة البضائع - سوبر ماركت اولاد قايد محمد
يدعم قواعد البيانات SQLite (للتطوير المحلي) و PostgreSQL (للإنتاج على Render)
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
        # SQLite (الكود الأصلي مع تعديل بسيط)
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


# =============================== واجهات العملاء (المعدلة) ===============================
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
            body { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; padding: 20px; }
            .container { max-width: 1400px; margin: 0 auto; display: grid; grid-template-columns: 1fr 350px; gap: 20px; }
            @media (max-width: 768px) { .container { grid-template-columns: 1fr; } }
            .main-content { background: rgba(255,255,255,0.1); border-radius: 20px; padding: 20px; backdrop-filter: blur(10px); }
            .cart-sidebar { background: white; border-radius: 20px; padding: 20px; box-shadow: 0 10px 30px rgba(0,0,0,0.2); height: fit-content; position: sticky; top: 20px; }
            h1 { color: white; text-align: center; margin-bottom: 20px; font-size: 2em; text-shadow: 2px 2px 4px rgba(0,0,0,0.3); }
            .nav { display: flex; gap: 10px; margin-bottom: 25px; flex-wrap: wrap; }
            .nav button { flex: 1; padding: 15px; background: rgba(255,255,255,0.2); color: white; border: none; border-radius: 12px; cursor: pointer; font-size: 18px; font-weight: bold; transition: 0.3s; min-width: 120px; }
            .nav button.active { background: #4CAF50; box-shadow: 0 5px 15px rgba(76,175,80,0.4); }
            .nav button:hover { transform: translateY(-2px); }
            .section { display: none; }
            .section.active { display: block; }
            .filters { display: flex; gap: 15px; margin-bottom: 25px; flex-wrap: wrap; }
            .filters select, .filters input { flex: 1; padding: 15px; border: none; border-radius: 12px; font-size: 16px; background: white; box-shadow: 0 3px 10px rgba(0,0,0,0.1); }
            .products-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 20px; }
            .product-card { background: white; border-radius: 15px; padding: 20px; text-align: center; box-shadow: 0 5px 15px rgba(0,0,0,0.1); transition: 0.3s; }
            .product-card:hover { transform: translateY(-5px); box-shadow: 0 10px 25px rgba(0,0,0,0.2); }
            .product-icon { font-size: 50px; margin-bottom: 10px; }
            .product-name { font-weight: bold; font-size: 18px; color: #333; margin-bottom: 5px; }
            .product-price { color: #e74c3c; font-size: 22px; font-weight: bold; margin: 10px 0; }
            .product-stock { color: #27ae60; font-size: 14px; margin-bottom: 15px; }
            .add-to-cart-btn { background: #3498db; color: white; border: none; padding: 12px; border-radius: 8px; width: 100%; font-size: 16px; cursor: pointer; transition: 0.3s; display: flex; align-items: center; justify-content: center; gap: 5px; }
            .add-to-cart-btn:hover { background: #2980b9; }
            .cart-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; padding-bottom: 15px; border-bottom: 2px solid #eee; }
            .cart-header h3 { color: #2c3e50; }
            .cart-items { max-height: 400px; overflow-y: auto; margin-bottom: 20px; }
            .cart-item { display: flex; justify-content: space-between; align-items: center; padding: 10px; background: #f8f9fa; border-radius: 8px; margin-bottom: 10px; }
            .cart-item-info { flex: 1; }
            .cart-item-name { font-weight: bold; color: #2c3e50; }
            .cart-item-price { color: #e74c3c; font-size: 14px; }
            .cart-item-actions { display: flex; gap: 5px; }
            .cart-item-actions button { background: none; border: none; cursor: pointer; font-size: 18px; padding: 5px; }
            .cart-total { background: #2c3e50; color: white; padding: 15px; border-radius: 10px; text-align: center; font-size: 20px; font-weight: bold; margin-top: 20px; }
            .whatsapp-btn { background: #25D366; color: white; border: none; padding: 15px; border-radius: 10px; width: 100%; font-size: 18px; font-weight: bold; cursor: pointer; margin-top: 15px; display: flex; align-items: center; justify-content: center; gap: 10px; transition: 0.3s; }
            .whatsapp-btn:hover { background: #128C7E; }
            .clear-cart-btn { background: #e74c3c; color: white; border: none; padding: 10px; border-radius: 5px; cursor: pointer; font-size: 14px; }
            .offer-card { background: white; border-radius: 15px; padding: 20px; margin-bottom: 15px; text-align: center; }
            .offer-code { background: #f1c40f; color: #2c3e50; padding: 5px 10px; border-radius: 5px; display: inline-block; margin-top: 10px; font-weight: bold; }
        </style>
    </head>
    <body>
        <h1>🛒 سوبر ماركت اولاد قايد محمد</h1>
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
                    <div style="background: white; border-radius: 15px; padding: 25px;">
                        <input type="tel" id="phone" placeholder="📱 أدخل رقم الهاتف" style="width:100%; padding:15px; border:2px solid #ddd; border-radius:10px; margin-bottom:15px;">
                        <button onclick="checkPoints()" style="background:#4CAF50; color:white; border:none; padding:15px; width:100%; border-radius:10px; font-size:18px;">🔍 استعلام عن النقاط</button>
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
                    <p style="text-align:center; color:#7f8c8d;">السلة فارغة</p>
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
                resultDiv.innerHTML = '<p>جاري البحث...</p>';
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
                            <div style="background:#e8f5e9; color:#2e7d32; padding:20px; border-radius:10px;">
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
                resultDiv.innerHTML = '<p style="color:white;">جاري تحميل المنتجات...</p>';
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
                            resultDiv.innerHTML = html || '<p style="color:white;">لا توجد منتجات</p>';
                        } else {
                            resultDiv.innerHTML = `<p style="color:white;">❌ ${data.message}</p>`;
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
                    cartDiv.innerHTML = '<p style="text-align:center; color:#7f8c8d;">السلة فارغة</p>';
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

            // إرسال الطلب عبر واتساب
            function sendWhatsApp() {
                if (cart.length === 0) {
                    alert('السلة فارغة، أضف منتجات أولاً');
                    return;
                }
                let message = '*طلب جديد من سوبر ماركت اولاد قايد محمد*%0A';
                let total = 0;
                cart.forEach(item => {
                    const itemTotal = item.price * item.quantity;
                    message += `- ${item.name} (${item.price} ريال) × ${item.quantity} = ${itemTotal} ريال%0A`;
                    total += itemTotal;
                });
                message += `%0A*الإجمالي: ${total} ريال*`;
                window.open(`https://wa.me/?text=${message}`, '_blank');
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


# =============================== واجهات البضائع (معدلة لإرجاع id) ===============================
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
        {"title": "خصم 10%", "description": "على مشترياتك القادمة", "code": "DISCOUNT10"},
        {"title": "توصيل مجاني", "description": "للطلبات فوق 100 ريال", "code": "FREESHIP"},
        {"title": "هدية مجانية", "description": "مع كل شراء فوق 200 ريال", "code": "FREE_GIFT"},
        {"title": "نقاط مضاعفة", "description": "في نهاية الأسبوع", "code": "DOUBLE_POINTS"}
    ]
    return jsonify({"success": True, "offers": offers})


# =============================== واجهات إدارة البضائع (بدون تغيير) ===============================
@app.route('/admin/products')
def admin_products():
    # نفس الكود الأصلي (تم حذفه للاختصار، لكنه موجود في الملف الكامل)
    return render_template_string('''
    <!DOCTYPE html>
    <html dir="rtl" lang="ar">
    ... (كما هو في السابق، لم يتغير) ...
    ''')


@app.route('/admin/products/stats')
def products_stats():
    # ... (نفس الكود الأصلي) ...
    pass


@app.route('/admin/products/list')
def admin_products_list():
    # ... (نفس الكود الأصلي) ...
    pass


@app.route('/admin/products/categories')
def product_categories():
    # ... (نفس الكود الأصلي) ...
    pass


@app.route('/admin/products/add', methods=['POST'])
def add_product():
    # ... (نفس الكود الأصلي) ...
    pass


@app.route('/admin/products/<int:product_id>')
def get_product(product_id):
    # ... (نفس الكود الأصلي) ...
    pass


@app.route('/admin/products/update', methods=['POST'])
def update_product():
    # ... (نفس الكود الأصلي) ...
    pass


@app.route('/admin/products/delete/<int:product_id>', methods=['DELETE'])
def delete_product(product_id):
    # ... (نفس الكود الأصلي) ...
    pass


@app.route('/admin/products/logs')
def inventory_logs():
    # ... (نفس الكود الأصلي) ...
    pass


# =============================== واجهات الإدارة الأصلية ===============================
@app.route('/admin')
def admin_dashboard():
    return render_template_string('''
    <!DOCTYPE html>
    <html dir="rtl" lang="ar">
    ... (كما هو في السابق) ...
    ''')


@app.route('/stats')
def stats():
    # ... (نفس الكود الأصلي) ...
    pass


@app.route('/admin/customers')
def admin_customers_list():
    # ... (نفس الكود الأصلي) ...
    pass


@app.route('/add')
def add_page():
    # ... (نفس الكود الأصلي) ...
    pass


@app.route('/add_customer', methods=['POST'])
def add_customer():
    # ... (نفس الكود الأصلي) ...
    pass


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
    print("   • إرسال الطلب عبر واتساب")
    print("   • نظام كامل لإدارة المتجر")
    print("=" * 70)
    print("⏳ جاري التشغيل...")
    app.run(host='127.0.0.1', port=5000, debug=True)
