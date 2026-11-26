import sqlite3
from pathlib import Path

from app import create_app


def setup(tmp_path):
    app = create_app({'TESTING': True, 'DATABASE': str(tmp_path / 'test.db'), 'SECRET_KEY': 'test'})
    client = app.test_client()
    client.get('/register')
    with client.session_transaction() as session:
        csrf = session['csrf']
    return app, client, csrf


def register(client, csrf, name, email):
    return client.post('/register', data={'csrf': csrf, 'name': name, 'email': email, 'password': 'password123'})


def test_project_task_comment_workflow(tmp_path):
    app, client, csrf = setup(tmp_path)
    assert register(client, csrf, 'Ada', 'ada@example.com').status_code == 302
    with client.session_transaction() as session:
        csrf = session['csrf']
    assert client.post('/projects', data={'csrf': csrf, 'name': 'Launch', 'description': 'Ship product'}).status_code == 302
    assert client.post('/projects/1/tasks', data={'csrf': csrf, 'title': 'Review', 'priority': 'high'}).status_code == 302
    assert client.post('/tasks/1', data={'csrf': csrf, 'status': 'done', 'assignee_id': '1'}).status_code == 302
    assert client.post('/tasks/1/comments', data={'csrf': csrf, 'body': 'Ready'}).status_code == 302
    page = client.get('/tasks/1')
    assert b'Ready' in page.data
    with app.app_context():
        with sqlite3.connect(app.config['DATABASE']) as db:
            assert db.execute('SELECT status,assignee_id FROM tasks').fetchone() == ('done', 1)


def test_private_project_and_csrf(tmp_path):
    _, client, csrf = setup(tmp_path)
    register(client, csrf, 'Ada', 'ada@example.com')
    with client.session_transaction() as session:
        csrf = session['csrf']
    client.post('/projects', data={'csrf': csrf, 'name': 'Private'})
    client.post('/logout', data={'csrf': csrf})
    client.get('/register')
    with client.session_transaction() as session:
        csrf = session['csrf']
    register(client, csrf, 'Grace', 'grace@example.com')
    assert client.get('/projects/1').status_code == 404
    assert client.post('/projects', data={'name': 'No token'}).status_code == 400
