import os
import secrets
import sqlite3
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

SCHEMA = '''
CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, password TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS projects (id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL REFERENCES users(id), name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS members (project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE, user_id INTEGER NOT NULL REFERENCES users(id), PRIMARY KEY(project_id,user_id));
CREATE TABLE IF NOT EXISTS tasks (id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'todo' CHECK(status IN ('todo','doing','done')), priority TEXT NOT NULL DEFAULT 'medium' CHECK(priority IN ('low','medium','high')), assignee_id INTEGER REFERENCES users(id), due_date TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS comments (id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE, user_id INTEGER NOT NULL REFERENCES users(id), body TEXT NOT NULL, created_at TEXT NOT NULL);
'''


def create_app(config=None):
    app = Flask(__name__)
    app.config.update(SECRET_KEY=os.environ.get('SECRET_KEY', 'dev-only-change-me'), DATABASE=os.environ.get('DATABASE', str(Path(__file__).with_name('teamboard.db'))))
    if config:
        app.config.update(config)

    def db():
        if 'db' not in g:
            g.db = sqlite3.connect(app.config['DATABASE'])
            g.db.row_factory = sqlite3.Row
            g.db.execute('PRAGMA foreign_keys=ON')
        return g.db

    @app.teardown_appcontext
    def close(_):
        connection = g.pop('db', None)
        if connection:
            connection.close()

    @app.before_request
    def guard():
        if 'csrf' not in session:
            session['csrf'] = secrets.token_hex(16)
        if request.method == 'POST' and not secrets.compare_digest(request.form.get('csrf', ''), session['csrf']):
            abort(400)
        g.user = db().execute('SELECT * FROM users WHERE id=?', (session.get('user_id', -1),)).fetchone()

    @app.context_processor
    def globals_for_templates():
        return {'csrf': session.get('csrf'), 'current_user': g.get('user')}

    def login_required(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not g.user:
                return redirect(url_for('login'))
            return fn(*args, **kwargs)
        return wrapped

    def project_for_user(project_id):
        project = db().execute('''SELECT p.* FROM projects p JOIN members m ON m.project_id=p.id
                                  WHERE p.id=? AND m.user_id=?''', (project_id, g.user['id'])).fetchone()
        if not project:
            abort(404)
        return project

    @app.route('/register', methods=['GET', 'POST'])
    def register():
        if request.method == 'POST':
            name = request.form.get('name', '').strip()
            email = request.form.get('email', '').strip().lower()
            password = request.form.get('password', '')
            if not name or not email or len(password) < 8:
                flash('Enter a name, email and password of at least 8 characters.')
            else:
                try:
                    with db():
                        user_id = db().execute('INSERT INTO users(name,email,password) VALUES(?,?,?)', (name, email, generate_password_hash(password))).lastrowid
                    session.clear()
                    session['user_id'] = user_id
                    session['csrf'] = secrets.token_hex(16)
                    return redirect(url_for('dashboard'))
                except sqlite3.IntegrityError:
                    flash('Email already registered.')
        return render_template('auth.html', title='Create account', action='register')

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            user = db().execute('SELECT * FROM users WHERE email=?', (request.form.get('email', '').strip().lower(),)).fetchone()
            if user and check_password_hash(user['password'], request.form.get('password', '')):
                session.clear()
                session['user_id'] = user['id']
                session['csrf'] = secrets.token_hex(16)
                return redirect(url_for('dashboard'))
            flash('Incorrect email or password.')
        return render_template('auth.html', title='Sign in', action='login')

    @app.post('/logout')
    def logout():
        session.clear()
        return redirect(url_for('login'))

    @app.get('/')
    @login_required
    def dashboard():
        projects = db().execute('''SELECT p.*, COUNT(t.id) AS total, SUM(CASE WHEN t.status='done' THEN 1 ELSE 0 END) AS done
                                   FROM projects p JOIN members m ON m.project_id=p.id LEFT JOIN tasks t ON t.project_id=p.id
                                   WHERE m.user_id=? GROUP BY p.id ORDER BY p.id DESC''', (g.user['id'],)).fetchall()
        return render_template('dashboard.html', projects=projects)

    @app.post('/projects')
    @login_required
    def new_project():
        name = request.form.get('name', '').strip()
        if not name:
            abort(400)
        with db():
            project_id = db().execute('INSERT INTO projects(owner_id,name,description) VALUES(?,?,?)', (g.user['id'], name, request.form.get('description', '').strip())).lastrowid
            db().execute('INSERT INTO members VALUES(?,?)', (project_id, g.user['id']))
        return redirect(url_for('project', project_id=project_id))

    @app.get('/projects/<int:project_id>')
    @login_required
    def project(project_id):
        record = project_for_user(project_id)
        tasks = db().execute('''SELECT t.*,u.name AS assignee FROM tasks t LEFT JOIN users u ON u.id=t.assignee_id WHERE t.project_id=? ORDER BY t.id DESC''', (project_id,)).fetchall()
        members = db().execute('SELECT u.* FROM users u JOIN members m ON m.user_id=u.id WHERE m.project_id=?', (project_id,)).fetchall()
        return render_template('project.html', project=record, tasks=tasks, members=members)

    @app.post('/projects/<int:project_id>/members')
    @login_required
    def add_member(project_id):
        project = project_for_user(project_id)
        if project['owner_id'] != g.user['id']:
            abort(403)
        user = db().execute('SELECT id FROM users WHERE email=?', (request.form.get('email', '').strip().lower(),)).fetchone()
        if user:
            with db():
                db().execute('INSERT OR IGNORE INTO members VALUES(?,?)', (project_id, user['id']))
        else:
            flash('That email has not registered yet.')
        return redirect(url_for('project', project_id=project_id))

    @app.post('/projects/<int:project_id>/tasks')
    @login_required
    def add_task(project_id):
        project_for_user(project_id)
        title = request.form.get('title', '').strip()
        priority = request.form.get('priority', 'medium')
        if not title or priority not in ('low', 'medium', 'high'):
            abort(400)
        due = request.form.get('due_date') or None
        with db():
            db().execute('INSERT INTO tasks(project_id,title,description,priority,due_date,created_at) VALUES(?,?,?,?,?,?)',
                         (project_id, title, request.form.get('description', '').strip(), priority, due, datetime.now(timezone.utc).isoformat()))
        return redirect(url_for('project', project_id=project_id))

    @app.post('/tasks/<int:task_id>')
    @login_required
    def update_task(task_id):
        task = db().execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
        if not task:
            abort(404)
        project_for_user(task['project_id'])
        status = request.form.get('status')
        assignee = request.form.get('assignee_id') or None
        if status not in ('todo', 'doing', 'done'):
            abort(400)
        if assignee and not db().execute('SELECT 1 FROM members WHERE project_id=? AND user_id=?', (task['project_id'], assignee)).fetchone():
            abort(400)
        with db():
            db().execute('UPDATE tasks SET status=?,assignee_id=? WHERE id=?', (status, assignee, task_id))
        return redirect(url_for('project', project_id=task['project_id']))

    @app.get('/tasks/<int:task_id>')
    @login_required
    def task_detail(task_id):
        task = db().execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
        if not task:
            abort(404)
        project_for_user(task['project_id'])
        comments = db().execute('SELECT c.*,u.name FROM comments c JOIN users u ON u.id=c.user_id WHERE task_id=? ORDER BY c.id', (task_id,)).fetchall()
        return render_template('task.html', task=task, comments=comments)

    @app.post('/tasks/<int:task_id>/comments')
    @login_required
    def comment(task_id):
        task = db().execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
        if not task:
            abort(404)
        project_for_user(task['project_id'])
        body = request.form.get('body', '').strip()
        if not body:
            abort(400)
        with db():
            db().execute('INSERT INTO comments(task_id,user_id,body,created_at) VALUES(?,?,?,?)', (task_id, g.user['id'], body, datetime.now(timezone.utc).isoformat()))
        return redirect(url_for('task_detail', task_id=task_id))

    with app.app_context():
        db().executescript(SCHEMA)
    return app


app = create_app()

if __name__ == '__main__':
    app.run(debug=True)
