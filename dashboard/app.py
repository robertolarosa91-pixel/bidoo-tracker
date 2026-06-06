import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from flask import Flask, render_template, jsonify
from scraper.scraper import get_latest_auctions, get_stats, init_db, DB_PATH
import sqlite3

app = Flask(__name__)

def get_history(limit=200):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""
        SELECT title, category, current_price, retail_price,
               bids_count, time_left, is_live, url, scraped_at
        FROM auctions ORDER BY scraped_at DESC LIMIT ?
    """, (limit,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

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

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/stats")
def api_stats():
    return jsonify(get_stats())

@app.route("/api/auctions")
def api_auctions():
    return jsonify(get_latest_auctions(limit=50))

@app.route("/api/history")
def api_history():
    return jsonify(get_history())

@app.route("/api/price-history")
def api_price_history():
    return jsonify(get_price_history())

if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)
