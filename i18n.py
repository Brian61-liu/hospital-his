"""
界面多语言支持（中文 / English）

- 中文原文直接作为翻译键，英文对照写在 translations_en.py 的 EN 字典中；
- 带变量的文字使用编号占位符，例如 _('{0} 已挂过该医生同一时段的号', name)，
  英文译文可以按英文语序调整占位符位置；
- 状态、医保类型等内部值在数据库中保持中文，只在显示时翻译。
"""
from flask import g, has_request_context

from translations_en import EN

LANG_NAMES = {'zh': '中文', 'en': 'English'}
WEEKDAYS = {'zh': '一二三四五六日', 'en': ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')}
MONTHS_EN = ('January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
             'September', 'October', 'November', 'December')
WEEKDAYS_EN_FULL = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')


def get_lang():
    return getattr(g, 'lang', 'zh') if has_request_context() else 'zh'


def _(text, *args, **kwargs):
    """翻译界面文字；英文对照缺失时原样返回中文"""
    if get_lang() == 'en' and text:
        text = EN.get(text, text)
    return text.format(*args, **kwargs) if (args or kwargs) else text


def missing_keys(keys):
    """测试用：返回没有英文对照的翻译键"""
    return sorted(k for k in keys if k not in EN)


# ---------------- 前端脚本用到的文字 ----------------
import glob as _glob
import os as _os
import re as _re

_BASE = _os.path.dirname(_os.path.abspath(__file__))
_T_CALL = _re.compile(r"""\bt\((['"])(.+?)\1""")


def _scan_js_keys():
    keys = set()
    files = _glob.glob(_os.path.join(_BASE, 'static', 'js', '*.js')) + _glob.glob(_os.path.join(_BASE, 'templates', '*.html'))
    for path in files:
        with open(path, encoding='utf-8') as f:
            keys.update(m.group(2) for m in _T_CALL.finditer(f.read()))
    return sorted(keys)


JS_KEYS = _scan_js_keys()


def js_strings():
    """前端 t('中文') 使用的译文；中文界面不需要传递"""
    return {k: EN.get(k, k) for k in JS_KEYS} if get_lang() == 'en' else {}
