"""
数据与业务层：负责 SQLite 建表、初始化演示数据，
以及挂号、开处方、缴费、发药等可复用的业务函数。

中文、英文各有一套独立的演示数据（hospital.db / hospital_en.db）。
单独运行本文件可重置两个数据库：python database.py
"""
import os
import sqlite3
from datetime import date, datetime, timedelta

from werkzeug.security import generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILES = {'zh': 'hospital.db', 'en': 'hospital_en.db'}   # 每种界面语言对应一套演示数据
LANGS = tuple(DB_FILES)


def db_path(lang='zh'):
    return os.path.join(BASE_DIR, DB_FILES[lang])

QUOTA_PER_PERIOD = 20                     # 每位医生每个时段的号源数
INSURANCE_RATIO = {                       # 医保统筹支付比例
    '自费': 0,
    '城镇职工医保': 0.7,
    '城乡居民医保': 0.5,
}

SCHEMA = """
CREATE TABLE departments (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    location TEXT,
    intro TEXT
);
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    name TEXT NOT NULL,
    role TEXT NOT NULL,                   -- admin/doctor/cashier/pharmacist/nurse
    dept_id INTEGER REFERENCES departments(id),
    title TEXT,                           -- 医生职称
    reg_fee REAL DEFAULT 0,               -- 挂号费
    specialty TEXT,                       -- 擅长
    active INTEGER DEFAULT 1              -- 1 在职 / 0 停用
);
CREATE TABLE patients (
    id INTEGER PRIMARY KEY,
    card_no TEXT UNIQUE NOT NULL,         -- 就诊卡号
    name TEXT NOT NULL,
    gender TEXT NOT NULL,
    birth TEXT NOT NULL,
    phone TEXT NOT NULL,
    id_card TEXT,
    insurance TEXT DEFAULT '自费',
    allergy TEXT DEFAULT '',
    address TEXT,
    created_at TEXT
);
CREATE TABLE registrations (
    id INTEGER PRIMARY KEY,
    reg_no TEXT UNIQUE,
    patient_id INTEGER NOT NULL REFERENCES patients(id),
    doctor_id INTEGER NOT NULL REFERENCES users(id),
    dept_id INTEGER NOT NULL REFERENCES departments(id),
    visit_date TEXT NOT NULL,
    period TEXT NOT NULL,                 -- 上午/下午
    queue_no INTEGER NOT NULL,
    fee REAL NOT NULL,
    status TEXT NOT NULL DEFAULT '待诊',  -- 待诊/就诊中/已诊/已退号
    created_at TEXT
);
CREATE TABLE records (
    id INTEGER PRIMARY KEY,
    reg_id INTEGER UNIQUE NOT NULL REFERENCES registrations(id),
    complaint TEXT,                       -- 主诉
    history TEXT,                         -- 现病史
    diagnosis TEXT,                       -- 诊断
    advice TEXT,                          -- 医嘱
    draft_rx TEXT DEFAULT '',             -- 暂存的处方草稿（JSON）
    updated_at TEXT
);
CREATE TABLE drugs (
    id INTEGER PRIMARY KEY,
    code TEXT UNIQUE,
    name TEXT NOT NULL,
    spec TEXT,
    unit TEXT,
    price REAL NOT NULL,
    stock INTEGER NOT NULL DEFAULT 0,
    warn_level INTEGER DEFAULT 20,        -- 库存预警线
    category TEXT,
    allergen TEXT DEFAULT ''              -- 过敏原关键字，用于开方时过敏校验
);
CREATE TABLE prescriptions (
    id INTEGER PRIMARY KEY,
    rx_no TEXT UNIQUE,
    reg_id INTEGER NOT NULL REFERENCES registrations(id),
    total REAL NOT NULL,
    status TEXT NOT NULL DEFAULT '待缴费', -- 待缴费/已缴费/已发药/已退费
    created_at TEXT,
    paid_at TEXT,
    dispensed_at TEXT
);
CREATE TABLE rx_items (
    id INTEGER PRIMARY KEY,
    rx_id INTEGER NOT NULL REFERENCES prescriptions(id),
    drug_id INTEGER NOT NULL REFERENCES drugs(id),
    qty INTEGER NOT NULL,
    price REAL NOT NULL,
    usage TEXT
);
CREATE TABLE payments (
    id INTEGER PRIMARY KEY,
    pay_no TEXT,
    patient_id INTEGER NOT NULL REFERENCES patients(id),
    item TEXT NOT NULL,
    amount REAL NOT NULL,                 -- 个人实付（负数表示退费）
    method TEXT,
    insurance_pay REAL DEFAULT 0,         -- 医保统筹支付
    operator TEXT,
    created_at TEXT
);
CREATE TABLE beds (
    id INTEGER PRIMARY KEY,
    ward TEXT NOT NULL,                   -- 所属病区名称（对应 wards.name）
    bed_no TEXT NOT NULL,
    daily_fee REAL DEFAULT 60,
    status TEXT NOT NULL DEFAULT '空闲'   -- 空闲/占用/维修/停用
);
CREATE TABLE admissions (
    id INTEGER PRIMARY KEY,
    adm_no TEXT,
    patient_id INTEGER NOT NULL REFERENCES patients(id),
    bed_id INTEGER NOT NULL REFERENCES beds(id),
    doctor_id INTEGER REFERENCES users(id),
    diagnosis TEXT,
    deposit REAL DEFAULT 0,
    admit_date TEXT,
    discharge_date TEXT,
    total_fee REAL,
    status TEXT DEFAULT '在院'            -- 在院/出院
);
"""

# 病房管理相关表（单独列出，便于给旧数据库补建）
WARD_SCHEMA = """
CREATE TABLE IF NOT EXISTS wards (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    code TEXT UNIQUE NOT NULL,            -- 床号前缀，如 N
    dept_id INTEGER REFERENCES departments(id),
    location TEXT,
    head_nurse TEXT,                      -- 护士长
    phone TEXT,
    bed_fee REAL DEFAULT 60,              -- 标准床位费
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS admission_requests (
    id INTEGER PRIMARY KEY,
    req_no TEXT,
    reg_id INTEGER REFERENCES registrations(id),   -- 来源门诊挂号
    patient_id INTEGER NOT NULL REFERENCES patients(id),
    doctor_id INTEGER NOT NULL REFERENCES users(id),
    diagnosis TEXT NOT NULL,                       -- 入院诊断
    note TEXT,                                     -- 病情说明 / 床位要求
    status TEXT NOT NULL DEFAULT '待安排',         -- 待安排/已入院/已撤销
    adm_id INTEGER REFERENCES admissions(id),
    created_at TEXT,
    handled_at TEXT
);
CREATE TABLE IF NOT EXISTS bed_transfers (
    id INTEGER PRIMARY KEY,
    adm_id INTEGER NOT NULL REFERENCES admissions(id),
    from_bed INTEGER NOT NULL REFERENCES beds(id),
    to_bed INTEGER NOT NULL REFERENCES beds(id),
    reason TEXT,
    operator TEXT,
    created_at TEXT
);
"""

# (病区名称, 床号前缀, 科室id, 位置, 护士长, 电话, 床位费, 床位数)
WARDS = [
    ('内科病区', 'N', 1, '住院楼5层', '杨梅', '0411-88881501', 60, 8),
    ('外科病区', 'W', 2, '住院楼6层', '周红', '0411-88881601', 60, 8),
    ('儿科病区', 'E', 3, '住院楼7层', '吴静', '0411-88881701', 50, 8),
]

DEPARTMENTS = [
    ('内科', '门诊楼2层A区', '高血压、糖尿病、呼吸道及消化道等常见内科疾病'),
    ('外科', '门诊楼2层B区', '创伤处理、普外疾病、术后复查'),
    ('儿科', '门诊楼3层A区', '0-14岁儿童常见病、发热、咳嗽'),
    ('妇产科', '门诊楼3层B区', '妇科常见病、孕期检查'),
    ('眼科', '门诊楼4层A区', '结膜炎、视力检查、干眼症'),
    ('口腔科', '门诊楼4层B区', '龋齿、牙周病、口腔黏膜病'),
    ('急诊科', '门诊楼1层东侧', '24小时急危重症处理'),
]

# (工号, 姓名, 角色, 科室id, 职称, 挂号费, 擅长)
USERS = [
    ('admin', '系统管理员', 'admin', None, None, 0, None),
    ('zhangwei', '张伟', 'doctor', 1, '主任医师', 50, '高血压、糖尿病等慢病管理'),
    ('liming', '李明', 'doctor', 1, '主治医师', 20, '呼吸道感染、慢性胃炎'),
    ('zhaolei', '赵磊', 'doctor', 2, '主任医师', 50, '普外科、创伤外科'),
    ('wangfang', '王芳', 'doctor', 3, '副主任医师', 30, '小儿呼吸、小儿消化'),
    ('chenjing', '陈静', 'doctor', 4, '主治医师', 20, '妇科炎症、孕期保健'),
    ('sunhao', '孙浩', 'doctor', 5, '主治医师', 20, '结膜炎、屈光不正'),
    ('zhouyan', '周燕', 'doctor', 6, '副主任医师', 30, '牙体牙髓、牙周治疗'),
    ('huangtao', '黄涛', 'doctor', 7, '主治医师', 30, '急危重症抢救'),
    ('shoufei', '刘洋', 'cashier', None, None, 0, None),
    ('yaofang', '马丽', 'pharmacist', None, None, 0, None),
    ('hushi', '杨梅', 'nurse', None, '护士长', 0, None),
]

# (姓名, 性别, 出生日期, 手机, 身份证, 医保类型, 过敏史, 住址)
PATIENTS = [
    ('张建国', '男', '1965-03-12', '13804110231', '210202196503124518', '城镇职工医保', '青霉素', '大连市中山区人民路12号'),
    ('李秀英', '女', '1972-08-25', '13998452210', '210204197208252347', '城乡居民医保', '', '大连市沙河口区西安路88号'),
    ('王小宝', '男', '2019-06-01', '15142236678', '', '城乡居民医保', '', '大连市甘井子区华北路5号'),
    ('刘晓燕', '女', '1993-11-17', '18640981234', '210211199311173026', '城镇职工医保', '头孢类', '大连市甘井子区软件园路8号'),
    ('陈志强', '男', '1980-01-05', '13700406655', '', '自费', '', '大连市西岗区长江路201号'),
    ('赵敏', '女', '1998-04-22', '15904115566', '', '自费', '', '大连市高新区黄浦路520号'),
    ('孙立新', '男', '1958-12-30', '13304117788', '210203195812301019', '城镇职工医保', '磺胺类', '大连市中山区解放路33号'),
    ('周雨桐', '女', '2016-09-09', '18842609911', '', '城乡居民医保', '', '大连市金州区友谊街道'),
    ('吴海涛', '男', '1987-07-14', '13591830022', '', '自费', '', '大连市旅顺口区黄河路17号'),
    ('郑丽华', '女', '1969-02-28', '13166902345', '210202196902285521', '城镇职工医保', '', '大连市中山区友好路66号'),
    ('马俊', '男', '2001-10-10', '17824113300', '', '城乡居民医保', '', '大连市甘井子区学府街'),
    ('黄佳琪', '女', '1990-05-19', '15541158899', '', '城镇职工医保', '', '大连市沙河口区星海广场'),
]

# (编码, 名称, 规格, 单位, 单价, 库存, 预警线, 分类, 过敏原)
DRUGS = [
    ('YP001', '阿莫西林胶囊', '0.25g×24粒', '盒', 18.5, 120, 30, '抗感染', '青霉素'),
    ('YP002', '头孢克肟分散片', '0.1g×6片', '盒', 32.0, 15, 20, '抗感染', '头孢'),
    ('YP003', '布洛芬缓释胶囊', '0.3g×20粒', '盒', 22.0, 200, 30, '解热镇痛', ''),
    ('YP004', '蒙脱石散', '3g×10袋', '盒', 15.8, 80, 20, '消化系统', ''),
    ('YP005', '奥美拉唑肠溶胶囊', '20mg×14粒', '盒', 26.5, 90, 20, '消化系统', ''),
    ('YP006', '盐酸氨溴索口服溶液', '100ml', '瓶', 28.0, 8, 15, '呼吸系统', ''),
    ('YP007', '硝苯地平控释片', '30mg×7片', '盒', 35.6, 150, 30, '心血管', ''),
    ('YP008', '盐酸二甲双胍片', '0.5g×48片', '盒', 12.3, 180, 30, '内分泌', ''),
    ('YP009', '阿托伐他汀钙片', '20mg×7片', '盒', 45.0, 60, 20, '心血管', ''),
    ('YP010', '小儿氨酚黄那敏颗粒', '6袋', '盒', 16.0, 70, 20, '儿科用药', ''),
    ('YP011', '左氧氟沙星滴眼液', '5ml', '支', 19.8, 40, 10, '眼科用药', '喹诺酮'),
    ('YP012', '复方氯己定含漱液', '300ml', '瓶', 24.0, 35, 10, '口腔用药', ''),
    ('YP013', '复方磺胺甲噁唑片', '0.48g×12片', '盒', 9.5, 50, 10, '抗感染', '磺胺'),
    ('YP014', '0.9%氯化钠注射液', '250ml', '袋', 6.5, 300, 50, '输液', ''),
    ('YP015', '维生素C片', '0.1g×100片', '瓶', 5.0, 12, 20, '维生素', ''),
    ('YP016', '云南白药气雾剂', '85g+30g', '盒', 58.0, 25, 10, '外科用药', ''),
]


# ---------------- 英文演示数据（结构与中文数据一一对应） ----------------
WARDS_EN = [
    ('Internal Medicine Ward', 'N', 1, 'Inpatient Bldg 5F', 'Grace Hall', '0411-88881501', 60, 8),
    ('Surgical Ward', 'W', 2, 'Inpatient Bldg 6F', 'Amy Young', '0411-88881601', 60, 8),
    ('Pediatric Ward', 'E', 3, 'Inpatient Bldg 7F', 'Lucy King', '0411-88881701', 50, 8),
]

DEPARTMENTS_EN = [
    ('Internal Medicine', 'Outpatient Bldg 2F, Zone A', 'Hypertension, diabetes, respiratory and digestive diseases'),
    ('Surgery', 'Outpatient Bldg 2F, Zone B', 'Trauma care, general surgery and post-operative follow-up'),
    ('Pediatrics', 'Outpatient Bldg 3F, Zone A', 'Common illnesses, fever and cough in children aged 0-14'),
    ('Obstetrics & Gynecology', 'Outpatient Bldg 3F, Zone B', 'Common gynecological conditions and prenatal care'),
    ('Ophthalmology', 'Outpatient Bldg 4F, Zone A', 'Conjunctivitis, vision tests and dry eye'),
    ('Dentistry', 'Outpatient Bldg 4F, Zone B', 'Dental caries, periodontal and oral mucosal diseases'),
    ('Emergency', 'Outpatient Bldg 1F, East Wing', '24-hour emergency and critical care'),
]

USERS_EN = [
    ('admin', 'System Administrator', 'admin', None, None, 0, None),
    ('jwilson', 'James Wilson', 'doctor', 1, 'Chief Physician', 50, 'Chronic disease management (hypertension, diabetes)'),
    ('echen', 'Emily Chen', 'doctor', 1, 'Attending Physician', 20, 'Respiratory infections, chronic gastritis'),
    ('rtaylor', 'Robert Taylor', 'doctor', 2, 'Chief Physician', 50, 'General surgery, trauma surgery'),
    ('sgarcia', 'Sofia Garcia', 'doctor', 3, 'Associate Chief Physician', 30, 'Pediatric respiratory and digestive diseases'),
    ('abrown', 'Anna Brown', 'doctor', 4, 'Attending Physician', 20, 'Gynecological infections, prenatal care'),
    ('dkim', 'Daniel Kim', 'doctor', 5, 'Attending Physician', 20, 'Conjunctivitis, refractive errors'),
    ('lmartin', 'Laura Martin', 'doctor', 6, 'Associate Chief Physician', 30, 'Endodontics, periodontal treatment'),
    ('mclark', 'Michael Clark', 'doctor', 7, 'Attending Physician', 30, 'Emergency and critical care'),
    ('owhite', 'Olivia White', 'cashier', None, None, 0, None),
    ('hadams', 'Henry Adams', 'pharmacist', None, None, 0, None),
    ('ghall', 'Grace Hall', 'nurse', None, 'Head Nurse', 0, None),
]

PATIENTS_EN = [
    ('George Miller', '男', '1965-03-12', '13804110231', '210202196503124518', '城镇职工医保', 'Penicillin', '12 Renmin Road, Zhongshan District, Dalian'),
    ('Linda Moore', '女', '1972-08-25', '13998452210', '210204197208252347', '城乡居民医保', '', '88 Xi\'an Road, Shahekou District, Dalian'),
    ('Leo Turner', '男', '2019-06-01', '15142236678', '', '城乡居民医保', '', '5 Huabei Road, Ganjingzi District, Dalian'),
    ('Rachel Evans', '女', '1993-11-17', '18640981234', '210211199311173026', '城镇职工医保', 'Cephalosporins', '8 Software Park Road, Ganjingzi District, Dalian'),
    ('Kevin Scott', '男', '1980-01-05', '13700406655', '', '自费', '', '201 Changjiang Road, Xigang District, Dalian'),
    ('Mia Collins', '女', '1998-04-22', '15904115566', '', '自费', '', '520 Huangpu Road, High-tech Zone, Dalian'),
    ('Frank Baker', '男', '1958-12-30', '13304117788', '210203195812301019', '城镇职工医保', 'Sulfonamides', '33 Jiefang Road, Zhongshan District, Dalian'),
    ('Chloe Reed', '女', '2016-09-09', '18842609911', '', '城乡居民医保', '', 'Youyi Subdistrict, Jinzhou District, Dalian'),
    ('Ryan Cooper', '男', '1987-07-14', '13591830022', '', '自费', '', '17 Huanghe Road, Lushunkou District, Dalian'),
    ('Helen Ward', '女', '1969-02-28', '13166902345', '210202196902285521', '城镇职工医保', '', '66 Youhao Road, Zhongshan District, Dalian'),
    ('Jack Hughes', '男', '2001-10-10', '17824113300', '', '城乡居民医保', '', 'Xuefu Street, Ganjingzi District, Dalian'),
    ('Natalie Price', '女', '1990-05-19', '15541158899', '', '城镇职工医保', '', 'Xinghai Square, Shahekou District, Dalian'),
]

DRUGS_EN = [
    ('YP001', 'Amoxicillin Capsules', '0.25 g x 24', 'box', 18.5, 120, 30, 'Anti-infective', 'Penicillin'),
    ('YP002', 'Cefixime Dispersible Tablets', '0.1 g x 6', 'box', 32.0, 15, 20, 'Anti-infective', 'Cephalosporin'),
    ('YP003', 'Ibuprofen SR Capsules', '0.3 g x 20', 'box', 22.0, 200, 30, 'Analgesic', ''),
    ('YP004', 'Montmorillonite Powder', '3 g x 10 sachets', 'box', 15.8, 80, 20, 'Digestive', ''),
    ('YP005', 'Omeprazole EC Capsules', '20 mg x 14', 'box', 26.5, 90, 20, 'Digestive', ''),
    ('YP006', 'Ambroxol Oral Solution', '100 ml', 'bottle', 28.0, 8, 15, 'Respiratory', ''),
    ('YP007', 'Nifedipine CR Tablets', '30 mg x 7', 'box', 35.6, 150, 30, 'Cardiovascular', ''),
    ('YP008', 'Metformin Tablets', '0.5 g x 48', 'box', 12.3, 180, 30, 'Endocrine', ''),
    ('YP009', 'Atorvastatin Tablets', '20 mg x 7', 'box', 45.0, 60, 20, 'Cardiovascular', ''),
    ('YP010', 'Pediatric Paracetamol Granules', '6 sachets', 'box', 16.0, 70, 20, 'Pediatric', ''),
    ('YP011', 'Levofloxacin Eye Drops', '5 ml', 'tube', 19.8, 40, 10, 'Ophthalmic', 'Quinolone'),
    ('YP012', 'Chlorhexidine Mouthwash', '300 ml', 'bottle', 24.0, 35, 10, 'Oral care', ''),
    ('YP013', 'Sulfamethoxazole Tablets', '0.48 g x 12', 'box', 9.5, 50, 10, 'Anti-infective', 'Sulfonamide'),
    ('YP014', '0.9% Sodium Chloride Injection', '250 ml', 'bag', 6.5, 300, 50, 'Infusion', ''),
    ('YP015', 'Vitamin C Tablets', '0.1 g x 100', 'bottle', 5.0, 12, 20, 'Vitamins', ''),
    ('YP016', 'Yunnan Baiyao Spray', '85 g + 30 g', 'box', 58.0, 25, 10, 'Topical', ''),
]

# 演示病历、处方用法等文字：{语言: 内容}，结构与 seed() 中的门诊记录一一对应
SEED_TEXT = {
    'zh': dict(
        cashier='刘洋', nurse='杨梅',
        old_record=('头晕1周', '高血压病史5年', '原发性高血压', '硝苯地平控释片每日1片，低盐饮食'),
        records=[
            ('头晕、头痛3天', '既往高血压病史5年，近日血压控制欠佳，最高160/100mmHg',
             '原发性高血压', '低盐低脂饮食，每日监测血压，2周后复诊'),
            ('口干、多饮、多尿1月', '空腹血糖8.6mmol/L，无酮症表现',
             '2型糖尿病', '控制饮食，适量运动，1个月后复查糖化血红蛋白'),
            ('发热、咳嗽2天', '体温最高38.5℃，咽部充血，双肺呼吸音清',
             '急性上呼吸道感染', '多饮水，体温超过38.5℃时及时复诊'),
            ('上腹部隐痛半月', '', '', ''),
        ],
        usages=[['口服 一日1次 每次1片'], ['口服 一日2次 每次1片', '口服 一日1次 每次1片'],
                ['口服 一日3次 每次1袋', '口服 一日2次 每次5ml']],
        request=('2型糖尿病（血糖控制不佳）', '需监测空腹及餐后血糖，调整降糖方案'),
        admissions=['急性阑尾炎术后', '社区获得性肺炎'],
    ),
    'en': dict(
        cashier='Olivia White', nurse='Grace Hall',
        old_record=('Dizziness for 1 week', 'History of hypertension for 5 years', 'Essential hypertension',
                    'Nifedipine CR 1 tablet daily; low-salt diet'),
        records=[
            ('Dizziness and headache for 3 days',
             'Hypertension for 5 years, poorly controlled recently; max BP 160/100 mmHg',
             'Essential hypertension', 'Low-salt, low-fat diet; monitor BP daily; follow up in 2 weeks'),
            ('Dry mouth, polydipsia and polyuria for 1 month', 'Fasting glucose 8.6 mmol/L, no ketosis',
             'Type 2 diabetes mellitus', 'Diet control and moderate exercise; recheck HbA1c in 1 month'),
            ('Fever and cough for 2 days', 'Max temperature 38.5 °C, pharyngeal congestion, clear breath sounds',
             'Acute upper respiratory tract infection', 'Drink plenty of water; return if temperature exceeds 38.5 °C'),
            ('Dull upper abdominal pain for 2 weeks', '', '', ''),
        ],
        usages=[['Oral, once daily, 1 tablet'], ['Oral, twice daily, 1 tablet', 'Oral, once daily, 1 tablet'],
                ['Oral, 3 times daily, 1 sachet', 'Oral, twice daily, 5 ml']],
        request=('Type 2 diabetes mellitus (poor glycemic control)',
                 'Monitor fasting and postprandial glucose; adjust hypoglycemic regimen'),
        admissions=['Post-appendectomy (acute appendicitis)', 'Community-acquired pneumonia'],
    ),
}

DATA = {
    'zh': dict(wards=WARDS, departments=DEPARTMENTS, users=USERS, patients=PATIENTS, drugs=DRUGS),
    'en': dict(wards=WARDS_EN, departments=DEPARTMENTS_EN, users=USERS_EN, patients=PATIENTS_EN, drugs=DRUGS_EN),
}

# 写入数据库的业务文字（收费项目等），按数据库语言写入
TEXTS = {
    'reg_fee': ('挂号费', 'Registration fee'),
    'reg_refund': ('挂号费退费', 'Registration fee refund'),
    'drug_fee': ('药费（处方 {0}）', 'Medication ({0})'),
    'drug_refund': ('药费退费（处方 {0}）', 'Medication refund ({0})'),
    'deposit': ('住院押金', 'Inpatient deposit'),
    'deposit_extra': ('住院押金（补交）', 'Additional deposit'),
    'settle_refund': ('住院结算退还押金', 'Deposit refund at discharge'),
    'settle_pay': ('住院结算补缴', 'Balance paid at discharge'),
    'shortage': ('{0}（需 {1}，库存 {2}）', '{0} (needed {1}, in stock {2})'),
}
_CONN_LANG = {}


def conn_lang(conn):
    return _CONN_LANG.get(id(conn), 'zh')


def txt(conn, key, *args):
    """按数据库语言返回业务文字"""
    zh, en = TEXTS[key]
    return (en if conn_lang(conn) == 'en' else zh).format(*args)


def get_conn(lang='zh'):
    conn = sqlite3.connect(db_path(lang))
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    _CONN_LANG[id(conn)] = lang
    return conn


def now_str():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def current_period():
    return '上午' if datetime.now().hour < 12 else '下午'


def next_no(conn, prefix, table, column):
    """生成形如 GH202610100001 的业务单号"""
    day = datetime.now().strftime('%Y%m%d')
    n = conn.execute(f'SELECT COUNT(*) FROM {table} WHERE {column} LIKE ?',
                     (f'{prefix}{day}%',)).fetchone()[0]
    return f'{prefix}{day}{n + 1:04d}'


def add_payment(conn, patient_id, item, amount, method, operator, insurance_pay=0.0):
    conn.execute(
        'INSERT INTO payments(pay_no, patient_id, item, amount, method, insurance_pay, operator, created_at) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
        (next_no(conn, 'SF', 'payments', 'pay_no'), patient_id, item, round(amount, 2),
         method, round(insurance_pay, 2), operator, now_str()))


def used_quota(conn, doctor_id, visit_date, period):
    return conn.execute(
        "SELECT COUNT(*) FROM registrations WHERE doctor_id=? AND visit_date=? AND period=? AND status!='已退号'",
        (doctor_id, visit_date, period)).fetchone()[0]


def create_registration(conn, patient_id, doctor_id, visit_date, period, method, operator):
    """挂号：分配排队序号并收取挂号费，返回挂号记录 id"""
    doctor = conn.execute('SELECT * FROM users WHERE id=?', (doctor_id,)).fetchone()
    # 序号包含已退号记录，保证同一时段序号不重复
    queue_no = conn.execute(
        'SELECT COUNT(*) FROM registrations WHERE doctor_id=? AND visit_date=? AND period=?',
        (doctor_id, visit_date, period)).fetchone()[0] + 1
    cur = conn.execute(
        'INSERT INTO registrations(reg_no, patient_id, doctor_id, dept_id, visit_date, period, queue_no, fee, status, created_at) '
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, '待诊', ?)",
        (next_no(conn, 'GH', 'registrations', 'reg_no'), patient_id, doctor_id, doctor['dept_id'],
         visit_date, period, queue_no, doctor['reg_fee'], now_str()))
    add_payment(conn, patient_id, txt(conn, 'reg_fee'), doctor['reg_fee'], method, operator)
    return cur.lastrowid


def save_record(conn, reg_id, complaint, history, diagnosis, advice, draft_rx=''):
    conn.execute(
        'INSERT INTO records(reg_id, complaint, history, diagnosis, advice, draft_rx, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?) '
        'ON CONFLICT(reg_id) DO UPDATE SET complaint=excluded.complaint, history=excluded.history, '
        'diagnosis=excluded.diagnosis, advice=excluded.advice, draft_rx=excluded.draft_rx, updated_at=excluded.updated_at',
        (reg_id, complaint, history, diagnosis, advice, draft_rx, now_str()))


def create_prescription(conn, reg_id, items):
    """开处方，items 为 [(drug_id, qty, usage), ...]，返回处方 id"""
    rows, total = [], 0
    for drug_id, qty, usage in items:
        price = conn.execute('SELECT price FROM drugs WHERE id=?', (drug_id,)).fetchone()[0]
        total += price * qty
        rows.append((drug_id, qty, price, usage))
    cur = conn.execute(
        "INSERT INTO prescriptions(rx_no, reg_id, total, status, created_at) VALUES (?, ?, ?, '待缴费', ?)",
        (next_no(conn, 'CF', 'prescriptions', 'rx_no'), reg_id, round(total, 2), now_str()))
    conn.executemany('INSERT INTO rx_items(rx_id, drug_id, qty, price, usage) VALUES (?, ?, ?, ?, ?)',
                     [(cur.lastrowid,) + r for r in rows])
    return cur.lastrowid


def pay_prescription(conn, rx_id, method, operator):
    """处方缴费：医保结算时按医保类型计算统筹支付，返回 (总额, 医保支付, 个人支付)"""
    rx = conn.execute(
        'SELECT rx.*, r.patient_id, p.insurance FROM prescriptions rx '
        'JOIN registrations r ON r.id = rx.reg_id JOIN patients p ON p.id = r.patient_id WHERE rx.id=?',
        (rx_id,)).fetchone()
    ratio = INSURANCE_RATIO.get(rx['insurance'], 0) if method == '医保结算' else 0
    insurance_pay = round(rx['total'] * ratio, 2)
    personal = round(rx['total'] - insurance_pay, 2)
    add_payment(conn, rx['patient_id'], txt(conn, 'drug_fee', rx['rx_no']), personal, method, operator, insurance_pay)
    conn.execute("UPDATE prescriptions SET status='已缴费', paid_at=? WHERE id=?", (now_str(), rx_id))
    return rx['total'], insurance_pay, personal


def refund_prescription(conn, rx_id, operator):
    """已缴费未发药的处方退费：按原支付方式和医保比例原路退回"""
    rx = conn.execute('SELECT rx.*, r.patient_id FROM prescriptions rx JOIN registrations r ON r.id = rx.reg_id '
                      'WHERE rx.id=?', (rx_id,)).fetchone()
    pay = conn.execute('SELECT * FROM payments WHERE item=? ORDER BY id DESC LIMIT 1',
                       (txt(conn, 'drug_fee', rx['rx_no']),)).fetchone()
    amount, ins, method = (pay['amount'], pay['insurance_pay'], pay['method']) if pay else (rx['total'], 0, '原路退回')
    add_payment(conn, rx['patient_id'], txt(conn, 'drug_refund', rx['rx_no']), -amount, method, operator, -ins)
    conn.execute("UPDATE prescriptions SET status='已退费' WHERE id=?", (rx_id,))
    return amount, ins


def dispense_prescription(conn, rx_id):
    """发药并扣减库存；库存不足时不做任何修改，返回缺药清单"""
    items = conn.execute(
        'SELECT i.qty, d.id, d.name, d.stock FROM rx_items i JOIN drugs d ON d.id = i.drug_id WHERE i.rx_id=?',
        (rx_id,)).fetchall()
    shortage = [txt(conn, 'shortage', it['name'], it['qty'], it['stock']) for it in items if it['stock'] < it['qty']]
    if shortage:
        return shortage
    for it in items:
        conn.execute('UPDATE drugs SET stock = stock - ? WHERE id=?', (it['qty'], it['id']))
    conn.execute("UPDATE prescriptions SET status='已发药', dispensed_at=? WHERE id=?", (now_str(), rx_id))
    return []


def seed(conn, lang='zh'):
    ts = now_str()
    today = date.today()
    period = current_period()
    data, text = DATA[lang], SEED_TEXT[lang]
    cashier, nurse = text['cashier'], text['nurse']

    conn.executemany('INSERT INTO departments(name, location, intro) VALUES (?, ?, ?)', data['departments'])
    pw = generate_password_hash('123456')
    for u in data['users']:
        conn.execute('INSERT INTO users(username, password, name, role, dept_id, title, reg_fee, specialty) '
                     'VALUES (?, ?, ?, ?, ?, ?, ?, ?)', (u[0], pw) + u[1:])
    for i, p in enumerate(data['patients'], 1):
        conn.execute('INSERT INTO patients(card_no, name, gender, birth, phone, id_card, insurance, allergy, address, created_at) '
                     'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', (f'P{today.year}{i:05d}',) + p + (ts,))
    conn.executemany('INSERT INTO drugs(code, name, spec, unit, price, stock, warn_level, category, allergen) '
                     'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', data['drugs'])
    for name, code, dept_id, location, head, phone, fee, count in data['wards']:
        conn.execute('INSERT INTO wards(name, code, dept_id, location, head_nurse, phone, bed_fee, created_at) '
                     'VALUES (?, ?, ?, ?, ?, ?, ?, ?)', (name, code, dept_id, location, head, phone, fee, ts))
        for k in range(1, count + 1):
            conn.execute('INSERT INTO beds(ward, bed_no, daily_fee) VALUES (?, ?, ?)', (name, f'{code}{k:02d}', fee))
    conn.execute("UPDATE beds SET status='维修' WHERE bed_no='E08'")   # 演示：一张床位维修中

    # 1 号患者一个月前的复诊记录，便于演示“历史就诊”
    old = create_registration(conn, 1, 2, (today - timedelta(days=30)).isoformat(), '上午', '医保结算', cashier)
    old_ts = (today - timedelta(days=30)).isoformat() + ' 09:12:00'
    conn.execute("UPDATE registrations SET status='已诊', created_at=? WHERE id=?", (old_ts, old))
    conn.execute('UPDATE payments SET created_at=? WHERE id=(SELECT MAX(id) FROM payments)', (old_ts,))
    save_record(conn, old, *text['old_record'])

    # 今日门诊：(患者id, 医生id, 状态, 病历, 处方明细, 处方状态)
    rec, use = text['records'], text['usages']
    visits = [
        (1, 2, '已诊', rec[0], [(7, 2, use[0][0])], '已发药'),
        (2, 2, '已诊', rec[1], [(8, 2, use[1][0]), (9, 1, use[1][1])], '待缴费'),
        (3, 5, '已诊', rec[2], [(10, 1, use[2][0]), (6, 1, use[2][1])], '已缴费'),
        (5, 2, '就诊中', rec[3], [], None),
        (7, 2, '待诊', None, [], None),
        (10, 3, '待诊', None, [], None),
        (12, 3, '待诊', None, [], None),
        (8, 5, '待诊', None, [], None),
        (9, 4, '待诊', None, [], None),
        (4, 7, '待诊', None, [], None),
    ]
    methods = ['微信', '现金', '支付宝', '银行卡']
    for k, (pid, did, status, rec, items, rx_status) in enumerate(visits):
        rid = create_registration(conn, pid, did, today.isoformat(), period, methods[k % 4], cashier)
        conn.execute('UPDATE registrations SET status=? WHERE id=?', (status, rid))
        if rec:
            save_record(conn, rid, *rec)
        if items:
            rx = create_prescription(conn, rid, items)
            if rx_status in ('已缴费', '已发药'):
                pay_prescription(conn, rx, '医保结算', cashier)
            if rx_status == '已发药':
                dispense_prescription(conn, rx)

    # 2 号医生为 2 号患者开具的住院申请，等待护士安排床位
    reg2 = conn.execute("SELECT id FROM registrations WHERE patient_id=2 AND visit_date=?", (today.isoformat(),)).fetchone()[0]
    conn.execute("INSERT INTO admission_requests(req_no, reg_id, patient_id, doctor_id, diagnosis, note, status, created_at) "
                 "VALUES (?, ?, 2, 2, ?, ?, '待安排', ?)",
                 (next_no(conn, 'ZZ', 'admission_requests', 'req_no'), reg2) + text['request'] + (ts,))

    # 在院患者：(患者id, 床位id, 医生id, 诊断, 押金, 入院天数)
    for pid, bed_id, did, diag, deposit, days in [(11, 9, 4, text['admissions'][0], 3000, 3),
                                                  (6, 3, 3, text['admissions'][1], 5000, 5)]:
        conn.execute("INSERT INTO admissions(adm_no, patient_id, bed_id, doctor_id, diagnosis, deposit, admit_date, status) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?, '在院')",
                     (next_no(conn, 'ZY', 'admissions', 'adm_no'), pid, bed_id, did, diag, deposit,
                      (today - timedelta(days=days)).isoformat()))
        conn.execute("UPDATE beds SET status='占用' WHERE id=?", (bed_id,))
        add_payment(conn, pid, txt(conn, 'deposit'), deposit, '银行卡', nurse)
        conn.execute('UPDATE payments SET created_at=? WHERE id=(SELECT MAX(id) FROM payments)',
                     ((today - timedelta(days=days)).isoformat() + ' 10:30:00',))


def ensure_ward_schema(conn):
    """旧版数据库没有病区表时自动补建，并根据已有床位生成病区记录"""
    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='wards'").fetchone()
    conn.executescript(WARD_SCHEMA)
    if exists:
        return
    preset = {w[0]: w for w in WARDS}
    for (name,) in conn.execute('SELECT DISTINCT ward FROM beds ORDER BY id').fetchall():
        bed = conn.execute('SELECT bed_no, daily_fee FROM beds WHERE ward=? ORDER BY id LIMIT 1', (name,)).fetchone()
        w = preset.get(name, (name, bed['bed_no'][0], None, '', '', '', bed['daily_fee'], 0))
        conn.execute('INSERT INTO wards(name, code, dept_id, location, head_nurse, phone, bed_fee, created_at) '
                     'VALUES (?, ?, ?, ?, ?, ?, ?, ?)', w[:7] + (now_str(),))


def init_db(lang='zh', reset=False):
    path = db_path(lang)
    if reset and os.path.exists(path):
        os.remove(path)
    if os.path.exists(path):
        conn = get_conn(lang)
        ensure_ward_schema(conn)
        cols = [r['name'] for r in conn.execute('PRAGMA table_info(records)')]
        if 'draft_rx' not in cols:                     # 旧版数据库补充处方草稿字段
            conn.execute("ALTER TABLE records ADD COLUMN draft_rx TEXT DEFAULT ''")
        if 'active' not in [r['name'] for r in conn.execute('PRAGMA table_info(users)')]:
            conn.execute('ALTER TABLE users ADD COLUMN active INTEGER DEFAULT 1')
        conn.commit()
        conn.close()
        return
    conn = get_conn(lang)
    conn.executescript(SCHEMA + WARD_SCHEMA)
    seed(conn, lang)
    conn.commit()
    conn.close()


if __name__ == '__main__':
    for lang in LANGS:
        init_db(lang, reset=True)
        print('Database reset / 数据库已重置：', db_path(lang))
