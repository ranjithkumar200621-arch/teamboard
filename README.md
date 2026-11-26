# Teamboard

A working project and task management web app. Users can register, create private projects, add registered teammates, assign tasks, move tasks across three stages, edit task details, set priorities and due dates, discuss work in comments, and let project owners remove tasks.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
flask --app app run
```

Open http://127.0.0.1:5000 and create an account. The SQLite database is created automatically. Set `DATABASE` to another path to change its location. To try collaboration, register a second account and add its email from a project owner's board.

## Design decisions

Projects and tasks are checked against project membership on every read and write. Only owners may add members. Passwords are hashed with Werkzeug. Forms use CSRF tokens. A task can only be assigned to a project member. SQLite foreign keys are enabled for each connection.

This is a local demo. For an internet deployment, set a durable `SECRET_KEY`, use HTTPS, and configure a production WSGI server.

## Tests

```bash
pip install pytest
pytest -q
```

The tests cover account creation, task assignment and comments, project access control, and CSRF protection.
