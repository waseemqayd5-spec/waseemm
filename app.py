from flask import Flask, render_template_string, jsonify
import os

app = Flask(__name__)

# 1. كود الـ HTML المتكامل (الواجهة)
html_template = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>وسيم - Portfolio</title>
    <link rel="manifest" href="/manifest.json">
    <meta name="theme-color" content="#d4af37">
    <style>
        body { 
            font-family: 'Arial', sans-serif; 
            margin: 0; display: flex; justify-content: center; align-items: center; 
            height: 100vh; background-color: #000; color: #d4af37; 
        }
        .container { 
            text-align: center; padding: 40px; 
            border: 2px solid #d4af37; border-radius: 20px; 
            box-shadow: 0 0 20px rgba(212, 175, 55, 0.5);
        }
        h1 { font-size: 2.5em; margin-bottom: 10px; }
        p { color: #fff; font-size: 1.2em; }
    </style>
</head>
<body>
    <div class="container">
        <h1>وسيم الهُميدي</h1>
        <p>مرحباً بك في تطبيقي الشخصي</p>
        <p>المهنة: مهندس ذكاء اصطناعي</p>
    </div>
</body>
</html>
"""

# 2. توليد المانيفست مع رابط أيقونة خارجي (لحل مشكلة الخطأ في الصورة)
@app.route('/manifest.json')
def manifest():
    return jsonify({
        "name": "Waseem Portfolio",
        "short_name": "Waseem",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#000000",
        "theme_color": "#d4af37",
        "icons": [
            {
                "src": "https://cdn-icons-png.flaticon.com/512/7153/7153150.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any"
            }
        ]
    })

@app.route('/')
def home():
    return render_template_string(html_template)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
