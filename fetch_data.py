#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""台股資金流量追蹤系統 — 資料抓取管線
資料來源:
  - FinMind API(自選股深度資料、市場總計、指數、股票清單)
  - 證交所 TWSE 開放資料(全市場單日快照:T86 法人、MI_MARGN 融資券、MI_INDEX 行情、BFI82U 法人金額)
  - 櫃買 TPEX 開放資料(全市場單日快照:法人、融資券、行情)
  - 集保 TDCC 股權分散表(週資料)
用法:
  python3 fetch_data.py --backfill   # 首次回補
  python3 fetch_data.py --update     # 每日增量更新(輸出 SUMMARY JSON)
"""
import argparse, csv, datetime as dt, io, json, os, re, sqlite3, sys, threading, time
import urllib.request, urllib.parse, urllib.error
from zoneinfo import ZoneInfo

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "funds.db")
CONFIG = json.load(open(os.path.join(BASE_DIR, "config.json"), encoding="utf-8"))
TPE = ZoneInfo("Asia/Taipei")

def _load_token():
    # 1) 本機 .env(開發用,不進 repo)
    p = os.path.join(BASE_DIR, ".env")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            for line in f:
                if line.startswith("FINMIND_TOKEN="):
                    return line.strip().split("=", 1)[1].strip()
    # 2) repo 內 token 檔(CI 用):優先於環境變數,避免設錯的 secret 蓋掉正確值
    tf = os.path.join(BASE_DIR, "finmind_token.txt")
    if os.path.exists(tf):
        t = open(tf, encoding="utf-8").read().strip()
        if t:
            return t
    # 3) 環境變數 / GitHub secret
    env = os.environ.get("FINMIND_TOKEN")
    if env:
        return env.strip()
    raise RuntimeError("FINMIND_TOKEN 未設定(.env / finmind_token.txt / 環境變數皆無)")

TOKEN = _load_token()
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
      "Accept": "application/json, text/plain, */*"}
SID_RE = re.compile(r"\d{4,6}[A-Z]?$")   # 含 00631L/00632R/00679B 等字尾代號 ETF

# ---------------------------------------------------------------- HTTP helpers
_domain_lock = {}
_domain_last = {}

def _throttle(domain, gap):
    lock = _domain_lock.setdefault(domain, threading.Lock())
    with lock:
        last = _domain_last.get(domain, 0.0)
        wait = last + gap - time.time()
        if wait > 0:
            time.sleep(wait)
        _domain_last[domain] = time.time()

def http_json(url, headers=None, tries=3, timeout=75, gap=1.0):
    domain = urllib.parse.urlparse(url).netloc
    h = dict(UA)
    if headers:
        h.update(headers)
    err = None
    for i in range(tries):
        _throttle(domain, gap)
        try:
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            body = b""
            try:
                body = e.read()
            except Exception:
                pass
            if e.code in (402, 429):   # FinMind rate limit
                log(f"  rate-limited ({e.code}), sleep 70s ...")
                time.sleep(70)
                err = e
                continue
            err = RuntimeError(f"HTTP {e.code} {body[:150]!r}")
            time.sleep(4 * (i + 1))
        except Exception as e:
            err = e
            time.sleep(4 * (i + 1))
    raise RuntimeError(f"GET failed {url} -> {err}")

def fm(dataset, **params):
    """FinMind v4 data API"""
    q = {"dataset": dataset}
    q.update({k: v for k, v in params.items() if v is not None})
    url = "https://api.finmindtrade.com/api/v4/data?" + urllib.parse.urlencode(q)
    body = http_json(url, headers={"Authorization": "Bearer " + TOKEN}, gap=0.35)
    return body.get("data") or []

def log(msg):
    print(f"[{dt.datetime.now(TPE).strftime('%H:%M:%S')}] {msg}", flush=True)

def num(s):
    """字串轉數值;'--'、'---'、''、'除息' 等 → None"""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    s = re.sub(r"<[^>]*>", "", str(s)).replace(",", "").replace("+", "").strip()
    if s in ("", "--", "---", "----", "N/A", "NA") or re.search(r"[一-鿿]", s):
        return None
    try:
        return float(s)
    except ValueError:
        return None

# ---------------------------------------------------------------- DB
SCHEMA = """
CREATE TABLE IF NOT EXISTS stock_info(stock_id TEXT PRIMARY KEY, name TEXT, industry TEXT, market TEXT);
CREATE TABLE IF NOT EXISTS index_daily(date TEXT, index_id TEXT, close REAL, spread REAL, volume REAL, amount REAL, PRIMARY KEY(date,index_id));
CREATE TABLE IF NOT EXISTS inst_total(date TEXT, name TEXT, buy REAL, sell REAL, PRIMARY KEY(date,name));
CREATE TABLE IF NOT EXISTS margin_total(date TEXT, item TEXT, today_bal REAL, yes_bal REAL, PRIMARY KEY(date,item));
CREATE TABLE IF NOT EXISTS watch_price(date TEXT, stock_id TEXT, open REAL, high REAL, low REAL, close REAL, spread REAL, volume REAL, amount REAL, PRIMARY KEY(date,stock_id));
CREATE TABLE IF NOT EXISTS watch_inst(date TEXT, stock_id TEXT, foreign_net REAL, trust_net REAL, dealer_net REAL, PRIMARY KEY(date,stock_id));
CREATE TABLE IF NOT EXISTS watch_margin(date TEXT, stock_id TEXT, margin_bal REAL, short_bal REAL, offset_ls REAL, PRIMARY KEY(date,stock_id));
CREATE TABLE IF NOT EXISTS watch_foreign(date TEXT, stock_id TEXT, ratio REAL, shares REAL, PRIMARY KEY(date,stock_id));
CREATE TABLE IF NOT EXISTS watch_sbl(date TEXT, stock_id TEXT, sbl_bal REAL, margin_short_bal REAL, PRIMARY KEY(date,stock_id));
CREATE TABLE IF NOT EXISTS watch_daytrade(date TEXT, stock_id TEXT, dt_volume REAL, dt_buy REAL, dt_sell REAL, PRIMARY KEY(date,stock_id));
CREATE TABLE IF NOT EXISTS mkt_daily(date TEXT, stock_id TEXT, market TEXT, name TEXT, close REAL, chg REAL, volume REAL, amount REAL,
  foreign_net REAL, trust_net REAL, dealer_net REAL, total_net REAL,
  margin_bal REAL, margin_prev REAL, short_bal REAL, short_prev REAL, PRIMARY KEY(date,stock_id));
CREATE TABLE IF NOT EXISTS tdcc(date TEXT, stock_id TEXT, pct400 REAL, pct1000 REAL, holders REAL, total_shares REAL, PRIMARY KEY(date,stock_id));
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS fx_daily(date TEXT PRIMARY KEY, cash_buy REAL, cash_sell REAL, spot_buy REAL, spot_sell REAL);
CREATE TABLE IF NOT EXISTS fut_daily(date TEXT, fid TEXT, contract TEXT, session TEXT, close REAL, spread_per REAL, volume REAL, oi REAL, PRIMARY KEY(date,fid,contract,session));
CREATE TABLE IF NOT EXISTS fut_inst(date TEXT, fid TEXT, inst TEXT, long_deal REAL, short_deal REAL, long_oi REAL, short_oi REAL, long_oi_amt REAL, short_oi_amt REAL, PRIMARY KEY(date,fid,inst));
CREATE TABLE IF NOT EXISTS fut_map(code TEXT PRIMARY KEY, stock_id TEXT, name TEXT, unit REAL);
CREATE TABLE IF NOT EXISTS stockfut_daily(date TEXT, code TEXT, stock_id TEXT, volume REAL, value REAL, close_near REAL, PRIMARY KEY(date,code));
CREATE TABLE IF NOT EXISTS market_stat(date TEXT, kind TEXT, amount REAL, PRIMARY KEY(date,kind));
"""

def db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)   # CI 全新 checkout 無 data/ 目錄時自動建立
    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.executescript(SCHEMA)
    for mig in ("ALTER TABLE tdcc ADD COLUMN total_shares REAL",
                "ALTER TABLE fut_map ADD COLUMN unit REAL",
                "ALTER TABLE fut_inst ADD COLUMN long_deal_amt REAL",
                "ALTER TABLE fut_inst ADD COLUMN short_deal_amt REAL"):
        try:
            conn.execute(mig)
        except sqlite3.OperationalError:
            pass
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def upsert(conn, table, rows, cols):
    if not rows:
        return 0
    ph = ",".join("?" * len(cols))
    conn.executemany(f"INSERT OR REPLACE INTO {table}({','.join(cols)}) VALUES({ph})", rows)
    conn.commit()
    return len(rows)

# ---------------------------------------------------------------- FinMind fetchers
def fetch_stock_info(conn):
    rows = fm("TaiwanStockInfo")
    seen = {}
    for r in rows:
        sid = str(r.get("stock_id", "")).strip()
        if not SID_RE.fullmatch(sid):
            continue
        if sid not in seen:
            seen[sid] = (sid, r.get("stock_name"), r.get("industry_category"), r.get("type"))
    n = upsert(conn, "stock_info", list(seen.values()), ["stock_id", "name", "industry", "market"])
    log(f"stock_info: {n} 檔")

def fetch_indexes(conn, start):
    for idx in ("TAIEX", "TPEx"):
        rows = fm("TaiwanStockPrice", data_id=idx, start_date=start)
        data = [(r["date"], idx, r.get("close"), r.get("spread"), r.get("Trading_Volume"), r.get("Trading_money")) for r in rows]
        upsert(conn, "index_daily", data, ["date", "index_id", "close", "spread", "volume", "amount"])
    log(f"index_daily 更新自 {start}")

def fetch_totals(conn, start):
    rows = fm("TaiwanStockTotalInstitutionalInvestors", start_date=start)
    data = [(r["date"], r["name"], r.get("buy"), r.get("sell")) for r in rows if r.get("name") != "total"]
    upsert(conn, "inst_total", data, ["date", "name", "buy", "sell"])
    rows = fm("TaiwanStockTotalMarginPurchaseShortSale", start_date=start)
    data = []
    for r in rows:
        tb, yb = r.get("TodayBalance"), r.get("YesBalance")
        if r["name"] == "MarginPurchaseMoney":   # FinMind 為「元」,統一存「仟元」(與證交所 MI_MARGN 一致)
            tb = tb / 1000 if tb is not None else None
            yb = yb / 1000 if yb is not None else None
        data.append((r["date"], r["name"], tb, yb))
    upsert(conn, "margin_total", data, ["date", "item", "today_bal", "yes_bal"])
    log(f"市場總計(法人金額/融資券)更新自 {start}")

def fetch_watch_stock(conn, sid, start):
    rows = fm("TaiwanStockPrice", data_id=sid, start_date=start)
    upsert(conn, "watch_price",
           [(r["date"], sid, r.get("open"), r.get("max"), r.get("min"), r.get("close"), r.get("spread"),
             r.get("Trading_Volume"), r.get("Trading_money")) for r in rows],
           ["date", "stock_id", "open", "high", "low", "close", "spread", "volume", "amount"])

    rows = fm("TaiwanStockInstitutionalInvestorsBuySell", data_id=sid, start_date=start)
    per = {}
    for r in rows:
        d = per.setdefault(r["date"], {"f": 0.0, "t": 0.0, "d": 0.0})
        net = (r.get("buy") or 0) - (r.get("sell") or 0)
        n = r.get("name")
        if n in ("Foreign_Investor", "Foreign_Dealer_Self"):
            d["f"] += net
        elif n == "Investment_Trust":
            d["t"] += net
        elif n in ("Dealer_self", "Dealer_Hedging"):
            d["d"] += net
    upsert(conn, "watch_inst", [(k, sid, v["f"], v["t"], v["d"]) for k, v in per.items()],
           ["date", "stock_id", "foreign_net", "trust_net", "dealer_net"])

    rows = fm("TaiwanStockMarginPurchaseShortSale", data_id=sid, start_date=start)
    upsert(conn, "watch_margin",
           [(r["date"], sid, r.get("MarginPurchaseTodayBalance"), r.get("ShortSaleTodayBalance"), r.get("OffsetLoanAndShort")) for r in rows],
           ["date", "stock_id", "margin_bal", "short_bal", "offset_ls"])

    rows = fm("TaiwanStockShareholding", data_id=sid, start_date=start)
    upsert(conn, "watch_foreign",
           [(r["date"], sid, r.get("ForeignInvestmentSharesRatio"), r.get("ForeignInvestmentShares")) for r in rows],
           ["date", "stock_id", "ratio", "shares"])

    rows = fm("TaiwanDailyShortSaleBalances", data_id=sid, start_date=start)
    upsert(conn, "watch_sbl",
           [(r["date"], sid, r.get("SBLShortSalesCurrentDayBalance"), r.get("MarginShortSalesCurrentDayBalance")) for r in rows],
           ["date", "stock_id", "sbl_bal", "margin_short_bal"])

    rows = fm("TaiwanStockDayTrading", data_id=sid, start_date=start)
    upsert(conn, "watch_daytrade",
           [(r["date"], sid, r.get("Volume"), r.get("BuyAmount"), r.get("SellAmount")) for r in rows],
           ["date", "stock_id", "dt_volume", "dt_buy", "dt_sell"])

# ---------------------------------------------------------------- TWSE 全市場快照
def twse_url(path, **q):
    q.setdefault("response", "json")
    return f"https://www.twse.com.tw/rwd/zh/{path}?" + urllib.parse.urlencode(q)

def fetch_twse_day(date):
    """date: 'YYYY-MM-DD' → dict sid -> row-dict;非交易日回 None"""
    d8 = date.replace("-", "")
    out = {}
    j = http_json(twse_url("afterTrading/MI_INDEX", date=d8, type="ALLBUT0999"), gap=1.0)
    if j.get("stat") != "OK":
        return None, None, None
    quotes_tbl = next((t for t in j.get("tables", []) if "每日收盤行情" in (t.get("title") or "")), None)
    if not quotes_tbl:
        return None, None, None
    for row in quotes_tbl.get("data", []):
        sid = row[0].strip()
        sign_html = str(row[9])
        sign = -1.0 if "-" in re.sub(r"<[^>]*>", "", sign_html) and "+" not in sign_html else (1.0 if "+" in sign_html else 0.0)
        diff = num(row[10])
        out[sid] = {"name": row[1].strip(), "close": num(row[8]),
                    "chg": (sign * diff) if diff is not None else None,
                    "volume": num(row[2]), "amount": num(row[4])}

    j = http_json(twse_url("fund/T86", date=d8, selectType="ALLBUT0999"), gap=1.0)
    if j.get("stat") == "OK":
        f = j["fields"]
        i_for = f.index("外陸資買賣超股數(不含外資自營商)")
        i_fds = f.index("外資自營商買賣超股數")
        i_tru = f.index("投信買賣超股數")
        i_dlr = f.index("自營商買賣超股數")
        i_tot = f.index("三大法人買賣超股數")
        for row in j.get("data", []):
            sid = row[0].strip()
            r = out.setdefault(sid, {"name": row[1].strip()})
            r["foreign_net"] = (num(row[i_for]) or 0) + (num(row[i_fds]) or 0)
            r["trust_net"] = num(row[i_tru]) or 0
            r["dealer_net"] = num(row[i_dlr]) or 0
            r["total_net"] = num(row[i_tot]) or 0

    margin_total_rows = []
    j = http_json(twse_url("marginTrading/MI_MARGN", date=d8, selectType="ALL"), gap=1.0)
    if j.get("stat") == "OK":
        tables = j.get("tables", [])
        if tables and tables[0].get("data"):
            name_map = {"融資(交易單位)": "MarginPurchase", "融券(交易單位)": "ShortSale", "融資金額(仟元)": "MarginPurchaseMoney"}
            for row in tables[0]["data"]:
                item = name_map.get(str(row[0]).strip())
                if item:
                    margin_total_rows.append((date, item, num(row[5]), num(row[4])))
        if len(tables) > 1:
            for row in tables[1].get("data", []):
                sid = row[0].strip()
                r = out.setdefault(sid, {"name": row[1].strip()})
                r["margin_prev"] = num(row[5]); r["margin_bal"] = num(row[6])
                r["short_prev"] = num(row[11]); r["short_bal"] = num(row[12])

    inst_total_rows = []
    j = http_json(twse_url("fund/BFI82U", dayDate=d8, type="day"), gap=1.0)
    if j.get("stat") == "OK":
        name_map = {"自營商(自行買賣)": "Dealer_self", "自營商(避險)": "Dealer_Hedging", "投信": "Investment_Trust",
                    "外資及陸資(不含外資自營商)": "Foreign_Investor", "外資自營商": "Foreign_Dealer_Self"}
        for row in j.get("data", []):
            n = name_map.get(str(row[0]).strip())
            if n:
                inst_total_rows.append((date, n, num(row[1]), num(row[2])))
    return out, margin_total_rows, inst_total_rows

# ---------------------------------------------------------------- TPEX 全市場快照
def roc(date):
    y, m, d = date.split("-")
    return f"{int(y)-1911}/{m}/{d}"

def tpex_url(path, **q):
    return f"https://www.tpex.org.tw/web/stock/{path}?" + urllib.parse.urlencode(q)

def fetch_tpex_day(date):
    out = {}
    j = http_json(tpex_url("aftertrading/otc_quotes_no1430/stk_wn1430_result.php", l="zh-tw", d=roc(date), se="EW", o="json"), gap=1.0)
    tbl = (j.get("tables") or [{}])[0]
    if not tbl.get("data"):
        return None, None
    for row in tbl["data"]:
        sid = str(row[0]).strip()
        if not SID_RE.fullmatch(sid):
            continue
        out[sid] = {"name": str(row[1]).strip(), "close": num(row[2]), "chg": num2_signed(row[3]),
                    "volume": num(row[7]), "amount": num(row[8])}

    j = http_json(tpex_url("3insti/daily_trade/3itrade_hedge_result.php", l="zh-tw", se="EW", t="D", d=roc(date), o="json"), gap=1.0)
    tbl = (j.get("tables") or [{}])[0]
    for row in tbl.get("data", []):
        sid = str(row[0]).strip()
        if not SID_RE.fullmatch(sid):
            continue
        r = out.setdefault(sid, {"name": str(row[1]).strip()})
        r["foreign_net"] = num(row[10]) or 0    # 外資及陸資合計買賣超
        r["trust_net"] = num(row[13]) or 0      # 投信買賣超
        r["dealer_net"] = num(row[22]) or 0     # 自營商合計買賣超
        r["total_net"] = num(row[23]) or 0      # 三大法人合計

    j = http_json(tpex_url("margin_trading/margin_balance/margin_bal_result.php", l="zh-tw", d=roc(date), o="json"), gap=1.0)
    tbl = (j.get("tables") or [{}])[0]
    for row in tbl.get("data", []):
        sid = str(row[0]).strip()
        if not SID_RE.fullmatch(sid):
            continue
        r = out.setdefault(sid, {"name": str(row[1]).strip()})
        r["margin_prev"] = num(row[2]); r["margin_bal"] = num(row[6])
        r["short_prev"] = num(row[10]); r["short_bal"] = num(row[14])
    return out, None

def num2_signed(s):
    """TPEX 漲跌欄:'+0.13' / '-1.2' / '0.00' / '除息' """
    s = str(s).strip()
    neg = s.startswith("-")
    v = num(s)
    if v is None:
        return None
    return -abs(v) if neg else v

# ---------------------------------------------------------------- snapshot 組裝
MKT_COLS = ["date", "stock_id", "market", "name", "close", "chg", "volume", "amount",
            "foreign_net", "trust_net", "dealer_net", "total_net",
            "margin_bal", "margin_prev", "short_bal", "short_prev"]

def store_snapshot(conn, date, twse_out, tpex_out, margin_total_rows, inst_total_rows):
    rows = []
    for market, data in (("twse", twse_out), ("tpex", tpex_out)):
        if not data:
            continue
        for sid, r in data.items():
            if not SID_RE.fullmatch(sid):
                continue
            rows.append((date, sid, market, r.get("name"), r.get("close"), r.get("chg"),
                         r.get("volume"), r.get("amount"),
                         r.get("foreign_net"), r.get("trust_net"), r.get("dealer_net"), r.get("total_net"),
                         r.get("margin_bal"), r.get("margin_prev"), r.get("short_bal"), r.get("short_prev")))
    n = upsert(conn, "mkt_daily", rows, MKT_COLS)
    # TWSE 官方即時 fallback(補足 FinMind 可能的延遲)
    if margin_total_rows:
        upsert(conn, "margin_total", margin_total_rows, ["date", "item", "today_bal", "yes_bal"])
    if inst_total_rows:
        upsert(conn, "inst_total", inst_total_rows, ["date", "name", "buy", "sell"])
    return n

def snapshot_days(conn, dates):
    """對缺少的交易日抓全市場快照(TWSE 與 TPEX 兩執行緒並行)"""
    results = {}
    def work_twse():
        for d in dates:
            try:
                results.setdefault(d, {})["twse"] = fetch_twse_day(d)
            except Exception as e:
                log(f"  TWSE {d} 失敗: {e}")
                results.setdefault(d, {})["twse"] = (None, None, None)
    def work_tpex():
        for d in dates:
            try:
                results.setdefault(d, {})["tpex"] = fetch_tpex_day(d)
            except Exception as e:
                log(f"  TPEX {d} 失敗: {e}")
                results.setdefault(d, {})["tpex"] = (None, None)
    t1 = threading.Thread(target=work_twse); t2 = threading.Thread(target=work_tpex)
    t1.start(); t2.start(); t1.join(); t2.join()
    total = 0
    for d in dates:
        r = results.get(d, {})
        twse_out, mt_rows, it_rows = r.get("twse", (None, None, None))
        tpex_out, _ = r.get("tpex", (None, None))
        n = store_snapshot(conn, d, twse_out, tpex_out, mt_rows, it_rows)
        total += n
        log(f"  快照 {d}: {n} 檔")
    return total

# ---------------------------------------------------------------- TDCC 股權分散
def fetch_tdcc(conn):
    url = "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5"
    _throttle("opendata.tdcc.com.tw", 1.0)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=300) as r:
        raw = r.read().decode("utf-8-sig", "replace")
    agg = {}
    for row in csv.reader(io.StringIO(raw)):
        if len(row) < 6 or row[0] == "資料日期":
            continue
        d8, sid, level = row[0].strip(), row[1].strip(), row[2].strip()
        if not SID_RE.fullmatch(sid):
            continue
        date = f"{d8[:4]}-{d8[4:6]}-{d8[6:]}"
        a = agg.setdefault((date, sid), {"pct400": 0.0, "pct1000": 0.0, "holders": None, "shares": None})
        try:
            lv = int(level)
        except ValueError:
            continue
        pct = num(row[5]) or 0.0
        if 12 <= lv <= 15:
            a["pct400"] += pct
        if lv == 15:
            a["pct1000"] = pct
        if lv == 17:
            a["holders"] = num(row[3])
            a["shares"] = num(row[4])
    rows = [(d, s, v["pct400"], v["pct1000"], v["holders"], v["shares"]) for (d, s), v in agg.items()]
    n = upsert(conn, "tdcc", rows, ["date", "stock_id", "pct400", "pct1000", "holders", "total_shares"])
    dates = sorted({d for (d, s) in agg})
    log(f"TDCC 股權分散: {n} 檔,資料日 {dates}")
    return dates

# ---------------------------------------------------------------- 匯率與期貨
def fetch_fx(conn, start):
    rows = fm("TaiwanExchangeRate", data_id="USD", start_date=start)
    upsert(conn, "fx_daily",
           [(r["date"], r.get("cash_buy"), r.get("cash_sell"), r.get("spot_buy"), r.get("spot_sell")) for r in rows
            if (r.get("spot_buy") or 0) > 0],
           ["date", "cash_buy", "cash_sell", "spot_buy", "spot_sell"])
    log(f"匯率 USD/TWD 更新自 {start}")

def fetch_futures(conn, start):
    for fid in CONFIG["futures"]["index"]:
        rows = fm("TaiwanFuturesDaily", data_id=fid, start_date=start)
        upsert(conn, "fut_daily",
               [(r["date"], fid, r.get("contract_date", "").strip(), r.get("trading_session", ""),
                 r.get("close"), r.get("spread_per"), r.get("volume"), r.get("open_interest")) for r in rows],
               ["date", "fid", "contract", "session", "close", "spread_per", "volume", "oi"])
    for fid in CONFIG["futures"]["inst"]:
        rows = fm("TaiwanFuturesInstitutionalInvestors", data_id=fid, start_date=start)
        upsert(conn, "fut_inst",
               [(r["date"], fid, r.get("institutional_investors"),
                 r.get("long_deal_volume"), r.get("short_deal_volume"),
                 r.get("long_open_interest_balance_volume"), r.get("short_open_interest_balance_volume"),
                 r.get("long_open_interest_balance_amount"), r.get("short_open_interest_balance_amount"),
                 r.get("long_deal_amount"), r.get("short_deal_amount")) for r in rows],
               ["date", "fid", "inst", "long_deal", "short_deal", "long_oi", "short_oi",
                "long_oi_amt", "short_oi_amt", "long_deal_amt", "short_deal_amt"])
    log(f"期貨({'/'.join(CONFIG['futures']['index'])})與三大法人部位(含契約金額)更新自 {start}")

def fetch_market_stat(conn, dates):
    """TWSE MI_INDEX:(1) type=MS 各證券種類成交金額;(2) type=0999* 權證分類(認購/認售/牛/熊)成交金額合計(元)"""
    kinds = {"7.認購(售)權證": "權證", "4.ETF": "ETF成交", "1.一般股票": "股票成交", "13.ETN": "ETN"}
    wclasses = [("0999", "認購"), ("0999P", "認售"), ("0999C", "牛證"), ("0999B", "熊證")]
    got = 0
    for d in dates:
        ds = d.replace("-", "")
        try:
            _throttle("www.twse.com.tw", 3.0)
            req = urllib.request.Request(
                f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={ds}&type=MS&response=json", headers=UA)
            j = json.load(urllib.request.urlopen(req, timeout=40))
            rows = []
            for tb in j.get("tables", []):
                if "統計" in tb.get("title", "") and tb.get("fields", [""])[0] == "成交統計":
                    for row in tb.get("data", []):
                        k = kinds.get(str(row[0]).strip())
                        if k:
                            rows.append((d, k, float(str(row[1]).replace(",", ""))))
            got += upsert(conn, "market_stat", rows, ["date", "kind", "amount"])
        except Exception as e:
            log(f"market_stat {d} 失敗:{repr(e)[:60]}")
        for t, k in wclasses:
            try:
                _throttle("www.twse.com.tw", 3.0)
                req = urllib.request.Request(
                    f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={ds}&type={t}&response=json", headers=UA)
                j = json.load(urllib.request.urlopen(req, timeout=90))
                s = None
                for tb in j.get("tables", []):
                    f = tb.get("fields") or []
                    amt_i = next((i for i, x in enumerate(f) if str(x).startswith("成交金額")), None)
                    if amt_i is None or "每日收盤行情" not in (tb.get("title") or ""):
                        continue
                    s = 0.0
                    for row in tb.get("data", []):
                        v = num(row[amt_i])
                        if v:
                            s += v
                if s is not None:
                    got += upsert(conn, "market_stat", [(d, k, s)], ["date", "kind", "amount"])
            except Exception as e:
                log(f"market_stat {d} {k} 失敗:{repr(e)[:60]}")
    if got:
        log(f"市場成交統計(權證分類等)更新 {got} 筆")

def fetch_fut_map(conn):
    """期交所個股期貨代碼(2碼)↔ 現貨對照"""
    _throttle("www.taifex.com.tw", 1.0)
    req = urllib.request.Request("https://www.taifex.com.tw/cht/2/stockLists", headers=UA)
    with urllib.request.urlopen(req, timeout=90) as r:
        html = r.read().decode("utf-8", "replace")
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        cells = [re.sub(r"<[^>]*>", "", c).replace("\r", "").replace("\n", "").replace("\t", "").strip()
                 for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        if len(cells) >= 5 and re.fullmatch(r"[A-Z]{2}", cells[0]) and SID_RE.fullmatch(cells[2]):
            unit = None
            for c in reversed(cells):          # 「標準型證券股數/受益權單位」欄:2,000 / 100 / 10,000
                if re.fullmatch(r"[\d,]+", c):
                    unit = float(c.replace(",", ""))
                    break
            rows.append((cells[0], cells[2], cells[3], unit or 2000.0))
    n = upsert(conn, "fut_map", rows, ["code", "stock_id", "name", "unit"])
    log(f"個股期貨對照表: {n} 檔(含契約單位)")

def fetch_stockfut_day(conn, date):
    """期交所每日成交檔(tick zip)→ 聚合個股期貨成交量值(乘數 2000 股/口)"""
    fmap = {r[0]: (r[1], r[2], r[3] or 2000.0) for r in conn.execute("SELECT code,stock_id,name,unit FROM fut_map")}
    if not fmap:
        return 0
    codes3 = {c + "F": c for c in fmap}   # tick 檔商品代號 = 2碼+F
    y, m, d = date.split("-")
    url = f"https://www.taifex.com.tw/file/taifex/Dailydownload/DailydownloadCSV/Daily_{y}_{m}_{d}.zip"
    _throttle("www.taifex.com.tw", 2.0)
    import io as _io, zipfile as _zip
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            raw = r.read()
        zf = _zip.ZipFile(_io.BytesIO(raw))
    except Exception as e:
        log(f"  個股期貨 {date} 無成交檔: {repr(e)[:80]}")
        return 0
    d8 = f"{y}{m}{d}"
    agg = {}
    with zf.open(zf.namelist()[0]) as f:
        f.readline()
        for bline in f:
            parts = bline.decode("big5", "replace").split(",")
            if len(parts) < 6 or parts[0].strip() != d8:
                continue
            code = parts[1].strip()
            if code not in codes3:
                continue
            try:
                price, qty = float(parts[4]), float(parts[5])
            except ValueError:
                continue
            contract = parts[2].strip()
            a = agg.setdefault(code, {"vol2": 0.0, "val2": 0.0, "near": {}})
            a["vol2"] += qty
            a["val2"] += price * qty
            if re.fullmatch(r"\d{6}", contract):
                a["near"][contract] = price   # 依檔案順序,最後一筆為近收
    rows = []
    for code, a in agg.items():
        sid, _, unit = fmap[codes3[code]]
        near_c = min(a["near"]) if a["near"] else None
        rows.append((date, code, sid, a["vol2"] / 2, a["val2"] / 2 * unit, a["near"].get(near_c)))
    n = upsert(conn, "stockfut_daily", rows, ["date", "code", "stock_id", "volume", "value", "close_near"])
    log(f"  個股期貨 {date}: {n} 檔(成交檔 {len(raw)//1024//1024}MB)")
    return n

# ---------------------------------------------------------------- 大小單分解(需 FinMind sponsor;register 自動略過)
def _fm_probe(dataset, **params):
    """單次不重試的權限探測;回 (True, data) 或 (False, 錯誤字串)"""
    q = urllib.parse.urlencode(dict(dataset=dataset, **params))
    req = urllib.request.Request(f"https://api.finmindtrade.com/api/v4/data?{q}",
                                 headers={"Authorization": "Bearer " + TOKEN})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return True, (json.load(r).get("data") or [])
    except urllib.error.HTTPError as e:
        return False, e.read()[:150].decode("utf-8", "replace")
    except Exception as e:
        return False, repr(e)[:120]

def _classify_ticks(ticks, day_volume_shares):
    """四層大小單分類:
    ① meta-order 重組:同秒+同方向連續成交合併(逐筆撮合下一張市價單掃簿會印成多筆)
    ② 單位自動偵測:Σvolume 對照官方日成交量(股),判斷 tick volume 是張或股
    ③ 金額自適應分級:特大=max(500萬,P99)、大=max(100萬,P95)、小<max(30萬,P50),餘為中單
    ④ 方向:TickType 1=外盤(主動買)/2=內盤(主動賣)/0→tick rule 補
    回傳各級 buy/sell 金額(元)與 meta-order 數"""
    if not ticks:
        return None
    sum_v = sum(t.get("volume") or 0 for t in ticks)
    if sum_v <= 0:
        return None
    unit = 1000.0 if (day_volume_shares and 0.5 < (day_volume_shares / (sum_v * 1000)) < 2) else 1.0
    metas = []
    prev_price, prev_dir = None, 1
    cur = None
    for t in sorted(ticks, key=lambda x: str(x.get("Time") or x.get("time") or "")):
        px = t.get("deal_price") or 0
        vol = (t.get("volume") or 0) * unit          # → 股
        tt = t.get("TickType")
        if tt == 1:
            d = 1
        elif tt == 2:
            d = -1
        else:                                        # tick rule
            d = prev_dir if (prev_price is None or px == prev_price) else (1 if px > prev_price else -1)
        sec = str(t.get("Time") or t.get("time") or "")[:8]
        if cur and cur["sec"] == sec and cur["d"] == d:
            cur["amt"] += px * vol
        else:
            if cur:
                metas.append(cur)
            cur = {"sec": sec, "d": d, "amt": px * vol}
        prev_price, prev_dir = px, d
    if cur:
        metas.append(cur)
    amts = sorted(m["amt"] for m in metas)
    if not amts:
        return None
    def pct(p):
        return amts[min(len(amts) - 1, int(len(amts) * p))]
    XL, BIG, SM = max(5e6, pct(0.99)), max(1e6, pct(0.95)), max(3e5, pct(0.50))
    out = {k: 0.0 for k in ("xl_buy", "xl_sell", "big_buy", "big_sell", "mid_buy", "mid_sell", "sm_buy", "sm_sell")}
    for m in metas:
        lv = "xl" if m["amt"] >= XL else ("big" if m["amt"] >= BIG else ("sm" if m["amt"] < SM else "mid"))
        out[f"{lv}_{'buy' if m['d'] > 0 else 'sell'}"] += m["amt"]
    out["n_meta"] = len(metas)
    return out

def fetch_ticks_bigsmall(conn):
    """自選股逐檔抓最新交易日逐筆 → 大小單分解入庫;register 等級自動略過(升級 sponsor 後自動啟用)"""
    conn.execute("""CREATE TABLE IF NOT EXISTS bigsmall_daily(
        date TEXT, stock_id TEXT, xl_buy REAL, xl_sell REAL, big_buy REAL, big_sell REAL,
        mid_buy REAL, mid_sell REAL, sm_buy REAL, sm_sell REAL, n_meta REAL,
        PRIMARY KEY(date, stock_id))""")
    conn.commit()
    days = trading_days(conn)
    if not days:
        return
    d0 = days[-1]
    ok, res = _fm_probe("TaiwanStockPriceTick", data_id=CONFIG["watchlist"][0], date=d0)
    if not ok:
        if "level is register" in str(res):
            log("大小單分解:逐筆資料需 FinMind sponsor,本次略過(升級後自動啟用)")
        else:
            log(f"大小單分解探測失敗,略過: {str(res)[:80]}")
        return
    log("大小單分解:sponsor 權限已解鎖,開始分析")
    for sid in CONFIG["watchlist"]:
        try:
            ticks = res if sid == CONFIG["watchlist"][0] else fm("TaiwanStockPriceTick", data_id=sid, date=d0)
            dayv = conn.execute("SELECT volume FROM watch_price WHERE stock_id=? AND date=?", (sid, d0)).fetchone()
            c = _classify_ticks(ticks, dayv[0] if dayv else None)
            if c:
                upsert(conn, "bigsmall_daily",
                       [(d0, sid, c["xl_buy"], c["xl_sell"], c["big_buy"], c["big_sell"],
                         c["mid_buy"], c["mid_sell"], c["sm_buy"], c["sm_sell"], c["n_meta"])],
                       ["date", "stock_id", "xl_buy", "xl_sell", "big_buy", "big_sell",
                        "mid_buy", "mid_sell", "sm_buy", "sm_sell", "n_meta"])
        except Exception as e:
            log(f"  {sid} 大小單失敗: {repr(e)[:80]}")
    log(f"大小單分解完成({d0})")

# ---------------------------------------------------------------- 央行統計(月頻:外資台幣存款池、外匯即期量)
def fetch_cbc_pools(conn):
    """cpx.cbc.gov.tw DataAPI:
       EF03M01 → 外國人新台幣存款(億) = 外資停泊池
       EG47M01 → 日平均外匯交易量-即期(百萬美元) = 熱錢量能(月均)"""
    def cbc(fid):
        _throttle("cpx.cbc.gov.tw", 1.0)
        req = urllib.request.Request(f"https://cpx.cbc.gov.tw/API/DataAPI/Get?FileName={fid}", headers=UA)
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.load(r)
    conn.execute("CREATE TABLE IF NOT EXISTS cbc_monthly(month TEXT, item TEXT, value REAL, PRIMARY KEY(month,item))")
    try:
        j = cbc("EF03M01")   # row = [period, (金額,年增率)×8科目];外國人新台幣存款=第6科目 → idx 11
        rows = [(r[0].replace("M", "-"), "foreign_twd_yi", num(r[11])) for r in j["data"]["dataSets"] if len(r) > 11]
        upsert(conn, "cbc_monthly", rows, ["month", "item", "value"])
        log(f"央行 外國人新台幣存款: {len(rows)} 期,最新 {rows[-1][0]} = {rows[-1][2]} 億")
    except Exception as e:
        log(f"央行 EF03M01 失敗(沿用舊值): {repr(e)[:90]}")
    try:
        j = cbc("EG47M01")   # 顧客即期 idx5 + 銀行間即期 idx19(百萬美元/日均)
        rows = []
        for r in j["data"]["dataSets"]:
            if len(r) > 19 and num(r[5]) is not None and num(r[19]) is not None:
                rows.append((r[0].replace("M", "-"), "fx_spot_musd", num(r[5]) + num(r[19])))
        upsert(conn, "cbc_monthly", rows, ["month", "item", "value"])
        log(f"央行 外匯即期日均量: {len(rows)} 期,最新 {rows[-1][0]} = {rows[-1][2]:.0f} 百萬美元")
    except Exception as e:
        log(f"央行 EG47M01 失敗(沿用舊值): {repr(e)[:90]}")

# ---------------------------------------------------------------- 邏輯
def trading_days(conn, last_n=None):
    rows = conn.execute("SELECT DISTINCT date FROM index_daily WHERE index_id='TAIEX' ORDER BY date").fetchall()
    days = [r[0] for r in rows]
    return days[-last_n:] if last_n else days

def missing_snapshot_days(conn, candidate_days):
    have = {r[0] for r in conn.execute("SELECT DISTINCT date FROM mkt_daily").fetchall()}
    return [d for d in candidate_days if d not in have]

def do_backfill():
    conn = db()
    t0 = time.time()
    log("=== 回補開始 ===")
    fetch_stock_info(conn)
    start = CONFIG["watch_history_start"]
    fetch_indexes(conn, start)
    fetch_totals(conn, start)
    wl = CONFIG["watchlist"]
    for i, sid in enumerate(wl, 1):
        fetch_watch_stock(conn, sid, start)
        log(f"自選股 {sid} 回補完成 ({i}/{len(wl)})")
    # 全市場快照回補到 flow_history_start(完整資金流歷史窗,非只 60 天)
    flow_start = CONFIG.get("flow_history_start") or start
    snap_days = [d for d in trading_days(conn) if d >= flow_start]
    miss = missing_snapshot_days(conn, snap_days)
    log(f"全市場快照需回補 {len(miss)} 個交易日: {miss[0] if miss else '-'} ~ {miss[-1] if miss else '-'}")
    snapshot_days(conn, miss)
    fetch_tdcc(conn)
    fetch_fx(conn, start)
    fetch_futures(conn, start)
    # 權證分類成交(近 12 個交易日足夠供徽章/5日均)
    try:
        fetch_market_stat(conn, [d for d in trading_days(conn)[-12:]])
    except Exception as e:
        log(f"市場成交統計回補失敗(不影響其他): {e}")
    fetch_cbc_pools(conn)
    fetch_fut_map(conn)
    for d in trading_days(conn)[-CONFIG.get("stockfut_backfill_days", 5):]:
        fetch_stockfut_day(conn, d)
    conn.execute("INSERT OR REPLACE INTO meta VALUES('last_backfill', ?)", (dt.datetime.now(TPE).isoformat(),))
    conn.commit()
    log(f"=== 回補完成,共 {time.time()-t0:.0f}s ===")

def build_summary(conn):
    last = conn.execute("SELECT MAX(date) FROM index_daily WHERE index_id='TAIEX'").fetchone()[0]
    s = {"last_date": last}
    r = conn.execute("SELECT close, spread FROM index_daily WHERE index_id='TAIEX' AND date=?", (last,)).fetchone()
    if r:
        close, spread = r
        prev = close - spread if (close is not None and spread is not None) else None
        s["taiex"] = {"close": close, "chg": spread, "chg_pct": round(spread / prev * 100, 2) if prev else None}
    rows = conn.execute("SELECT name, buy, sell FROM inst_total WHERE date=?", (last,)).fetchall()
    if rows:
        f = t = d0 = 0.0
        for n, b, sl in rows:
            netv = (b or 0) - (sl or 0)
            if n in ("Foreign_Investor", "Foreign_Dealer_Self"): f += netv
            elif n == "Investment_Trust": t += netv
            else: d0 += netv
        s["inst_net_yi"] = {"foreign": round(f / 1e8, 1), "trust": round(t / 1e8, 1), "dealer": round(d0 / 1e8, 1),
                            "total": round((f + t + d0) / 1e8, 1)}
    r = conn.execute("SELECT today_bal, yes_bal FROM margin_total WHERE date=? AND item='MarginPurchaseMoney'", (last,)).fetchone()
    if r and r[0] is not None and r[1] is not None:
        s["margin_chg_yi"] = round((r[0] - r[1]) / 1e5, 1)   # 仟元 → 億
    n = conn.execute("SELECT COUNT(*) FROM mkt_daily WHERE date=?", (last,)).fetchone()[0]
    s["snapshot_stocks"] = n
    fx = conn.execute("SELECT date,(spot_buy+spot_sell)/2 FROM fx_daily ORDER BY date DESC LIMIT 2").fetchall()
    if fx:
        s["usd_twd"] = round(fx[0][1], 3)
        if len(fx) > 1:
            s["usd_twd_chg"] = round(fx[0][1] - fx[1][1], 3)
    tx = conn.execute("SELECT date, long_oi-short_oi FROM fut_inst WHERE fid='TX' AND inst='外資' ORDER BY date DESC LIMIT 2").fetchall()
    if tx:
        s["tx_foreign_net_oi"] = int(tx[0][1])
        if len(tx) > 1:
            s["tx_foreign_net_oi_chg"] = int(tx[0][1] - tx[1][1])
    r = conn.execute("SELECT stock_id, value FROM stockfut_daily WHERE date=(SELECT MAX(date) FROM stockfut_daily) ORDER BY value DESC LIMIT 1").fetchone()
    if r:
        s["top_stockfut"] = {"stock_id": r[0], "value_yi": round(r[1] / 1e8, 1)}
    return s

def do_update():
    conn = db()
    today = dt.datetime.now(TPE).date().isoformat()
    log("=== 增量更新開始 ===")
    # 自癒式回看:一般抓近 10 天,但若資料庫有缺口(例如 CI 快取遺失、停機數日),
    # 就把 lookback 延伸到最後一筆快照之後,確保缺口被補起來(下限=flow_history_start)
    flow_start = CONFIG.get("flow_history_start") or CONFIG["watch_history_start"]
    snap_last = conn.execute("SELECT MAX(date) FROM mkt_daily").fetchone()[0]
    lookback = (dt.datetime.now(TPE).date() - dt.timedelta(days=10)).isoformat()
    if snap_last and snap_last < lookback:
        lookback = max(snap_last, flow_start)      # 有缺口 → 延伸回看以填補
    elif not snap_last:
        lookback = flow_start                       # 空庫 → 等同回補
    fetch_indexes(conn, lookback)
    fetch_totals(conn, lookback)
    days = trading_days(conn)
    is_trading = today in days
    # 每週一或 stock_info 空 → 更新股票清單
    if dt.datetime.now(TPE).weekday() == 0 or not conn.execute("SELECT 1 FROM stock_info LIMIT 1").fetchone():
        fetch_stock_info(conn)
    if is_trading:
        for sid in CONFIG["watchlist"]:
            fetch_watch_stock(conn, sid, lookback)
        log("自選股增量完成")
        try:
            fetch_ticks_bigsmall(conn)
        except Exception as e:
            log(f"大小單分解異常(不影響其他): {e}")
    # 補全市場快照:填補「flow 視窗內」所有缺的交易日(自癒),正常情況只差 0~1 天
    flow_days = [d for d in days if d >= flow_start]
    miss = missing_snapshot_days(conn, flow_days)
    if miss:
        log(f"快照缺 {len(miss)} 日待補:{miss[0]} ~ {miss[-1]}")
        snapshot_days(conn, miss)
    fetch_fx(conn, lookback)
    fetch_futures(conn, lookback)
    # 市場成交統計(權證金額等):補最近缺的交易日
    have_ms = {r[0] for r in conn.execute("SELECT DISTINCT date FROM market_stat WHERE kind='認購'").fetchall()}
    need_ms = [x for x in days[-5:] if x not in have_ms]
    if need_ms:
        try:
            fetch_market_stat(conn, need_ms)
        except Exception as e:
            log(f"市場成交統計更新失敗(不影響其他): {e}")
    try:
        fetch_cbc_pools(conn)
    except Exception as e:
        log(f"央行月資料更新失敗(不影響其他): {e}")
    if dt.datetime.now(TPE).weekday() == 0 or not conn.execute("SELECT 1 FROM fut_map LIMIT 1").fetchone():
        try:
            fetch_fut_map(conn)
        except Exception as e:
            log(f"個股期貨對照表更新失敗(沿用舊表): {e}")
    have_sf = {r[0] for r in conn.execute("SELECT DISTINCT date FROM stockfut_daily").fetchall()}
    for d in [x for x in days[-3:] if x not in have_sf]:
        try:
            fetch_stockfut_day(conn, d)
        except Exception as e:
            log(f"個股期貨 {d} 更新失敗: {e}")
    # TDCC:每日抓一次無妨,只有出新週資料才會新增
    try:
        fetch_tdcc(conn)
    except Exception as e:
        log(f"TDCC 更新失敗(不影響其他資料): {e}")
    conn.execute("INSERT OR REPLACE INTO meta VALUES('last_update', ?)", (dt.datetime.now(TPE).isoformat(),))
    conn.commit()
    s = build_summary(conn)
    s["trading_day"] = is_trading
    s["today"] = today
    print("SUMMARY " + json.dumps(s, ensure_ascii=False), flush=True)
    log("=== 增量更新完成 ===")
    return s

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true")
    ap.add_argument("--update", action="store_true")
    a = ap.parse_args()
    if a.backfill:
        do_backfill()
    elif a.update:
        do_update()
    else:
        ap.print_help()
