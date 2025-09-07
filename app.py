from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user
import sqlite3
from datetime import datetime, timedelta
import pandas as pd
from fpdf import FPDF
import urllib.parse

app = Flask(__name__)
app.secret_key = "sua_chave_secreta_aqui"

# ---------------------------
# Login
# ---------------------------
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

# Usuário fixo para protetor simples
USUARIO = {"username": "admin", "password": "123456"}

class User(UserMixin):
    def __init__(self, id):
        self.id = id

@login_manager.user_loader
def load_user(user_id):
    return User(user_id)

# ---------------------------
# Utilidades
# ---------------------------
DB = "financas.db"

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def formatar_valor(valor):
    try:
        return f"{float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except:
        return valor

def formatar_data(data):
    try:
        dt = datetime.strptime(data, "%Y-%m-%d")
        return dt.strftime("%d/%m/%Y")
    except:
        return data

# ---------------------------
# Rotas
# ---------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if username == USUARIO["username"] and password == USUARIO["password"]:
            user = User(1)
            login_user(user)
            return redirect(url_for("dashboard"))
        else:
            flash("Usuário ou senha incorretos", "danger")
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))

@app.route("/")
@login_required
def dashboard():
    conn = get_db()
    c = conn.cursor()

    # Totais
    c.execute("SELECT SUM(valor) FROM transacoes WHERE tipo='Entrada' AND status='Pendente'")
    total_receber = c.fetchone()[0] or 0.0
    c.execute("SELECT SUM(valor) FROM transacoes WHERE tipo='Saída' AND status='Pendente'")
    total_pagar = c.fetchone()[0] or 0.0
    saldo = total_receber - total_pagar

    # Transações
    c.execute("SELECT * FROM transacoes ORDER BY data_vencimento DESC")
    transacoes = c.fetchall()

    # Contas a pagar e receber
    c.execute("SELECT * FROM transacoes WHERE tipo='Saída' AND status='Pendente'")
    contas_pagar = c.fetchall()
    c.execute("SELECT * FROM transacoes WHERE tipo='Entrada' AND status='Pendente'")
    contas_receber = c.fetchall()

    # ---------------------------
    # Notificações de vencimento próximo
    # ---------------------------
    hoje = datetime.now().date()
    cinco_dias = hoje + timedelta(days=5)

    # Contas a pagar próximas
    avisos_pagar = []
    for t in contas_pagar:
        vencimento = datetime.strptime(t["data_vencimento"], "%Y-%m-%d").date()
        if hoje <= vencimento <= cinco_dias:
            avisos_pagar.append(f"{t['descricao']} ({t['entidade']}) - R$ {formatar_valor(t['valor'])} vence em {vencimento.strftime('%d/%m/%Y')}")
    if avisos_pagar:
        flash("💡 Contas a pagar próximas: " + "; ".join(avisos_pagar), "warning")

    # Contas a receber próximas
    avisos_receber = []
    for t in contas_receber:
        vencimento = datetime.strptime(t["data_vencimento"], "%Y-%m-%d").date()
        if hoje <= vencimento <= cinco_dias:
            avisos_receber.append(f"{t['descricao']} ({t['entidade']}) - R$ {formatar_valor(t['valor'])} vence em {vencimento.strftime('%d/%m/%Y')}")
    if avisos_receber:
        flash("💡 Contas a receber próximas: " + "; ".join(avisos_receber), "success")

    return render_template(
        "dashboard.html",
        total_receber=formatar_valor(total_receber),
        total_pagar=formatar_valor(total_pagar),
        saldo=formatar_valor(saldo),
        transacoes=transacoes,
        contas_pagar=contas_pagar,
        contas_receber=contas_receber,
        formatar_valor=formatar_valor,
        formatar_data=formatar_data
    )

# ---------------------------
# Transações
# ---------------------------
@app.route("/transacao/add", methods=["GET", "POST"])
@login_required
def add_transacao():
    conn = get_db()
    c = conn.cursor()
    if request.method == "POST":
        tipo = request.form["tipo"]
        entidade = request.form["entidade"].strip().title()
        entidade_tipo = request.form["natureza"]
        categoria = request.form["categoria"] or "Outros"
        descricao = request.form["descricao"]
        valor = float(request.form["valor"].replace('.', '').replace(',', '.'))
        data_vencimento = request.form["data_vencimento"]
        status = request.form["status"]

        # Inserir entidade se não existir
        table = {"Cliente":"clientes","Colaborador":"colaboradores","Despesa Geral":"despesas_fixas"}[entidade_tipo]
        c.execute(f"INSERT OR IGNORE INTO {table}(nome) VALUES (?)", (entidade,))

        c.execute("""INSERT INTO transacoes (tipo, entidade, entidade_tipo, categoria, descricao, valor, data_vencimento, status)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                  (tipo, entidade, entidade_tipo, categoria, descricao, valor, data_vencimento, status))
        conn.commit()
        flash("Transação adicionada com sucesso!", "success")
        return redirect(url_for("dashboard"))

    # Sugestões
    c.execute("SELECT nome FROM clientes ORDER BY nome")
    clientes = [r[0] for r in c.fetchall()]
    c.execute("SELECT nome FROM colaboradores ORDER BY nome")
    colaboradores = [r[0] for r in c.fetchall()]
    c.execute("SELECT nome FROM despesas_fixas ORDER BY nome")
    despesas = [r[0] for r in c.fetchall()]

    return render_template("transacao_form.html", clientes=clientes, colaboradores=colaboradores, despesas=despesas, transacao=None)

@app.route("/transacao/edit/<int:id>", methods=["GET", "POST"])
@login_required
def edit_transacao(id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM transacoes WHERE id=?", (id,))
    transacao = c.fetchone()
    if not transacao:
        flash("Transação não encontrada!", "danger")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        tipo = request.form["tipo"]
        entidade = request.form["entidade"].strip().title()
        entidade_tipo = request.form["natureza"]
        categoria = request.form["categoria"] or "Outros"
        descricao = request.form["descricao"]
        valor = float(request.form["valor"].replace('.', '').replace(',', '.'))
        data_vencimento = request.form["data_vencimento"]
        status = request.form["status"]

        # Atualiza entidade se necessário
        table = {"Cliente":"clientes","Colaborador":"colaboradores","Despesa Geral":"despesas_fixas"}[entidade_tipo]
        c.execute(f"INSERT OR IGNORE INTO {table}(nome) VALUES (?)", (entidade,))

        c.execute("""UPDATE transacoes SET tipo=?, entidade=?, entidade_tipo=?, categoria=?, descricao=?, valor=?, data_vencimento=?, status=?
                     WHERE id=?""",
                  (tipo, entidade, entidade_tipo, categoria, descricao, valor, data_vencimento, status, id))
        conn.commit()
        flash("Transação atualizada com sucesso!", "success")
        return redirect(url_for("dashboard"))

    # Sugestões
    c.execute("SELECT nome FROM clientes ORDER BY nome")
    clientes = [r[0] for r in c.fetchall()]
    c.execute("SELECT nome FROM colaboradores ORDER BY nome")
    colaboradores = [r[0] for r in c.fetchall()]
    c.execute("SELECT nome FROM despesas_fixas ORDER BY nome")
    despesas = [r[0] for r in c.fetchall()]

    return render_template("transacao_form.html", clientes=clientes, colaboradores=colaboradores, despesas=despesas, transacao=transacao)

@app.route("/transacao/delete/<int:id>")
@login_required
def delete_transacao(id):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM transacoes WHERE id=?", (id,))
    conn.commit()
    flash("Transação excluída com sucesso!", "success")
    return redirect(url_for("dashboard"))

@app.route("/transacao/pdf/<int:id>")
@login_required
def transacao_pdf(id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM transacoes WHERE id=?", (id,))
    t = c.fetchone()
    if not t:
        flash("Transação não encontrada!", "danger")
        return redirect(url_for("dashboard"))

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt=f"Recibo - {t['tipo']}", ln=True, align='C')
    pdf.ln(10)
    for key in ["entidade", "categoria", "descricao", "valor", "data_vencimento", "status"]:
        valor = t[key]
        if key == "valor":
            valor = formatar_valor(valor)
        elif key == "data_vencimento":
            valor = formatar_data(valor)
        pdf.cell(0, 10, txt=f"{key.capitalize()}: {valor}", ln=True)
    filename = f"recibo_{id}.pdf"
    pdf.output(filename)
    return send_file(filename, as_attachment=True)

@app.route("/transacao/whatsapp/<int:id>")
@login_required
def transacao_whatsapp(id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM transacoes WHERE id=?", (id,))
    t = c.fetchone()
    if not t:
        flash("Transação não encontrada!", "danger")
        return redirect(url_for("dashboard"))

    # Dados da empresa
    empresa = {
        "nome": "Aura Soluções em Mobiliários Planejados",
        "telefone": "(11) 98765-4321",
        "email": "aura.moveisplanejados225@gmail.com",
        "instagram": "@aura.moveisplanejados"
    }

    agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    # Mensagem profissional e visual
    texto = (
        f"🔔 *Aviso de Transação - {empresa['nome']}*\n\n"
        f"👤 *Cliente / Entidade:* {t['entidade']}\n"
        f"💳 *Transação:* {t['descricao']}\n"
        f"💰 *Valor:* R$ {formatar_valor(t['valor'])}\n"
        f"🗂 *Categoria:* {t['categoria']}\n"
        f"📅 *Vencimento:* {formatar_data(t['data_vencimento'])}\n"
        f"✅ *Status:* {t['status']}\n"
        f"🕒 *Emitido em:* {agora}\n\n"
        f"Esta mensagem foi gerada automaticamente pelo *AuraTech*, garantindo tecnologia, precisão e profissionalismo.\n\n"
        f"📞 {empresa['telefone']} | ✉ {empresa['email']} | 📸 {empresa['instagram']}"
    )

    link = f"https://api.whatsapp.com/send?text={urllib.parse.quote(texto)}"
    return redirect(link)

@app.route("/export/csv")
@login_required
def export_csv():
    conn = get_db()
    df = pd.read_sql_query("SELECT * FROM transacoes", conn)
    filename = "transacoes.csv"
    df.to_csv(filename, index=False, sep=";")
    return send_file(filename, as_attachment=True)

# ---------------------------
# Inicialização
# ---------------------------
if __name__ == "__main__":
    conn = get_db()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS transacoes(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tipo TEXT,
                    entidade TEXT,
                    entidade_tipo TEXT,
                    categoria TEXT,
                    descricao TEXT,
                    valor REAL,
                    data_vencimento TEXT,
                    status TEXT
                )""")
    c.execute("CREATE TABLE IF NOT EXISTS clientes(nome TEXT PRIMARY KEY)")
    c.execute("CREATE TABLE IF NOT EXISTS colaboradores(nome TEXT PRIMARY KEY)")
    c.execute("CREATE TABLE IF NOT EXISTS despesas_fixas(nome TEXT PRIMARY KEY)")
    conn.commit()
    conn.close()

    app.run(debug=True)
