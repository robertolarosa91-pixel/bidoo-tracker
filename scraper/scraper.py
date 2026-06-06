"""
Bidoo.it Scraper Core
"""
import requests
import sqlite3
import logging
import re
from datetime import datetime
from bs4 import BeautifulSoup
from dataclasses import dataclass, asdict

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_URL = "https://it.bidoo.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "it-IT,it;q=0.9",
}

DB_PATH = "data/bidoo.db"

@dataclass
class Auction:
    id: str
    title: str
    category: str
    current_price: float
    retail_price: float
    bids_count: int
    time_left: str
    image_url: str
    url: str
    is_live: bool
    scraped_at: str

@dataclass
class ClosedAuction:
    id: str
    title: str
    final_price: float
    retail_price: float
    bids_count: int
    winner: str
    image_url: str
    url: str
    closed_at: str
    scraped_at: str

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS auctions (
            id TEXT, title TEXT, category TEXT,
            current_price REAL, retail_price REAL,
            bids_count INTEGER, time_left TEXT,
            image_url TEXT, url TEXT,
            is_live INTEGER, scraped_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS closed_auctions (
            id TEXT PRIMARY KEY,
            title TEXT,
            final_price REAL,
            retail_price REAL,
            bids_count INTEGER,
            winner TEXT,
            image_url TEXT,
            url TEXT,
            closed_at TEXT,
            scraped_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            auction_id TEXT, keyword TEXT,
            max_price REAL, chat_id TEXT,
            active INTEGER DEFAULT 1, created_at TEXT
        )
    """)
    conn.commit()
    conn.close()
    logger.info("Database inizializzato.")

def save_auctions(auctions):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    for a in auctions:
        c.execute("INSERT INTO auctions VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
            a.id, a.title, a.category, a.current_price,
            a.retail_price, a.bids_count, a.time_left,
            a.image_url, a.url, int(a.is_live), a.scraped_at
        ))
    conn.commit()
    conn.close()

def save_closed_auctions(auctions):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    for a in auctions:
        c.execute("""
            INSERT OR IGNORE INTO closed_auctions VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (
            a.id, a.title, a.final_price, a.retail_price,
            a.bids_count, a.winner, a.image_url,
            a.url, a.closed_at, a.scraped_at
        ))
    saved = c.rowcount
    conn.commit()
    conn.close()
    return saved

def get_latest_auctions(limit=50):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""
        SELECT * FROM auctions
        WHERE scraped_at = (SELECT MAX(scraped_at) FROM auctions)
        ORDER BY bids_count DESC LIMIT ?
    """, (limit,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

def get_stats():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM auctions WHERE scraped_at=(SELECT MAX(scraped_at) FROM auctions)")
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM auctions WHERE is_live=1 AND scraped_at=(SELECT MAX(scraped_at) FROM auctions)")
    live = c.fetchone()[0]
    c.execute("SELECT category, COUNT(*) FROM auctions WHERE scraped_at=(SELECT MAX(scraped_at) FROM auctions) GROUP BY category ORDER BY COUNT(*) DESC")
    categories = c.fetchall()
    c.execute("SELECT AVG(current_price) FROM auctions WHERE scraped_at=(SELECT MAX(scraped_at) FROM auctions)")
    avg = c.fetchone()[0] or 0
    c.execute("SELECT COUNT(*) FROM closed_auctions")
    total_closed = c.fetchone()[0]
    conn.close()
    return {
        "total": total, "live": live,
        "categories": [{"name": r[0], "count": r[1]} for r in categories],
        "avg_price": round(avg, 2),
        "total_closed": total_closed,
        "last_update": datetime.now().strftime("%H:%M:%S")
    }

def search_product_history(keyword):
    """Cerca tutte le aste chiuse per un prodotto e restituisce statistiche."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""
        SELECT * FROM closed_auctions
        WHERE LOWER(title) LIKE ?
        ORDER BY scraped_at DESC
    """, (f"%{keyword.lower()}%",))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()

    if not rows:
        return None

    prices = [r["final_price"] for r in rows]
    bids = [r["bids_count"] for r in rows]

    return {
        "keyword": keyword,
        "total_auctions": len(rows),
        "avg_price": round(sum(prices) / len(prices), 2),
        "min_price": min(prices),
        "max_price": max(prices),
        "avg_bids": round(sum(bids) / len(bids), 1),
        "min_bids": min(bids),
        "max_bids": max(bids),
        "auctions": rows
    }

def scrape_closed_auctions():
    """Scrapa it.bidoo.com/closed per le aste chiuse recenti."""
    scraped_at = datetime.now().isoformat()
    auctions = []

    try:
        resp = requests.get(f"{BASE_URL}/closed", headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Ispeziona DevTools per i selettori esatti — questi sono generici
        items = soup.select(".auction-closed, .closed-item, [data-auction-id], .auction-item")

        if not items:
            logger.warning("Nessun item trovato in /closed — controlla i selettori CSS")
            return _demo_closed_data(scraped_at)

        for item in items:
            try:
                def text(el): return el.get_text(strip=True) if el else ""
                def price(el):
                    try: return float(text(el).replace("€","").replace(",",".").strip())
                    except: return 0.0

                title_el = item.select_one(".title, h2, h3, .product-name")
                price_el = item.select_one(".price, .final-price, .winning-price")
                retail_el = item.select_one(".retail, .original-price")
                bids_el = item.select_one(".bids, .bid-count, .puntate")
                winner_el = item.select_one(".winner, .username, .vincitore")
                img_el = item.select_one("img")
                link_el = item.select_one("a")
                time_el = item.select_one(".time, .closed-at, .quando")

                auction_id = item.get("data-id", item.get("id", f"closed_{len(auctions)}"))

                auctions.append(ClosedAuction(
                    id=str(auction_id),
                    title=text(title_el) or "N/A",
                    final_price=price(price_el),
                    retail_price=price(retail_el),
                    bids_count=int(re.sub(r"[^\d]", "", text(bids_el)) or 0),
                    winner=text(winner_el) or "?",
                    image_url=img_el.get("src","") if img_el else "",
                    url=(BASE_URL + link_el.get("href","")) if link_el else "",
                    closed_at=text(time_el) or scraped_at,
                    scraped_at=scraped_at
                ))
            except Exception as e:
                logger.error(f"Errore parsing item: {e}")

    except Exception as e:
        logger.error(f"Errore scraping /closed: {e}")
        return _demo_closed_data(scraped_at)

    logger.info(f"Trovate {len(auctions)} aste chiuse.")
    return auctions

def scrape_auctions():
    scraped_at = datetime.now().isoformat()
    return _demo_data(scraped_at)

def _demo_closed_data(scraped_at):
    import random
    products = [
        ("PlayStation 5", 549, 320), ("iPhone 15 Pro", 1299, 480),
        ("MacBook Air M3", 1299, 510), ("PlayStation 5", 549, 290),
        ("AirPods Pro 2", 249, 180), ("iPhone 15 Pro", 1299, 520),
        ("Nintendo Switch OLED", 349, 220), ("PlayStation 5", 549, 350),
        ("Smart TV Samsung 65", 799, 410), ("AirPods Pro 2", 249, 160),
        ("MacBook Air M3", 1299, 490), ("DJI Mini 4 Pro", 759, 380),
        ("PlayStation 5", 549, 270), ("iPhone 15 Pro", 1299, 440),
    ]
    winners = ["mario92", "luca_x", "gianna77", "franco_b", "sara_m", "ale99"]
    result = []
    for i, (name, retail, bids) in enumerate(products):
        price = round(random.uniform(0.50, retail * 0.08), 2)
        result.append(ClosedAuction(
            id=f"closed_demo_{i}",
            title=name,
            final_price=price,
            retail_price=retail,
            bids_count=bids + random.randint(-30, 30),
            winner=random.choice(winners),
            image_url="",
            url=f"https://it.bidoo.com/auction/{i}",
            closed_at=f"2026-06-0{random.randint(1,6)}",
            scraped_at=scraped_at
        ))
    return result

def _demo_data(scraped_at):
    import random
    categories = ["Elettronica", "Casa", "Sport", "Moda", "Auto", "Giochi"]
    products = [
        ("iPhone 15 Pro 256GB", 1299), ("PlayStation 5", 549),
        ("MacBook Air M3", 1299), ("Smart TV Samsung 65\"", 799),
        ("AirPods Pro 2", 249), ("Nintendo Switch OLED", 349),
    ]
    result = []
    for i, (name, retail) in enumerate(products):
        price = round(random.uniform(0.05, retail * 0.15), 2)
        result.append(Auction(
            id=f"demo_{i}", title=name,
            category=random.choice(categories),
            current_price=price, retail_price=retail,
            bids_count=random.randint(10, 500),
            time_left=random.choice(["LIVE", "1h 20m", "3h 45m"]),
            image_url="",
            url=f"https://it.bidoo.com/auction/{i}",
            is_live=random.choice([True, False]),
            scraped_at=scraped_at
        ))
    return result

def check_alerts(auctions):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM alerts WHERE active=1")
    alerts = [dict(r) for r in c.fetchall()]
    conn.close()
    triggered = []
    for alert in alerts:
        for auction in auctions:
            keyword_match = alert["keyword"] and alert["keyword"].lower() in auction.title.lower()
            price_match = alert["max_price"] and auction.current_price <= alert["max_price"]
            if keyword_match or price_match:
                triggered.append({"chat_id": alert["chat_id"], "auction": asdict(auction), "alert": alert})
    return triggered

if __name__ == "__main__":
    import os
    os.makedirs("data", exist_ok=True)
    init_db()
    closed = scrape_closed_auctions()
    save_closed_auctions(closed)
    print(f"Salvate {len(closed)} aste chiuse")
    result = search_product_history("PlayStation")
    if result:
        print(f"\nPS5: {result['total_auctions']} aste")
        print(f"Prezzo medio: €{result['avg_price']}")
        print(f"Puntate medie: {result['avg_bids']}")