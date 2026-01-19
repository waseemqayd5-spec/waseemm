"""
تطبيق ويب بسيط لعرض نقاط العملاء - ويندوز
"""

from flask import Flask, render_template_string, request, jsonify
import sqlite3
import json
import os
import datetime

app = Flask(__name__)


# الصفحة الرئيسية
@app.route('/')
def home():
    return '''
    <!DOCTYPE html>
    <html dir="rtl" lang="ar">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>سوبر ماركت - نظام الولاء</title>
        <style>
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
                font-family: 'Segoe UI', 'Arial', sans-serif;
            }

            body {
                background: linear-gradient(135deg, #6a11cb 0%, #2575fc 100%);
                min-height: 100vh;
                display: flex;
                justify-content: center;
                align-items: center;
                padding: 20px;
            }

            .container {
                width: 100%;
                max-width: 500px;
            }

            .card {
                background: white;
                border-radius: 20px;
                box-shadow: 0 15px 35px rgba(0,0,0,0.3);
                overflow: hidden;
                animation: fadeIn 0.5s ease;
            }

            @keyframes fadeIn {
                from { opacity: 0; transform: translateY(20px); }
                to { opacity: 1; transform: translateY(0); }
            }

            .header {
                background: linear-gradient(to right, #4CAF50, #2E7D32);
                color: white;
                padding: 30px;
                text-align: center;
                position: relative;
            }

            .header h1 {
                font-size: 28px;
                margin-bottom: 10px;
                display: flex;
                align-items: center;
                justify-content: center;
                gap: 10px;
            }

            .header p {
                opacity: 0.9;
                font-size: 16px;
            }

            .content {
                padding: 30px;
            }

            .form-group {
                margin-bottom: 25px;
            }

            .form-group label {
                display: block;
                margin-bottom: 8px;
                color: #333;
                font-weight: 600;
                font-size: 16px;
                display: flex;
                align-items: center;
                gap: 8px;
            }

            .input-with-icon {
                position: relative;
            }

            .input-with-icon input {
                width: 100%;
                padding: 15px 15px 15px 50px;
                border: 2px solid #e0e0e0;
                border-radius: 12px;
                font-size: 18px;
                transition: all 0.3s;
                background: #f8f9fa;
            }

            .input-with-icon input:focus {
                outline: none;
                border-color: #4CAF50;
                background: white;
                box-shadow: 0 0 0 3px rgba(76, 175, 80, 0.1);
            }

            .input-icon {
                position: absolute;
                left: 15px;
                top: 50%;
                transform: translateY(-50%);
                font-size: 20px;
                color: #666;
            }

            .btn {
                background: linear-gradient(to right, #4CAF50, #45a049);
                color: white;
                border: none;
                padding: 18px;
                border-radius: 12px;
                font-size: 18px;
                font-weight: 600;
                cursor: pointer;
                width: 100%;
                display: flex;
                align-items: center;
                justify-content: center;
                gap: 10px;
                transition: all 0.3s;
                margin-top: 10px;
            }

            .btn:hover {
                transform: translateY(-3px);
                box-shadow: 0 10px 20px rgba(76, 175, 80, 0.3);
            }

            .btn:active {
                transform: translateY(-1px);
            }

            .result {
                margin-top: 25px;
                padding: 25px;
                background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
                border-radius: 15px;
                border: 2px solid #4CAF50;
                display: none;
                animation: slideIn 0.5s ease;
            }

            @keyframes slideIn {
                from { opacity: 0; transform: translateY(-20px); }
                to { opacity: 1; transform: translateY(0); }
            }

            .customer-info {
                text-align: center;
                margin-bottom: 20px;
            }

            .customer-name {
                font-size: 24px;
                color: #2c3e50;
                margin-bottom: 10px;
            }

            .points-display {
                font-size: 60px;
                color: #e74c3c;
                font-weight: bold;
                margin: 20px 0;
                text-shadow: 2px 2px 4px rgba(0,0,0,0.1);
            }

            .info-grid {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 15px;
                margin-top: 20px;
            }

            .info-item {
                background: white;
                padding: 15px;
                border-radius: 10px;
                box-shadow: 0 3px 10px rgba(0,0,0,0.1);
            }

            .info-label {
                font-size: 12px;
                color: #7f8c8d;
                margin-bottom: 5px;
            }

            .info-value {
                font-size: 18px;
                font-weight: bold;
                color: #2c3e50;
            }

            .offers-grid {
                display: grid;
                gap: 10px;
                margin-top: 20px;
            }

            .offer-card {
                background: linear-gradient(to right, #ffeaa7, #fab1a0);
                padding: 15px;
                border-radius: 10px;
                border-left: 5px solid #e74c3c;
            }

            .offer-title {
                font-weight: bold;
                color: #2d3436;
                margin-bottom: 5px;
            }

            .offer-desc {
                color: #636e72;
                font-size: 14px;
                margin-bottom: 8px;
            }

            .offer-code {
                background: #2c3e50;
                color: white;
                padding: 5px 10px;
                border-radius: 5px;
                font-family: monospace;
                display: inline-block;
            }

            .loader {
                border: 5px solid #f3f3f3;
                border-top: 5px solid #4CAF50;
                border-radius: 50%;
                width: 50px;
                height: 50px;
                animation: spin 1s linear infinite;
                margin: 20px auto;
            }

            @keyframes spin {
                0% { transform: rotate(0deg); }
                100% { transform: rotate(360deg); }
            }

            .error {
                background: #ffebee;
                border: 2px solid #ef5350;
                color: #c62828;
                padding: 20px;
                border-radius: 10px;
                text-align: center;
            }

            .success {
                background: #e8f5e9;
                border: 2px solid #4CAF50;
                color: #2e7d32;
                padding: 20px;
                border-radius: 10px;
                text-align: center;
            }

            @media (max-width: 600px) {
                .card {
                    border-radius: 10px;
                }

                .header {
                    padding: 20px;
                }

                .content {
                    padding: 20px;
                }

                .points-display {
                    font-size: 48px;
                }

                .info-grid {
                    grid-template-columns: 1fr;
                }
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="card">
                <div class="header">
                    <h1>🛒 سوبر ماركت الولاء</h1>
                    <p>استعلم عن نقاطك وعروضك الخاصة</p>
                </div>

                <div class="content">
                    <div class="form-group">
                        <label for="phone">
                            <span>📱</span>
                            أدخل رقم هاتفك المسجل:
                        </label>
                        <div class="input-with-icon">
                            <div class="input-icon">📞</div>
                            <input type="tel" id="phone" placeholder="مثال: 0551234567" required>
                        </div>
                    </div>

                    <button class="btn" onclick="checkPoints()">
                        <span>🔍</span>
                        استعلم عن نقاطي
                    </button>

                    <div id="result" class="result">
                        <!-- سيتم ملؤه بالجافاسكريبت -->
                    </div>
                </div>
            </div>
        </div>

        <script>
            function checkPoints() {
                const phone = document.getElementById('phone').value;
                const resultDiv = document.getElementById('result');

                if (!phone || phone.length < 10) {
                    showError('⚠ يرجى إدخال رقم هاتف صحيح (10 أرقام)');
                    return;
                }

                // إظهار تحميل
                resultDiv.style.display = 'block';
                resultDiv.innerHTML = `
                    <div class="loader"></div>
                    <p style="text-align: center; margin-top: 10px;">جاري البحث عن بياناتك...</p>
                `;

                // إرسال الطلب للخادم
                fetch('/check_points', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ phone: phone })
                })
                .then(response => {
                    if (!response.ok) {
                        throw new Error('خطأ في الاتصال بالخادم');
                    }
                    return response.json();
                })
                .then(data => {
                    if (data.success) {
                        showCustomerInfo(data);
                    } else {
                        showError(data.message);
                    }
                })
                .catch(error => {
                    showError('❌ حدث خطأ في الاتصال بالخادم. حاول مرة أخرى.');
                    console.error('Error:', error);
                });
            }

            function showCustomerInfo(data) {
                const resultDiv = document.getElementById('result');
                const customer = data.customer;
                const offers = data.offers;

                let html = `
                    <div class="success">
                        <div class="customer-info">
                            <div class="customer-name">👤 مرحباً ${customer.name}</div>
                            <div class="points-display">${customer.points} ⭐</div>
                        </div>

                        <div class="info-grid">
                            <div class="info-item">
                                <div class="info-label">💰 إجمالي إنفاقك</div>
                                <div class="info-value">${customer.total_spent} ريال</div>
                            </div>
                            <div class="info-item">
                                <div class="info-label">🛒 عدد زياراتك</div>
                                <div class="info-value">${customer.visits}</div>
                            </div>
                            <div class="info-item">
                                <div class="info-label">📅 آخر زيارة</div>
                                <div class="info-value">${customer.last_visit}</div>
                            </div>
                            <div class="info-item">
                                <div class="info-label">🏆 مستواك</div>
                                <div class="info-value">${customer.tier || 'عادي'}</div>
                            </div>
                        </div>
                `;

                if (offers && offers.length > 0) {
                    html += `
                        <div style="margin-top: 25px;">
                            <h3 style="text-align: center; margin-bottom: 15px; color: #2c3e50;">🎁 العروض المتاحة لك</h3>
                            <div class="offers-grid">
                    `;

                    offers.forEach(offer => {
                        html += `
                            <div class="offer-card">
                                <div class="offer-title">${offer.title}</div>
                                <div class="offer-desc">${offer.description}</div>
                                <div class="offer-code">${offer.code}</div>
                            </div>
                        `;
                    });

                    html += `
                            </div>
                        </div>
                    `;
                }

                html += `
                        <div style="text-align: center; margin-top: 20px; color: #7f8c8d; font-size: 12px;">
                            آخر تحديث: ${new Date().toLocaleString('ar-SA')}
                        </div>
                    </div>
                `;

                resultDiv.innerHTML = html;
            }

            function showError(message) {
                const resultDiv = document.getElementById('result');
                resultDiv.style.display = 'block';
                resultDiv.innerHTML = `
                    <div class="error">
                        <div style="font-size: 48px; margin-bottom: 10px;">❌</div>
                        <p>${message}</p>
                        <p style="margin-top: 15px; font-size: 14px;">
                            يمكنك التسجيل عند زيارتك القادمة للمتجر
                        </p>
                    </div>
                `;
            }

            // السماح بالضغط على Enter
            document.getElementById('phone').addEventListener('keypress', function(e) {
                if (e.key === 'Enter') {
                    checkPoints();
                }
            });

            // تعبئة تلقائية لرقم تجريبي (للغرض التجريبي فقط)
            window.addEventListener('load', function() {
                document.getElementById('phone').value = '0551234567';
            });
        </script>
    </body>
    </html>
    '''


# API للتحقق من النقاط
@app.route('/check_points', methods=['POST'])
def check_points():
    try:
        data = request.json
        phone = data.get('phone')

        if not phone:
            return jsonify({
                "success": False,
                "message": "رقم الهاتف مطلوب"
            })

        # الاتصال بقاعدة البيانات
        db_path = 'data/supermarket.db'

        if not os.path.exists(db_path):
            return jsonify({
                "success": False,
                "message": "قاعدة البيانات غير موجودة. سجل عميلاً أولاً."
            })

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # البحث عن العميل
        cursor.execute('''
            SELECT name, loyalty_points, total_spent, visits, last_visit, customer_tier
            FROM customers 
            WHERE phone = ? AND is_active = 1
        ''', (phone,))

        customer_data = cursor.fetchone()

        if customer_data:
            # تحديد العروض بناءً على مستوى العميل
            offers = get_offers_for_customer(customer_data[5], customer_data[1])

            conn.close()

            return jsonify({
                "success": True,
                "customer": {
                    "name": customer_data[0],
                    "points": customer_data[1],
                    "total_spent": customer_data[2],
                    "visits": customer_data[3],
                    "last_visit": customer_data[4],
                    "tier": customer_data[5]
                },
                "offers": offers
            })
        else:
            conn.close()
            return jsonify({
                "success": False,
                "message": "رقم الهاتف غير مسجل. قم بزيارة أقرب فرع للتسجيل."
            })

    except Exception as e:
        return jsonify({
            "success": False,
            "message": f"حدث خطأ: {str(e)}"
        })


# API للحصول على إحصائيات
@app.route('/stats')
def stats():
    try:
        db_path = 'data/supermarket.db'

        if not os.path.exists(db_path):
            return jsonify({
                "error": "قاعدة البيانات غير موجودة"
            })

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute('SELECT COUNT(*) FROM customers')
        total_customers = cursor.fetchone()[0] or 0

        cursor.execute('SELECT COUNT(*) FROM customers WHERE is_active = 1')
        active_customers = cursor.fetchone()[0] or 0

        cursor.execute('SELECT SUM(total_spent) FROM customers')
        total_spent = cursor.fetchone()[0] or 0

        cursor.execute('SELECT SUM(loyalty_points) FROM customers')
        total_points = cursor.fetchone()[0] or 0

        conn.close()

        return jsonify({
            "total_customers": total_customers,
            "active_customers": active_customers,
            "total_spent": total_spent,
            "total_points": total_points,
            "average_spent": total_spent / active_customers if active_customers > 0 else 0
        })

    except Exception as e:
        return jsonify({
            "error": str(e)
        })


# API للحصول على قائمة العملاء
@app.route('/customers')
def customers():
    try:
        db_path = 'data/supermarket.db'

        if not os.path.exists(db_path):
            return jsonify({"customers": []})

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT phone, name, loyalty_points, total_spent, customer_tier, last_visit
            FROM customers 
            WHERE is_active = 1
            ORDER BY total_spent DESC
        ''')

        customers_list = []
        for row in cursor.fetchall():
            customers_list.append({
                "phone": row[0],
                "name": row[1],
                "points": row[2],
                "total_spent": row[3],
                "tier": row[4],
                "last_visit": row[5]
            })

        conn.close()

        return jsonify({
            "count": len(customers_list),
            "customers": customers_list
        })

    except Exception as e:
        return jsonify({
            "error": str(e)
        })


def get_offers_for_customer(tier, points):
    """إرجاع العروض المناسبة لمستوى العميل ونقاطه"""
    offers = []

    # عروض عامة للجميع
    offers.append({
        "title": "خصم 10%",
        "description": "خصم على جميع مشترياتك",
        "code": "WELCOME10"
    })

    offers.append({
        "title": "توصيل مجاني",
        "description": "للطلبات فوق 100 ريال",
        "code": "FREE100"
    })

    # عروض حسب المستوى
    if tier in ["ذهبي", "ممتاز"]:
        offers.append({
            "title": "خصم VIP 20%",
            "description": "خصم حصري للعملاء الدائمين",
            "code": "VIP20"
        })

    if tier == "ممتاز":
        offers.append({
            "title": "هدية مفاجئة",
            "description": "مع كل شراء فوق 200 ريال",
            "code": "GIFT200"
        })

    # عروض حسب النقاط
    if points >= 500:
        offers.append({
            "title": "خصم 50 نقطة",
            "description": "استبدل 50 نقطة بخصم 25 ريال",
            "code": "POINTS50"
        })

    if points >= 1000:
        offers.append({
            "title": "خصم 100 نقطة",
            "description": "استبدل 100 نقطة بخصم 50 ريال",
            "code": "POINTS100"
        })

    return offers


# صفحة لوحة التحكم للإدارة
@app.route('/admin')
def admin_dashboard():
    return '''
    <!DOCTYPE html>
    <html dir="rtl" lang="ar">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>لوحة التحكم - إدارة العملاء</title>
        <style>
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            }

            body {
                background: #f5f5f5;
                padding: 20px;
            }

            .container {
                max-width: 1200px;
                margin: 0 auto;
            }

            .header {
                background: linear-gradient(to right, #2c3e50, #4a6491);
                color: white;
                padding: 30px;
                border-radius: 10px;
                margin-bottom: 30px;
                box-shadow: 0 5px 15px rgba(0,0,0,0.2);
            }

            .header h1 {
                font-size: 32px;
                margin-bottom: 10px;
                display: flex;
                align-items: center;
                gap: 15px;
            }

            .stats-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
                gap: 20px;
                margin-bottom: 30px;
            }

            .stat-card {
                background: white;
                padding: 25px;
                border-radius: 10px;
                box-shadow: 0 3px 10px rgba(0,0,0,0.1);
                text-align: center;
            }

            .stat-number {
                font-size: 36px;
                font-weight: bold;
                color: #2c3e50;
                margin: 10px 0;
            }

            .stat-label {
                color: #7f8c8d;
                font-size: 14px;
            }

            .customers-table {
                background: white;
                border-radius: 10px;
                overflow: hidden;
                box-shadow: 0 3px 10px rgba(0,0,0,0.1);
                margin-top: 20px;
            }

            table {
                width: 100%;
                border-collapse: collapse;
            }

            th {
                background: #3498db;
                color: white;
                padding: 15px;
                text-align: right;
            }

            td {
                padding: 12px 15px;
                border-bottom: 1px solid #eee;
            }

            tr:hover {
                background: #f9f9f9;
            }

            .tier-badge {
                background: #2ecc71;
                color: white;
                padding: 5px 10px;
                border-radius: 20px;
                font-size: 12px;
                display: inline-block;
            }

            .tier-gold {
                background: #f39c12;
            }

            .tier-platinum {
                background: #9b59b6;
            }

            .loading {
                text-align: center;
                padding: 50px;
                color: #7f8c8d;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>📊 لوحة تحكم إدارة العملاء</h1>
                <p>نظام إدارة علاقات العملاء - سوبر ماركت</p>
            </div>

            <div id="stats" class="stats-grid">
                <!-- سيتم ملؤه بالجافاسكريبت -->
            </div>

            <div class="customers-table">
                <h3 style="padding: 20px; margin: 0; color: #2c3e50;">👥 قائمة العملاء</h3>
                <div id="customers-list" class="loading">
                    جاري تحميل بيانات العملاء...
                </div>
            </div>
        </div>

        <script>
            // جلب الإحصائيات
            fetch('/stats')
                .then(response => response.json())
                .then(data => {
                    if (data.error) {
                        document.getElementById('stats').innerHTML = `
                            <div class="stat-card">
                                <div class="stat-label">❌ خطأ</div>
                                <div class="stat-number">--</div>
                            </div>
                        `;
                        return;
                    }

                    document.getElementById('stats').innerHTML = `
                        <div class="stat-card">
                            <div class="stat-label">👥 إجمالي العملاء</div>
                            <div class="stat-number">${data.total_customers}</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-label">✅ العملاء النشطين</div>
                            <div class="stat-number">${data.active_customers}</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-label">💰 إجمالي المبيعات</div>
                            <div class="stat-number">${data.total_spent.toFixed(2)} ريال</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-label">⭐ إجمالي النقاط</div>
                            <div class="stat-number">${data.total_points}</div>
                        </div>
                    `;
                })
                .catch(error => {
                    console.error('Error:', error);
                });

            // جلب قائمة العملاء
            fetch('/customers')
                .then(response => response.json())
                .then(data => {
                    const container = document.getElementById('customers-list');

                    if (data.error) {
                        container.innerHTML = <p style="color: red; padding: 20px;">${data.error}</p>;
                        return;
                    }

                    if (data.count === 0) {
                        container.innerHTML = '<p style="padding: 20px; text-align: center;">لا يوجد عملاء مسجلين</p>';
                        return;
                    }

                    let html = `
                        <table>
                            <thead>
                                <tr>
                                    <th>الاسم</th>
                                    <th>رقم الهاتف</th>
                                    <th>المستوى</th>
                                    <th>النقاط</th>
                                    <th>إجمالي الإنفاق</th>
                                    <th>آخر زيارة</th>
                                </tr>
                            </thead>
                            <tbody>
                    `;

                    data.customers.forEach(customer => {
                        let tierClass = '';
                        if (customer.tier === 'ذهبي') tierClass = 'tier-gold';
                        if (customer.tier === 'ممتاز') tierClass = 'tier-platinum';

                        html += `
                            <tr>
                                <td>${customer.name}</td>
                                <td>${customer.phone}</td>
                                <td><span class="tier-badge ${tierClass}">${customer.tier || 'عادي'}</span></td>
                                <td>${customer.points}</td>
                                <td>${customer.total_spent.toFixed(2)} ريال</td>
                                <td>${customer.last_visit}</td>
                            </tr>
                        `;
                    });

                    html += `
                            </tbody>
                        </table>
                        <div style="padding: 15px; background: #f9f9f9; text-align: center; color: #7f8c8d;">
                            إجمالي العملاء: ${data.count} عميل
                        </div>
                    `;

                    container.innerHTML = html;
                })
                .catch(error => {
                    document.getElementById('customers-list').innerHTML = `
                        <p style="color: red; padding: 20px;">خطأ في تحميل البيانات: ${error}</p>
                    `;
                });
        </script>
    </body>
    </html>
    '''


# صفحة الإعدادات
@app.route('/settings')
def settings():
    return '''
    <!DOCTYPE html>
    <html dir="rtl" lang="ar">
    <head>
        <meta charset="UTF-8">
        <title>الإعدادات</title>
    </head>
    <body>
        <h1>⚙ صفحة الإعدادات</h1>
        <p>تحت التطوير...</p>
    </body>
    </html>
    '''


if __name__ == '__main__':
    print("=" * 60)
    print("🚀 بدء تشغيل تطبيق ويب نظام الولاء")
    print("=" * 60)
    print("📁 قاعدة البيانات: data/supermarket.db")
    print("🌐 التطبيق يعمل على:")
    print("   👉 http://localhost:5000      - للعملاء")
    print("   👉 http://localhost:5000/admin - للإدارة")
    print("=" * 60)
    print("⏳ جاري التشغيل...")

    # إنشاء مجلد data إذا لم يكن موجوداً
    if not os.path.exists('data'):
        os.makedirs('data')
        print("✅ تم إنشاء مجلد data")

    app.run(debug=True,port = 5000)