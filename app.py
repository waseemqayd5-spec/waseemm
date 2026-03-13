from flask import Flask, render_template_string, jsonify
import os

app = Flask(__name__)

# 1. كود الـ HTML المتكامل مع إعدادات التطبيق
html_template = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>وسيم - Portfolio</title>
    
    <link rel="manifest" href="/manifest.json">
    <meta name="theme-color" content="#000000">
    <meta name="mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black">
    
    <style>
        body { 
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
            margin: 0; 
            display: flex; 
            justify-content: center; 
            align-items: center; 
            height: 100vh; 
            background-color: #1a1a1a; 
            color: white; 
        }
        .container { 
            text-align: center; 
            padding: 30px; 
            border: 2px solid #d4af37; 
            border-radius: 15px; 
            background: #000;
            box-shadow: 0 10px 30px rgba(0,0,0,0.5);
        }
        h1 { color: #d4af37; margin-bottom: 10px; }
        p { color: #ccc; font-size: 1.1em; }
        .btn {
            display: inline-block;
            margin-top: 20px;
            padding: 10px 25px;
            background-color: #d4af37;
            color: black;
            text-decoration: none;
            border-radius: 5px;
            font-weight: bold;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>مرحباً بك في تطبيقي</h1>
        <p>هذا الموقع الآن مجهز تماماً ليصبح تطبيق أندرويد.</p>
        <p>المبرمج: وسيم الهُميدي</p>
        <a href="#" class="btn">استكشف أعمالي</a>
    </div>
</body>
</html>
"""

# 2. توليد ملف المانيفست (Manifest) تلقائياً
@app.route('/manifest.json')
def manifest():
    return jsonify({
        "name": "وسيم بورتفوليو",
        "short_name": "Waseem",
        "description": "معرض أعمال المبرمج وسيم",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#1a1a1a",
        "theme_color": "#000000",
        "icons": [
            {
                "src": "https://waseemm-2.onrender.com/static/icons/icon-512x512.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any maskable"
            }
        ]
    })

# 3. الصفحة الرئيسية
@app.route('/')
def home():
    return render_template_string(html_template)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
