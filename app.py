import os
import random
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timedelta
from io import BytesIO

from flask import (Flask, flash, g, redirect, render_template, request,
                    send_file, send_from_directory, session, url_for)
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from PIL import Image, UnidentifiedImageError
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "checkin.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_EXT = {"png", "jpg", "jpeg", "webp"}

# Se DATABASE_URL estiver definida (Render/Supabase Postgres), o app usa
# Postgres. Sem ela, cai para SQLite local — útil para testar na sua máquina.
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
USE_POSTGRES = bool(DATABASE_URL)

if USE_POSTGRES:
    import psycopg2
    import psycopg2.extras

    IntegrityError = psycopg2.IntegrityError
else:
    IntegrityError = sqlite3.IntegrityError

# Senha padrão do painel do professor/admin. TROQUE antes de usar de verdade!
# Pode também ser definida pela variável de ambiente ADMIN_PASSWORD.
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "treino123")

# Limites de tentativas de PIN (proteção simples contra tentativa e erro).
MAX_PIN_ATTEMPTS = 5
LOCKOUT_MINUTES = 15

# Compressão de fotos: qualquer foto enviada é redimensionada e reencodada
# para não pesar o armazenamento (importante em planos gratuitos).
MAX_PHOTO_DIMENSION = 720
PHOTO_JPEG_QUALITY = 82

# Paleta usada para colorir o avatar de quem ainda não tem foto (cor fixa
# por aluno, calculada a partir do id, para reconhecer o cartão dele rápido).
AVATAR_COLORS = [
    "#3a7bc8", "#c0453f", "#3f9463", "#d4af37",
    "#8b5fbf", "#c97a3d", "#4a8fa8", "#a3475f",
]

# Faixas (Hapkido) usadas como indicador de progresso: sobe conforme o
# total de treinos confirmados ao longo da vida do aluno no app.
BELTS = [
    {"min": 0, "name": "Faixa Branca", "color": "#f2f2ee"},
    {"min": 10, "name": "Faixa Amarela", "color": "#e7c548"},
    {"min": 25, "name": "Faixa Verde", "color": "#3f9463"},
    {"min": 50, "name": "Faixa Azul", "color": "#3a7bc8"},
    {"min": 80, "name": "Faixa Vermelha", "color": "#c0453f"},
    {"min": 120, "name": "Faixa Preta", "color": "#1b1b1b"},
]


def belt_info(total_checkins):
    """Retorna dados da faixa atual do aluno e progresso até a próxima."""
    current = BELTS[0]
    idx = 0
    for i, b in enumerate(BELTS):
        if total_checkins >= b["min"]:
            current = b
            idx = i

    if idx == len(BELTS) - 1:
        span = max(1, total_checkins - current["min"] or 1)
        progressed = span
        next_name, remaining = None, 0
    else:
        nxt = BELTS[idx + 1]
        span = nxt["min"] - current["min"]
        progressed = total_checkins - current["min"]
        next_name, remaining = nxt["name"], nxt["min"] - total_checkins

    pct = 100 if idx == len(BELTS) - 1 else max(0, min(100, round(progressed / span * 100)))
    return {
        "name": current["name"],
        "color": current["color"],
        "pct": pct,
        "next_name": next_name,
        "remaining": remaining,
    }

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "troque-esta-chave-em-producao")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# --------------------------------------------------------------------------
# Banco de dados — camada fina que funciona com SQLite (dev local) ou
# Postgres (produção), usando sempre "?" como marcador de parâmetro no
# código e traduzindo para "%s" quando o backend é Postgres.
# --------------------------------------------------------------------------
class DB:
    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=()):
        cur = self._conn.cursor()
        if USE_POSTGRES:
            sql = sql.replace("?", "%s")
        cur.execute(sql, params)
        return cur

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


def _raw_connect():
    if USE_POSTGRES:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
        conn.autocommit = False
        return conn
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db():
    if "db" not in g:
        g.db = DB(_raw_connect())
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    if USE_POSTGRES:
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS students (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                nickname TEXT,
                photo TEXT,
                pin TEXT,
                pin_attempts INTEGER NOT NULL DEFAULT 0,
                pin_locked_until TEXT,
                pin_is_custom INTEGER NOT NULL DEFAULT 0,
                birth_date TEXT,
                real_belt TEXT,
                phone TEXT,
                guardian_name TEXT,
                guardian_phone TEXT,
                address TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS checkins (
                id SERIAL PRIMARY KEY,
                student_id INTEGER NOT NULL REFERENCES students (id),
                workout_date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                reviewed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS champions (
                id SERIAL PRIMARY KEY,
                year INTEGER NOT NULL UNIQUE,
                student_id INTEGER NOT NULL REFERENCES students (id),
                total_checkins INTEGER NOT NULL,
                closed_at TEXT NOT NULL
            );
            """
        )
        # Migração seguindo para bancos criados antes destas colunas existirem.
        cur.execute("ALTER TABLE students ADD COLUMN IF NOT EXISTS pin TEXT")
        cur.execute("ALTER TABLE students ADD COLUMN IF NOT EXISTS pin_attempts INTEGER NOT NULL DEFAULT 0")
        cur.execute("ALTER TABLE students ADD COLUMN IF NOT EXISTS pin_locked_until TEXT")
        cur.execute("ALTER TABLE students ADD COLUMN IF NOT EXISTS pin_is_custom INTEGER NOT NULL DEFAULT 0")
        cur.execute("ALTER TABLE students ADD COLUMN IF NOT EXISTS birth_date TEXT")
        cur.execute("ALTER TABLE students ADD COLUMN IF NOT EXISTS real_belt TEXT")
        cur.execute("ALTER TABLE students ADD COLUMN IF NOT EXISTS phone TEXT")
        cur.execute("ALTER TABLE students ADD COLUMN IF NOT EXISTS guardian_name TEXT")
        cur.execute("ALTER TABLE students ADD COLUMN IF NOT EXISTS guardian_phone TEXT")
        cur.execute("ALTER TABLE students ADD COLUMN IF NOT EXISTS address TEXT")
        cur.close()
        conn.close()
        return

    db = sqlite3.connect(DB_PATH)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            nickname TEXT,
            photo TEXT,
            pin TEXT,
            pin_attempts INTEGER NOT NULL DEFAULT 0,
            pin_locked_until TEXT,
            pin_is_custom INTEGER NOT NULL DEFAULT 0,
            birth_date TEXT,
            real_belt TEXT,
            phone TEXT,
            guardian_name TEXT,
            guardian_phone TEXT,
            address TEXT,
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
    # Migração segura: bancos criados antes destas colunas existirem.
    for stmt in (
        "ALTER TABLE students ADD COLUMN pin TEXT",
        "ALTER TABLE students ADD COLUMN pin_attempts INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE students ADD COLUMN pin_locked_until TEXT",
        "ALTER TABLE students ADD COLUMN pin_is_custom INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE students ADD COLUMN birth_date TEXT",
        "ALTER TABLE students ADD COLUMN real_belt TEXT",
        "ALTER TABLE students ADD COLUMN phone TEXT",
        "ALTER TABLE students ADD COLUMN guardian_name TEXT",
        "ALTER TABLE students ADD COLUMN guardian_phone TEXT",
        "ALTER TABLE students ADD COLUMN address TEXT",
    ):
        try:
            db.execute(stmt)
        except sqlite3.OperationalError:
            pass  # coluna já existe
    db.commit()
    db.close()


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT


def save_student_photo(file_storage, name):
    """Recebe o arquivo de foto enviado, redimensiona e comprime antes de
    salvar (sempre como .jpg), para não pesar o armazenamento. Retorna o
    nome do arquivo salvo, ou None se não havia foto ou o arquivo é inválido."""
    if not file_storage or not file_storage.filename:
        return None
    if not allowed_file(file_storage.filename):
        return None

    try:
        img = Image.open(file_storage.stream)
        img = img.convert("RGB")
    except UnidentifiedImageError:
        return None

    img.thumbnail((MAX_PHOTO_DIMENSION, MAX_PHOTO_DIMENSION), Image.LANCZOS)

    safe_base = secure_filename(name).lower() or "aluno"
    filename = f"{safe_base}-{int(datetime.now().timestamp())}.jpg"
    img.save(
        os.path.join(app.config["UPLOAD_FOLDER"], filename),
        "JPEG",
        quality=PHOTO_JPEG_QUALITY,
        optimize=True,
    )
    return filename


def generate_pin():
    return f"{random.randint(0, 9999):04d}"


def is_student_verified(student_id):
    """Alunos sem PIN definido (cadastro antigo) passam direto, para não
    trancar ninguém fora. Quem tem PIN precisa ter verificado nesta sessão."""
    student = get_student(student_id)
    if not student or not student["pin"]:
        return True
    return student_id in session.get("verified_students", [])


def mark_student_verified(student_id):
    verified = session.get("verified_students", [])
    if student_id not in verified:
        verified.append(student_id)
    session["verified_students"] = verified


def pin_lock_remaining_minutes(student):
    """Minutos restantes de bloqueio por tentativas erradas, ou 0 se livre."""
    locked_until = student["pin_locked_until"]
    if not locked_until:
        return 0
    until = datetime.fromisoformat(locked_until)
    remaining = (until - datetime.now()).total_seconds()
    if remaining <= 0:
        return 0
    return max(1, int(remaining // 60) + 1)


def register_failed_pin(student_id, current_attempts):
    db = get_db()
    attempts = (current_attempts or 0) + 1
    if attempts >= MAX_PIN_ATTEMPTS:
        locked_until = (datetime.now() + timedelta(minutes=LOCKOUT_MINUTES)).isoformat()
        db.execute(
            "UPDATE students SET pin_attempts = 0, pin_locked_until = ? WHERE id = ?",
            (locked_until, student_id),
        )
    else:
        db.execute("UPDATE students SET pin_attempts = ? WHERE id = ?", (attempts, student_id))
    db.commit()
    return attempts


def reset_pin_attempts(student_id):
    db = get_db()
    db.execute(
        "UPDATE students SET pin_attempts = 0, pin_locked_until = NULL WHERE id = ?",
        (student_id,),
    )
    db.commit()


def today_str():
    return date.today().isoformat()


def calculate_age(birth_date_str):
    if not birth_date_str:
        return None
    try:
        b = date.fromisoformat(birth_date_str)
    except ValueError:
        return None
    today = date.today()
    age = today.year - b.year - ((today.month, today.day) < (b.month, b.day))
    return age


def display_name(student):
    return student["nickname"] or student["name"]


def get_active_students():
    db = get_db()
    return db.execute(
        "SELECT * FROM students WHERE active = 1 ORDER BY LOWER(name)"
    ).fetchall()


def get_student(student_id):
    db = get_db()
    return db.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()


def counts_for_student(student_id):
    """Retorna (semana, mes, ano, total_vitalicio) de check-ins APROVADOS."""
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
    return week, month, year, len(rows)


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
    return {
        "is_admin": is_admin(),
        "current_year": date.today().year,
        "AVATAR_COLORS": AVATAR_COLORS,
    }


# --------------------------------------------------------------------------
# Rotas públicas / aluno
# --------------------------------------------------------------------------
@app.route("/")
def index():
    students = get_active_students()
    ranking_year = build_ranking("year")[:3]
    return render_template("index.html", students=students, top3=ranking_year)


def attempt_pin(student, pin):
    """Assume que já checamos que a conta não está bloqueada.
    Retorna (sucesso: bool, tentativas_restantes: int|None)."""
    if pin == student["pin"]:
        reset_pin_attempts(student["id"])
        mark_student_verified(student["id"])
        return True, None
    attempts = register_failed_pin(student["id"], student["pin_attempts"])
    left = MAX_PIN_ATTEMPTS - attempts
    return False, left


@app.route("/aluno/<int:student_id>/entrar", methods=["GET", "POST"])
def aluno_entrar(student_id):
    student = get_student(student_id)
    if not student:
        flash("Aluno não encontrado.", "error")
        return redirect(url_for("index"))

    if is_student_verified(student_id):
        return redirect(url_for("aluno_dashboard", student_id=student_id))

    remaining = pin_lock_remaining_minutes(student)
    if remaining:
        flash(
            f"PIN bloqueado após várias tentativas erradas. Tente de novo em "
            f"{remaining} minuto(s), ou peça ajuda ao professor.",
            "error",
        )
        return render_template("aluno_entrar.html", student=student, locked=True)

    if request.method == "POST":
        pin = request.form.get("pin", "").strip()
        ok, left = attempt_pin(student, pin)
        if ok:
            return redirect(url_for("aluno_dashboard", student_id=student_id))
        if left > 0:
            flash(f"PIN incorreto. Mais {left} tentativa(s) antes do bloqueio temporário.", "error")
        else:
            flash(f"PIN incorreto várias vezes. Bloqueado por {LOCKOUT_MINUTES} minutos.", "error")
            return render_template("aluno_entrar.html", student=student, locked=True)

    return render_template("aluno_entrar.html", student=student, locked=False)


@app.route("/entrar", methods=["POST"])
def entrar_por_nome():
    """Login direto pela home: nome (ou apelido) + PIN, sem precisar tocar
    numa foto — usado pelo formulário de entrada no topo da página inicial."""
    nome_digitado = request.form.get("nome", "").strip()
    pin = request.form.get("pin", "").strip()

    if not nome_digitado:
        flash("Digite seu nome para entrar.", "error")
        return redirect(url_for("index"))

    db = get_db()
    student = db.execute(
        "SELECT * FROM students WHERE active = 1 "
        "AND (LOWER(nickname) = LOWER(?) OR LOWER(name) = LOWER(?)) LIMIT 1",
        (nome_digitado, nome_digitado),
    ).fetchone()

    if not student:
        flash("Não encontramos esse nome. Confira a grafia ou peça ajuda ao professor.", "error")
        return redirect(url_for("index"))

    if not student["pin"]:
        # Alunos antigos sem PIN cadastrado continuam entrando direto.
        mark_student_verified(student["id"])
        return redirect(url_for("aluno_dashboard", student_id=student["id"]))

    remaining = pin_lock_remaining_minutes(student)
    if remaining:
        flash(
            f"PIN bloqueado após várias tentativas erradas. Tente de novo em "
            f"{remaining} minuto(s), ou peça ajuda ao professor.",
            "error",
        )
        return redirect(url_for("index"))

    ok, left = attempt_pin(student, pin)
    if ok:
        return redirect(url_for("aluno_dashboard", student_id=student["id"]))
    if left > 0:
        flash(f"PIN incorreto. Mais {left} tentativa(s) antes do bloqueio temporário.", "error")
    else:
        flash(f"PIN incorreto várias vezes. Bloqueado por {LOCKOUT_MINUTES} minutos.", "error")
    return redirect(url_for("index"))


@app.route("/aluno/<int:student_id>")
def aluno_dashboard(student_id):
    student = get_student(student_id)
    if not student:
        flash("Aluno não encontrado.", "error")
        return redirect(url_for("index"))

    if not is_student_verified(student_id):
        return redirect(url_for("aluno_entrar", student_id=student_id))

    week, month, year, total = counts_for_student(student_id)
    belt = belt_info(total)

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
        total=total,
        belt=belt,
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

    if not is_student_verified(student_id):
        return redirect(url_for("aluno_entrar", student_id=student_id))

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


@app.route("/aluno/<int:student_id>/pin", methods=["POST"])
def alterar_pin(student_id):
    student = get_student(student_id)
    if not student:
        flash("Aluno não encontrado.", "error")
        return redirect(url_for("index"))

    if not is_student_verified(student_id):
        return redirect(url_for("aluno_entrar", student_id=student_id))

    novo_pin = request.form.get("novo_pin", "").strip()
    confirmar_pin = request.form.get("confirmar_pin", "").strip()

    if not (novo_pin.isdigit() and len(novo_pin) == 4):
        flash("O novo PIN precisa ter exatamente 4 números.", "error")
    elif novo_pin != confirmar_pin:
        flash("Os dois PINs digitados não são iguais. Tente de novo.", "error")
    else:
        db = get_db()
        db.execute(
            "UPDATE students SET pin = ?, pin_is_custom = 1, pin_attempts = 0, pin_locked_until = NULL WHERE id = ?",
            (novo_pin, student_id),
        )
        db.commit()
        flash("PIN atualizado! A partir de agora só você sabe esse número — nem o professor consegue ver.", "success")

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


@app.route("/admin/ranking/exportar")
def exportar_ranking():
    if not require_admin():
        return redirect(url_for("admin_login"))

    period = request.args.get("periodo", "month")
    if period not in ("week", "month", "year"):
        period = "month"
    labels = {"week": "Semana", "month": "Mês", "year": "Ano"}
    data = build_ranking(period)

    wb = Workbook()
    ws = wb.active
    ws.title = "Ranking"
    ws.append(["Posição", "Aluno", "Treinos confirmados"])
    header_fill = PatternFill("solid", fgColor="11141B")
    header_font = Font(bold=True, color="FFFFFF")
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")

    for i, r in enumerate(data, start=1):
        ws.append([i, r["name"], r["count"]])

    ws.column_dimensions["A"].width = 10
    ws.column_dimensions["B"].width = 30
    ws.column_dimensions["C"].width = 22

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    label = labels.get(period, period)
    filename = f"ranking-elite-hapkido-{label.lower()}-{today_str()}.xlsx"
    return send_file(
        buffer,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


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

    total_alunos = db.execute(
        "SELECT COUNT(*) AS total FROM students WHERE active = 1"
    ).fetchone()["total"]

    return render_template(
        "admin_dashboard.html",
        pendentes=pendentes,
        recentes=recentes,
        total_alunos=total_alunos,
        using_postgres=USE_POSTGRES,
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
    students = db.execute(
        "SELECT * FROM students ORDER BY active DESC, LOWER(name)"
    ).fetchall()
    return render_template("admin_alunos.html", students=students)


@app.route("/admin/alunos/<int:student_id>/editar", methods=["GET", "POST"])
def admin_editar_aluno(student_id):
    if not require_admin():
        return redirect(url_for("admin_login"))

    student = get_student(student_id)
    if not student:
        flash("Aluno não encontrado.", "error")
        return redirect(url_for("admin_alunos"))

    if request.method == "POST":
        birth_date = request.form.get("birth_date", "").strip()
        real_belt = request.form.get("real_belt", "").strip()
        phone = request.form.get("phone", "").strip()
        guardian_name = request.form.get("guardian_name", "").strip()
        guardian_phone = request.form.get("guardian_phone", "").strip()
        address = request.form.get("address", "").strip()

        if birth_date:
            try:
                date.fromisoformat(birth_date)
            except ValueError:
                flash("Data de nascimento inválida.", "error")
                return redirect(url_for("admin_editar_aluno", student_id=student_id))

        db = get_db()
        db.execute(
            "UPDATE students SET birth_date = ?, real_belt = ?, phone = ?, "
            "guardian_name = ?, guardian_phone = ?, address = ? WHERE id = ?",
            (
                birth_date or None,
                real_belt or None,
                phone or None,
                guardian_name or None,
                guardian_phone or None,
                address or None,
                student_id,
            ),
        )
        db.commit()
        flash("Ficha do aluno atualizada!", "success")
        return redirect(url_for("admin_alunos"))

    age = calculate_age(student["birth_date"])
    return render_template("admin_editar_aluno.html", student=student, age=age)


@app.route("/admin/alunos/novo", methods=["POST"])
def admin_novo_aluno():
    if not require_admin():
        return redirect(url_for("admin_login"))

    name = request.form.get("name", "").strip()
    nickname = request.form.get("nickname", "").strip()
    pin = request.form.get("pin", "").strip()
    if not name:
        flash("O nome do aluno é obrigatório.", "error")
        return redirect(url_for("admin_alunos"))

    if pin and (not pin.isdigit() or len(pin) != 4):
        flash("O PIN precisa ter exatamente 4 números. Deixe em branco para gerar automaticamente.", "error")
        return redirect(url_for("admin_alunos"))
    if not pin:
        pin = generate_pin()

    file = request.files.get("photo")
    photo_filename = save_student_photo(file, name)
    if file and file.filename and photo_filename is None:
        flash("Não consegui processar essa foto (formato inválido). Aluno cadastrado sem foto.", "info")

    db = get_db()
    db.execute(
        "INSERT INTO students (name, nickname, photo, pin, active, created_at) VALUES (?, ?, ?, ?, 1, ?)",
        (name, nickname or None, photo_filename, pin, datetime.now().isoformat()),
    )
    db.commit()
    flash(f"Aluno {name} cadastrado! PIN de acesso: {pin} (repasse esse número a ele).", "success")
    return redirect(url_for("admin_alunos"))


@app.route("/admin/alunos/<int:student_id>/novo-pin", methods=["POST"])
def admin_novo_pin(student_id):
    if not require_admin():
        return redirect(url_for("admin_login"))
    student = get_student(student_id)
    if not student:
        flash("Aluno não encontrado.", "error")
        return redirect(url_for("admin_alunos"))

    new_pin = generate_pin()
    db = get_db()
    db.execute(
        "UPDATE students SET pin = ?, pin_is_custom = 0, pin_attempts = 0, pin_locked_until = NULL WHERE id = ?",
        (new_pin, student_id),
    )
    db.commit()
    # Invalida a verificação de sessão anterior para esse aluno, se houver.
    verified = session.get("verified_students", [])
    if student_id in verified:
        verified.remove(student_id)
        session["verified_students"] = verified
    flash(f"Novo PIN de {student['nickname'] or student['name']}: {new_pin}", "success")
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
    except IntegrityError:
        db.rollback()
        flash(f"O ano {year} já foi fechado anteriormente.", "error")

    return redirect(url_for("admin_campeoes"))


# Cria/atualiza as tabelas do banco assim que o módulo é carregado — precisa
# rodar tanto com "python app.py" (local) quanto com "gunicorn app:app"
# (produção), já que o gunicorn nunca executa o bloco abaixo.
init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
