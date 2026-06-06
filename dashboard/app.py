import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from flask import Flask, render_template, jsonify, request
from scraper.scraper import (
    get_latest_auctions, get_stats, init_db,
    search_product_history, DB_PATH
)
import sqlite3

app = Flask(__name__)

def get_price_history(limit=50):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT strftime('%H:%M', scraped_at) as ora,
               ROUND(AVG(current_price), 2) as avg_price,
               COUNT(*) as total
        FROM auctions
        GROUP BY strftime('%Y-%m-%d %H:%M', scraped_at)
        ORDER BY scraped_at DESC LIMIT ?
    """, (limit,))
    rows = c.fetchall()
    conn.close()
    return [{"time": r[0], "avg_price": r[1], "total": r[2]} for r in reversed(rows)]

def get_recent_closed(limit=20):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""
        SELECT * FROM closed_auctions
        ORDER BY scraped_at DESC LIMIT ?
    """, (limit,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/stats")
def api_stats():
    return jsonify(get_stats())

@app.route("/api/auctions")
def api_auctions():
    return jsonify(get_latest_auctions(limit=50))

@app.route("/api/price-history")
def api_price_history():
    return jsonify(get_price_history())

@app.route("/api/closed")
def api_closed():
    return jsonify(get_recent_closed())

@app.route("/api/search")
def api_search():
    keyword = request.args.get("q", "").strip()
    if not keyword:
        return jsonify({"error": "Inserisci un prodotto"}), 400
    result = search_product_history(keyword)
    if not result:
        return jsonify({"error": f"Nessuna asta trovata per '{keyword}'"}), 404
    return jsonify(result)

if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)