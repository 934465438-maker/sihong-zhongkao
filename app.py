#!/usr/bin/env python3
"""泗洪中考志愿模拟填报 - Flask后端"""
import os, csv, re, sqlite3, random, time, hashlib
import requests as req_lib
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, send_file

app = Flask(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, 'registrations.db')
CSV_PATH = os.path.join(DATA_DIR, 'registrations.csv')
ADMIN_TOKEN = os.environ.get('ADMIN_TOKEN', 'sihong2026')

# ====== 短信验证码配置 ======
SMS_PROVIDER = os.environ.get('SMS_PROVIDER', 'mock')  # mock | smsbao
SMSBAO_USER = os.environ.get('SMSBAO_USER', '')
SMSBAO_PASS = os.environ.get('SMSBAO_PASS', '')
SMS_SIGN_NAME = os.environ.get('SMS_SIGN_NAME', '泗洪中考')
SMS_CODE_EXPIRE_MINUTES = int(os.environ.get('SMS_CODE_EXPIRE_MINUTES', '5'))
SMS_CODE_LENGTH = int(os.environ.get('SMS_CODE_LENGTH', '6'))
SMS_DAILY_LIMIT = int(os.environ.get('SMS_DAILY_LIMIT', '10'))
SMS_INTERVAL_SECONDS = int(os.environ.get('SMS_INTERVAL_SECONDS', '60'))

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
    db.execute('''CREATE TABLE IF NOT EXISTS sms_codes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phone TEXT NOT NULL,
        code TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expired_at TEXT NOT NULL,
        used INTEGER DEFAULT 0
    )''')
    db.commit()
    db.close()

init_db()

# ====== 短信发送函数 ======
def send_sms_smsbao(phone, code):
    """通过短信宝发送验证码"""
    if not SMSBAO_USER or not SMSBAO_PASS:
        return False, "短信宝账号或密码未配置"
    content = f"【{SMS_SIGN_NAME}】您的验证码是{code}，{SMS_CODE_EXPIRE_MINUTES}分钟内有效。请勿泄露给他人。"
    md5_pass = hashlib.md5(SMSBAO_PASS.encode('utf-8')).hexdigest()
    try:
        resp = req_lib.get('http://api.smsbao.com/sms', params={
            'u': SMSBAO_USER,
            'p': md5_pass,
            'm': phone,
            'c': content
        }, timeout=10)
        # 短信宝返回状态码：0=成功
        code_map = {
            '0': '成功', '1': '账号或密码错误', '2': '余额不足',
            '3': '手机号格式错误', '4': '内容含敏感词', '5': '签名不正确',
            '6': '频率过高', '7': '内容过长', '8': '号码不在白名单',
            '9': '账号被锁定', '10': 'IP不在白名单', '11': '不支持该运营商',
            '12': '模板不合规', '13': '内容过长', '14': '未知错误'
        }
        if resp.text == '0':
            return True, '验证码已发送'
        else:
            err_msg = code_map.get(resp.text, f'发送失败(代码{resp.text})')
            return False, f"短信发送失败: {err_msg}"
    except Exception as e:
        return False, f"短信服务异常: {str(e)}"

def send_sms_mock(phone, code):
    """模拟模式：验证码直接返回给前端（仅用于开发测试）"""
    return True, '验证码已发送（模拟模式）'

def generate_code():
    """生成指定长度的数字验证码"""
    code = ''
    for _ in range(SMS_CODE_LENGTH):
        code += str(random.randint(0, 9))
    return code

# ====== 验证码校验函数 ======
def verify_sms_code(phone, code):
    """校验验证码是否正确且未过期"""
    if not code:
        return False, '请输入验证码'
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    db = get_db()
    row = db.execute(
        'SELECT * FROM sms_codes WHERE phone = ? AND code = ? AND used = 0 AND expired_at > ? ORDER BY id DESC LIMIT 1',
        (phone, code, now)
    ).fetchone()
    if not row:
        db.close()
        return False, '验证码错误或已过期'
    # 标记为已使用
    db.execute('UPDATE sms_codes SET used = 1 WHERE id = ?', (row['id'],))
    db.commit()
    db.close()
    return True, '验证码正确'

@app.route('/')
def index():
    return render_template('index.html')

# ====== 发送验证码 API ======
@app.route('/api/send-code', methods=['POST'])
def send_code():
    data = request.get_json(force=True)
    phone = (data.get('phone') or '').strip()

    # 手机号格式校验
    if not phone:
        return jsonify({'ok': False, 'errors': ['请输入手机号']}), 400
    if not re.match(r'^1[3-9]\d{9}$', phone):
        return jsonify({'ok': False, 'errors': ['请输入有效的11位手机号码']}), 400

    db = get_db()
    now = datetime.now()
    now_str = now.strftime('%Y-%m-%d %H:%M:%S')

    # 频率限制：60秒内不能重复发送
    recent = db.execute(
        'SELECT created_at FROM sms_codes WHERE phone = ? AND created_at > ? ORDER BY id DESC LIMIT 1',
        (phone, (now - timedelta(seconds=SMS_INTERVAL_SECONDS)).strftime('%Y-%m-%d %H:%M:%S'))
    ).fetchone()
    if recent:
        elapsed = (now - datetime.strptime(recent['created_at'], '%Y-%m-%d %H:%M:%S')).total_seconds()
        remaining = int(SMS_INTERVAL_SECONDS - elapsed)
        db.close()
        return jsonify({'ok': False, 'errors': [f'发送太频繁，请{remaining}秒后再试']}), 429

    # 每日限制：每天最多10条
    today_start = now.strftime('%Y-%m-%d') + ' 00:00:00'
    today_count = db.execute(
        'SELECT COUNT(*) as cnt FROM sms_codes WHERE phone = ? AND created_at >= ?',
        (phone, today_start)
    ).fetchone()['cnt']
    if today_count >= SMS_DAILY_LIMIT:
        db.close()
        return jsonify({'ok': False, 'errors': [f'今日验证码发送次数已达上限（{SMS_DAILY_LIMIT}次）']}), 429

    # 生成验证码
    code = generate_code()
    expired_at = (now + timedelta(minutes=SMS_CODE_EXPIRE_MINUTES)).strftime('%Y-%m-%d %H:%M:%S')

    # 存入数据库
    db.execute(
        'INSERT INTO sms_codes (phone, code, created_at, expired_at, used) VALUES (?, ?, ?, ?, 0)',
        (phone, code, now_str, expired_at)
    )
    db.commit()
    db.close()

    # 发送短信
    if SMS_PROVIDER == 'mock':
        success, msg = send_sms_mock(phone, code)
    elif SMS_PROVIDER == 'smsbao':
        success, msg = send_sms_smsbao(phone, code)
    else:
        success, msg = False, "未配置短信服务商"

    if not success:
        return jsonify({'ok': False, 'errors': [msg]}), 500

    result = {'ok': True, 'msg': msg}
    # 模拟模式下返回验证码（方便开发调试，生产环境不会走这个分支）
    if SMS_PROVIDER == 'mock':
        result['code'] = code
    return jsonify(result)

# ====== 注册 API（增加验证码校验） ======
@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json(force=True)
    name = (data.get('name') or '').strip()
    school = (data.get('school') or '').strip()
    score_raw = data.get('score', '')
    phone = (data.get('phone') or '').strip()
    code = (data.get('code') or '').strip()

    errors = []
    if not name:
        errors.append('请输入学生姓名')
    if not school:
        errors.append('请选择所在初中')
    if not phone:
        errors.append('请输入联系电话')
    elif not re.match(r'^1[3-9]\d{9}$', phone):
        errors.append('请输入有效的11位手机号码（1开头）')
    if not code:
        errors.append('请输入验证码')

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

    # 校验验证码
    code_ok, code_msg = verify_sms_code(phone, code)
    if not code_ok:
        return jsonify({'ok': False, 'errors': [code_msg]}), 400

    db = get_db()
    try:
        db.execute(
            'INSERT INTO registrations (timestamp, name, school, score, phone) VALUES (?, ?, ?, ?, ?)',
            (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), name, school, str(score) if score != '' else '未填', phone)
        )
        db.commit()
    except sqlite3.IntegrityError:
        return jsonify({'ok': False, 'errors': ['该手机号已注册，请直接登录']}), 400
    finally:
        db.close()

    return jsonify({'ok': True, 'msg': '注册成功！', 'name': name, 'phone': phone})

# ====== 登录 API（增加验证码校验） ======
@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json(force=True)
    phone = (data.get('phone') or '').strip()
    code = (data.get('code') or '').strip()

    if not phone:
        return jsonify({'ok': False, 'errors': ['请输入手机号']}), 400
    if not re.match(r'^1[3-9]\d{9}$', phone):
        return jsonify({'ok': False, 'errors': ['手机号格式不正确']}), 400
    if not code:
        return jsonify({'ok': False, 'errors': ['请输入验证码']}), 400

    # 校验验证码
    code_ok, code_msg = verify_sms_code(phone, code)
    if not code_ok:
        return jsonify({'ok': False, 'errors': [code_msg]}), 400

    db = get_db()
    row = db.execute('SELECT name, school, score FROM registrations WHERE phone = ?', (phone,)).fetchone()
    db.close()

    if not row:
        return jsonify({'ok': False, 'errors': ['该手机号未注册，请先填写信息']}), 400

    return jsonify({'ok': True, 'name': row['name'], 'phone': phone, 'school': row['school'], 'score': row['score']})

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
