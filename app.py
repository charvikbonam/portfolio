import os, sqlite3, requests
from functools import wraps
from datetime import datetime
from flask import (Flask, render_template, request, jsonify, redirect,
                   url_for, session, flash, abort)
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ADMIN_USER = os.getenv("ADMIN_USER", "komal")
ADMIN_PASS = os.getenv("ADMIN_PASS", "admin")
DB = os.path.join(os.path.dirname(__file__), "portfolio.db")

CATEGORIES = {
    "articles":    {"title": "Articles",           "icon": "📝", "desc": "Long-form articles and editorial features."},
    "blogs":       {"title": "Blogs",              "icon": "✍️", "desc": "Brand blogs, personal essays, guest posts."},
    "meta-ads":    {"title": "Meta Ad Content",    "icon": "📢", "desc": "Facebook & Instagram ad copy that converts."},
    "campaigns":   {"title": "Ad Campaigns",       "icon": "🎯", "desc": "End-to-end campaign strategy and execution."},
    "shortform":   {"title": "Short-form Content", "icon": "🎬", "desc": "Reels, Shorts and TikTok scripts."},
    "static-ads":  {"title": "Static Ads",         "icon": "🖼️", "desc": "Design-ready ad copy for static creatives."},
    "newsletters": {"title": "Newsletters",        "icon": "📧", "desc": "Emails people actually open."},
}

@app.context_processor
def inject_globals():
    return {"categories": CATEGORIES}

def get_db():
    conn = sqlite3.connect(DB); conn.row_factory = sqlite3.Row; return conn

def init_db():
    with get_db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL, title TEXT NOT NULL, client TEXT,
            summary TEXT, body TEXT, link TEXT, created_at TEXT NOT NULL)""")
init_db()

def send_telegram(text):
    if not BOT_TOKEN or not CHAT_ID: return False
    try:
        r = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}, timeout=10)
        return r.ok and r.json().get("ok", False)
    except Exception as e:
        print(f"[telegram] {e}"); return False

def login_required(f):
    @wraps(f)
    def wrapper(*a, **k):
        if not session.get("logged_in"):
            return redirect(url_for("login", next=request.path))
        return f(*a, **k)
    return wrapper

@app.route("/")
def home(): return render_template("index.html")

@app.route("/about")
def about(): return render_template("about.html")

@app.route("/works")
def works():
    with get_db() as conn:
        rows = conn.execute("SELECT category, COUNT(*) as c FROM posts GROUP BY category").fetchall()
    counts = {r["category"]: r["c"] for r in rows}
    return render_template("works.html", counts=counts)

@app.route("/works/<category>")
def work_category(category):
    if category not in CATEGORIES: abort(404)
    with get_db() as conn:
        posts = conn.execute("SELECT * FROM posts WHERE category=? ORDER BY id DESC", (category,)).fetchall()
    return render_template("category.html", cat_key=category, cat=CATEGORIES[category], posts=posts)

@app.route("/works/<category>/<int:post_id>")
def work_post(category, post_id):
    if category not in CATEGORIES: abort(404)
    with get_db() as conn:
        post = conn.execute("SELECT * FROM posts WHERE id=? AND category=?", (post_id, category)).fetchone()
    if not post: abort(404)
    return render_template("post.html", cat_key=category, cat=CATEGORIES[category], post=post)

@app.route("/connect")
def connect(): return render_template("connect.html")

@app.route("/api/contact", methods=["POST"])
def contact():
    d = request.get_json(silent=True) or {}
    n=(d.get("name")or"").strip(); p=(d.get("phone")or"").strip()
    e=(d.get("email")or"").strip(); q=(d.get("query")or"").strip()
    if not n or not p or not q:
        return jsonify(success=False, message="Name, phone, and query required."), 400
    msg = f"📬 *New Contact Form Submission*\n\n👤 *Name:* {n}\n📞 *Phone:* {p}\n📧 *Email:* {e or '—'}\n💬 *Query:* {q}"
    if send_telegram(msg): return jsonify(success=True, message="Delivered.")
    return jsonify(success=False, message="Telegram unreachable."), 500

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u=request.form.get("username","").strip(); pw=request.form.get("password","").strip()
        if u == ADMIN_USER and pw == ADMIN_PASS:
            session["logged_in"]=True; session["user"]=u
            return redirect(request.args.get("next") or url_for("admin"))
        flash("Invalid credentials", "error")
    return render_template("login.html")

@app.route("/logout")
def logout(): session.clear(); return redirect(url_for("login"))

@app.route("/admin")
@login_required
def admin():
    with get_db() as conn:
        posts = conn.execute("SELECT * FROM posts ORDER BY id DESC").fetchall()
    return render_template("admin.html", posts=posts)

@app.route("/admin/new", methods=["GET", "POST"])
@login_required
def admin_new():
    if request.method == "POST":
        d=_post_from_form()
        with get_db() as conn:
            conn.execute("INSERT INTO posts (category,title,client,summary,body,link,created_at) VALUES (?,?,?,?,?,?,?)",
                (d["category"],d["title"],d["client"],d["summary"],d["body"],d["link"],
                 datetime.utcnow().isoformat(timespec="seconds")))
        flash("Post created.", "success"); return redirect(url_for("admin"))
    return render_template("admin_edit.html", post=None)

@app.route("/admin/edit/<int:post_id>", methods=["GET", "POST"])
@login_required
def admin_edit(post_id):
    with get_db() as conn:
        post = conn.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
    if not post: abort(404)
    if request.method == "POST":
        d=_post_from_form()
        with get_db() as conn:
            conn.execute("UPDATE posts SET category=?, title=?, client=?, summary=?, body=?, link=? WHERE id=?",
                (d["category"],d["title"],d["client"],d["summary"],d["body"],d["link"],post_id))
        flash("Post updated.", "success"); return redirect(url_for("admin"))
    return render_template("admin_edit.html", post=post)

@app.route("/admin/delete/<int:post_id>", methods=["POST"])
@login_required
def admin_delete(post_id):
    with get_db() as conn:
        conn.execute("DELETE FROM posts WHERE id=?", (post_id,))
    flash("Post deleted.", "success"); return redirect(url_for("admin"))

def _post_from_form():
    cat=request.form.get("category","").strip()
    if cat not in CATEGORIES: abort(400)
    return {"category":cat, "title":request.form.get("title","").strip(),
            "client":request.form.get("client","").strip(), "summary":request.form.get("summary","").strip(),
            "body":request.form.get("body","").strip(), "link":request.form.get("link","").strip()}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
