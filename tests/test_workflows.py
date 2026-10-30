"""End-to-end tests of the outpatient and inpatient workflows through the Flask test client."""
from datetime import date, timedelta

import pytest

import app as his
from database import current_period
from conftest import login

TODAY = date.today().isoformat()


def card(no):
    return f'P{date.today().year}{no:05d}'


def drug(conn, code):
    return conn.execute('SELECT * FROM drugs WHERE code=?', (code,)).fetchone()


def register(client, patient_no, doctor_id, method='微信'):
    return client.post('/registration', data={'card': card(patient_no), 'doctor_id': doctor_id,
                                              'visit_date': TODAY, 'period': current_period(), 'method': method})


def latest_registration(conn, patient_no, doctor_id):
    return conn.execute('SELECT * FROM registrations WHERE patient_id=? AND doctor_id=? AND visit_date=? '
                        'ORDER BY id DESC', (patient_no, doctor_id, TODAY)).fetchone()


# ---------------------------------------------------------------- access control
def test_login_rejects_wrong_password(client):
    resp = login(client, 'shoufei', 'wrong')
    assert resp.status_code == 200
    with client.session_transaction() as s:
        assert 'user_id' not in s


def test_pages_require_login(client):
    resp = client.get('/billing')
    assert resp.status_code == 302 and '/login' in resp.headers['Location']


def test_role_cannot_open_other_workstation(client):
    login(client, 'shoufei')                       # cashier
    resp = client.get('/pharmacy')
    assert resp.status_code == 302 and resp.headers['Location'].endswith('/')


def test_disabled_account_is_signed_out(client, conn):
    login(client, 'shoufei')
    conn.execute("UPDATE users SET active=0 WHERE username='shoufei'")
    conn.commit()
    resp = client.get('/registration')
    assert resp.status_code == 302 and '/login' in resp.headers['Location']


@pytest.mark.parametrize('lang, user', [('zh', 'admin'), ('en', 'admin')])
def test_every_page_renders_for_admin(client, lang, user):
    client.set_cookie('lang', lang)
    login(client, user)
    for path in ['/', '/patients', '/patients/1', '/registration', '/clinic', '/billing', '/pharmacy',
                 '/inpatient', '/wards', '/staff', '/profile', '/help']:
        assert client.get(path).status_code == 200, path


# ---------------------------------------------------------------- outpatient
def test_outpatient_flow_with_allergy_check_insurance_and_dispensing(client, conn):
    amoxicillin = drug(conn, 'YP001')             # allergen: penicillin; patient 1 is allergic

    login(client, 'shoufei')
    register(client, 1, 3)                         # Dr. Li Ming
    reg = latest_registration(conn, 1, 3)
    assert reg['status'] == '待诊' and reg['fee'] == 20

    register(client, 1, 3)                         # same doctor, same period
    assert conn.execute('SELECT COUNT(*) FROM registrations WHERE patient_id=1 AND doctor_id=3').fetchone()[0] == 1

    login(client, 'liming')
    client.get(f'/clinic/visit/{reg["id"]}')
    visit = {'action': 'finish', 'complaint': '咽痛', 'diagnosis': '急性咽炎',
             'drug_id': amoxicillin['id'], 'qty': '1', 'usage': '口服 一日3次 每次1粒'}

    client.post(f'/clinic/visit/{reg["id"]}', data=visit)
    assert latest_registration(conn, 1, 3)['status'] == '就诊中'      # blocked by allergy check
    assert conn.execute('SELECT COUNT(*) FROM prescriptions WHERE reg_id=?', (reg['id'],)).fetchone()[0] == 0

    client.post(f'/clinic/visit/{reg["id"]}', data={**visit, 'allergy_confirm': '1'})
    assert latest_registration(conn, 1, 3)['status'] == '已诊'
    rx = conn.execute('SELECT * FROM prescriptions WHERE reg_id=?', (reg['id'],)).fetchone()
    assert rx['status'] == '待缴费' and rx['total'] == pytest.approx(18.5)

    login(client, 'shoufei')
    client.post(f'/billing/{rx["id"]}/pay', data={'method': '医保结算'})   # employee insurance covers 70 %
    pay = conn.execute('SELECT * FROM payments ORDER BY id DESC').fetchone()
    assert pay['insurance_pay'] == pytest.approx(12.95) and pay['amount'] == pytest.approx(5.55)

    login(client, 'yaofang')
    client.post(f'/pharmacy/{rx["id"]}/dispense')
    assert conn.execute('SELECT status FROM prescriptions WHERE id=?', (rx['id'],)).fetchone()[0] == '已发药'
    assert drug(conn, 'YP001')['stock'] == amoxicillin['stock'] - 1


def test_self_pay_patient_cannot_use_insurance(client, conn):
    reg = latest_registration(conn, 5, 2)          # seeded: self-pay patient in consultation
    login(client, 'zhangwei')
    client.post(f'/clinic/visit/{reg["id"]}', data={'action': 'finish', 'diagnosis': '慢性胃炎',
                                                     'drug_id': drug(conn, 'YP005')['id'], 'qty': '1',
                                                     'usage': '口服 一日1次 每次1粒'})
    rx = conn.execute('SELECT * FROM prescriptions WHERE reg_id=?', (reg['id'],)).fetchone()

    login(client, 'shoufei')
    client.post(f'/billing/{rx["id"]}/pay', data={'method': '医保结算'})
    assert conn.execute('SELECT status FROM prescriptions WHERE id=?', (rx['id'],)).fetchone()[0] == '待缴费'
    client.post(f'/billing/{rx["id"]}/pay', data={'method': '现金'})
    pay = conn.execute('SELECT * FROM payments ORDER BY id DESC').fetchone()
    assert pay['insurance_pay'] == 0 and pay['amount'] == pytest.approx(26.5)


def test_prescription_quantity_cannot_exceed_stock(client, conn):
    ambroxol = drug(conn, 'YP006')                 # 8 bottles in stock
    reg = latest_registration(conn, 5, 2)
    login(client, 'zhangwei')
    client.post(f'/clinic/visit/{reg["id"]}', data={'action': 'finish', 'diagnosis': '急性支气管炎',
                                                     'drug_id': ambroxol['id'], 'qty': str(ambroxol['stock'] + 1),
                                                     'usage': '口服 一日2次 每次5ml'})
    assert conn.execute('SELECT COUNT(*) FROM prescriptions WHERE reg_id=?', (reg['id'],)).fetchone()[0] == 0


def test_dispensing_with_insufficient_stock_changes_nothing(client, conn):
    rx = conn.execute("SELECT * FROM prescriptions WHERE status='已缴费'").fetchone()
    conn.execute('UPDATE drugs SET stock=0 WHERE id IN (SELECT drug_id FROM rx_items WHERE rx_id=?)', (rx['id'],))
    conn.commit()
    login(client, 'yaofang')
    client.post(f'/pharmacy/{rx["id"]}/dispense')
    assert conn.execute('SELECT status FROM prescriptions WHERE id=?', (rx['id'],)).fetchone()[0] == '已缴费'


def test_registration_respects_quota(client, conn, monkeypatch):
    booked = conn.execute("SELECT COUNT(*) FROM registrations WHERE doctor_id=7 AND visit_date=? AND period=?",
                          (TODAY, current_period())).fetchone()[0]
    monkeypatch.setattr(his, 'QUOTA_PER_PERIOD', booked)
    login(client, 'shoufei')
    register(client, 6, 7)
    assert latest_registration(conn, 6, 7) is None


def test_refund_returns_insurance_share(client, conn):
    rx = conn.execute("SELECT * FROM prescriptions WHERE status='已缴费'").fetchone()
    login(client, 'shoufei')
    client.post(f'/billing/{rx["id"]}/refund')
    refund = conn.execute('SELECT * FROM payments ORDER BY id DESC').fetchone()
    paid = conn.execute('SELECT * FROM payments WHERE item LIKE ? AND amount > 0', (f'%{rx["rx_no"]}%',)).fetchone()
    assert refund['amount'] == -paid['amount'] and refund['insurance_pay'] == -paid['insurance_pay']
    assert conn.execute('SELECT status FROM prescriptions WHERE id=?', (rx['id'],)).fetchone()[0] == '已退费'


# ---------------------------------------------------------------- inpatient
def test_admission_transfer_and_discharge_bill_bed_fees_by_segment(client, conn):
    n01 = conn.execute("SELECT * FROM beds WHERE bed_no='N01'").fetchone()     # 60 / day
    e02 = conn.execute("SELECT * FROM beds WHERE bed_no='E02'").fetchone()     # 50 / day
    login(client, 'hushi')
    client.post('/inpatient/admit', data={'card': card(1), 'bed_id': n01['id'], 'diagnosis': '肺炎',
                                          'deposit': '5000', 'doctor_id': 2, 'method': '银行卡'})
    adm = conn.execute("SELECT * FROM admissions WHERE patient_id=1 AND status='在院'").fetchone()
    assert adm and conn.execute('SELECT status FROM beds WHERE id=?', (n01['id'],)).fetchone()[0] == '占用'

    client.post('/inpatient/admit', data={'card': card(1), 'bed_id': e02['id'], 'diagnosis': '肺炎', 'deposit': '5000'})
    assert conn.execute("SELECT COUNT(*) FROM admissions WHERE patient_id=1 AND status='在院'").fetchone()[0] == 1

    client.post(f'/beds/{n01["id"]}/transfer', data={'to_bed': e02['id'], 'reason': '病情需要'})
    # Admitted 10 days ago, moved after 6 days: 6 × 60 + 4 × 50 bed fee + 10 × 25 nursing fee = 810
    conn.execute('UPDATE admissions SET admit_date=? WHERE id=?', ((date.today() - timedelta(days=10)).isoformat(), adm['id']))
    conn.execute('UPDATE bed_transfers SET created_at=? WHERE adm_id=?',
                 ((date.today() - timedelta(days=4)).isoformat() + ' 09:00:00', adm['id']))
    conn.commit()

    client.post(f'/inpatient/{adm["id"]}/discharge')
    done = conn.execute('SELECT * FROM admissions WHERE id=?', (adm['id'],)).fetchone()
    assert done['status'] == '出院' and done['total_fee'] == pytest.approx(810)
    settle = conn.execute('SELECT * FROM payments ORDER BY id DESC').fetchone()
    assert settle['amount'] == pytest.approx(-(5000 - 810))
    assert conn.execute('SELECT status FROM beds WHERE id=?', (e02['id'],)).fetchone()[0] == '空闲'


def test_admission_requires_minimum_deposit(client, conn):
    login(client, 'hushi')
    bed = conn.execute("SELECT id FROM beds WHERE status='空闲' LIMIT 1").fetchone()[0]
    client.post('/inpatient/admit', data={'card': card(4), 'bed_id': bed, 'diagnosis': '阑尾炎',
                                          'deposit': str(his.MIN_DEPOSIT - 1)})
    assert conn.execute("SELECT COUNT(*) FROM admissions WHERE patient_id=4").fetchone()[0] == 0


def test_open_redirects_are_rejected():
    assert his.safe_path('/inpatient') == '/inpatient'
    for bad in ('//evil.example', 'https://evil.example', '/\\evil.example', ''):
        assert his.safe_path(bad) is None
