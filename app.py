"""
医院信息管理系统（HIS）—— Flask 后端主程序

功能页面：登录、工作台、患者档案、门诊挂号、医生工作站、收费结算、药房管理、住院管理、帮助中心
业务流程：建档 → 挂号 → 医生接诊开方 → 收费 → 药房发药；医生可转住院，护士办理入院/出院结算

运行：python app.py  然后浏览器访问 http://127.0.0.1:5000/
"""
import json
import os
import re
from datetime import date, datetime, timedelta
from functools import wraps

from flask import (Flask, abort, flash, g, jsonify, redirect, render_template,
                   request, session, url_for)
from markupsafe import Markup
from werkzeug.security import check_password_hash, generate_password_hash

from database import (INSURANCE_RATIO, LANGS, QUOTA_PER_PERIOD, add_payment, refund_prescription, create_prescription,
                      create_registration, current_period, dispense_prescription, get_conn,
                      init_db, next_no, now_str, pay_prescription, save_record, txt, used_quota)
from i18n import LANG_NAMES, MONTHS_EN, WEEKDAYS, WEEKDAYS_EN_FULL, _, get_lang, js_strings

app = Flask(__name__)
# 部署时请通过环境变量 SECRET_KEY 设置随机密钥；本地演示使用默认值
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'his-demo-secret-key')

ROLE_NAMES = {'admin': '系统管理员', 'doctor': '门诊医生', 'cashier': '挂号收费员',
              'pharmacist': '药剂师', 'nurse': '病区护士'}

# 侧边栏菜单：(端点, 名称, 图标, 可访问角色；None 表示所有角色)
MENU = [
    ('dashboard', '工作台', 'home', None),
    ('patients', '患者档案', 'users', {'doctor', 'cashier', 'nurse'}),
    ('registration', '门诊挂号', 'clipboard', {'cashier'}),
    ('clinic', '医生工作站', 'activity', {'doctor'}),
    ('billing', '收费结算', 'card', {'cashier'}),
    ('pharmacy', '药房管理', 'package', {'pharmacist'}),
    ('inpatient', '住院管理', 'bed', {'nurse'}),
    ('staff', '人员管理', 'settings', set()),          # 仅管理员
    ('help_page', '帮助中心', 'help', None),
]

# 线性图标（SVG 路径），统一使用当前文字颜色
ICONS = {
    'home': '<path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z"/>',
    'users': '<circle cx="9" cy="8" r="4"/><path d="M1 21v-1a6 6 0 0 1 6-6h4a6 6 0 0 1 6 6v1"/><path d="M16 4a4 4 0 0 1 0 8"/><path d="M23 21v-1a6 6 0 0 0-4-5.6"/>',
    'clipboard': '<rect x="5" y="4" width="14" height="18" rx="2"/><rect x="9" y="2" width="6" height="4" rx="1"/><path d="M9 12h6M9 16h4"/>',
    'activity': '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
    'card': '<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20M6 15h4"/>',
    'package': '<path d="M21 8 12 3 3 8v8l9 5 9-5z"/><path d="m3 8 9 5 9-5M12 13v8"/>',
    'bed': '<path d="M2 4v16M2 8h16a4 4 0 0 1 4 4v8M2 16h20"/><circle cx="7" cy="12" r="2"/>',
    'building': '<rect x="4" y="2" width="16" height="20" rx="1"/><path d="M9 22v-4h6v4M8 6h2M14 6h2M8 10h2M14 10h2M8 14h2M14 14h2"/>',
    'help': '<circle cx="12" cy="12" r="10"/><path d="M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3M12 17h.01"/>',
    'clock': '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
    'alert': '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/>',
    'money': '<path d="M12 1v22M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>',
    'search': '<circle cx="11" cy="11" r="7"/><path d="m21 21-5-5"/>',
    'settings': '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
}


def icon(name, size=18):
    return Markup(f'<svg class="icon" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
                  f'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
                  f'{ICONS.get(name, "")}</svg>')


STATUS_CLASS = {'待安排': 'danger', '已入院': 'ok', '已撤销': 'muted', '待诊': 'wait', '就诊中': 'info', '已诊': 'ok', '已退号': 'muted',
                '待缴费': 'danger', '已缴费': 'info', '已发药': 'ok',
                '在院': 'info', '出院': 'muted', '空闲': 'ok', '占用': 'info', '维修': 'danger', '停用': 'muted',
                '已过期': 'muted', '已退费': 'muted'}
BED_STATUSES = ['空闲', '维修', '停用']   # 可手动设置的床位状态（占用由入院/出院自动维护）
PAY_METHODS = ['微信', '支付宝', '现金', '银行卡', '医保结算']
DEMO_ACCOUNTS = {   # 登录页展示的核心演示账号（每种语言一套演示数据）
    'zh': ['admin', 'zhangwei', 'zhaolei', 'shoufei', 'yaofang', 'hushi'],
    'en': ['admin', 'jwilson', 'rtaylor', 'owhite', 'hadams', 'ghall'],
}
COMMON_DIAGNOSES = {   # 各科室常用诊断：{语言: {科室id: [诊断]}}
    'zh': {
        1: ['急性上呼吸道感染', '急性支气管炎', '原发性高血压', '2型糖尿病', '慢性胃炎', '高脂血症', '急性胃肠炎'],
        2: ['软组织挫伤', '皮肤裂伤', '急性阑尾炎', '腹股沟疝', '浅表脓肿', '腰椎间盘突出症'],
        3: ['小儿发热', '急性上呼吸道感染', '小儿腹泻', '疱疹性咽峡炎', '小儿支气管炎'],
        4: ['阴道炎', '早孕', '月经不调', '盆腔炎'],
        5: ['细菌性结膜炎', '干眼症', '屈光不正', '睑腺炎'],
        6: ['龋齿', '牙周炎', '慢性牙髓炎', '口腔溃疡'],
        7: ['急性胃肠炎', '软组织挫伤', '发热待查', '急性酒精中毒'],
    },
    'en': {
        1: ['Acute upper respiratory tract infection', 'Acute bronchitis', 'Essential hypertension',
            'Type 2 diabetes mellitus', 'Chronic gastritis', 'Hyperlipidemia', 'Acute gastroenteritis'],
        2: ['Soft tissue contusion', 'Skin laceration', 'Acute appendicitis', 'Inguinal hernia',
            'Superficial abscess', 'Lumbar disc herniation'],
        3: ['Fever in children', 'Acute upper respiratory tract infection', 'Diarrhea in children',
            'Herpangina', 'Bronchitis in children'],
        4: ['Vaginitis', 'Early pregnancy', 'Irregular menstruation', 'Pelvic inflammatory disease'],
        5: ['Bacterial conjunctivitis', 'Dry eye syndrome', 'Refractive error', 'Hordeolum'],
        6: ['Dental caries', 'Periodontitis', 'Chronic pulpitis', 'Oral ulcer'],
        7: ['Acute gastroenteritis', 'Soft tissue contusion', 'Fever of unknown origin', 'Acute alcohol intoxication'],
    },
}
COMMON_USAGES = {
    'zh': ['口服 一日3次 每次1粒', '口服 一日2次 每次1片', '口服 一日1次 每次1片',
           '口服 一日3次 每次1袋', '口服 一日2次 每次5ml', '滴眼 一日4次 每次1滴',
           '含漱 一日3次', '外用 一日3次', '静脉滴注 一日1次'],
    'en': ['Oral, 3 times daily, 1 capsule', 'Oral, twice daily, 1 tablet', 'Oral, once daily, 1 tablet',
           'Oral, 3 times daily, 1 sachet', 'Oral, twice daily, 5 ml', 'Eye drops, 4 times daily, 1 drop',
           'Gargle, 3 times daily', 'Topical, 3 times daily', 'IV infusion, once daily'],
}
NURSING_FEE = 25        # 住院每日护理费
MIN_DEPOSIT = 500       # 最低住院押金
MAX_DEPOSIT = 1000000   # 单次押金上限

app.jinja_env.globals.update(STATUS_CLASS=STATUS_CLASS, ROLE_NAMES=ROLE_NAMES, icon=icon, _=_,
                             get_lang=get_lang, LANG_NAMES=LANG_NAMES, js_strings=js_strings)


# ====================== 数据库工具 ======================
def db():
    if 'db' not in g:
        g.db = get_conn(get_lang())
    return g.db


@app.teardown_appcontext
def close_db(exc):
    conn = g.pop('db', None)
    if conn is not None:
        conn.close()


def one(sql, *args):
    return db().execute(sql, args).fetchone()


def rows(sql, *args):
    return db().execute(sql, args).fetchall()


def scalar(sql, *args):
    return db().execute(sql, args).fetchone()[0]


REG_SQL = ('SELECT r.*, p.name pname, p.card_no, p.gender, p.birth, p.allergy, p.insurance, '
           'u.name dname, u.title, d.name dept_name, d.location '
           'FROM registrations r JOIN patients p ON p.id = r.patient_id '
           'JOIN users u ON u.id = r.doctor_id JOIN departments d ON d.id = r.dept_id ')

RX_SQL = ('SELECT rx.*, r.reg_no, r.patient_id, p.name pname, p.card_no, p.gender, p.birth, p.insurance, '
          'u.name dname, d.name dept_name, rec.diagnosis '
          'FROM prescriptions rx JOIN registrations r ON r.id = rx.reg_id '
          'JOIN patients p ON p.id = r.patient_id JOIN users u ON u.id = r.doctor_id '
          'JOIN departments d ON d.id = r.dept_id LEFT JOIN records rec ON rec.reg_id = r.id ')


def rx_items_map(rx_ids):
    """批量读取处方明细：{处方id: [明细, ...]}"""
    result = {i: [] for i in rx_ids}
    if rx_ids:
        marks = ','.join('?' * len(rx_ids))
        for it in rows(f'SELECT i.*, d.name, d.spec, d.unit, d.stock FROM rx_items i '
                       f'JOIN drugs d ON d.id = i.drug_id WHERE i.rx_id IN ({marks})', *rx_ids):
            result[it['rx_id']].append(it)
    return result


# ====================== 登录与权限 ======================
def safe_path(path):
    """只允许站内相对路径，防止 next/back 参数被利用跳转到外部网站"""
    if path and path.startswith('/') and not path.startswith('//') and '\\' not in path:
        return path
    return None


def login_required(*roles):
    """登录校验；传入角色时，只有这些角色和管理员可以访问"""
    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if 'user_id' not in session:
                flash(_('登录已失效，请重新登录'), 'warning')
                nxt = request.full_path.rstrip('?') if request.method == 'GET' else None
                return redirect(url_for('login', next=nxt))
            if not scalar('SELECT COALESCE(MAX(active), 0) FROM users WHERE id=?', session['user_id']):
                session.clear()
                flash(_('该账号已停用，请联系信息科'), 'danger')
                return redirect(url_for('login'))
            if roles and session['role'] != 'admin' and session['role'] not in roles:
                flash(_('您的岗位无权使用该功能，如需开通请联系信息科'), 'danger')
                return redirect(url_for('dashboard'))
            return view(*args, **kwargs)
        return wrapper
    return decorator


def my_dept_id():
    """当前登录医生的科室 id；非医生返回 None"""
    if session.get('role') != 'doctor':
        return None
    return scalar('SELECT dept_id FROM users WHERE id=?', session['user_id'])


@app.template_filter('age')
def age_filter(birth):
    try:
        b = date.fromisoformat(birth)
    except (TypeError, ValueError):
        return ''
    t = date.today()
    years = t.year - b.year - ((t.month, t.day) < (b.month, b.day))
    if years > 0:
        return _('{0}岁', years)
    return _('{0}个月', max((t - b).days // 30, 0))


@app.template_filter('money')
def money_filter(v):
    return f'¥{(v or 0):,.2f}'


@app.before_request
def select_language():
    """界面语言：优先使用用户选择（cookie），否则按浏览器语言；中英文各用一套演示数据"""
    lang = request.cookies.get('lang')
    if lang not in LANGS:
        lang = request.accept_languages.best_match(['en', 'zh'], default='en')
    g.lang = lang


@app.before_request
def expire_registrations():
    today = date.today().isoformat()
    done = app.config.setdefault('EXPIRED_ON', {})
    if request.endpoint != 'static' and done.get(g.lang) != today:
        db().execute("UPDATE registrations SET status='已过期' WHERE visit_date < ? AND status='待诊'", (today,))
        db().commit()
        done[g.lang] = today


@app.route('/lang/<code>')
def switch_language(code):
    """切换界面语言；两种语言的演示数据相互独立，因此需要重新登录"""
    if code not in LANGS:
        abort(404)
    was_logged_in = 'user_id' in session
    session.clear()
    g.lang = code
    if was_logged_in:
        flash(_('已切换为中文界面，请使用中文演示账号重新登录'), 'info')
    resp = redirect(url_for('login'))
    resp.set_cookie('lang', code, max_age=365 * 24 * 3600)
    return resp


@app.context_processor
def inject_layout():
    """侧边栏菜单与待办角标（状态可见）"""
    if 'user_id' not in session:
        return {}
    role = session['role']
    today = date.today().isoformat()
    menu = [m for m in MENU if m[3] is None or role == 'admin' or role in m[3]]
    if role == 'doctor':
        waiting = scalar("SELECT COUNT(*) FROM registrations WHERE visit_date=? AND status='待诊' AND doctor_id=?",
                         today, session['user_id'])
    else:
        waiting = scalar("SELECT COUNT(*) FROM registrations WHERE visit_date=? AND status='待诊'", today)
    badges = {
        'clinic': waiting,
        'billing': scalar("SELECT COUNT(*) FROM prescriptions WHERE status='待缴费'"),
        'pharmacy': scalar("SELECT COUNT(*) FROM prescriptions WHERE status='已缴费'"),
        'inpatient': scalar("SELECT COUNT(*) FROM admission_requests WHERE status='待安排'"),
    }
    now = datetime.now()
    if get_lang() == 'en':
        today_text = f'{WEEKDAYS_EN_FULL[now.weekday()]}, {MONTHS_EN[now.month - 1]} {now.day}, {now.year}'
    else:
        today_text = f"{now.year}年{now.month}月{now.day}日 星期{WEEKDAYS['zh'][now.weekday()]}"
    can_search = any(m[0] == 'patients' for m in menu)
    return dict(menu=menu, badges=badges, role_name=_(ROLE_NAMES[role]), now_hour=now.hour, can_search=can_search,
                today_text=today_text, today_iso=date.today().isoformat())


@app.route('/login', methods=['GET', 'POST'])
def login():
    demo = DEMO_ACCOUNTS[get_lang()]
    marks = ','.join('?' * len(demo))
    accounts = rows(f'SELECT u.username, u.name, u.role, u.title, d.name dept_name FROM users u '
                    f'LEFT JOIN departments d ON d.id = u.dept_id WHERE u.username IN ({marks}) ORDER BY u.id',
                    *demo)
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        if not username or not password:
            flash(_('请输入工号和密码'), 'warning')
        else:
            user = one('SELECT u.*, d.name dept_name FROM users u LEFT JOIN departments d ON d.id = u.dept_id '
                       'WHERE username=?', username)
            if user and check_password_hash(user['password'], password) and not user['active']:
                flash(_('该账号已停用，如有疑问请联系信息科'), 'danger')
            elif user and check_password_hash(user['password'], password):
                session.clear()
                session.update(user_id=user['id'], username=user['username'], name=user['name'],
                               role=user['role'], dept_id=user['dept_id'], dept_name=user['dept_name'] or '',
                               title=user['title'] or '')
                flash(_('欢迎回来，{0}！', user['name']), 'success')
                nxt = request.args.get('next', '')
                resp = redirect(safe_path(nxt) or url_for('dashboard'))
                resp.set_cookie('last_user', username, max_age=30 * 24 * 3600)   # 记住上次登录工号
                return resp
            flash(_('工号或密码错误，请检查后重新输入'), 'danger')
        return render_template('login.html', username=username, accounts=accounts)
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('login.html', username=request.cookies.get('last_user', ''), accounts=accounts)


@app.route('/logout')
def logout():
    name = session.get('name', '')
    session.clear()
    flash(_('{0} 已安全退出系统', name), 'success')
    return redirect(url_for('login'))


# ====================== 工作台 ======================
@app.route('/')
@login_required()
def dashboard():
    today = date.today().isoformat()
    if session['role'] == 'doctor':
        return doctor_dashboard(today)
    stats = {
        'reg_today': scalar("SELECT COUNT(*) FROM registrations WHERE visit_date=? AND status!='已退号'", today),
        'waiting': scalar("SELECT COUNT(*) FROM registrations WHERE visit_date=? AND status IN ('待诊','就诊中')", today),
        'done': scalar("SELECT COUNT(*) FROM registrations WHERE visit_date=? AND status='已诊'", today),
        'unpaid': scalar("SELECT COUNT(*) FROM prescriptions WHERE status='待缴费'"),
        'undispensed': scalar("SELECT COUNT(*) FROM prescriptions WHERE status='已缴费'"),
        'inpatients': scalar("SELECT COUNT(*) FROM admissions WHERE status='在院'"),
        'free_beds': scalar("SELECT COUNT(*) FROM beds WHERE status='空闲'"),
        'total_beds': scalar("SELECT COUNT(*) FROM beds WHERE status!='停用'"),
        'income': scalar('SELECT COALESCE(SUM(amount), 0) FROM payments WHERE date(created_at)=?', today),
        'low_stock': scalar('SELECT COUNT(*) FROM drugs WHERE stock <= warn_level'),
        'new_patients': scalar('SELECT COUNT(*) FROM patients WHERE date(created_at)=?', today),
        'dispensed': scalar("SELECT COUNT(*) FROM prescriptions WHERE status='已发药' AND date(dispensed_at)=?", today),
        'drug_kinds': scalar('SELECT COUNT(*) FROM drugs'),
        'pending_req': scalar("SELECT COUNT(*) FROM admission_requests WHERE status='待安排'"),
        'admit_today': scalar('SELECT COUNT(*) FROM admissions WHERE admit_date=?', today),
        'discharge_today': scalar('SELECT COUNT(*) FROM admissions WHERE discharge_date=?', today),
    }
    st, m = stats, money_filter
    cards = {   # 各岗位工作台的统计卡片：(图标, 数值, 说明, 是否警示)
        'admin': [('clipboard', st['reg_today'], _('今日挂号（已诊 {0}）', st['done']), False),
                  ('clock', st['waiting'], _('候诊 / 就诊中'), False),
                  ('card', st['unpaid'], _('待缴费处方'), False), ('package', st['undispensed'], _('待发药处方'), False),
                  ('money', m(st['income']), _('今日实收（个人支付）'), False), ('bed', st['inpatients'], _('在院患者'), False),
                  ('building', f"{st['free_beds']}/{st['total_beds']}", _('空闲床位'), False),
                  ('alert', st['low_stock'], _('库存预警药品'), st['low_stock'] > 0)],
        'cashier': [('clipboard', st['reg_today'], _('今日挂号（已诊 {0}）', st['done']), False),
                    ('card', st['unpaid'], _('待缴费处方'), st['unpaid'] > 0),
                    ('money', m(st['income']), _('今日实收（个人支付）'), False),
                    ('users', st['new_patients'], _('今日新建档案'), False)],
        'pharmacist': [('package', st['undispensed'], _('待发药处方'), st['undispensed'] > 0),
                       ('activity', st['dispensed'], _('今日已发药'), False),
                       ('alert', st['low_stock'], _('库存预警药品'), st['low_stock'] > 0),
                       ('clipboard', st['drug_kinds'], _('药品目录品种'), False)],
        'nurse': [('clipboard', st['pending_req'], _('待入院申请'), st['pending_req'] > 0),
                  ('bed', st['inpatients'], _('在院患者'), False),
                  ('building', f"{st['free_beds']}/{st['total_beds']}", _('空闲床位'), False),
                  ('activity', f"{st['admit_today']} / {st['discharge_today']}", _('今日入院 / 出院'), False)],
    }[session['role']]
    dept_load = rows("SELECT d.name, d.location, COUNT(r.id) n FROM departments d "
                     "LEFT JOIN registrations r ON r.dept_id = d.id AND r.visit_date=? AND r.status!='已退号' "
                     "GROUP BY d.id ORDER BY n DESC", today)
    max_load = max([d['n'] for d in dept_load] + [1])
    recent = rows(REG_SQL + 'WHERE r.visit_date=? ORDER BY r.id DESC LIMIT 8', today)
    low_drugs = rows('SELECT * FROM drugs WHERE stock <= warn_level ORDER BY stock')
    to_dispense = rows(RX_SQL + "WHERE rx.status='已缴费' ORDER BY rx.paid_at LIMIT 8")
    pending_req = rows("SELECT q.*, p.name pname, p.gender, p.birth, u.name dname FROM admission_requests q "
                       "JOIN patients p ON p.id = q.patient_id JOIN users u ON u.id = q.doctor_id "
                       "WHERE q.status='待安排' ORDER BY q.id")
    inpatients = []
    for a in rows("SELECT a.*, p.name pname, p.gender, p.birth, b.ward, b.bed_no, b.daily_fee, u.name dname "
                  "FROM admissions a JOIN patients p ON p.id = a.patient_id JOIN beds b ON b.id = a.bed_id "
                  "LEFT JOIN users u ON u.id = a.doctor_id WHERE a.status='在院' ORDER BY b.ward, b.bed_no"):
        info = dict(a)
        info['days'], info['fee'] = admission_bill(a['id'], a['admit_date'], a['daily_fee'])
        inpatients.append(info)
    desc = _({'admin': '今日全院运行概况', 'cashier': '今日门诊挂号与收费概况',
               'pharmacist': '今日药房工作概况', 'nurse': '今日住院病区概况'}[session['role']])
    return render_template('dashboard.html', stats=stats, cards=cards, desc=desc, dept_load=dept_load,
                           max_load=max_load, recent=recent, low_drugs=low_drugs, to_dispense=to_dispense,
                           pending_req=pending_req, inpatients=inpatients)


def doctor_dashboard(today):
    """医生工作台：只显示本科室和本人的数据"""
    dept_id, uid = my_dept_id(), session['user_id']
    dept = one('SELECT * FROM departments WHERE id=?', dept_id)
    valid = "status NOT IN ('已退号','已过期')"
    stats = {
        'dept_reg': scalar(f'SELECT COUNT(*) FROM registrations WHERE visit_date=? AND dept_id=? AND {valid}', today, dept_id),
        'my_waiting': scalar("SELECT COUNT(*) FROM registrations WHERE visit_date=? AND doctor_id=? AND status IN ('待诊','就诊中')",
                             today, uid),
        'my_done': scalar("SELECT COUNT(*) FROM registrations WHERE visit_date=? AND doctor_id=? AND status='已诊'", today, uid),
        'dept_inpatients': scalar("SELECT COUNT(*) FROM admissions a JOIN users u ON u.id = a.doctor_id "
                                  "WHERE a.status='在院' AND u.dept_id=?", dept_id),
    }
    my_queue = rows(REG_SQL + "WHERE r.visit_date=? AND r.doctor_id=? AND r.status IN ('待诊','就诊中') "
                              "ORDER BY CASE r.status WHEN '就诊中' THEN 0 ELSE 1 END, r.period, r.queue_no", today, uid)
    recent = rows(REG_SQL + 'WHERE r.visit_date=? AND r.dept_id=? ORDER BY r.id DESC LIMIT 8', today, dept_id)
    doctor_load = rows(f"SELECT u.id, u.name, u.title, COUNT(r.id) n, COALESCE(SUM(r.status='已诊'), 0) done FROM users u "
                       f"LEFT JOIN registrations r ON r.doctor_id = u.id AND r.visit_date=? AND r.{valid} "
                       f"WHERE u.role='doctor' AND u.dept_id=? GROUP BY u.id ORDER BY n DESC", today, dept_id)
    inpatients = rows("SELECT a.*, p.name pname, p.gender, p.birth, b.ward, b.bed_no, u.name dname FROM admissions a "
                      "JOIN patients p ON p.id = a.patient_id JOIN beds b ON b.id = a.bed_id JOIN users u ON u.id = a.doctor_id "
                      "WHERE a.status='在院' AND u.dept_id=? ORDER BY a.admit_date", dept_id)
    requests_ = rows("SELECT q.*, p.name pname, p.gender, p.birth, b.ward, b.bed_no FROM admission_requests q "
                     "JOIN patients p ON p.id = q.patient_id LEFT JOIN admissions a ON a.id = q.adm_id "
                     "LEFT JOIN beds b ON b.id = a.bed_id WHERE q.doctor_id=? "
                     "ORDER BY q.status='待安排' DESC, q.id DESC LIMIT 6", uid)
    return render_template('dashboard_doctor.html', dept=dept, stats=stats, my_queue=my_queue, recent=recent,
                           doctor_load=doctor_load, max_load=max([d['n'] for d in doctor_load] + [1]),
                           inpatients=inpatients, requests=requests_)


# ====================== 患者档案 ======================
def validate_patient(f, pid=None):
    """校验患者表单，返回 {字段: 错误提示}"""
    errors = {}
    name = f.get('name', '').strip()
    if not name:
        errors['name'] = _('请填写患者姓名')
    elif len(name) > 20:
        errors['name'] = _('姓名不能超过20个字')
    if f.get('gender') not in ('男', '女'):
        errors['gender'] = _('请选择性别')
    try:
        birth = date.fromisoformat(f.get('birth', ''))
        if birth > date.today():
            errors['birth'] = _('出生日期不能晚于今天')
        elif birth.year < 1900:
            errors['birth'] = _('出生日期不正确')
    except ValueError:
        errors['birth'] = _('请选择出生日期')
    if not re.fullmatch(r'1[3-9]\d{9}', f.get('phone', '').strip()):
        errors['phone'] = _('手机号应为以1开头的11位数字')
    id_card = f.get('id_card', '').strip().upper()
    if id_card:
        if not re.fullmatch(r'\d{17}[\dX]', id_card):
            errors['id_card'] = _('身份证号应为18位，最后一位可为X')
        elif one('SELECT id FROM patients WHERE id_card=? AND id!=?', id_card, pid or 0):
            errors['id_card'] = _('该身份证号已建档，请勿重复建档（可在患者列表中搜索）')
    if f.get('insurance') not in INSURANCE_RATIO:
        errors['insurance'] = _('请选择医保类型')
    return errors


def patient_values(f):
    return (f['name'].strip(), f['gender'], f['birth'], f['phone'].strip(),
            f.get('id_card', '').strip().upper(), f['insurance'],
            f.get('allergy', '').strip(), f.get('address', '').strip())


@app.route('/patients')
@login_required('doctor', 'cashier', 'nurse')
def patients():
    q = request.args.get('q', '').strip()
    dept_id = my_dept_id()
    scope = request.args.get('scope', 'dept' if dept_id else 'all')
    sql = ("SELECT p.*, (SELECT MAX(visit_date) FROM registrations WHERE patient_id = p.id AND status!='已退号') last_visit, "
           "(SELECT COUNT(*) FROM admissions WHERE patient_id = p.id AND status='在院') in_hospital FROM patients p WHERE 1=1 ")
    args = []
    if dept_id and scope == 'dept':
        sql += ("AND (p.id IN (SELECT patient_id FROM registrations WHERE dept_id=?) OR p.id IN "
                "(SELECT a.patient_id FROM admissions a JOIN users u ON u.id = a.doctor_id WHERE u.dept_id=?)) ")
        args += [dept_id, dept_id]
    if q:
        sql += 'AND (p.name LIKE ? OR p.card_no LIKE ? OR p.phone LIKE ? OR p.id_card LIKE ?) '
        args += [f'%{q}%'] * 4
    patient_list = rows(sql + 'ORDER BY p.id DESC', *args)
    return render_template('patients.html', patients=patient_list, q=q, scope=scope, is_doctor=bool(dept_id))


@app.route('/patients/new', methods=['GET', 'POST'])
@login_required('doctor', 'cashier', 'nurse')
def patient_new():
    nxt = request.args.get('next', '')
    if request.method == 'POST':
        errors = validate_patient(request.form)
        if errors:
            flash(_('信息填写有误，请根据红色提示修改'), 'danger')
            return render_template('patient_form.html', form=request.form, errors=errors, mode='new', nxt=nxt)
        card_no = f"P{date.today().year}{scalar('SELECT COALESCE(MAX(id), 0) FROM patients') + 1:05d}"
        db().execute('INSERT INTO patients(card_no, name, gender, birth, phone, id_card, insurance, allergy, address, created_at) '
                     'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', (card_no,) + patient_values(request.form) + (now_str(),))
        db().commit()
        flash(_('建档成功！{0} 的就诊卡号为 {1}', request.form['name'].strip(), card_no), 'success')
        if nxt == 'registration':
            return redirect(url_for('registration', card=card_no))
        if nxt == 'inpatient':
            return redirect(url_for('inpatient', card=card_no) + '#admit')
        return redirect(url_for('patient_detail', pid=scalar('SELECT id FROM patients WHERE card_no=?', card_no)))
    return render_template('patient_form.html', form={'insurance': '自费'}, errors={}, mode='new', nxt=nxt)


@app.route('/patients/<int:pid>/edit', methods=['GET', 'POST'])
@login_required('doctor', 'cashier', 'nurse')
def patient_edit(pid):
    patient = one('SELECT * FROM patients WHERE id=?', pid) or abort(404)
    if request.method == 'POST':
        errors = validate_patient(request.form, pid)
        if errors:
            flash(_('信息填写有误，请根据红色提示修改'), 'danger')
            return render_template('patient_form.html', form=request.form, errors=errors, mode='edit', patient=patient)
        db().execute('UPDATE patients SET name=?, gender=?, birth=?, phone=?, id_card=?, insurance=?, allergy=?, address=? '
                     'WHERE id=?', patient_values(request.form) + (pid,))
        db().commit()
        flash(_('患者信息已更新'), 'success')
        return redirect(url_for('patient_detail', pid=pid))
    return render_template('patient_form.html', form=dict(patient), errors={}, mode='edit', patient=patient)


@app.route('/patients/<int:pid>')
@login_required('doctor', 'cashier', 'nurse')
def patient_detail(pid):
    patient = one('SELECT * FROM patients WHERE id=?', pid) or abort(404)
    visits = rows('SELECT r.*, u.name dname, d.name dept_name, rec.diagnosis, rec.complaint, rec.advice '
                  'FROM registrations r JOIN users u ON u.id = r.doctor_id JOIN departments d ON d.id = r.dept_id '
                  'LEFT JOIN records rec ON rec.reg_id = r.id WHERE r.patient_id=? ORDER BY r.visit_date DESC, r.id DESC', pid)
    payments = rows('SELECT * FROM payments WHERE patient_id=? ORDER BY id DESC', pid)
    admissions = rows('SELECT a.*, b.ward, b.bed_no, u.name dname FROM admissions a JOIN beds b ON b.id = a.bed_id '
                      'LEFT JOIN users u ON u.id = a.doctor_id WHERE a.patient_id=? ORDER BY a.id DESC', pid)
    return render_template('patient_detail.html', p=patient, visits=visits, payments=payments, admissions=admissions)


@app.route('/api/patient/<card>')
@login_required()
def api_patient(card):
    p = one('SELECT * FROM patients WHERE card_no=?', card.strip().upper())
    if not p:
        return jsonify(found=False)
    return jsonify(found=True, id=p['id'], name=p['name'], gender=_(p['gender']), age=age_filter(p['birth']),
                   insurance=_(p['insurance']), allergy=p['allergy'], phone=p['phone'][:3] + '****' + p['phone'][-4:])


# ====================== 门诊挂号 ======================
def visit_dates():
    """可预约日期：今天起 7 天"""
    result = []
    for i in range(7):
        d = date.today() + timedelta(days=i)
        if i < 2:
            label = _('今天') if i == 0 else _('明天')
        elif get_lang() == 'en':
            label = WEEKDAYS['en'][d.weekday()]
        else:
            label = '周' + WEEKDAYS['zh'][d.weekday()]
        result.append((d.isoformat(), f'{d.month}-{d.day} {label}'))
    return result


@app.route('/api/quota')
@login_required()
def api_quota():
    used = used_quota(db(), request.args.get('doctor_id', type=int), request.args.get('date', ''),
                      request.args.get('period', ''))
    return jsonify(used=used, remain=QUOTA_PER_PERIOD - used, total=QUOTA_PER_PERIOD)


@app.route('/registration', methods=['GET', 'POST'])
@login_required('cashier')
def registration():
    today = date.today().isoformat()
    form = {'card': request.args.get('card', ''), 'visit_date': today, 'period': current_period(), 'method': '微信'}
    if request.method == 'POST':
        form = request.form.to_dict()
        card = form.get('card', '').strip().upper().split(' ')[0]
        patient = one('SELECT * FROM patients WHERE card_no=?', card)
        doctor = one("SELECT * FROM users WHERE id=? AND role='doctor' AND active=1", request.form.get('doctor_id', type=int))
        errors = []
        if not patient:
            errors.append(_('未找到该就诊卡号，请核对或先为患者建档'))
        if not doctor:
            errors.append(_('请选择科室和就诊医生'))
        if form.get('visit_date') not in dict(visit_dates()):
            errors.append(_('就诊日期只能选择今天起7天内'))
        if form.get('period') not in ('上午', '下午'):
            errors.append(_('请选择就诊时段'))
        if form.get('method') not in PAY_METHODS[:4]:
            errors.append(_('请选择挂号费支付方式'))
        if form.get('visit_date') == today and form.get('period') == '上午' and datetime.now().hour >= 12:
            errors.append(_('今日上午门诊已结束，请选择下午或其他日期'))
        if not errors:
            if one("SELECT id FROM registrations WHERE patient_id=? AND doctor_id=? AND visit_date=? AND period=? "
                   "AND status!='已退号'", patient['id'], doctor['id'], form['visit_date'], form['period']):
                errors.append(_('{0} 已挂过该医生同一时段的号，请勿重复挂号', patient['name']))
            elif used_quota(db(), doctor['id'], form['visit_date'], form['period']) >= QUOTA_PER_PERIOD:
                errors.append(_('{0} 医生该时段号源已满，请选择其他时段或医生', doctor['name']))
        if errors:
            for e in errors:
                flash(e, 'danger')
        else:
            rid = create_registration(db(), patient['id'], doctor['id'], form['visit_date'], form['period'],
                                      form['method'], session['name'])
            db().commit()
            flash(_('挂号成功！{0} 已挂 {1} 医生的号，已收挂号费 ¥{2:.2f}', patient['name'], doctor['name'], doctor['reg_fee']), 'success')
            return redirect(url_for('registration', done=rid))

    status = request.args.get('status', '')
    sql = REG_SQL + 'WHERE r.visit_date=? '
    args = [today]
    if status:
        sql += 'AND r.status=? '
        args.append(status)
    today_regs = rows(sql + 'ORDER BY r.id DESC', *args)
    slip = one(REG_SQL + 'WHERE r.id=?', request.args.get('done', type=int) or 0)
    depts = rows('SELECT * FROM departments ORDER BY id')
    doctors = rows("SELECT id, name, title, reg_fee, specialty, dept_id FROM users WHERE role='doctor' AND active=1 "
                   "ORDER BY dept_id, reg_fee DESC")
    all_patients = rows('SELECT card_no, name, gender, birth FROM patients ORDER BY id DESC')
    recent_patients = rows('SELECT p.card_no, p.name FROM registrations r JOIN patients p ON p.id = r.patient_id '
                           'GROUP BY p.id ORDER BY MAX(r.id) DESC LIMIT 6')
    return render_template('registration.html', form=form, today_regs=today_regs, slip=slip, depts=depts,
                           doctors=[dict(d) for d in doctors], all_patients=all_patients,
                           recent_patients=recent_patients, dates=visit_dates(), status=status,
                           methods=PAY_METHODS[:4], today=today, am_closed=datetime.now().hour >= 12)


@app.route('/registration/<int:rid>/cancel', methods=['POST'])
@login_required('cashier')
def registration_cancel(rid):
    reg = one(REG_SQL + 'WHERE r.id=?', rid) or abort(404)
    if reg['status'] != '待诊':
        flash(_('该号当前状态为“{0}”，只有待诊状态才能退号', _(reg['status'])), 'warning')
    else:
        db().execute("UPDATE registrations SET status='已退号' WHERE id=?", (rid,))
        add_payment(db(), reg['patient_id'], txt(db(), 'reg_refund'), -reg['fee'], '原路退回', session['name'])
        db().commit()
        flash(_('已为 {0} 退号，挂号费 ¥{1:.2f} 将原路退回', reg['pname'], reg['fee']), 'success')
    return redirect(url_for('registration'))


# ====================== 医生工作站 ======================
def clinic_doctor_id():
    if session['role'] == 'doctor':
        return session['user_id']
    return request.values.get('doctor_id', type=int) or scalar("SELECT id FROM users WHERE role='doctor' ORDER BY id LIMIT 1")


@app.route('/clinic')
@login_required('doctor')
def clinic():
    doctor_id = clinic_doctor_id()
    today = date.today().isoformat()
    queue = rows(REG_SQL + "WHERE r.visit_date=? AND r.doctor_id=? AND r.status!='已退号' "
                           "ORDER BY CASE r.status WHEN '就诊中' THEN 0 WHEN '待诊' THEN 1 ELSE 2 END, r.period, r.queue_no",
                 today, doctor_id)
    doctor = one('SELECT u.*, d.name dept_name, d.location FROM users u JOIN departments d ON d.id = u.dept_id WHERE u.id=?',
                 doctor_id)
    if not doctor:
        abort(404)
    doctors = rows("SELECT u.id, u.name, d.name dept_name FROM users u JOIN departments d ON d.id = u.dept_id "
                   "WHERE role='doctor' ORDER BY u.dept_id")
    return render_template('clinic.html', queue=queue, doctor=doctor, doctors=doctors)


@app.route('/clinic/call-next', methods=['POST'])
@login_required('doctor')
def clinic_call_next():
    doctor_id = clinic_doctor_id()
    current = one(REG_SQL + "WHERE r.visit_date=? AND r.doctor_id=? AND r.status='就诊中'", date.today().isoformat(), doctor_id)
    if current:
        flash(_('{0} 正在就诊，请先完成就诊；如患者去做检查，可在接诊页点击“患者暂离”', current['pname']), 'warning')
        return redirect(url_for('clinic_visit', rid=current['id']))
    reg = one("SELECT * FROM registrations WHERE visit_date=? AND doctor_id=? AND status='待诊' "
              "ORDER BY period, queue_no LIMIT 1", date.today().isoformat(), doctor_id)
    if not reg:
        flash(_('当前没有待诊患者'), 'info')
        return redirect(url_for('clinic', doctor_id=doctor_id))
    return redirect(url_for('clinic_visit', rid=reg['id']))


@app.route('/clinic/visit/<int:rid>', methods=['GET', 'POST'])
@login_required('doctor')
def clinic_visit(rid):
    reg = one(REG_SQL + 'WHERE r.id=?', rid) or abort(404)
    if session['role'] == 'doctor' and reg['doctor_id'] != session['user_id']:
        flash(_('只能接诊挂在自己名下的患者'), 'danger')
        return redirect(url_for('clinic'))
    if reg['status'] in ('已退号', '已过期'):
        flash(_('该号已退号，无法接诊') if reg['status'] == '已退号' else _('该号已过期，无法接诊'), 'warning')
        return redirect(url_for('clinic', doctor_id=reg['doctor_id']))
    if reg['status'] == '待诊' and reg['visit_date'] != date.today().isoformat():
        flash(_('{0} 预约的是 {1} {2}，尚未到就诊日期', reg['pname'], reg['visit_date'], _(reg['period'])), 'warning')
        return redirect(url_for('clinic', doctor_id=reg['doctor_id']))
    if reg['status'] == '待诊':
        db().execute("UPDATE registrations SET status='就诊中' WHERE id=?", (rid,))
        db().commit()
        reg = one(REG_SQL + 'WHERE r.id=?', rid)

    patient = one('SELECT * FROM patients WHERE id=?', reg['patient_id'])
    record = one('SELECT * FROM records WHERE reg_id=?', rid)
    rx = one('SELECT * FROM prescriptions WHERE reg_id=?', rid)
    rx_items = rx_items_map([rx['id']])[rx['id']] if rx else []
    history = rows('SELECT r.visit_date, u.name dname, d.name dept_name, rec.complaint, rec.diagnosis, rec.advice '
                   'FROM registrations r JOIN records rec ON rec.reg_id = r.id JOIN users u ON u.id = r.doctor_id '
                   "JOIN departments d ON d.id = r.dept_id WHERE r.patient_id=? AND r.id!=? AND r.status='已诊' "
                   'ORDER BY r.visit_date DESC LIMIT 5', reg['patient_id'], rid)
    drugs = [dict(d) for d in rows('SELECT id, name, spec, unit, price, stock, allergen FROM drugs ORDER BY category, name')]
    form = dict(record) if record else {}
    items = []
    if record and record['draft_rx'] and reg['status'] == '就诊中':
        items = json.loads(record['draft_rx'])

    if request.method == 'POST' and reg['status'] != '就诊中':
        flash(_('本次就诊已完成，病历和处方已锁定，不能再修改'), 'warning')
    elif request.method == 'POST':
        items = []                     # 以本次提交的处方为准，不叠加之前的草稿
        action = request.form.get('action')
        form = request.form.to_dict()
        drug_map = {d['id']: d for d in drugs}
        errors = []
        for drug_id, qty, usage in zip(request.form.getlist('drug_id'), request.form.getlist('qty'),
                                       request.form.getlist('usage')):
            if not drug_id:
                continue
            drug = drug_map.get(int(drug_id)) if drug_id.isdigit() else None
            if not drug:
                continue
            if any(i['drug_id'] == drug['id'] for i in items):
                errors.append(_('{0} 重复添加，请合并为一行并填写总数量', drug['name']))
            items.append({'drug_id': drug['id'], 'qty': qty.strip(), 'usage': usage.strip()})
            if action == 'finish' and not usage.strip():
                errors.append(_('请填写 {0} 的用法用量', drug['name']))
            if not qty.strip().isdigit() or int(qty) <= 0:
                errors.append(_('{0} 的数量必须为正整数', drug['name']))
            elif int(qty) > drug['stock']:
                errors.append(_('{0} 库存仅剩 {1}{2}，请减少数量或更换药品', drug['name'], drug['stock'], drug['unit']))
        if action == 'finish':
            if not form.get('diagnosis', '').strip():
                errors.append(_('完成就诊前请填写诊断'))
            allergy = patient['allergy'] or ''
            risky = [drug_map[i['drug_id']]['name'] for i in items
                     if drug_map[i['drug_id']]['allergen'] and drug_map[i['drug_id']]['allergen'] in allergy]
            if risky and not request.form.get('allergy_confirm'):
                errors.append(_('患者有【{0}】过敏史，{1} 存在过敏风险！如确需使用，请勾选“已评估过敏风险”后再提交', allergy, '、'.join(risky)))
        if errors:
            for e in errors:
                flash(e, 'danger')
        else:
            draft = json.dumps(items, ensure_ascii=False) if action != 'finish' and items else ''
            save_record(db(), rid, form.get('complaint', '').strip(), form.get('history', '').strip(),
                        form.get('diagnosis', '').strip(), form.get('advice', '').strip(), draft)
            if action == 'suspend':     # 患者暂离（如去做检查），回到候诊队列，病历与处方草稿保留
                db().execute("UPDATE registrations SET status='待诊' WHERE id=?", (rid,))
                db().commit()
                flash(_('{0} 已暂离，病历草稿已保存；患者返回后可重新接诊', patient['name']), 'success')
                return redirect(url_for('clinic', doctor_id=reg['doctor_id']))
            if action == 'finish':
                if items:
                    create_prescription(db(), rid, [(i['drug_id'], int(i['qty']), i['usage']) for i in items])
                db().execute("UPDATE registrations SET status='已诊' WHERE id=?", (rid,))
                db().commit()
                flash(_('{0} 就诊完成，处方已发送至收费处', patient['name']) if items
                      else _('{0} 就诊完成（未开处方）', patient['name']), 'success')
                return redirect(url_for('clinic', doctor_id=reg['doctor_id']))
            db().commit()
            flash(_('病历和处方草稿已暂存，可稍后继续接诊') if items else _('病历已暂存'), 'success')
            return redirect(url_for('clinic_visit', rid=rid))

    adm_request = one('SELECT * FROM admission_requests WHERE reg_id=? ORDER BY id DESC', rid)
    in_hospital = one("SELECT a.*, b.ward, b.bed_no FROM admissions a JOIN beds b ON b.id = a.bed_id "
                      "WHERE a.patient_id=? AND a.status='在院'", reg['patient_id'])
    return render_template('clinic_visit.html', reg=reg, p=patient, form=form, items=items, rx=rx,
                           adm_request=adm_request, in_hospital=in_hospital,
                           rx_items=rx_items, history=history, drugs=drugs,
                           diagnoses=COMMON_DIAGNOSES[get_lang()].get(reg['dept_id'], sum(COMMON_DIAGNOSES[get_lang()].values(), [])),
                           usages=COMMON_USAGES[get_lang()])


@app.route('/clinic/visit/<int:rid>/admission-request', methods=['POST'])
@login_required('doctor')
def admission_request_new(rid):
    reg = one(REG_SQL + 'WHERE r.id=?', rid) or abort(404)
    if session['role'] == 'doctor' and reg['doctor_id'] != session['user_id']:
        flash(_('只能为自己接诊的患者开具住院证'), 'danger')
        return redirect(url_for('clinic'))
    diagnosis = request.form.get('diagnosis', '').strip()
    if reg['status'] not in ('就诊中', '已诊'):
        flash(_('请先接诊患者，再开具住院证'), 'warning')
    elif not diagnosis:
        flash(_('请填写入院诊断'), 'danger')
    elif one("SELECT id FROM admissions WHERE patient_id=? AND status='在院'", reg['patient_id']):
        flash(_('{0} 目前已在院，无需重复开具住院证', reg['pname']), 'warning')
    elif one("SELECT id FROM admission_requests WHERE patient_id=? AND status='待安排'", reg['patient_id']):
        flash(_('{0} 已有待安排的住院申请，请勿重复开具', reg['pname']), 'warning')
    else:
        db().execute("INSERT INTO admission_requests(req_no, reg_id, patient_id, doctor_id, diagnosis, note, status, created_at) "
                     "VALUES (?, ?, ?, ?, ?, ?, '待安排', ?)",
                     (next_no(db(), 'ZZ', 'admission_requests', 'req_no'), rid, reg['patient_id'], reg['doctor_id'],
                      diagnosis, request.form.get('note', '').strip(), now_str()))
        db().commit()
        flash(_('已为 {0} 开具住院证，已通知病区护士安排床位', reg['pname']), 'success')
    return redirect(url_for('clinic_visit', rid=rid))


@app.route('/admission-requests/<int:qid>/cancel', methods=['POST'])
@login_required('doctor', 'nurse')
def admission_request_cancel(qid):
    req = one('SELECT q.*, p.name pname FROM admission_requests q JOIN patients p ON p.id = q.patient_id WHERE q.id=?',
              qid) or abort(404)
    if session['role'] == 'doctor' and req['doctor_id'] != session['user_id']:
        flash(_('只能撤销自己开具的住院申请'), 'danger')
    elif req['status'] != '待安排':
        flash(_('该申请当前为“{0}”，不能撤销', _(req['status'])), 'warning')
    else:
        db().execute("UPDATE admission_requests SET status='已撤销', handled_at=? WHERE id=?", (now_str(), qid))
        db().commit()
        flash(_('已退回 {0} 的住院申请', req['pname']) if session['role'] == 'nurse'
              else _('已撤销 {0} 的住院申请', req['pname']), 'success')
    back = request.form.get('back', '')
    return redirect(safe_path(back) or url_for('dashboard'))


# ====================== 收费结算 ======================
@app.route('/billing')
@login_required('cashier')
def billing():
    q = request.args.get('q', '').strip()
    sql = RX_SQL + "WHERE rx.status='待缴费' "
    args = []
    if q:
        sql += 'AND (p.card_no LIKE ? OR p.name LIKE ?) '
        args = [f'%{q}%'] * 2
    pending = rows(sql + 'ORDER BY rx.id', *args)
    items = rx_items_map([r['id'] for r in pending])
    today = date.today().isoformat()
    flow = rows('SELECT pay.*, p.name pname, p.card_no FROM payments pay JOIN patients p ON p.id = pay.patient_id '
                'WHERE date(pay.created_at)=? ORDER BY pay.id DESC', today)
    summary = rows('SELECT method, COUNT(*) n, SUM(amount) total FROM payments WHERE date(created_at)=? '
                   'GROUP BY method ORDER BY total DESC', today)
    insurance_total = scalar('SELECT COALESCE(SUM(insurance_pay), 0) FROM payments WHERE date(created_at)=?', today)
    paid = rows(RX_SQL + "WHERE rx.status='已缴费' ORDER BY rx.paid_at DESC")
    items.update(rx_items_map([r['id'] for r in paid]))
    return render_template('billing.html', pending=pending, items=items, flow=flow, summary=summary, q=q,
                           paid=paid, tab=request.args.get('tab', 'pending'),
                           insurance_total=insurance_total, methods=PAY_METHODS, ratio=INSURANCE_RATIO)


@app.route('/billing/<int:rx_id>/refund', methods=['POST'])
@login_required('cashier')
def billing_refund(rx_id):
    rx = one(RX_SQL + 'WHERE rx.id=?', rx_id) or abort(404)
    if rx['status'] == '已发药':
        flash(_('药品已发出，需先到药房办理退药后才能退费'), 'warning')
    elif rx['status'] != '已缴费':
        flash(_('处方当前为“{0}”，无需退费', _(rx['status'])), 'warning')
    else:
        amount, ins = refund_prescription(db(), rx_id, session['name'])
        db().commit()
        if ins:
            flash(_('已为 {0} 办理退费：个人退回 ¥{1:.2f}，医保退回 ¥{2:.2f}', rx['pname'], amount, ins), 'success')
        else:
            flash(_('已为 {0} 办理退费：个人退回 ¥{1:.2f}', rx['pname'], amount), 'success')
    return redirect(url_for('billing', tab='paid'))


@app.route('/billing/<int:rx_id>/pay', methods=['POST'])
@login_required('cashier')
def billing_pay(rx_id):
    rx = one(RX_SQL + 'WHERE rx.id=?', rx_id) or abort(404)
    method = request.form.get('method')
    if rx['status'] != '待缴费':
        flash(_('该处方已缴费，请勿重复收费'), 'warning')
    elif method not in PAY_METHODS:
        flash(_('请选择支付方式'), 'danger')
    elif method == '医保结算' and rx['insurance'] == '自费':
        flash(_('{0} 为自费患者，不能使用医保结算，请选择其他支付方式', rx['pname']), 'danger')
    else:
        total, ins, personal = pay_prescription(db(), rx_id, method, session['name'])
        db().commit()
        if ins:
            flash(_('收费成功：{0} 处方总额 ¥{1:.2f}，医保统筹支付 ¥{2:.2f}，个人支付 ¥{3:.2f}（{4}）。请患者到药房取药',
                    rx['pname'], total, ins, personal, _(method)), 'success')
        else:
            flash(_('收费成功：{0} 处方总额 ¥{1:.2f}，个人支付 ¥{2:.2f}（{3}）。请患者到药房取药',
                    rx['pname'], total, personal, _(method)), 'success')
    return redirect(url_for('billing'))


# ====================== 药房管理 ======================
@app.route('/pharmacy')
@login_required('pharmacist')
def pharmacy():
    tab = request.args.get('tab', 'dispense')
    q = request.args.get('q', '').strip()
    to_dispense = rows(RX_SQL + "WHERE rx.status='已缴费' ORDER BY rx.paid_at")
    dispensed = rows(RX_SQL + "WHERE rx.status='已发药' AND date(rx.dispensed_at)=? ORDER BY rx.dispensed_at DESC",
                     date.today().isoformat())
    items = rx_items_map([r['id'] for r in list(to_dispense) + list(dispensed)])
    sql, args = 'SELECT * FROM drugs ', []
    if q:
        sql += 'WHERE name LIKE ? OR code LIKE ? OR category LIKE ? '
        args = [f'%{q}%'] * 3
    drugs = rows(sql + 'ORDER BY (stock <= warn_level) DESC, category, code', *args)
    categories = [r[0] for r in rows('SELECT DISTINCT category FROM drugs ORDER BY category')]
    return render_template('pharmacy.html', tab=tab, q=q, to_dispense=to_dispense, dispensed=dispensed,
                           items=items, drugs=drugs, categories=categories, form={})


@app.route('/pharmacy/<int:rx_id>/dispense', methods=['POST'])
@login_required('pharmacist')
def pharmacy_dispense(rx_id):
    rx = one(RX_SQL + 'WHERE rx.id=?', rx_id) or abort(404)
    if rx['status'] != '已缴费':
        flash(_('处方状态为“{0}”，无法发药', _(rx['status'])), 'warning')
    else:
        shortage = dispense_prescription(db(), rx_id)
        if shortage:
            flash(_('库存不足，无法发药：{0}。请先入库', _('；').join(shortage)), 'danger')
        else:
            db().commit()
            flash(_('已为 {0} 完成发药，请核对药品并交代用法用量', rx['pname']), 'success')
    return redirect(url_for('pharmacy'))


@app.route('/pharmacy/drug/<int:drug_id>/stock-in', methods=['POST'])
@login_required('pharmacist')
def pharmacy_stock_in(drug_id):
    drug = one('SELECT * FROM drugs WHERE id=?', drug_id) or abort(404)
    qty = request.form.get('qty', '')
    if not qty.isdigit() or not 1 <= int(qty) <= 10000:
        flash(_('入库数量应为 1~10000 的整数'), 'danger')
    else:
        db().execute('UPDATE drugs SET stock = stock + ? WHERE id=?', (int(qty), drug_id))
        db().commit()
        flash(_('{0} 入库 {1}{2}，当前库存 {3}{4}', drug['name'], qty, drug['unit'], drug['stock'] + int(qty), drug['unit']), 'success')
    return redirect(url_for('pharmacy', tab='stock', q=request.form.get('q', '')))


@app.route('/pharmacy/drug/<int:drug_id>/price', methods=['POST'])
@login_required('pharmacist')
def pharmacy_price(drug_id):
    drug = one('SELECT * FROM drugs WHERE id=?', drug_id) or abort(404)
    try:
        price = round(float(request.form.get('price', '')), 2)
        if not 0 < price <= 100000:
            raise ValueError
        db().execute('UPDATE drugs SET price=? WHERE id=?', (price, drug_id))
        db().commit()
        flash(_('{0} 单价由 ¥{1:.2f} 调整为 ¥{2:.2f}（已开具的处方仍按原价结算）', drug['name'], drug['price'], price), 'success')
    except ValueError:
        flash(_('单价应为 0.01~100000 之间的数字'), 'danger')
    return redirect(url_for('pharmacy', tab='stock', q=request.form.get('q', '')))


@app.route('/pharmacy/drug/new', methods=['POST'])
@login_required('pharmacist')
def pharmacy_drug_new():
    f = request.form
    errors = []
    code = f.get('code', '').strip().upper()
    if not re.fullmatch(r'YP\d{3,}', code):
        errors.append(_('药品编码格式为 YP + 数字，如 YP017'))
    elif one('SELECT id FROM drugs WHERE code=?', code):
        errors.append(_('药品编码 {0} 已存在', code))
    if not f.get('name', '').strip():
        errors.append(_('请填写药品名称'))
    try:
        price = float(f.get('price', ''))
        if price <= 0:
            raise ValueError
    except ValueError:
        errors.append(_('单价必须为大于0的数字'))
    for key, label in (('stock', '初始库存'), ('warn_level', '预警线')):
        if not f.get(key, '').isdigit():
            errors.append(_('{0}必须为非负整数', _(label)))
    if errors:
        for e in errors:
            flash(e, 'danger')
        return redirect(url_for('pharmacy', tab='stock'))
    db().execute('INSERT INTO drugs(code, name, spec, unit, price, stock, warn_level, category, allergen) '
                 'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                 (code, f['name'].strip(), f.get('spec', '').strip(), f.get('unit', _('盒')).strip() or _('盒'),
                  price, int(f['stock']), int(f['warn_level']), f.get('category', '').strip() or _('其他'),
                  f.get('allergen', '').strip()))
    db().commit()
    flash(_('新药品 {0} 已加入药品目录', f['name'].strip()), 'success')
    return redirect(url_for('pharmacy', tab='stock'))


# ====================== 住院管理 ======================
def admission_bill(adm_id, admit_date, daily_fee):
    """住院费用：床位费按转床前后分段计算，护理费按总天数计算，不足1天按1天计"""
    start = date.fromisoformat(admit_date)
    days = max((date.today() - start).days, 1)
    moves = rows('SELECT t.created_at, b.daily_fee FROM bed_transfers t JOIN beds b ON b.id = t.from_bed '
                 'WHERE t.adm_id=? ORDER BY t.id', adm_id)
    bed_total, counted, cursor = 0, 0, start
    for m in moves:
        moved_on = date.fromisoformat(m['created_at'][:10])
        seg = max((moved_on - cursor).days, 0)
        bed_total += seg * m['daily_fee']
        counted += seg
        cursor = moved_on
    bed_total += max(days - counted, 0) * daily_fee
    return days, bed_total + days * NURSING_FEE


@app.route('/inpatient')
@login_required('nurse')
def inpatient():
    dept_id = my_dept_id()
    where, args = '', []
    if dept_id:
        where, args = 'WHERE w.dept_id=? OR u.dept_id=? ', [dept_id, dept_id]
    beds = rows("SELECT b.*, a.id adm_id, a.adm_no, a.admit_date, a.diagnosis, a.deposit, "
                "p.name pname, p.gender, p.birth, p.card_no, p.allergy, u.name dname "
                "FROM beds b LEFT JOIN wards w ON w.name = b.ward "
                "LEFT JOIN admissions a ON a.bed_id = b.id AND a.status='在院' "
                "LEFT JOIN patients p ON p.id = a.patient_id LEFT JOIN users u ON u.id = a.doctor_id "
                + where + "ORDER BY w.id, b.bed_no", *args)
    wards = {}
    for b in beds:
        info = dict(b)
        if b['adm_id']:
            info['days'], info['fee'] = admission_bill(b['adm_id'], b['admit_date'], b['daily_fee'])
        wards.setdefault(b['ward'], []).append(info)
    # 可选床位：本科室病区排在前面（本科室没有病区时也可收治到其他病区）
    free_beds = rows("SELECT b.*, w.dept_id FROM beds b LEFT JOIN wards w ON w.name = b.ward WHERE b.status='空闲' "
                     "ORDER BY (w.dept_id IS ?) DESC, w.id, b.bed_no", dept_id)
    doctors = rows("SELECT u.id, u.name, d.name dept_name FROM users u JOIN departments d ON d.id = u.dept_id "
                   "WHERE role='doctor' " + ("AND u.dept_id=? " if dept_id else "") + "ORDER BY u.dept_id",
                   *([dept_id] if dept_id else []))
    discharged = rows("SELECT a.*, p.name pname, b.ward, b.bed_no FROM admissions a JOIN patients p ON p.id = a.patient_id "
                      "JOIN beds b ON b.id = a.bed_id LEFT JOIN users u ON u.id = a.doctor_id WHERE a.status='出院' "
                      + ("AND u.dept_id=? " if dept_id else "") + "ORDER BY a.id DESC LIMIT 5",
                      *([dept_id] if dept_id else []))
    form = {'card': request.args.get('card', ''), 'bed_id': request.args.get('bed', ''),
            'diagnosis': request.args.get('diagnosis', ''), 'deposit': '3000',
            'doctor_id': request.args.get('doctor', ''), 'req_id': ''}
    pending = rows("SELECT q.*, p.name pname, p.gender, p.birth, p.card_no, p.allergy, u.name dname, d.name dept_name "
                   "FROM admission_requests q JOIN patients p ON p.id = q.patient_id JOIN users u ON u.id = q.doctor_id "
                   "JOIN departments d ON d.id = u.dept_id WHERE q.status='待安排' ORDER BY q.id")
    chosen = next((q for q in pending if q['id'] == request.args.get('req', type=int)), None)
    if chosen:
        form.update(card=chosen['card_no'], diagnosis=chosen['diagnosis'], doctor_id=chosen['doctor_id'], req_id=chosen['id'])
    return render_template('inpatient.html', wards=wards, free_beds=free_beds, doctors=doctors, form=form,
                           discharged=discharged, nursing_fee=NURSING_FEE, min_deposit=MIN_DEPOSIT,
                           dept_id=dept_id, pending=pending, chosen=chosen)


@app.route('/inpatient/admit', methods=['POST'])
@login_required('nurse')
def inpatient_admit():
    f = request.form
    patient = one('SELECT * FROM patients WHERE card_no=?', f.get('card', '').strip().upper())
    bed = one('SELECT * FROM beds WHERE id=?', f.get('bed_id', type=int) or 0)
    errors = []
    if not patient:
        errors.append(_('未找到该就诊卡号，请先为患者建档'))
    elif one("SELECT id FROM admissions WHERE patient_id=? AND status='在院'", patient['id']):
        errors.append(_('{0} 目前已在院，不能重复办理入院', patient['name']))
    if not bed:
        errors.append(_('请选择床位'))
    elif bed['status'] != '空闲':
        errors.append(_('{0} {1} 床当前为“{2}”，请选择其他空闲床位', bed['ward'], bed['bed_no'], _(bed['status'])))
    if not f.get('diagnosis', '').strip():
        errors.append(_('请填写入院诊断'))
    try:
        deposit = float(f.get('deposit', ''))
        if deposit < MIN_DEPOSIT:
            errors.append(_('住院押金不能少于 ¥{0}', MIN_DEPOSIT))
        elif deposit > MAX_DEPOSIT:
            errors.append(_('押金金额过大，请核对后重新输入'))
    except ValueError:
        errors.append(_('押金金额格式不正确'))
    if errors:
        for e in errors:
            flash(e, 'danger')
        if f.get('req_id'):
            return redirect(url_for('inpatient', req=f['req_id'], bed=f.get('bed_id', '')) + '#admit')
        return redirect(url_for('inpatient', card=f.get('card', ''), bed=f.get('bed_id', ''),
                                diagnosis=f.get('diagnosis', ''), doctor=f.get('doctor_id', '')) + '#admit')
    db().execute("INSERT INTO admissions(adm_no, patient_id, bed_id, doctor_id, diagnosis, deposit, admit_date, status) "
                 "VALUES (?, ?, ?, ?, ?, ?, ?, '在院')",
                 (next_no(db(), 'ZY', 'admissions', 'adm_no'), patient['id'], bed['id'],
                  f.get('doctor_id', type=int), f['diagnosis'].strip(), deposit, date.today().isoformat()))
    db().execute("UPDATE beds SET status='占用' WHERE id=?", (bed['id'],))
    adm_id = scalar("SELECT MAX(id) FROM admissions WHERE patient_id=?", patient['id'])
    db().execute("UPDATE admission_requests SET status='已入院', adm_id=?, handled_at=? WHERE patient_id=? AND status='待安排'",
                 (adm_id, now_str(), patient['id']))
    add_payment(db(), patient['id'], txt(db(), 'deposit'), deposit, f.get('method', '银行卡'), session['name'])
    db().commit()
    flash(_('{0} 已办理入院，床位 {1} {2}，收取押金 ¥{3:.2f}', patient['name'], bed['ward'], bed['bed_no'], deposit), 'success')
    return redirect(url_for('inpatient'))


@app.route('/inpatient/<int:aid>/deposit', methods=['POST'])
@login_required('nurse')
def inpatient_deposit(aid):
    adm = one("SELECT a.*, p.name pname FROM admissions a JOIN patients p ON p.id = a.patient_id WHERE a.id=?", aid) or abort(404)
    try:
        amount = float(request.form.get('amount', ''))
    except ValueError:
        amount = 0
    if adm['status'] != '在院':
        flash(_('患者已出院，不能补交押金'), 'warning')
    elif not 100 <= amount <= MAX_DEPOSIT:
        flash(_('补交金额应在 ¥100 以上'), 'danger')
    else:
        db().execute('UPDATE admissions SET deposit = deposit + ? WHERE id=?', (amount, aid))
        add_payment(db(), adm['patient_id'], txt(db(), 'deposit_extra'), amount, request.form.get('method', '银行卡'), session['name'])
        db().commit()
        flash(_('{0} 补交押金 ¥{1:.2f}，押金合计 ¥{2:.2f}', adm['pname'], amount, adm['deposit'] + amount), 'success')
    return redirect(safe_path(request.form.get('back', '')) or url_for('inpatient'))


@app.route('/inpatient/<int:aid>/discharge', methods=['POST'])
@login_required('nurse')
def inpatient_discharge(aid):
    adm = one("SELECT a.*, b.daily_fee, b.ward, b.bed_no, p.name pname FROM admissions a JOIN beds b ON b.id = a.bed_id "
              "JOIN patients p ON p.id = a.patient_id WHERE a.id=?", aid) or abort(404)
    if adm['status'] != '在院':
        flash(_('该患者已出院'), 'warning')
        return redirect(url_for('inpatient'))
    days, total = admission_bill(adm['id'], adm['admit_date'], adm['daily_fee'])
    balance = adm['deposit'] - total
    db().execute("UPDATE admissions SET status='出院', discharge_date=?, total_fee=? WHERE id=?",
                 (date.today().isoformat(), total, aid))
    db().execute("UPDATE beds SET status='空闲' WHERE id=?", (adm['bed_id'],))
    if balance >= 0:
        add_payment(db(), adm['patient_id'], txt(db(), 'settle_refund'), -balance, '原路退回', session['name'])
        tail = _('退还押金 ¥{0:.2f}', balance)
    else:
        add_payment(db(), adm['patient_id'], txt(db(), 'settle_pay'), -balance, '银行卡', session['name'])
        tail = _('需补缴 ¥{0:.2f}', -balance)
    db().commit()
    flash(_('{0} 出院结算完成：住院 {1} 天，费用 ¥{2:.2f}，押金 ¥{3:.2f}，{4}', adm['pname'], days, total, adm['deposit'], tail), 'success')
    return redirect(url_for('inpatient'))


# ====================== 住院管理 · 病区设置 ======================
WARD_STATS_SQL = ("SELECT w.*, d.name dept_name, COUNT(b.id) total, "
                  "COALESCE(SUM(b.status='占用'), 0) used, COALESCE(SUM(b.status='空闲'), 0) free, "
                  "COALESCE(SUM(b.status='维修'), 0) repair, COALESCE(SUM(b.status='停用'), 0) disabled "
                  "FROM wards w LEFT JOIN departments d ON d.id = w.dept_id LEFT JOIN beds b ON b.ward = w.name ")


def validate_ward(f, ward_id=None):
    errors = []
    name = f.get('name', '').strip()
    if not name:
        errors.append(_('请填写病区名称'))
    elif one('SELECT id FROM wards WHERE name=? AND id!=?', name, ward_id or 0):
        errors.append(_('病区“{0}”已存在', name))
    if ward_id is None:
        code = f.get('code', '').strip().upper()
        if not re.fullmatch(r'[A-Z]{1,2}', code):
            errors.append(_('床号前缀应为 1~2 个英文字母，如 N、IC'))
        elif one('SELECT id FROM wards WHERE code=?', code):
            errors.append(_('床号前缀 {0} 已被其他病区使用', code))
    try:
        if float(f.get('bed_fee', '')) <= 0:
            raise ValueError
    except ValueError:
        errors.append(_('床位费必须为大于0的数字'))
    phone = f.get('phone', '').strip()
    if phone and not re.fullmatch(r'[\d-]{7,15}', phone):
        errors.append(_('联系电话格式不正确'))
    return errors


def add_beds(ward, count):
    """按“前缀+两位序号”续号新增床位，返回起止序号"""
    prefix = ward['code']
    nums = [int(r['bed_no'][len(prefix):]) for r in rows('SELECT bed_no FROM beds WHERE ward=?', ward['name'])
            if r['bed_no'][len(prefix):].isdigit()]
    start = max(nums + [0]) + 1
    for k in range(start, start + count):
        db().execute('INSERT INTO beds(ward, bed_no, daily_fee) VALUES (?, ?, ?)',
                     (ward['name'], f'{prefix}{k:02d}', ward['bed_fee']))
    return start, start + count - 1


@app.route('/wards')
@login_required('nurse')
def wards():
    ward_list = rows(WARD_STATS_SQL + 'GROUP BY w.id ORDER BY w.id')
    totals = {k: sum(w[k] for w in ward_list) for k in ('total', 'used', 'free', 'repair', 'disabled')}
    usable = totals['total'] - totals['disabled']
    totals['rate'] = round(totals['used'] / usable * 100) if usable else 0
    transfers = rows('SELECT t.*, p.name pname, fb.ward from_ward, fb.bed_no from_no, tb.ward to_ward, tb.bed_no to_no '
                     'FROM bed_transfers t JOIN admissions a ON a.id = t.adm_id JOIN patients p ON p.id = a.patient_id '
                     'JOIN beds fb ON fb.id = t.from_bed JOIN beds tb ON tb.id = t.to_bed ORDER BY t.id DESC LIMIT 8')
    depts = rows('SELECT * FROM departments ORDER BY id')
    return render_template('wards.html', wards=ward_list, totals=totals, transfers=transfers, depts=depts)


@app.route('/wards/new', methods=['POST'])
@login_required('nurse')
def ward_new():
    f = request.form
    errors = validate_ward(f)
    count = f.get('count', '0')
    if not count.isdigit() or int(count) > 50:
        errors.append(_('初始床位数应为 0~50 的整数'))
    if errors:
        for e in errors:
            flash(e, 'danger')
        return redirect(url_for('wards'))
    db().execute('INSERT INTO wards(name, code, dept_id, location, head_nurse, phone, bed_fee, created_at) '
                 'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                 (f['name'].strip(), f['code'].strip().upper(), f.get('dept_id', type=int), f.get('location', '').strip(),
                  f.get('head_nurse', '').strip(), f.get('phone', '').strip(), float(f['bed_fee']), now_str()))
    ward = one('SELECT * FROM wards WHERE name=?', f['name'].strip())
    if int(count):
        add_beds(ward, int(count))
    db().commit()
    flash(_('病区“{0}”已创建，共 {1} 张床位', ward['name'], int(count)), 'success')
    return redirect(url_for('ward_detail', wid=ward['id']))


@app.route('/wards/<int:wid>')
@login_required('nurse')
def ward_detail(wid):
    ward = one(WARD_STATS_SQL + 'WHERE w.id=? GROUP BY w.id', wid) or abort(404)
    beds = rows("SELECT b.*, a.id adm_id, a.admit_date, a.diagnosis, p.name pname, p.gender, p.birth, p.card_no, "
                "(SELECT COUNT(*) FROM admissions WHERE bed_id = b.id) used_times "
                "FROM beds b LEFT JOIN admissions a ON a.bed_id = b.id AND a.status='在院' "
                "LEFT JOIN patients p ON p.id = a.patient_id WHERE b.ward=? ORDER BY b.bed_no", ward['name'])
    free_beds = rows("SELECT b.id, b.ward, b.bed_no, b.daily_fee FROM beds b LEFT JOIN wards w ON w.name = b.ward "
                     "WHERE b.status='空闲' ORDER BY w.id, b.bed_no")
    depts = rows('SELECT * FROM departments ORDER BY id')
    return render_template('ward_detail.html', ward=ward, beds=beds, free_beds=free_beds, depts=depts,
                           bed_statuses=BED_STATUSES)


@app.route('/wards/<int:wid>/edit', methods=['POST'])
@login_required('nurse')
def ward_edit(wid):
    ward = one('SELECT * FROM wards WHERE id=?', wid) or abort(404)
    f = request.form
    errors = validate_ward(f, wid)
    if errors:
        for e in errors:
            flash(e, 'danger')
        return redirect(url_for('ward_detail', wid=wid))
    name, fee = f['name'].strip(), float(f['bed_fee'])
    db().execute('UPDATE wards SET name=?, dept_id=?, location=?, head_nurse=?, phone=?, bed_fee=? WHERE id=?',
                 (name, f.get('dept_id', type=int), f.get('location', '').strip(), f.get('head_nurse', '').strip(),
                  f.get('phone', '').strip(), fee, wid))
    db().execute('UPDATE beds SET ward=? WHERE ward=?', (name, ward['name']))
    if f.get('sync_fee'):
        db().execute("UPDATE beds SET daily_fee=? WHERE ward=? AND status!='占用'", (fee, name))
    db().commit()
    flash(_('病区信息已保存，本病区空闲床位的床位费已同步调整（在住床位待出院后再调整）') if f.get('sync_fee')
          else _('病区信息已保存'), 'success')
    return redirect(url_for('ward_detail', wid=wid))


@app.route('/wards/<int:wid>/delete', methods=['POST'])
@login_required('nurse')
def ward_delete(wid):
    ward = one('SELECT * FROM wards WHERE id=?', wid) or abort(404)
    if scalar('SELECT COUNT(*) FROM beds WHERE ward=?', ward['name']):
        flash(_('该病区还有床位，请先删除全部床位后再撤销病区'), 'danger')
        return redirect(url_for('ward_detail', wid=wid))
    db().execute('DELETE FROM wards WHERE id=?', (wid,))
    db().commit()
    flash(_('病区“{0}”已撤销', ward['name']), 'success')
    return redirect(url_for('wards'))


@app.route('/wards/<int:wid>/beds/add', methods=['POST'])
@login_required('nurse')
def ward_add_beds(wid):
    ward = one('SELECT * FROM wards WHERE id=?', wid) or abort(404)
    count = request.form.get('count', '')
    if not count.isdigit() or not 1 <= int(count) <= 20:
        flash(_('每次可增加 1~20 张床位'), 'danger')
    else:
        start, end = add_beds(ward, int(count))
        db().commit()
        flash(_('已新增 {0} 张床位：{1}{2:02d} ~ {3}{4:02d}', count, ward['code'], start, ward['code'], end), 'success')
    return redirect(url_for('ward_detail', wid=wid))


def bed_ward_id(bed):
    return scalar('SELECT id FROM wards WHERE name=?', bed['ward'])


@app.route('/beds/<int:bid>/status', methods=['POST'])
@login_required('nurse')
def bed_status(bid):
    bed = one('SELECT * FROM beds WHERE id=?', bid) or abort(404)
    status = request.form.get('status')
    if bed['status'] == '占用':
        flash(_('{0} 床有患者在住，不能修改状态，请先转床或办理出院', bed['bed_no']), 'danger')
    elif status not in BED_STATUSES:
        flash(_('床位状态不正确'), 'danger')
    else:
        db().execute('UPDATE beds SET status=? WHERE id=?', (status, bid))
        db().commit()
        flash(_('{0} 床已设为“{1}”', bed['bed_no'], _(status)), 'success')
    return redirect(url_for('ward_detail', wid=bed_ward_id(bed)))


@app.route('/beds/<int:bid>/fee', methods=['POST'])
@login_required('nurse')
def bed_fee(bid):
    bed = one('SELECT * FROM beds WHERE id=?', bid) or abort(404)
    if bed['status'] == '占用':
        flash(_('{0} 床有患者在住，为避免已产生费用被重新计价，请在患者出院或转床后再调整', bed['bed_no']), 'warning')
        return redirect(url_for('ward_detail', wid=bed_ward_id(bed)))
    try:
        fee = float(request.form.get('daily_fee', ''))
        if fee <= 0:
            raise ValueError
        db().execute('UPDATE beds SET daily_fee=? WHERE id=?', (fee, bid))
        db().commit()
        flash(_('{0} 床床位费已调整为 ¥{1:.2f}/天', bed['bed_no'], fee), 'success')
    except ValueError:
        flash(_('床位费必须为大于0的数字'), 'danger')
    return redirect(url_for('ward_detail', wid=bed_ward_id(bed)))


@app.route('/beds/<int:bid>/delete', methods=['POST'])
@login_required('nurse')
def bed_delete(bid):
    bed = one('SELECT * FROM beds WHERE id=?', bid) or abort(404)
    if bed['status'] == '占用':
        flash(_('{0} 床有患者在住，不能删除', bed['bed_no']), 'danger')
    elif scalar('SELECT COUNT(*) FROM admissions WHERE bed_id=?', bid) or \
            scalar('SELECT COUNT(*) FROM bed_transfers WHERE from_bed=? OR to_bed=?', bid, bid):
        flash(_('{0} 床有历史住院记录，为便于追溯不能删除，可将其设为“停用”', bed['bed_no']), 'warning')
    else:
        db().execute('DELETE FROM beds WHERE id=?', (bid,))
        db().commit()
        flash(_('{0} 床已删除', bed['bed_no']), 'success')
    return redirect(url_for('ward_detail', wid=bed_ward_id(bed)))


@app.route('/beds/<int:bid>/transfer', methods=['POST'])
@login_required('nurse')
def bed_transfer(bid):
    bed = one('SELECT * FROM beds WHERE id=?', bid) or abort(404)
    adm = one("SELECT a.*, p.name pname FROM admissions a JOIN patients p ON p.id = a.patient_id "
              "WHERE a.bed_id=? AND a.status='在院'", bid)
    target = one('SELECT * FROM beds WHERE id=?', request.form.get('to_bed', type=int) or 0)
    back = request.form.get('back', '')
    if not adm:
        flash(_('该床位没有在院患者，无需转床'), 'warning')
    elif not target:
        flash(_('请选择要转入的床位'), 'danger')
    elif target['status'] != '空闲':
        flash(_('{0} {1} 床当前为“{2}”，请选择空闲床位', target['ward'], target['bed_no'], _(target['status'])), 'danger')
    else:
        db().execute('UPDATE admissions SET bed_id=? WHERE id=?', (target['id'], adm['id']))
        db().execute("UPDATE beds SET status='空闲' WHERE id=?", (bid,))
        db().execute("UPDATE beds SET status='占用' WHERE id=?", (target['id'],))
        db().execute('INSERT INTO bed_transfers(adm_id, from_bed, to_bed, reason, operator, created_at) '
                     'VALUES (?, ?, ?, ?, ?, ?)',
                     (adm['id'], bid, target['id'], request.form.get('reason', '').strip() or _('病情需要'),
                      session['name'], now_str()))
        db().commit()
        flash(_('{0} 已由 {1} {2} 床转至 {3} {4} 床', adm['pname'], bed['ward'], bed['bed_no'], target['ward'], target['bed_no']), 'success')
    if safe_path(back):
        return redirect(back)
    return redirect(url_for('ward_detail', wid=bed_ward_id(bed)))


# ====================== 个人中心 / 人员管理 ======================
@app.route('/profile', methods=['GET', 'POST'])
@login_required()
def profile():
    user = one('SELECT u.*, d.name dept_name FROM users u LEFT JOIN departments d ON d.id = u.dept_id WHERE u.id=?',
               session['user_id'])
    if request.method == 'POST':
        old, new, again = (request.form.get(k, '') for k in ('old', 'new', 'again'))
        if not check_password_hash(user['password'], old):
            flash(_('原密码不正确'), 'danger')
        elif len(new) < 6:
            flash(_('新密码至少 6 位'), 'danger')
        elif new != again:
            flash(_('两次输入的新密码不一致'), 'danger')
        elif new == old:
            flash(_('新密码不能与原密码相同'), 'danger')
        else:
            db().execute('UPDATE users SET password=? WHERE id=?', (generate_password_hash(new), user['id']))
            db().commit()
            flash(_('密码修改成功，下次登录请使用新密码'), 'success')
            return redirect(url_for('profile'))
    return render_template('profile.html', user=user)


@app.route('/staff')
@login_required('admin')
def staff():
    users = rows('SELECT u.*, d.name dept_name FROM users u LEFT JOIN departments d ON d.id = u.dept_id '
                 'ORDER BY u.active DESC, CASE u.role WHEN \'admin\' THEN 0 WHEN \'doctor\' THEN 1 ELSE 2 END, u.dept_id, u.id')
    return render_template('staff.html', users=users, depts=rows('SELECT * FROM departments ORDER BY id'),
                           role_filter=request.args.get('role', ''))


@app.route('/staff/new', methods=['POST'])
@login_required('admin')
def staff_new():
    f = request.form
    username, name, role = f.get('username', '').strip().lower(), f.get('name', '').strip(), f.get('role', '')
    errors = []
    if not re.fullmatch(r'[a-z][a-z0-9]{2,19}', username):
        errors.append(_('工号为 3~20 位小写字母或数字，且以字母开头'))
    elif one('SELECT id FROM users WHERE username=?', username):
        errors.append(_('工号 {0} 已存在', username))
    if not name:
        errors.append(_('请填写姓名'))
    if role not in ROLE_NAMES or role == 'admin':
        errors.append(_('请选择岗位'))
    dept_id = f.get('dept_id', type=int) if role == 'doctor' else None
    fee = 0
    if role == 'doctor':
        if not one('SELECT id FROM departments WHERE id=?', dept_id or 0):
            errors.append(_('医生必须选择所属科室'))
        try:
            fee = float(f.get('reg_fee', ''))
            if fee < 0:
                raise ValueError
        except ValueError:
            errors.append(_('挂号费必须为非负数字'))
    if errors:
        for e in errors:
            flash(e, 'danger')
        return redirect(url_for('staff') + '#newStaff')
    db().execute('INSERT INTO users(username, password, name, role, dept_id, title, reg_fee, specialty, active) '
                 'VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)',
                 (username, generate_password_hash('123456'), name, role, dept_id, f.get('title', '').strip() or None,
                  fee, f.get('specialty', '').strip() or None))
    db().commit()
    flash(_('已新增{0} {1}，工号 {2}，初始密码 123456（请提醒其登录后修改）', _(ROLE_NAMES[role]), name, username), 'success')
    return redirect(url_for('staff'))


@app.route('/staff/<int:uid>/<action>', methods=['POST'])
@login_required('admin')
def staff_action(uid, action):
    user = one('SELECT * FROM users WHERE id=?', uid) or abort(404)
    if uid == session['user_id'] and action in ('disable', 'reset'):
        flash(_('不能停用或重置当前登录的账号，请在“个人中心”修改自己的密码'), 'warning')
    elif action == 'reset':
        db().execute('UPDATE users SET password=? WHERE id=?', (generate_password_hash('123456'), uid))
        db().commit()
        flash(_('{0} 的密码已重置为 123456', user['name']), 'success')
    elif action == 'disable':
        if user['role'] == 'doctor' and scalar("SELECT COUNT(*) FROM registrations WHERE doctor_id=? AND visit_date>=? "
                                                "AND status IN ('待诊','就诊中')", uid, date.today().isoformat()):
            flash(_('{0} 还有未完成的挂号（含预约），请先处理后再停用', user['name']), 'danger')
        else:
            db().execute('UPDATE users SET active=0 WHERE id=?', (uid,))
            db().commit()
            flash(_('{0} 的账号已停用，将无法登录', user['name']), 'success')
    elif action == 'enable':
        db().execute('UPDATE users SET active=1 WHERE id=?', (uid,))
        db().commit()
        flash(_('{0} 的账号已启用', user['name']), 'success')
    else:
        abort(404)
    return redirect(url_for('staff'))


# ====================== 帮助中心 ======================
@app.route('/help')
@login_required()
def help_page():
    return render_template('help.html', quota=QUOTA_PER_PERIOD, ratio=INSURANCE_RATIO,
                           nursing_fee=NURSING_FEE, min_deposit=MIN_DEPOSIT)


@app.errorhandler(404)
def not_found(e):
    return render_template('error.html', code=404, message=_('您访问的页面或记录不存在')), 404


@app.errorhandler(405)
def method_not_allowed(e):
    return render_template('error.html', code=405, message=_('请通过页面上的按钮进行操作')), 405


@app.errorhandler(500)
def server_error(e):
    return render_template('error.html', code=500, message=_('系统繁忙，请稍后重试；如多次出现请联系信息科（分机 6016）')), 500


for _lang in LANGS:                     # 首次运行时自动生成中、英文两套演示数据
    init_db(_lang)

if __name__ == '__main__':
    app.run(debug=True)
