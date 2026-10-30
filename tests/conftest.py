import os
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import database  # noqa: E402

# Point the databases at a temporary folder before app.py creates them on import.
database.BASE_DIR = tempfile.mkdtemp(prefix='his-test-')

import app as his  # noqa: E402


@pytest.fixture
def client():
    for lang in database.LANGS:
        database.init_db(lang, reset=True)
    his.app.config.update(TESTING=True, EXPIRED_ON={})
    c = his.app.test_client()
    c.set_cookie('lang', 'zh')
    return c


@pytest.fixture
def conn():
    c = database.get_conn('zh')
    yield c
    c.close()


def login(client, username, password='123456'):
    client.get('/logout')
    return client.post('/login', data={'username': username, 'password': password})
