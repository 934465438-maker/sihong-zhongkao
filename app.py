#!/usr/bin/env python3
"""泗洪中考志愿模拟填报 - Flask后端"""
import os, csv, sqlite3
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_file

app = Flask(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, 'registrations.db')
CSV_PATH = os.path.join(DATA_DIR, 'registrations.csv')
ADMIN_TOKEN = os.environ.get('ADMIN_TOKEN', 'sihong2026')

def get_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db

def init_db():
    db = get_db()
    db.execute('''CREATE TABLE IF NOT EXISTS registrations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        name TEXT NOT NULL,
        school TEXT NOT NULL,
        score TEXT DEFAULT '',
        phone TEXT NOT NULL UNIQUE
    )''')
    db.commit()
    db.close()

init_db()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json(force=True)
    name = (data.get('name') or '').strip()
    school = (data.get('school') or '').strip()
    score_raw = data.get('score', '')
    phone = (data.get('phone') or '').strip()

    errors = []
    if not name:
        errors.append('请输入学生姓名')
    if not school:
        errors.append('请选择所在初中')
    if not phone:
        errors.append('请输入联系电话')
    elif not phone.isdigit() or len(phone) != 11:
        errors.append('请输入11位手机号码')

    try:
        score = int(score_raw) if score_raw != '' else ''
        if score != '' and (score < 0 or score > 800):
            errors.append('分数应在0-800之间')
    except (ValueError, TypeError):
        score = score_raw
        if score_raw:
            errors.append('分数格式不正确')

    if errors:
        return jsonify({'ok': False, 'errors': errors}), 400

    # 写入数据库
    db = get_db()
    try:
        db.execute(
            'INSERT INTO registrations (timestamp, name, school, score, phone) VALUES (?, ?, ?, ?, ?)',
            (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), name, school, str(score) if score != '' else '未填', phone)
        )
        db.commit()
    except sqlite3.IntegrityError:
        return jsonify({'ok': False, 'errors': ['该手机号已注册，无需重复提交']}), 400
    finally:
        db.close()

    return jsonify({'ok': True, 'msg': '注册成功！我们会及时与您联系。'})

@app.route('/admin')
def admin():
    token = request.args.get('token', '')
    if token != ADMIN_TOKEN:
        return '<h3>访问被拒绝</h3><p>请在URL中添加正确的token</p>', 403
    db = get_db()
    records = [dict(r) for r in db.execute('SELECT * FROM registrations ORDER BY id DESC').fetchall()]
    db.close()
    school_count = {}
    for r in records:
        s = r.get('school', '未知')
        school_count[s] = school_count.get(s, 0) + 1
    school_stats = sorted(school_count.items(), key=lambda x: -x[1])
    return render_template('admin.html', records=records, total=len(records), school_stats=school_stats, token=token)

@app.route('/admin/export')
def export_csv():
    token = request.args.get('token', '')
    if token != ADMIN_TOKEN:
        return '拒绝访问', 403
    db = get_db()
    records = db.execute('SELECT * FROM registrations ORDER BY id').fetchall()
    db.close()
    with open(CSV_PATH, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=['timestamp', 'name', 'school', 'score', 'phone'])
        w.writeheader()
        for r in records:
            w.writerow(dict(r))
    return send_file(CSV_PATH, as_attachment=True, download_name='注册数据_' + datetime.now().strftime('%Y%m%d') + '.csv', mimetype='text/csv')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port, debug=False)
