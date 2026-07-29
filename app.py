import os
import sqlite3
from collections import defaultdict
from datetime import date, datetime

from flask import (Flask, flash, g, redirect, render_template, request,
                    send_from_directory, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "checkin.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_EXT = {"png", "jpg", "jpeg", "webp"}

# Senha padrão do painel do professor/admin. TROQUE antes de usar de verdade!
# Pode também ser definida pela variável de ambiente ADMIN_PASSWORD.
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "treino123")

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "troque-esta-chave-em-producao")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# --------------------------------------------------------------------------
# Banco de dados
# --------------------------------------------------------------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            nickname TEXT,
            photo TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS checkins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            workout_date TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            reviewed_at TEXT,
            FOREIGN KEY (student_id) REFERENCES students (id)
        );

        CREATE TABLE IF NOT EXISTS champions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            year INTEGER NOT NULL UNIQUE,
            student_id INTEGER NOT NULL,
            total_checkins INTEGER NOT NULL,
            closed_at TEXT NOT NULL,
            FOREIGN KEY (student_id) REFERENCES students (id)
        );
        """
    )
    db.commit()
    db.close()


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT


def today_str():
    return date.today().isoformat()


def display_name(student):
    return student["nickname"] or student["name"]


def get_active_students():
    db = get_db()
    return db.execute(
        "SELECT * FROM students WHERE active = 1 ORDER BY name COLLATE NOCASE"
    ).fetchall()


def get_student(student_id):
    db = get_db()
    return db.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()


def counts_for_student(student_id):
    """Retorna (semana, mes, ano) de check-ins APROVADOS para um aluno."""
    db = get_db()
    rows = db.execute(
        "SELECT workout_date FROM checkins WHERE student_id = ? AND status = 'approved'",
        (student_id,),
    ).fetchall()
    today = date.today()
    cur_iso_year, cur_week, _ = today.isocalendar()
    week = month = year = 0
    for r in rows:
        d = date.fromisoformat(r["workout_date"])
        iso_year, iso_week, _ = d.isocalendar()
        if iso_year == cur_iso_year and iso_week == cur_week:
            week += 1
        if d.year == today.year and d.month == today.month:
            month += 1
        if d.year == today.year:
            year += 1
    return week, month, year


def build_ranking(period):
    """period: 'week' | 'month' | 'year'. Retorna lista ordenada de dicts."""
    db = get_db()
    students = get_active_students()
    rows = db.execute(
        "SELECT student_id, workout_date FROM checkins WHERE status = 'approved'"
    ).fetchall()
    today = date.today()
    cur_iso_year, cur_week, _ = today.isocalendar()

    tally = defaultdict(int)
    for r in rows:
        d = date.fromisoformat(r["workout_date"])
        match = False
        if period == "week":
            iso_year, iso_week, _ = d.isocalendar()
            match = iso_year == cur_iso_year and iso_week == cur_week
        elif period == "month":
            match = d.year == today.year and d.month == today.month
        elif period == "year":
            match = d.year == today.year
        if match:
            tally[r["student_id"]] += 1

    ranking = []
    for s in students:
        ranking.append(
            {
                "id": s["id"],
                "name": display_name(s),
                "photo": s["photo"],
                "count": tally.get(s["id"], 0),
            }
        )
    ranking.sort(key=lambda x: (-x["count"], x["name"].lower()))
    return ranking


def is_admin():
    return session.get("is_admin", False)


@app.context_processor
def inject_globals():
    return {"is_admin": is_admin(), "current_year": date.today().year}


# --------------------------------------------------------------------------
# Rotas públicas / aluno
# --------------------------------------------------------------------------
@app.route("/")
def index():
    students = get_active_students()
    ranking_year = build_ranking("year")[:3]
    return render_template("index.html", students=students, top3=ranking_year)


@app.route("/aluno/<int:student_id>")
def aluno_dashboard(student_id):
    student = get_student(student_id)
    if not student:
        flash("Aluno não encontrado.", "error")
        return redirect(url_for("index"))

    week, month, year = counts_for_student(student_id)

    db = get_db()
    today_checkin = db.execute(
        "SELECT * FROM checkins WHERE student_id = ? AND workout_date = ?",
        (student_id, today_str()),
    ).fetchone()

    ranking_month = build_ranking("month")
    my_position = next(
        (i + 1 for i, r in enumerate(ranking_month) if r["id"] == student_id), None
    )

    return render_template(
        "aluno_dashboard.html",
        student=student,
        week=week,
        month=month,
        year=year,
        today_checkin=today_checkin,
        ranking_month=ranking_month[:5],
        my_position=my_position,
    )


@app.route("/aluno/<int:student_id>/checkin", methods=["POST"])
def fazer_checkin(student_id):
    student = get_student(student_id)
    if not student:
        flash("Aluno não encontrado.", "error")
        return redirect(url_for("index"))

    db = get_db()
    existing = db.execute(
        "SELECT * FROM checkins WHERE student_id = ? AND workout_date = ?",
        (student_id, today_str()),
    ).fetchone()
    if existing:
        flash("Você já registrou o treino de hoje. Aguarde a confirmação do professor.", "info")
    else:
        db.execute(
            "INSERT INTO checkins (student_id, workout_date, status, created_at) VALUES (?, ?, 'pending', ?)",
            (student_id, today_str(), datetime.now().isoformat()),
        )
        db.commit()
        flash("Check-in registrado! Assim que o professor confirmar, ele conta no ranking.", "success")

    return redirect(url_for("aluno_dashboard", student_id=student_id))


@app.route("/ranking")
def ranking():
    period = request.args.get("periodo", "month")
    if period not in ("week", "month", "year"):
        period = "month"
    data = build_ranking(period)

    db = get_db()
    champion = db.execute(
        "SELECT c.*, s.name, s.nickname, s.photo FROM champions c "
        "JOIN students s ON s.id = c.student_id ORDER BY c.year DESC LIMIT 1"
    ).fetchone()

    return render_template("ranking.html", ranking=data, period=period, champion=champion)


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


@app.route("/sw.js")
def service_worker():
    # Servido na raiz (não em /static/) para que o service worker consiga
    # controlar o app inteiro (scope "/"), permitindo instalar como PWA.
    response = send_from_directory(os.path.join(BASE_DIR, "static"), "sw.js")
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache"
    return response


# --------------------------------------------------------------------------
# Admin (professor)
# --------------------------------------------------------------------------
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        senha = request.form.get("senha", "")
        if senha == ADMIN_PASSWORD:
            session["is_admin"] = True
            flash("Login realizado.", "success")
            return redirect(url_for("admin_dashboard"))
        flash("Senha incorreta.", "error")
    return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("index"))


def require_admin():
    if not is_admin():
        flash("Faça login como professor para acessar essa página.", "error")
        return False
    return True


@app.route("/admin")
def admin_dashboard():
    if not require_admin():
        return redirect(url_for("admin_login"))

    db = get_db()
    pendentes = db.execute(
        "SELECT c.*, s.name, s.nickname, s.photo FROM checkins c "
        "JOIN students s ON s.id = c.student_id "
        "WHERE c.status = 'pending' ORDER BY c.workout_date DESC, c.created_at ASC"
    ).fetchall()

    recentes = db.execute(
        "SELECT c.*, s.name, s.nickname FROM checkins c "
        "JOIN students s ON s.id = c.student_id "
        "WHERE c.status != 'pending' ORDER BY c.reviewed_at DESC LIMIT 15"
    ).fetchall()

    total_alunos = db.execute("SELECT COUNT(*) FROM students WHERE active = 1").fetchone()[0]

    return render_template(
        "admin_dashboard.html", pendentes=pendentes, recentes=recentes, total_alunos=total_alunos
    )


@app.route("/admin/checkin/<int:checkin_id>/aprovar", methods=["POST"])
def aprovar_checkin(checkin_id):
    if not require_admin():
        return redirect(url_for("admin_login"))
    db = get_db()
    db.execute(
        "UPDATE checkins SET status = 'approved', reviewed_at = ? WHERE id = ?",
        (datetime.now().isoformat(), checkin_id),
    )
    db.commit()
    flash("Presença confirmada!", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/checkin/<int:checkin_id>/rejeitar", methods=["POST"])
def rejeitar_checkin(checkin_id):
    if not require_admin():
        return redirect(url_for("admin_login"))
    db = get_db()
    db.execute(
        "UPDATE checkins SET status = 'rejected', reviewed_at = ? WHERE id = ?",
        (datetime.now().isoformat(), checkin_id),
    )
    db.commit()
    flash("Check-in rejeitado.", "info")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/alunos")
def admin_alunos():
    if not require_admin():
        return redirect(url_for("admin_login"))
    db = get_db()
    students = db.execute("SELECT * FROM students ORDER BY active DESC, name COLLATE NOCASE").fetchall()
    return render_template("admin_alunos.html", students=students)


@app.route("/admin/alunos/novo", methods=["POST"])
def admin_novo_aluno():
    if not require_admin():
        return redirect(url_for("admin_login"))

    name = request.form.get("name", "").strip()
    nickname = request.form.get("nickname", "").strip()
    if not name:
        flash("O nome do aluno é obrigatório.", "error")
        return redirect(url_for("admin_alunos"))

    photo_filename = None
    file = request.files.get("photo")
    if file and file.filename and allowed_file(file.filename):
        ext = file.filename.rsplit(".", 1)[1].lower()
        safe_base = secure_filename(name).lower() or "aluno"
        photo_filename = f"{safe_base}-{int(datetime.now().timestamp())}.{ext}"
        file.save(os.path.join(app.config["UPLOAD_FOLDER"], photo_filename))

    db = get_db()
    db.execute(
        "INSERT INTO students (name, nickname, photo, active, created_at) VALUES (?, ?, ?, 1, ?)",
        (name, nickname or None, photo_filename, datetime.now().isoformat()),
    )
    db.commit()
    flash(f"Aluno {name} cadastrado!", "success")
    return redirect(url_for("admin_alunos"))


@app.route("/admin/alunos/<int:student_id>/inativar", methods=["POST"])
def admin_inativar_aluno(student_id):
    if not require_admin():
        return redirect(url_for("admin_login"))
    db = get_db()
    db.execute("UPDATE students SET active = 0 WHERE id = ?", (student_id,))
    db.commit()
    flash("Aluno removido da lista ativa.", "info")
    return redirect(url_for("admin_alunos"))


@app.route("/admin/alunos/<int:student_id>/reativar", methods=["POST"])
def admin_reativar_aluno(student_id):
    if not require_admin():
        return redirect(url_for("admin_login"))
    db = get_db()
    db.execute("UPDATE students SET active = 1 WHERE id = ?", (student_id,))
    db.commit()
    flash("Aluno reativado.", "success")
    return redirect(url_for("admin_alunos"))


@app.route("/admin/campeoes")
def admin_campeoes():
    if not require_admin():
        return redirect(url_for("admin_login"))
    db = get_db()
    campeoes = db.execute(
        "SELECT c.*, s.name, s.nickname, s.photo FROM champions c "
        "JOIN students s ON s.id = c.student_id ORDER BY c.year DESC"
    ).fetchall()
    ranking_year = build_ranking("year")
    already_closed = any(c["year"] == date.today().year for c in campeoes)
    return render_template(
        "admin_campeoes.html",
        campeoes=campeoes,
        ranking_year=ranking_year,
        already_closed=already_closed,
    )


@app.route("/admin/campeoes/fechar", methods=["POST"])
def fechar_ano():
    if not require_admin():
        return redirect(url_for("admin_login"))

    year = date.today().year
    ranking_year = build_ranking("year")
    if not ranking_year or ranking_year[0]["count"] == 0:
        flash("Ainda não há check-ins aprovados este ano para fechar o ranking.", "error")
        return redirect(url_for("admin_campeoes"))

    winner = ranking_year[0]
    db = get_db()
    try:
        db.execute(
            "INSERT INTO champions (year, student_id, total_checkins, closed_at) VALUES (?, ?, ?, ?)",
            (year, winner["id"], winner["count"], datetime.now().isoformat()),
        )
        db.commit()
        flash(f"Ano {year} fechado! Campeão: {winner['name']} com {winner['count']} treinos.", "success")
    except sqlite3.IntegrityError:
        flash(f"O ano {year} já foi fechado anteriormente.", "error")

    return redirect(url_for("admin_campeoes"))


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
