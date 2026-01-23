from flask import Flask, request, jsonify, render_template_string, redirect, url_for
import sqlite3
import os
from twilio.twiml.messaging_response import MessagingResponse

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "supermarket.db")

# ---------- إنشاء قاعدة البيانات ----------
def init_db():
    db = sqlite3.connect(DB_PATH)
    cursor = db.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        price REAL NOT NULL
    )
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phone TEXT NOT NULL,
        items TEXT NOT NULL,
        total REAL NOT NULL,
        created_at TEXT NOT NULL
    )
    """)
    db.commit()
    db.close()

init_db()

# ---------- واجهة إدارة المنتجات (HTML) ----------
ADMIN_HTML = """
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
<meta charset="utf-8">
<title>لوحة إدارة السلع</title>
<style>
  body{font-family: Arial; padding:20px; background:#f5f5f5}
  .box{background:#fff; padding:20px; border-radius:8px; max-width:600px; margin:auto;}
  input,button{padding:10px; margin:5px 0; width:100%;}
  table{width:100%; border-collapse:collapse; margin-top:20px;}
  th,td{padding:8px; border:1px solid #ddd;}
</style>
</head>
<body>
<div class="box">
  <h2>إضافة سلعة</h2>
  <form method="post" action="/add_product">
    <input name="name" placeholder="اسم السلعة" required>
    <input name="price" placeholder="السعر" type="number" step="0.01" required>
    <button type="submit">إضافة</button>
  </form>

  <h3>السلع المتاحة</h3>
  <table>
    <tr><th>الاسم</th><th>السعر</th></tr>
    {% for p in products %}
      <tr>
        <td>{{ p[1] }}</td>
        <td>{{ p[2] }}</td>
      </tr>
    {% endfor %}
  </table>
</div>
</body>
</html>
"""

# ---------- صفحة إدارة المنتجات ----------
@app.route("/admin")
def admin():
    db = sqlite3.connect(DB_PATH)
    cursor = db.cursor()
    cursor.execute("SELECT * FROM products")
    products = cursor.fetchall()
    db.close()
    return render_template_string(ADMIN_HTML, products=products)

# ---------- إضافة سلعة ----------
@app.route("/add_product", methods=["POST"])
def add_product():
    name = request.form.get("name")
    price = float(request.form.get("price"))
    db = sqlite3.connect(DB_PATH)
    cursor = db.cursor()
    cursor.execute("INSERT INTO products (name, price) VALUES (?, ?)", (name, price))
    db.commit()
    db.close()
    return redirect(url_for("admin"))

# ---------- WhatsApp webhook ----------
@app.route("/whatsapp", methods=["POST"])
def whatsapp():
    msg = request.form.get("Body").strip().lower()
    phone = request.form.get("From")

    resp = MessagingResponse()

    # إذا كتب الزبون "قائمة" يظهر له المنتجات
    if msg == "قائمة":
        db = sqlite3.connect(DB_PATH)
        cursor = db.cursor()
        cursor.execute("SELECT * FROM products")
        products = cursor.fetchall()
        db.close()

        text = "قائمة المنتجات:\n"
        for p in products:
            text += f"{p[0]}) {p[1]} - {p[2]} ريال\n"
        text += "\nأرسل طلبك بهذا الشكل:\n1:2,2:1 (يعني رقم المنتج:الكمية)"
        resp.message(text)
        return str(resp)

    # إذا كتب الزبون طلب
    if ":" in msg:
        try:
            db = sqlite3.connect(DB_PATH)
            cursor = db.cursor()
            cursor.execute("SELECT * FROM products")
            products = cursor.fetchall()

            # تحويل المنتجات لقاموس
            prod_dict = {str(p[0]): (p[1], p[2]) for p in products}

            items = msg.split(",")
            total = 0
            order_text = ""

            for item in items:
                pid, qty = item.split(":")
                qty = int(qty)
                name, price = prod_dict[pid]
                total += price * qty
                order_text += f"{name} x{qty} = {price*qty} ريال\n"

            # حفظ الطلب في قاعدة البيانات
            import datetime
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute(
                "INSERT INTO orders (phone, items, total, created_at) VALUES (?, ?, ?, ?)",
                (phone, msg, total, now)
            )
            db.commit()
            db.close()

            resp.message(f"تم استلام طلبك:\n{order_text}\nالإجمالي: {total} ريال\nشكراً لك!")
            return str(resp)

        except Exception as e:
            resp.message("حدث خطأ في الطلب. تأكد من كتابة الطلب بهذا الشكل:\n1:2,2:1")
            return str(resp)

    # الرد الافتراضي
    resp.message("أهلاً! اكتب 'قائمة' لعرض المنتجات.")
    return str(resp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

