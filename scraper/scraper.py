"""
Bidoo.it Scraper Core
Raccoglie dati sulle aste: prezzi, timer, offerte, categorie
"""

import requests
import sqlite3
import json
import time
import logging
from datetime import datetime
from bs4 import BeautifulSoup
from dataclasses import dataclass, asdict
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_URL = "https://www.bidoo.com/it"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "it-IT,it;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

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

DB_PATH = "data/bidoo.db"

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
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            auction_id TEXT, keyword TEXT,
            max_price REAL, chat_id TEXT,
            active INTEGER DEFAULT 1, created_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS won_auctions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            auction_id TEXT, title TEXT,
            final_price REAL, retail_price REAL,
            savings REAL, winner TEXT, won_at TEXT
        )
    """)
    conn.commit()
    conn.close()

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
    c.execute("SELECT COUNT(*) FROM auctions WHERE scraped_at = (SELECT MAX(scraped_at) FROM auctions)")
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM auctions WHERE is_live=1 AND scraped_at = (SELECT MAX(scraped_at) FROM auctions)")
    live = c.fetchone()[0]
    c.execute("SELECT category, COUNT(*) as cnt FROM auctions WHERE scraped_at = (SELECT MAX(scraped_at) FROM auctions) GROUP BY category ORDER BY cnt DESC")
    categories = c.fetchall()
    c.execute("SELECT AVG(current_price) FROM auctions WHERE scraped_at = (SELECT MAX(scraped_at) FROM auctions)")
    avg_price = c.fetchone()[0] or 0
    conn.close()
    return {
        "total": total, "live": live,
        "categories": [{"name": r[0], "count": r[1]} for r in categories],
        "avg_price": round(avg_price, 2),
        "last_update": datetime.now().strftime("%H:%M:%S")
    }

def scrape_auctions():
    auctions = []
    scraped_at = datetime.now().isoformat()
    try:
        resp = requests.get(f"{BASE_URL}/aste/", headers=HEADERS, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        cards = soup.select(".auction-item, .product-card, [data-auction-id]")
        if not cards:
            return _demo_data(scraped_at)
        for card in cards:
            try:
                def text(el): return el.get_text(strip=True) if el else ""
                def price(el):
                    try: return float(text(el).replace("€","").replace(",",".").strip())
                    except: return 0.0
                auction_id = card.get("data-auction-id", card.get("id", "unknown"))
                title = card.select_one(".title, .auction-title, h2, h3")
                price_el = card.select_one(".price, .current-price, [data-price]")
                retail_el = card.select_one(".retail, .original-price, .msrp")
                bids_el = card.select_one(".bids, .bid-count, [data-bids]")
                timer_el = card.select_one(".timer, .countdown, [data-timer]")
                img_el = card.select_one("img")
                link_el = card.select_one("a")
                category_el = card.select_one(".category, .cat")
                auctions.append(Auction(
                    id=str(auction_id), title=text(title) or "N/A",
                    category=text(category_el) or "Generale",
                    current_price=price(price_el), retail_price=price(retail_el),
                    bids_count=int(text(bids_el).replace("offerte","").strip() or 0),
                    time_left=text(timer_el) or "?",
                    image_url=img_el.get("src","") if img_el else "",
                    url=link_el.get("href","") if link_el else "",
                    is_live="live" in text(timer_el).lower(),
                    scraped_at=scraped_at
                ))
            except Exception as e:
                logger.error(f"Errore card: {e}")
    except Exception as e:
        logger.error(f"Errore HTTP: {e}")
        return _demo_data(scraped_at)
    return auctions

def _demo_data(scraped_at):
    import random
    categories = ["Elettronica", "Casa", "Sport", "Moda", "Auto", "Giochi"]
    products = [
        ("iPhone 15 Pro 256GB", 1299), ("PlayStation 5", 549),
        ("MacBook Air M3", 1299), ("Smart TV Samsung 65\"", 799),
        ("AirPods Pro 2", 249), ("Nintendo Switch OLED", 349),
        ("DJI Mini 4 Pro", 759), ("Robot Aspirapolvere", 299),
        ("Bici Elettrica", 1499), ("Oculus Quest 3", 549),
    ]
    result = []
    for i, (name, retail) in enumerate(products):
        price = round(random.uniform(0.05, retail * 0.15), 2)
        result.append(Auction(
            id=f"demo_{i}", title=name,
            category=random.choice(categories),
            current_price=price, retail_price=retail,
            bids_count=random.randint(10, 500),
            time_left=random.choice(["LIVE", "1h 20m", "3h 45m", "12h"]),
            image_url="",
            url=f"https://www.bidoo.com/it/asta/{i}",
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
    init_db()
    aste = scrape_auctions()
    save_auctions(aste)
    print(get_stats())
