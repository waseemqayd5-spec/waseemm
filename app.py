from flask import Flask, request, jsonify
import sqlite3
import os

app = Flask(__name__)

DB_PATH = "data/supermarket.db"


# =========================
# تهيئة قاعدة البيانات
# =========================
def init_db():
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # جدول العملاء (مختصر)
    c.execute("""
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

    # جدول العروض
    c.execute("""
    CREATE TABLE IF NOT EXISTS offers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        description TEXT,
        code TEXT,
        min_points INTEGER DEFAULT 0,
        tier TEXT DEFAULT 'عادي',
        is_active INTEGER DEFAULT 1
    )
    """)

    conn.commit()
    conn.close()


# =========================
# جلب العروض حسب العميل
# =========================
def get_offers_for_customer(tier, points):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        SELECT title, description, code
        FROM offers
        WHERE is_active = 1
        AND min_points <= ?
        AND (tier = ? OR tier = 'عادي')
    """, (points, tier))

    offers = []
    for row in c.fetchall():
        offers.append({
            "title": row[0],
            "description": row[1],
            "code": row[2]
        })

    conn.close()
    return offers


# =========================
# صفحة عرض العروض
# =========================
@app.route('/admin/offers')
def admin_offers_list():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, title, description, code, min_points, tier, is_active FROM offers")
    offers = c.fetchall()
    conn.close()

    # تحويل العروض إلى HTML
    rows_html = ""
    for offer in offers:
        rows_html += f"""
        <tr>
            <td>{offer[0]}</td>
            <td>{offer[1]}</td>
            <td>{offer[2]}</td>
            <td>{offer[3]}</td>
            <td>{offer[4]}</td>
            <td>{offer[5]}</td>
            <td>{'نشط' if offer[6] == 1 else 'معطل'}</td>
            <td>
                <button onclick="deleteOffer({offer[0]})">🗑️ حذف</button>
            </td>
        </tr>
        """

    return f"""
    <!DOCTYPE html>
    <html lang="ar" dir="rtl">
    <head>
        <meta charset="UTF-8">
        <title>العروض الموجودة</title>
        <style>
            body {{ font-family: Arial; background: #f4f6f8; padding: 30px; }}
            .box {{ background: white; padding: 25px; border-radius: 10px; max-width: 1000px; margin: auto; }}
            table {{ width: 100%; border-collapse: collapse; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; text-align: center; }}
            th {{ background: #f2f2f2; }}
            button {{
                padding: 8px 12px;
                border-radius: 6px;
                border: 1px solid #ccc;
                cursor: pointer;
            }}
            button:hover {{ opacity: 0.8; }}
            .add-btn {{
                background: #27ae60; color: white;
                margin-bottom: 15px;
            }}
        </style>
    </head>
    <body>
        <div class="box">
            <h2>📦 العروض الموجودة</h2>

            <button class="add-btn" onclick="window.location.href='/admin/offers/add'">
                ➕ إضافة عرض جديد
            </button>

            <table>
                <tr>
                    <th>رقم</th>
                    <th>العنوان</th>
                    <th>الوصف</th>
                    <th>الكود</th>
                    <th>أقل نقاط</th>
                    <th>الدرجة</th>
                    <th>الحالة</th>
                    <th>إجراءات</th>
                </tr>
                {rows_html}
            </table>
        </div>

        <script>
            function deleteOffer(id) {{
                fetch("/api/delete_offer", {{
                    method: "POST",
                    headers: {{ "Content-Type": "application/json" }},
                    body: JSON.stringify({{ id: id }})
                }})
                .then(r => r.json())
                .then(d => {{
                    alert(d.message);
                    if (d.success) window.location.reload();
                }});
            }}
        </script>
    </body>
    </html>
    """


# =========================
# صفحة إضافة عرض
# =========================
@app.route('/admin/offers/add')
def admin_offers_add():
    return """
    <!DOCTYPE html>
    <html lang="ar" dir="rtl">
    <head>
        <meta charset="UTF-8">
        <title>إضافة عرض جديد</title>
        <style>
            body { font-family: Arial; background: #f4f6f8; padding: 30px; }
            .box { background: white; padding: 25px; border-radius: 10px; max-width: 500px; margin: auto; }
            input, select, button {
                width: 100%; padding: 12px; margin-top: 10px;
                border-radius: 6px; border: 1px solid #ccc;
            }
            button {
                background: #27ae60; color: white; font-size: 16px; cursor: pointer;
            }
            button:hover { background: #219150; }
        </style>
    </head>
    <body>
        <div class="box">
            <h2>➕ إضافة عرض جديد</h2>

            <input id="title" placeholder="عنوان العرض">
            <input id="desc" placeholder="وصف العرض">
            <input id="code" placeholder="كود العرض">
            <input id="points" type="number" placeholder="أقل عدد نقاط">
            
            <select id="tier">
                <option value="عادي">عادي</option>
                <option value="ذهبي">ذهبي</option>
                <option value="ممتاز">ممتاز</option>
            </select>

            <button onclick="saveOffer()">💾 حفظ العرض</button>
            <p id="msg"></p>
        </div>

        <script>
            function saveOffer() {
                fetch("/api/add_offer", {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({
                        title: title.value,
                        description: desc.value,
                        code: code.value,
                        min_points: points.value,
                        tier: tier.value
                    })
                })
                .then(r => r.json())
                .then(d => {
                    msg.innerText = d.message;
                    msg.style.color = d.success ? "green" : "red";
                    if (d.success) window.location.href = "/admin/offers";
                });
            }
        </script>
    </body>
    </html>
    """


# =========================
# API إضافة عرض
# =========================
@app.route("/api/add_offer", methods=["POST"])
def add_offer():
    data = request.json

    if not data.get("title"):
        return jsonify(success=False, message="العنوان مطلوب")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        INSERT INTO offers (title, description, code, min_points, tier)
        VALUES (?, ?, ?, ?, ?)
    """, (
        data["title"],
        data.get("description", ""),
        data.get("code", ""),
        data.get("min_points", 0),
        data.get("tier", "عادي")
    ))

    conn.commit()
    conn.close()

    return jsonify(success=True, message="✅ تم إضافة العرض بنجاح")


# =========================
# API حذف عرض
# =========================
@app.route("/api/delete_offer", methods=["POST"])
def delete_offer():
    data = request.json
    offer_id = data.get("id")

    if not offer_id:
        return jsonify(success=False, message="رقم العرض مطلوب")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("DELETE FROM offers WHERE id = ?", (offer_id,))
    conn.commit()
    conn.close()

    return jsonify(success=True, message="تم حذف العرض بنجاح")


# =========================
# API فحص نقاط العميل
# =========================
@app.route("/check_points", methods=["POST"])
def check_points():
    phone = request.json.get("phone")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        SELECT name, loyalty_points, customer_tier
        FROM customers
        WHERE phone = ? AND is_active = 1
    """, (phone,))

    row = c.fetchone()
    conn.close()

    if not row:
        return jsonify(success=False, message="العميل غير مسجل")

    offers = get_offers_for_customer(row[2], row[1])

    return jsonify(
        success=True,
        customer={
            "name": row[0],
            "points": row[1],
            "tier": row[2]
        },
        offers=offers
    )


# =========================
# تشغيل التطبيق
# =========================
if __name__ == "__main__":
    init_db()
    print("🚀 التطبيق يعمل على http://localhost:10000")
    print("🧑‍💼 إدارة العروض: http://localhost:10000/admin/offers")
    app.run(host="0.0.0.0", port=10000)
