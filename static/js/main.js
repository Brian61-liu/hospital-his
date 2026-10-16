/* HIS 公共脚本：时钟、快捷键、确认框、消息提示、输入清除 */

// 界面翻译：中文原文作为键，英文译文由服务器注入 window.I18N；{0}、{1} 为占位符
function t(key, ...args) {
    const text = (window.I18N && window.I18N[key]) || key;
    return text.replace(/\{(\d+)\}/g, (m, i) => (args[i] !== undefined ? args[i] : m));
}

// 转义 HTML，防止患者姓名等内容被当作网页代码执行
function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
}

// 顶部实时时钟（状态可见）
(function clock() {
    const el = document.getElementById('clock');
    if (!el) return;
    const week = window.LANG === 'en' ? ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
                                      : ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
    const tick = () => {
        const d = new Date();
        const p = n => String(n).padStart(2, '0');
        el.textContent = `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${week[d.getDay()]} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
    };
    tick();
    setInterval(tick, 1000);
})();

// 快捷键（灵活高效）：/ 聚焦搜索，Alt+数字 切换菜单，Esc 关闭弹窗
document.addEventListener('keydown', e => {
    const typing = ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName);
    if (e.key === '/' && !typing) {
        const s = document.getElementById('globalSearch');
        if (s) { e.preventDefault(); s.focus(); }
    }
    if (e.altKey && /^[1-9]$/.test(e.key)) {
        const link = document.querySelector(`.nav-item[data-key="${e.key}"]`);
        if (link) { e.preventDefault(); location.href = link.href; }
    }
    if (e.key === 'Escape') closeModal(false);
});

// 消息提示：成功消息自动消失，错误消息保留到用户手动关闭
document.querySelectorAll('.toast').forEach(toast => {
    toast.querySelector('.close').onclick = () => toast.remove();
    if (toast.classList.contains('success') || toast.classList.contains('info')) {
        setTimeout(() => toast.remove(), 5000);
    }
});

// 统一确认框（预防出错 / 用户可控）
const modal = document.getElementById('confirmModal');
let modalCallback = null;
function openModal(text, onOk, danger) {
    if (!modal) { if (confirm(text)) onOk(); return; }
    modal.querySelector('p').textContent = text;
    const ok = modal.querySelector('.ok');
    ok.className = 'btn ok ' + (danger ? 'btn-danger' : '');
    modalCallback = onOk;
    modal.classList.add('show');
    ok.focus();
}
function closeModal(confirmed) {
    if (!modal || !modal.classList.contains('show')) return;
    modal.classList.remove('show');
    if (confirmed && modalCallback) modalCallback();
    modalCallback = null;
}
if (modal) {
    modal.querySelector('.ok').onclick = () => closeModal(true);
    modal.querySelector('.cancel').onclick = () => closeModal(false);
    modal.addEventListener('click', e => { if (e.target === modal) closeModal(false); });
}

document.addEventListener('click', e => {
    const el = e.target.closest('[data-confirm]');
    if (!el || el.dataset.confirmed) return;
    if (el.tagName === 'A') {
        e.preventDefault();
        openModal(el.dataset.confirm, () => { location.href = el.href; }, el.dataset.danger !== undefined);
    } else if (el.tagName === 'BUTTON' && el.form) {
        if (!el.form.checkValidity()) return;          // 先让浏览器提示必填项
        e.preventDefault();
        openModal(el.dataset.confirm, () => {
            el.dataset.confirmed = '1';
            el.form.requestSubmit(el);
        }, el.dataset.danger !== undefined);
    }
});

// 输入框右侧的 × 清除按钮（沿用猜数游戏的“X”清除交互）
document.querySelectorAll('.input-clear .x').forEach(btn => {
    btn.addEventListener('click', () => {
        const input = btn.parentElement.querySelector('input');
        input.value = '';
        input.dispatchEvent(new Event('input'));
        input.focus();
    });
});

// 防止重复提交：表单提交后禁用提交按钮（未写 type 的按钮默认也是提交按钮）
document.querySelectorAll('form[data-once]').forEach(f => {
    f.addEventListener('submit', () => {
        setTimeout(() => f.querySelectorAll('button:not([type=button]):not([type=reset])').forEach(b => {
            if (!b.disabled) { b.disabled = true; b.dataset.onceDisabled = '1'; }
        }), 0);
    });
});
// 浏览器“后退”回到页面时，恢复被禁用的按钮
window.addEventListener('pageshow', () => {
    document.querySelectorAll('[data-once-disabled]').forEach(b => { b.disabled = false; delete b.dataset.onceDisabled; });
});

// 查询患者卡号，供挂号/入院页面预览患者信息
async function lookupPatient(card, box) {
    card = (card || '').trim().split(' ')[0].toUpperCase();
    if (!card) { box.innerHTML = `<span class="muted">${t('输入或选择就诊卡号后，这里会显示患者信息')}</span>`; return null; }
    let p;
    try {
        const res = await fetch(`/api/patient/${encodeURIComponent(card)}`);
        p = await res.json();
    } catch (e) {
        box.innerHTML = `<span class="text-danger">${t('查询失败，登录可能已失效，请刷新页面')}</span>`;
        return null;
    }
    if (!p.found) {
        box.innerHTML = `<span class="text-danger">${esc(t('未找到卡号 {0}', card))}</span>`;
        return null;
    }
    box.innerHTML = `<b>${esc(p.name)}</b>　${esc(p.gender)}　${esc(p.age)}　<span class="tag">${esc(p.insurance)}</span>　${esc(p.phone)}` +
        (p.allergy ? `<br><span class="allergy-tag">${esc(t('过敏史：{0}', p.allergy))}</span>` : '');
    return p;
}
