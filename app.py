#!/usr/bin/env python3
"""泗洪中考志愿模拟填报 - Flask后端（Supabase PostgreSQL版）"""
import os, csv, re, tempfile
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_file
from supabase import create_client, Client

app = Flask(__name__)

# ====== Supabase 配置 ======
SUPABASE_URL = os.environ.get('SUPABASE_URL', 'https://gyilfegdbmjdhwgrdpme.supabase.co')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imd5aWxmZWdkYm1qZGh3Z3JkcG1lIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4MDcxMTM5OSwiZXhwIjoyMDk2Mjg3Mzk5fQ.L67W1BWpTWe2F7GVq4q4CDHoHHF42Kn9fBX5aigIMhg')

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

ADMIN_TOKEN = os.environ.get('ADMIN_TOKEN', 'sihong2026')

@app.route('/')
def index():
    return render_template('index.html')

# ====== 注册 API ======
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
    elif not re.match(r'^1[3-9]\d{9}$', phone):
        errors.append('请输入有效的11位手机号码（1开头）')

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

    # 检查手机号是否已注册
    existing = supabase.table('registrations').select('id').eq('phone', phone).execute()
    if existing.data:
        return jsonify({'ok': False, 'errors': ['该手机号已注册，请直接登录']}), 400

    # 插入注册数据
    try:
        supabase.table('registrations').insert({
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'name': name,
            'school': school,
            'score': str(score) if score != '' else '未填',
            'phone': phone
        }).execute()
    except Exception as e:
        if 'duplicate' in str(e).lower() or 'unique' in str(e).lower():
            return jsonify({'ok': False, 'errors': ['该手机号已注册，请直接登录']}), 400
        return jsonify({'ok': False, 'errors': [f'注册失败，请重试']}), 500

    return jsonify({'ok': True, 'msg': '注册成功！', 'name': name, 'phone': phone})

# ====== 登录 API ======
@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json(force=True)
    phone = (data.get('phone') or '').strip()

    if not phone:
        return jsonify({'ok': False, 'errors': ['请输入手机号']}), 400
    if not re.match(r'^1[3-9]\d{9}$', phone):
        return jsonify({'ok': False, 'errors': ['手机号格式不正确']}), 400

    result = supabase.table('registrations').select('name, school, score').eq('phone', phone).execute()

    if not result.data:
        return jsonify({'ok': False, 'errors': ['该手机号未注册，请先填写信息']}), 400

    row = result.data[0]
    return jsonify({'ok': True, 'name': row['name'], 'phone': phone, 'school': row['school'], 'score': row['score']})

# ====== 管理后台 ======
@app.route('/admin')
def admin():
    token = request.args.get('token', '')
    if token != ADMIN_TOKEN:
        return '<h3>访问被拒绝</h3><p>请在URL中添加正确的token</p>', 403

    result = supabase.table('registrations').select('*').order('id', desc=True).execute()
    records = result.data

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

    result = supabase.table('registrations').select('*').order('id').execute()
    records = result.data

    # 写入临时文件
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8-sig', newline='')
    with tmp:
        w = csv.DictWriter(tmp, fieldnames=['timestamp', 'name', 'school', 'score', 'phone'])
        w.writeheader()
        for r in records:
            w.writerow({k: r.get(k, '') for k in ['timestamp', 'name', 'school', 'score', 'phone']})

    return send_file(tmp.name, as_attachment=True, download_name='注册数据_' + datetime.now().strftime('%Y%m%d') + '.csv', mimetype='text/csv')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port, debug=False)
