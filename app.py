```python
from flask import Flask, render_template_string, request, jsonify, g, redirect, url_for
import sqlite3
import os
from datetime import datetime

# إعداد التطبيق وقاعدة البيانات
app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "customers.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT UNIQUE,
    points INTEGER DEFAULT 0,
    updated_at TEXT
);
"""

# مساعدة لفتح اتصال قاعدة البيانات لكل طلب
def get_db():
    db = getattr(g, "_database", None)
    if db is None:
        db = g._database = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
    return db

# إغلاق الاتصال بعد انتهاء الطلب
@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()

# تهيئة القاعدة عند بدء التشغيل (آمنة للاستدعاء المتكرر)
def init_db():
    os.makedirs(BASE_DIR, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    try:
        db.executescript(SCHEMA)
        db.commit()
    finally:
        db.close()

# قوالب HTML بسيطة مضمّنة (RTL، عربي)
BASE_HTML = """
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>نقاط العملاء</title>
<style>
  body{font-family: "Segoe UI", Tahoma, Arial; background:#f4f6fb; margin:0; padding:20px}
  .container{max-width:900px;margin:0 auto;background:#fff;padding:20px;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,0.08)}
  h1{margin-bottom:10px}
  form{display:flex;gap:10px;flex-wrap:wrap}
  input,button{padding:8px;font-size:14px}
  table{width:100%;border-collapse:collapse;margin-top:16px}
  th,td{padding:8px;border-bottom:1px solid #eee;text-align:right}
  .actions{display:flex;gap:6px;justify-content:flex-end}
  .small{font-size:13px;color:#666}
</style>
</head>
<body>
<div class="container">
  <h1>تطبيق نقاط العملاء</h1>
  <p class="small">أضف، حدّث، أو ابحث عن عميل لعرض نقاطه</p>

  <form method="post" action="{{ url_for('add_or_update') }}">
    <input name="name" placeholder="الاسم" required>
    <input name="phone" placeholder="رقم الهاتف" required>
    <input name="points" placeholder="النقاط (رقم)" type="number" value="0" required>
    <button type="submit">حفظ / تحديث</button>
  </form>

  <form method="get" action="{{ url_for('home') }}" style="margin-top:12px">
    <input name="q" placeholder="بحث باسم أو رقم هاتف" value="{{ q|default('') }}">
    <button type="submit">بحث</button>
    <a href="{{ url_for('home') }}" style="margin-left:8px;text-decoration:none">إظهار الكل</a>
  </form>

  <table aria-live="polite">
    <thead>
      <tr><th>الاسم</th><th>الهاتف</th><th>النقاط</th><th>آخر تعديل</th><th></th></tr>
    </thead>
    <tbody>
    {% for c in customers %}
      <tr>
        <td>{{ c.name }}</td>
        <td>{{ c.phone }}</td>
        <td>{{ c.points }}</td>


