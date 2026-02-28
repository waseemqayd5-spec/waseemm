"""
تطبيق ويب لنظام نقاط العملاء وإدارة البضائع - سوبر ماركت اولاد قايد محمد
نسخة متوافقة مع Render (تستخدم /tmp للتخزين المؤقت)
"""

# =============================== الاستيرادات ===============================
from flask import Flask, request, jsonify
import sqlite3
import os
import datetime

app = Flask(__name__)

# =============================== إعداد مسار قاعدة البيانات ===============================
def get_db_path():
    """تحديد مسار قاعدة البيانات حسب بيئة التشغيل (محلي أو Render)"""
    if 'RENDER' in os.environ:
        # على Render، نستخدم المجلد /tmp القابل للكتابة
        return '/tmp/supermarket.db'
    else:
        # محلياً، نستخدم مجلد data
        if not os.path.exists('data'):
            os.makedirs('data')
        return 'data/supermarket.db'

# =============================== تهيئة قاعدة البيانات ===============================
def init_db():
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # جدول العملاء
    cursor.execute("""
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

    # جدول البضائع
    cursor.execute("""
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

    # جدول حركات المخزون
    cursor.execute("""
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

    # إضافة عميل افتراضي إذا كانت قاعدة البيانات فارغة
    cursor.execute("SELECT COUNT(*) FROM customers")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
            INSERT INTO customers (phone, name, loyalty_points, total_spent, visits, last_visit)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("0500000000", "عميل تجريبي", 50, 200.0, 5, datetime.date.today().isoformat()))

    # إضافة بضائع افتراضية إذا كانت قاعدة البيانات فارغة
    cursor.execute("SELECT COUNT(*) FROM products")
    if cursor.fetchone()[0] == 0:
        today = datetime.date.today()
        future_date = today + datetime.timedelta(days=180)

        default_products = [
            ("8801234567890", "أرز بسمتي", "مواد غذائية", 25.0, 18.0, 50, 10, "كيلو", "مورد الأرز", future_date.isoformat()),
            ("8809876543210", "سكر", "مواد غذائية", 15.0, 11.0, 100, 20, "كيلو", "مورد السكر", future_date.isoformat()),
            ("8801122334455", "زيت دوار الشمس", "مواد غذائية", 35.0, 28.0, 30, 10, "لتر", "مورد الزيوت", future_date.isoformat()),
            ("8805566778899", "حليب طازج", "مبردات", 8.0, 6.0, 40, 15, "لتر", "شركة الألبان", (today + datetime.timedelta(days=14)).isoformat()),
            ("8809988776655", "شاي", "مواد غذائية", 20.0, 15.0, 60, 15, "علبة", "مورد الشاي", future_date.isoformat()),
        ]

        for barcode, name, category, price, cost, quantity, min_qty, unit, supplier, expiry in default_products:
            cursor.execute("""
                INSERT INTO products (barcode, name, category, price, cost_price, quantity, min_quantity, unit, supplier, expiry_date, added_date, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (barcode, name, category, price, cost, quantity, min_qty, unit, supplier, expiry, today.isoformat(), today.isoformat()))

    conn.commit()
    conn.close()
    print(f"✅ قاعدة البيانات جاهزة في: {db_path}")

# =============================== واجهات العملاء ===============================
@app.route('/')
def home():
    return '''<!DOCTYPE html>...'''  # (هنا ضع كود HTML الكامل للصفحة الرئيسية - سبق أن كتبناه)

@app.route('/check_points', methods=['POST'])
def check_points():
    try:
        phone = request.json.get('phone')
        if not phone:
            return jsonify({"success": False, "message": "رقم الهاتف مطلوب"})

        conn = sqlite3.connect(get_db_path())
        cursor = conn.cursor()
        cursor.execute("""
            SELECT name, loyalty_points, total_spent, visits, last_visit, customer_tier
            FROM customers WHERE phone = ? AND is_active = 1
        """, (phone,))
        customer = cursor.fetchone()
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
            return jsonify({"success": False, "message": "رقم الهاتف غير مسجل"})
    except Exception as e:
        return jsonify({"success": False, "message": f"خطأ: {str(e)}"})

@app.route('/products')
def get_products():
    try:
        category = request.args.get('category', '')
        search = request.args.get('search', '')
        conn = sqlite3.connect(get_db_path())
        cursor = conn.cursor()

        query = "SELECT name, price, quantity, unit, category FROM products WHERE is_active = 1"
        params = []
        if category:
            query += " AND category = ?"
            params.append(category)
        if search:
            query += " AND (name LIKE ? OR barcode LIKE ?)"
            params.append(f'%{search}%')
            params.append(f'%{search}%')
        query += " ORDER BY name"

        cursor.execute(query, params)
        products = cursor.fetchall()
        conn.close()

        products_list = [{"name": p[0], "price": p[1], "quantity": p[2], "unit": p[3], "category": p[4]} for p in products]
        return jsonify({"success": True, "products": products_list})
    except Exception as e:
        return jsonify({"success": False, "message": f"خطأ: {str(e)}"})

@app.route('/offers')
def get_offers():
    offers = [
        {"title": "خصم 10%", "description": "على مشترياتك القادمة", "code": "DISCOUNT10"},
        {"title": "توصيل مجاني", "description": "للطلبات فوق 100 ريال", "code": "FREESHIP"},
        {"title": "هدية مجانية", "description": "مع كل شراء فوق 200 ريال", "code": "FREE_GIFT"},
        {"title": "نقاط مضاعفة", "description": "في نهاية الأسبوع", "code": "DOUBLE_POINTS"}
    ]
    return jsonify({"success": True, "offers": offers})

# =============================== واجهات إدارة البضائع ===============================
@app.route('/admin/products')
def admin_products():
    return '''<!DOCTYPE html>...'''  # (ضع كود HTML لإدارة البضائع هنا - سبق أن كتبناه)

@app.route('/admin/products/stats')
def products_stats():
    try:
        conn = sqlite3.connect(get_db_path())
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM products WHERE is_active = 1")
        total_products = cursor.fetchone()[0] or 0

        cursor.execute("SELECT SUM(price * quantity) FROM products WHERE is_active = 1")
        total_value = cursor.fetchone()[0] or 0

        cursor.execute("SELECT COUNT(*) FROM products WHERE quantity <= min_quantity AND quantity > 0 AND is_active = 1")
        low_stock = cursor.fetchone()[0] or 0

        cursor.execute("SELECT COUNT(DISTINCT category) FROM products WHERE is_active = 1")
        categories = cursor.fetchone()[0] or 0

        cursor.execute("SELECT id, name, quantity, min_quantity, unit FROM products WHERE quantity <= min_quantity AND is_active = 1 ORDER BY quantity ASC LIMIT 10")
        low_stock_products = [{"id": r[0], "name": r[1], "quantity": r[2], "min_quantity": r[3], "unit": r[4]} for r in cursor.fetchall()]

        conn.close()
        return jsonify({"success": True, "total_products": total_products, "total_value": total_value, "low_stock": low_stock, "categories": categories, "low_stock_products": low_stock_products})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

@app.route('/admin/products/list')
def admin_products_list():
    try:
        search = request.args.get('search', '')
        category = request.args.get('category', '')
        conn = sqlite3.connect(get_db_path())
        cursor = conn.cursor()

        query = "SELECT id, barcode, name, category, price, cost_price, quantity, min_quantity, unit, supplier, expiry_date, added_date FROM products WHERE is_active = 1"
        params = []
        if search:
            query += " AND (name LIKE ? OR barcode LIKE ?)"
            params.append(f'%{search}%')
            params.append(f'%{search}%')
        if category:
            query += " AND category = ?"
            params.append(category)
        query += " ORDER BY name"

        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()

        products = []
        for r in rows:
            products.append({
                "id": r[0], "barcode": r[1], "name": r[2], "category": r[3], "price": r[4],
                "cost_price": r[5], "quantity": r[6], "min_quantity": r[7], "unit": r[8],
                "supplier": r[9], "expiry_date": r[10], "added_date": r[11]
            })
        return jsonify({"success": True, "products": products})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

@app.route('/admin/products/categories')
def product_categories():
    try:
        conn = sqlite3.connect(get_db_path())
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT category FROM products WHERE is_active = 1 ORDER BY category")
        categories = [row[0] for row in cursor.fetchall() if row[0]]
        conn.close()
        return jsonify({"success": True, "categories": categories})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

@app.route('/admin/products/add', methods=['POST'])
def add_product():
    try:
        data = request.json
        required = ['barcode', 'name', 'price', 'quantity']
        for field in required:
            if not data.get(field):
                return jsonify({"success": False, "message": f"حقل {field} مطلوب"})

        conn = sqlite3.connect(get_db_path())
        cursor = conn.cursor()

        # التحقق من الباركود
        cursor.execute("SELECT id FROM products WHERE barcode = ?", (data['barcode'],))
        if cursor.fetchone():
            conn.close()
            return jsonify({"success": False, "message": "الباركود مسجل مسبقاً"})

        today = datetime.date.today().isoformat()
        cursor.execute("""
            INSERT INTO products (barcode, name, category, price, cost_price, quantity, min_quantity, unit, supplier, expiry_date, added_date, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data['barcode'], data['name'], data.get('category', 'مواد غذائية'), float(data['price']),
            float(data.get('cost_price', 0)), int(data['quantity']), int(data.get('min_quantity', 10)),
            data.get('unit', 'قطعة'), data.get('supplier', ''), data.get('expiry_date', ''), today, today
        ))
        product_id = cursor.lastrowid

        cursor.execute("""
            INSERT INTO inventory_logs (product_id, product_name, change_type, quantity_change, old_quantity, new_quantity, notes, user, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (product_id, data['name'], 'إضافة', int(data['quantity']), 0, int(data['quantity']), 'إضافة منتج جديد', 'admin', datetime.datetime.now().isoformat()))

        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": "تم إضافة المنتج بنجاح"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

@app.route('/admin/products/<int:product_id>')
def get_product(product_id):
    try:
        conn = sqlite3.connect(get_db_path())
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, price, quantity, category, barcode, unit, min_quantity FROM products WHERE id = ? AND is_active = 1", (product_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return jsonify({"success": True, "product": {"id": row[0], "name": row[1], "price": row[2], "quantity": row[3], "category": row[4], "barcode": row[5], "unit": row[6], "min_quantity": row[7]}})
        else:
            return jsonify({"success": False, "message": "المنتج غير موجود"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

@app.route('/admin/products/update', methods=['POST'])
def update_product():
    try:
        data = request.json
        if not data.get('id'):
            return jsonify({"success": False, "message": "معرف المنتج مطلوب"})

        conn = sqlite3.connect(get_db_path())
        cursor = conn.cursor()
        cursor.execute("SELECT quantity, name FROM products WHERE id = ?", (data['id'],))
        current = cursor.fetchone()
        if not current:
            conn.close()
            return jsonify({"success": False, "message": "المنتج غير موجود"})

        old_quantity = current[0]
        product_name = current[1]
        new_quantity = int(data.get('quantity', old_quantity))
        quantity_change = new_quantity - old_quantity

        cursor.execute("UPDATE products SET name = ?, price = ?, quantity = ?, last_updated = ? WHERE id = ?",
                       (data['name'], float(data['price']), new_quantity, datetime.date.today().isoformat(), data['id']))

        if quantity_change != 0:
            cursor.execute("""
                INSERT INTO inventory_logs (product_id, product_name, change_type, quantity_change, old_quantity, new_quantity, notes, user, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (data['id'], product_name, 'تعديل', quantity_change, old_quantity, new_quantity, 'تعديل المنتج', 'admin', datetime.datetime.now().isoformat()))

        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": "تم تحديث المنتج بنجاح"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

@app.route('/admin/products/delete/<int:product_id>', methods=['DELETE'])
def delete_product(product_id):
    try:
        conn = sqlite3.connect(get_db_path())
        cursor = conn.cursor()
        cursor.execute("SELECT name, quantity FROM products WHERE id = ?", (product_id,))
        product = cursor.fetchone()
        if not product:
            conn.close()
            return jsonify({"success": False, "message": "المنتج غير موجود"})

        cursor.execute("UPDATE products SET is_active = 0 WHERE id = ?", (product_id,))
        cursor.execute("""
            INSERT INTO inventory_logs (product_id, product_name, change_type, quantity_change, old_quantity, new_quantity, notes, user, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (product_id, product[0], 'حذف', -product[1], product[1], 0, 'حذف المنتج', 'admin', datetime.datetime.now().isoformat()))

        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": "تم حذف المنتج بنجاح"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

@app.route('/admin/products/logs')
def inventory_logs():
    try:
        conn = sqlite3.connect(get_db_path())
        cursor = conn.cursor()
        cursor.execute("SELECT product_name, change_type, quantity_change, old_quantity, new_quantity, notes, user, timestamp FROM inventory_logs ORDER BY timestamp DESC LIMIT 50")
        logs = [{"product_name": r[0], "change_type": r[1], "quantity_change": r[2], "old_quantity": r[3], "new_quantity": r[4], "notes": r[5], "user": r[6], "timestamp": r[7]} for r in cursor.fetchall()]
        conn.close()
        return jsonify({"success": True, "logs": logs})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

# =============================== واجهات الإدارة الأخرى ===============================
@app.route('/admin')
def admin_dashboard():
    return '''<!DOCTYPE html>...'''  # (ضع كود HTML للوحة التحكم الرئيسية)

@app.route('/admin/customers')
def admin_customers_list():
    try:
        conn = sqlite3.connect(get_db_path())
        cursor = conn.cursor()
        cursor.execute("SELECT phone, name, loyalty_points, total_spent, visits, last_visit, customer_tier FROM customers WHERE is_active = 1 ORDER BY total_spent DESC")
        customers = cursor.fetchall()
        conn.close()
        # أنشئ صفحة HTML لعرض العملاء (يمكنك كتابتها أو استخدام القالب السابق)
        html = '''<!DOCTYPE html>...'''  # ضع كود HTML مناسب
        return html
    except Exception as e:
        return f"خطأ: {str(e)}"

@app.route('/stats')
def stats():
    try:
        conn = sqlite3.connect(get_db_path())
        cursor = conn.cursor()
        total_customers = cursor.execute("SELECT COUNT(*) FROM customers").fetchone()[0] or 0
        active_customers = cursor.execute("SELECT COUNT(*) FROM customers WHERE is_active = 1").fetchone()[0] or 0
        total_spent = cursor.execute("SELECT SUM(total_spent) FROM customers").fetchone()[0] or 0
        total_points = cursor.execute("SELECT SUM(loyalty_points) FROM customers").fetchone()[0] or 0
        total_products = cursor.execute("SELECT COUNT(*) FROM products WHERE is_active = 1").fetchone()[0] or 0
        inventory_value = cursor.execute("SELECT SUM(price * quantity) FROM products WHERE is_active = 1").fetchone()[0] or 0
        conn.close()
        return f'''<!DOCTYPE html>...'''  # ضع كود HTML للإحصائيات
    except Exception as e:
        return f"خطأ: {str(e)}"

@app.route('/add')
def add_page():
    return '''<!DOCTYPE html>...'''  # ضع كود HTML لإضافة عميل

@app.route('/add_customer', methods=['POST'])
def add_customer():
    try:
        data = request.json
        phone = data.get('phone')
        name = data.get('name')
        if not phone or not name:
            return jsonify({"success": False, "message": "الاسم والهاتف مطلوبان"})

        conn = sqlite3.connect(get_db_path())
        cursor = conn.cursor()
        cursor.execute("INSERT INTO customers (phone, name, last_visit) VALUES (?, ?, ?)", (phone, name, datetime.date.today().isoformat()))
        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": "✅ تم إضافة العميل بنجاح"})
    except sqlite3.IntegrityError:
        return jsonify({"success": False, "message": "⚠ رقم الهاتف مسجل مسبقاً"})
    except Exception as e:
        return jsonify({"success": False, "message": f"خطأ: {str(e)}"})

# =============================== التشغيل الرئيسي ===============================
if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
