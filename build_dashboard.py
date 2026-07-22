#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""台股資金流量追蹤系統 — 儀表板產生器
從 SQLite 計算指標,產出單檔 dashboard.html
"""
import datetime as dt, json, os, re, sqlite3, urllib.request
from zoneinfo import ZoneInfo

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "funds.db")
OUT_PATH = os.path.join(BASE_DIR, "dashboard.html")
CONFIG = json.load(open(os.path.join(BASE_DIR, "config.json"), encoding="utf-8"))
TPE = ZoneInfo("Asia/Taipei")

conn = sqlite3.connect(DB_PATH)

def q(sql, *args):
    return conn.execute(sql, args).fetchall()

def r1(v): return None if v is None else round(v, 1)
def r2(v): return None if v is None else round(v, 2)
def rint(v): return None if v is None else int(round(v))

# ---------------------------------------------------------------- 基礎
dates_all = [r[0] for r in q("SELECT date FROM index_daily WHERE index_id='TAIEX' AND close IS NOT NULL ORDER BY date")]
if not dates_all:
    raise SystemExit("資料庫沒有指數資料,請先執行 fetch_data.py --backfill")
LAST = dates_all[-1]
D60, D120 = dates_all[-60:], dates_all[-120:]
# 資金流/池/輪動的完整歷史窗:從 config.flow_history_start 起、且實際有全市場快照的交易日
FLOW_START = CONFIG.get("flow_history_start") or D60[0]
_snap_days = [r[0] for r in q("SELECT DISTINCT date FROM mkt_daily WHERE date>=? ORDER BY date", FLOW_START)]
DFLOW = _snap_days if len(_snap_days) >= 2 else D60
L5, L20 = dates_all[-5:], dates_all[-20:]
prev5_anchor = dates_all[-6] if len(dates_all) >= 6 else dates_all[0]
prev20_anchor = dates_all[-21] if len(dates_all) >= 21 else dates_all[0]

idx = {}
for d, i, c, s, v, a in q("SELECT date,index_id,close,spread,volume,amount FROM index_daily"):
    idx[(d, i)] = (c, s, a)

info = {}
for sid, name, ind, mkt in q("SELECT stock_id,name,industry,market FROM stock_info"):
    info[sid] = (name, ind or "其他", mkt)

# 法人金額(元)→ 每日 f/t/d
inst_by_date = {}
for d, n, b, s in q("SELECT date,name,buy,sell FROM inst_total"):
    a = inst_by_date.setdefault(d, {"f": 0.0, "t": 0.0, "d": 0.0})
    net = (b or 0) - (s or 0)
    if n in ("Foreign_Investor", "Foreign_Dealer_Self"): a["f"] += net
    elif n == "Investment_Trust": a["t"] += net
    elif n in ("Dealer_self", "Dealer_Hedging"): a["d"] += net

margin_by_date = {}
for d, item, tb, yb in q("SELECT date,item,today_bal,yes_bal FROM margin_total WHERE item='MarginPurchaseMoney'"):
    margin_by_date[d] = (tb, yb)

def sget(dic, d, k=None):
    v = dic.get(d)
    if v is None: return None
    return v if k is None else v[k]

# ---------------------------------------------------------------- overview
tai_close = [sget(idx, (d, "TAIEX"), 0) for d in D60]
tpx_close = [sget(idx, (d, "TPEx"), 0) for d in D60]
inst_f = [r1(inst_by_date[d]["f"] / 1e8) if d in inst_by_date else None for d in D60]
inst_t = [r1(inst_by_date[d]["t"] / 1e8) if d in inst_by_date else None for d in D60]
inst_d = [r1(inst_by_date[d]["d"] / 1e8) if d in inst_by_date else None for d in D60]

cum_f, cum_t, cum_d = [], [], []
cf = ct = cd = 0.0
for a, b, c in zip(inst_f, inst_t, inst_d):
    cf += a or 0; ct += b or 0; cd += c or 0
    cum_f.append(r1(cf)); cum_t.append(r1(ct)); cum_d.append(r1(cd))

margin_money = [r1(margin_by_date[d][0] / 1e5) if d in margin_by_date and margin_by_date[d][0] is not None else None for d in D60]
margin_chg = [r1((margin_by_date[d][0] - margin_by_date[d][1]) / 1e5) if d in margin_by_date and None not in margin_by_date[d] else None for d in D60]
amount_yi = [r1(((sget(idx, (d, "TAIEX"), 2) or 0) + (sget(idx, (d, "TPEx"), 2) or 0)) / 1e8) or None for d in D60]

def idx_kpi(iid):
    c, s, a = idx.get((LAST, iid), (None, None, None))
    prev = (c - s) if (c is not None and s is not None) else None
    return {"close": r2(c), "chg": r2(s), "chg_pct": r2(s / prev * 100) if prev else None}

k_inst = inst_by_date.get(LAST, {})
kpi = {
    "taiex": idx_kpi("TAIEX"), "tpex": idx_kpi("TPEx"),
    "foreign_yi": r1(k_inst.get("f", 0) / 1e8) if k_inst else None,
    "trust_yi": r1(k_inst.get("t", 0) / 1e8) if k_inst else None,
    "dealer_yi": r1(k_inst.get("d", 0) / 1e8) if k_inst else None,
    "total_yi": r1(sum(k_inst.values()) / 1e8) if k_inst else None,
    "margin_bal_yi": r1(margin_by_date[LAST][0] / 1e5) if LAST in margin_by_date and margin_by_date[LAST][0] else None,
    "margin_chg_yi": r1((margin_by_date[LAST][0] - margin_by_date[LAST][1]) / 1e5) if LAST in margin_by_date and None not in margin_by_date[LAST] else None,
    "amount_yi": amount_yi[-1] if amount_yi else None,
}

recent5 = []
for d in reversed(L5):
    a = inst_by_date.get(d, {})
    c, s, _ = idx.get((d, "TAIEX"), (None, None, None))
    prev = (c - s) if (c is not None and s is not None) else None
    mm = margin_by_date.get(d, (None, None))
    recent5.append({"date": d, "taiex": r2(c), "chg_pct": r2(s / prev * 100) if prev else None,
                    "f": r1(a.get("f", 0) / 1e8) if a else None, "t": r1(a.get("t", 0) / 1e8) if a else None,
                    "d": r1(a.get("d", 0) / 1e8) if a else None,
                    "total": r1(sum(a.values()) / 1e8) if a else None,
                    "margin_chg": r1((mm[0] - mm[1]) / 1e5) if None not in mm else None})

overview = {"dates": D60, "taiex": tai_close, "tpex": tpx_close,
            "inst": {"f": inst_f, "t": inst_t, "d": inst_d},
            "cum": {"f": cum_f, "t": cum_t, "d": cum_d},
            "margin_money": margin_money, "margin_chg": margin_chg,
            "amount": amount_yi, "kpi": kpi, "recent5": recent5}

# ---------------------------------------------------------------- 全市場歷史 (資金流完整窗)
hist = {}          # sid -> {date -> row dict}(載入 DFLOW 全窗供時間視窗/動畫/自訂日期用)
D21 = dates_all[-21:]
for row in q("""SELECT date,stock_id,market,name,close,chg,volume,amount,foreign_net,trust_net,dealer_net,total_net,
                margin_bal,margin_prev,short_bal,short_prev FROM mkt_daily WHERE date>=?""", DFLOW[0]):
    d, sid = row[0], row[1]
    hist.setdefault(sid, {})[d] = {
        "market": row[2], "name": row[3], "close": row[4], "chg": row[5], "volume": row[6], "amount": row[7],
        "f": row[8], "t": row[9], "dl": row[10], "tot": row[11],
        "mb": row[12], "mp": row[13], "sb": row[14], "sp": row[15]}

def is_etf(sid): return sid.startswith("00")

tdcc_dates = [r[0] for r in q("SELECT DISTINCT date FROM tdcc ORDER BY date")]
td_last, td_prev = ({}, {})
if tdcc_dates:
    td_last = {r[0]: (r[1], r[2]) for r in q("SELECT stock_id,pct400,pct1000 FROM tdcc WHERE date=?", tdcc_dates[-1])}
    if len(tdcc_dates) > 1:
        td_prev = {r[0]: (r[1], r[2]) for r in q("SELECT stock_id,pct400,pct1000 FROM tdcc WHERE date=?", tdcc_dates[-2])}

def tdcc_of(sid):
    cur = td_last.get(sid)
    if not cur: return None, None
    prev = td_prev.get(sid)
    chg = r2(cur[0] - prev[0]) if prev else None
    return r2(cur[0]), chg

# ---------------------------------------------------------------- 類股輪動
EXCLUDE_INDS = {"ETF", "ETN", "指數投資證券(ETN)", "存託憑證", "受益證券", "Index", "大盤"}

def sector_agg(window):
    agg = {}
    for sid, days in hist.items():
        if is_etf(sid): continue
        ind = info.get(sid, (None, "其他", None))[1]
        if ind in EXCLUDE_INDS: continue
        for d in window:
            r = days.get(d)
            if not r or r["tot"] is None or r["close"] is None: continue
            a = agg.setdefault(ind, {"net": 0.0, "amount": 0.0, "up": 0, "down": 0, "stocks": []})
            net_yi = r["tot"] * r["close"] / 1e8
            a["net"] += net_yi
            if d == LAST:
                a["amount"] += (r["amount"] or 0) / 1e8
                if (r["chg"] or 0) > 0: a["up"] += 1
                elif (r["chg"] or 0) < 0: a["down"] += 1
                a["stocks"].append((sid, r["name"], net_yi, (r["chg"] / (r["close"] - r["chg"]) * 100) if r["chg"] is not None and r["close"] and r["close"] != r["chg"] else None))
    return agg

agg_today = sector_agg([LAST])
agg5 = sector_agg(L5)
agg20 = sector_agg(L20)

sectors = []
for ind, a in agg_today.items():
    tops = sorted(a["stocks"], key=lambda x: -abs(x[2]))[:3]
    sectors.append({"ind": ind, "net": r1(a["net"]), "net5": r1(agg5.get(ind, {}).get("net", 0)),
                    "net20": r1(agg20.get(ind, {}).get("net", 0)),
                    "amount": r1(a["amount"]), "up": a["up"], "down": a["down"],
                    "top": [{"sid": s, "name": n, "net": r1(v), "chg_pct": r2(cp)} for s, n, v, cp in tops]})
sectors.sort(key=lambda x: -(x["net"] or 0))

# ---------------------------------------------------------------- 全市場掃描
scan_cfg = CONFIG.get("scanner", {})
MIN_AMT = scan_cfg.get("min_amount", 5e7)
TOPN = scan_cfg.get("top_n", 30)

def streak_of(days, key):
    c = 0
    for d in reversed(D21):
        r = days.get(d)
        v = r.get(key) if r else None
        if v is not None and v > 0: c += 1
        else: break
    return c

universe = []
for sid, days in hist.items():
    r = days.get(LAST)
    if not r: continue
    if scan_cfg.get("exclude_etf", True) and is_etf(sid): continue
    if (r["amount"] or 0) < MIN_AMT or not r["close"]: continue
    prev_close = (r["close"] - r["chg"]) if r["chg"] is not None else None
    chg_pct = r2(r["chg"] / prev_close * 100) if prev_close else None
    f5 = sum((days.get(d, {}).get("f") or 0) for d in L5)
    t5 = sum((days.get(d, {}).get("t") or 0) for d in L5)
    net5_yi = sum(((days.get(d, {}).get("tot") or 0) * (days.get(d, {}).get("close") or 0)) for d in L5) / 1e8
    net20_yi = sum(((days.get(d, {}).get("tot") or 0) * (days.get(d, {}).get("close") or 0)) for d in L20) / 1e8
    amt5 = sum((days.get(d, {}).get("amount") or 0) for d in L5)
    conc5 = (sum(((days.get(d, {}).get("tot") or 0) * (days.get(d, {}).get("close") or 0)) for d in L5) / amt5 * 100) if amt5 > 0 else None
    mb, mp5 = r["mb"], days.get(prev5_anchor, {}).get("mb")
    m_chg5 = (mb - mp5) if (mb is not None and mp5 is not None) else None
    m_chg5_pct = r2(m_chg5 / mp5 * 100) if (m_chg5 is not None and mp5) else None
    p400, p400c = tdcc_of(sid)
    universe.append({
        "sid": sid, "name": r["name"] or info.get(sid, ("", "", ""))[0], "market": r["market"],
        "ind": info.get(sid, (None, "其他", None))[1],
        "close": r2(r["close"]), "chg_pct": chg_pct, "amount_yi": r1((r["amount"] or 0) / 1e8),
        "fs": streak_of(days, "f"), "ts": streak_of(days, "t"),
        "f5_z": rint(f5 / 1000), "t5_z": rint(t5 / 1000),
        "net5_yi": r1(net5_yi), "net20_yi": r1(net20_yi), "conc5": r2(conc5),
        "mb": rint(mb), "m_chg5": rint(m_chg5), "m_chg5_pct": m_chg5_pct,
        "p400": p400, "p400c": p400c})

def topk(items, key, reverse=True, flt=None, n=TOPN):
    xs = [x for x in items if (flt is None or flt(x)) and x.get(key) is not None]
    return sorted(xs, key=lambda x: x[key], reverse=reverse)[:n]

scanner = {
    "date": LAST, "min_amt_yi": r1(MIN_AMT / 1e8), "universe_n": len(universe),
    "foreign_streak": topk([dict(x, sort2=x["net5_yi"]) for x in universe], "fs", flt=lambda x: x["fs"] >= 3,
                           n=TOPN),
    "trust_streak": topk(universe, "ts", flt=lambda x: x["ts"] >= 3, n=TOPN),
    "net5_top": topk(universe, "net5_yi", n=TOPN),
    "net5_bottom": topk(universe, "net5_yi", reverse=False, n=TOPN),
    "conc_top": topk(universe, "conc5", flt=lambda x: (x["net5_yi"] or 0) > 0, n=TOPN),
    "margin_up": topk(universe, "m_chg5_pct", flt=lambda x: (x["m_chg5"] or 0) > 0 and (x["mb"] or 0) >= 1000, n=TOPN),
    "margin_down": topk(universe, "m_chg5_pct", reverse=False, flt=lambda x: (x["m_chg5"] or 0) < 0 and (x["mb"] or 0) >= 1000, n=TOPN),
}
# 連買排行以連買天數為主鍵、5日買超金額為次鍵
scanner["foreign_streak"].sort(key=lambda x: (-x["fs"], -(x["net5_yi"] or 0)))
scanner["trust_streak"].sort(key=lambda x: (-x["ts"], -(x["net5_yi"] or 0)))

# ---------------------------------------------------------------- 自選股
def series_map(table, cols):
    out = {}
    for row in q(f"SELECT date,stock_id,{cols} FROM {table} WHERE date>=?", D120[0]):
        out.setdefault(row[1], {})[row[0]] = row[2:]
    return out

wp = series_map("watch_price", "open,high,low,close,spread,volume,amount")
wi = series_map("watch_inst", "foreign_net,trust_net,dealer_net")
wm = series_map("watch_margin", "margin_bal,short_bal")
wf = series_map("watch_foreign", "ratio")
ws = series_map("watch_sbl", "sbl_bal")
wd = series_map("watch_daytrade", "dt_volume,dt_buy,dt_sell")

# 大小單分解(sponsor 解鎖後才有資料)
bs_map = {}
try:
    for row in q("SELECT date,stock_id,xl_buy,xl_sell,big_buy,big_sell,sm_buy,sm_sell FROM bigsmall_daily"):
        bs_map.setdefault(row[1], {})[row[0]] = row[2:]
except Exception:
    pass

watch = []
for sid in CONFIG["watchlist"]:
    nm, ind, mkt = info.get(sid, (sid, "其他", None))
    p, ins = wp.get(sid, {}), wi.get(sid, {})
    close_s = [r2(p[d][3]) if d in p else None for d in D120]
    f_z = [r1((ins[d][0] or 0) / 1000) if d in ins else None for d in D120]
    t_z = [r1((ins[d][1] or 0) / 1000) if d in ins else None for d in D120]
    # 散戶 proxy:融資餘額日增減(張)
    wm_s = wm.get(sid, {})
    m_z = []
    _pv = None
    for d in D120:
        cur = wm_s.get(d)
        cur = cur[0] if cur else None
        m_z.append(r1(cur - _pv) if (cur is not None and _pv is not None) else None)
        if cur is not None:
            _pv = cur
    lastp = p.get(LAST)
    chg = lastp[4] if lastp else None
    close = lastp[3] if lastp else None
    prev = (close - chg) if (close is not None and chg is not None) else None
    ratio_now = wf.get(sid, {}).get(LAST)
    ratio_20 = wf.get(sid, {}).get(prev20_anchor)
    mb_now = wm.get(sid, {}).get(LAST)
    mb_5 = wm.get(sid, {}).get(prev5_anchor)
    sbl_now = ws.get(sid, {}).get(LAST)
    sbl_5 = ws.get(sid, {}).get(prev5_anchor)
    dt_pct = None
    for d in reversed(D120):
        r = wd.get(sid, {}).get(d)
        if r and (r[0] or 0) > 0 and d in p and (p[d][5] or 0) > 0:
            dt_pct = r2(r[0] / p[d][5] * 100)
            break
    fstreak = tstreak = 0
    for d in reversed(D120):
        v = ins.get(d)
        if v and (v[0] or 0) > 0: fstreak += 1
        else: break
    for d in reversed(D120):
        v = ins.get(d)
        if v and (v[1] or 0) > 0: tstreak += 1
        else: break
    net5_z = sum(sum(x or 0 for x in ins[d]) for d in L5 if d in ins) / 1000
    net20_z = sum(sum(x or 0 for x in ins[d]) for d in L20 if d in ins) / 1000
    p400, p400c = tdcc_of(sid)
    bs = None
    if sid in bs_map:
        bdates = sorted(bs_map[sid])[-20:]
        bs = {"dates": bdates,
              "big": [r2((bs_map[sid][d][0] + bs_map[sid][d][2] - bs_map[sid][d][1] - bs_map[sid][d][3]) / 1e8) for d in bdates],
              "sm":  [r2((bs_map[sid][d][4] - bs_map[sid][d][5]) / 1e8) for d in bdates]}
    watch.append({
        "sid": sid, "name": nm, "ind": ind, "market": mkt, "bs": bs,
        "dates": D120, "close": close_s, "f_z": f_z, "t_z": t_z, "m_z": m_z,
        "kpi": {"close": r2(close), "chg": r2(chg), "chg_pct": r2(chg / prev * 100) if prev else None,
                "ratio": r2(ratio_now[0]) if ratio_now else None,
                "ratio_chg20": r2(ratio_now[0] - ratio_20[0]) if (ratio_now and ratio_20) else None,
                "mb": rint(mb_now[0]) if mb_now else None,
                "mb_chg5": rint(mb_now[0] - mb_5[0]) if (mb_now and mb_5 and mb_now[0] is not None and mb_5[0] is not None) else None,
                "sbl_z": rint((sbl_now[0] or 0) / 1000) if sbl_now else None,
                "sbl_chg5_z": rint(((sbl_now[0] or 0) - (sbl_5[0] or 0)) / 1000) if (sbl_now and sbl_5) else None,
                "dt_pct": dt_pct, "fs": fstreak, "ts": tstreak,
                "net5_z": rint(net5_z), "net20_z": rint(net20_z),
                "p400": p400, "p400c": p400c}})

# ---------------------------------------------------------------- 金流總覽
FG = CONFIG.get("etf_groups", {})

amt_all = []
for d in dates_all:
    a = (sget(idx, (d, "TAIEX"), 2) or 0) + (sget(idx, (d, "TPEx"), 2) or 0)
    amt_all.append(a / 1e8 if a else None)

def roll(series, n):
    out = []
    for i in range(len(series)):
        w = [x for x in series[max(0, i - n + 1):i + 1] if x]
        out.append(r1(sum(w) / len(w)) if w else None)
    return out

amt20_all, amt60_all = roll(amt_all, 20), roll(amt_all, 60)
amount_today = amt_all[-1]
vs20 = r1((amount_today / amt20_all[-1] - 1) * 100) if (amount_today and amt20_all[-1]) else None

# --- 成交金額前 20 個股(排除 ETF)
tv = []
for sid, days in hist.items():
    if is_etf(sid):
        continue
    r = days.get(LAST)
    if not r or not r.get("amount") or not r.get("close"):
        continue
    h20 = [days[d]["amount"] for d in D21[:-1] if d in days and days[d].get("amount")]
    avg20 = (sum(h20) / len(h20)) if h20 else None
    prev_close = (r["close"] - r["chg"]) if r["chg"] is not None else None
    tv.append({
        "sid": sid, "name": r["name"], "market": r["market"], "ind": info.get(sid, (None, "其他", None))[1],
        "close": r2(r["close"]), "chg_pct": r2(r["chg"] / prev_close * 100) if prev_close else None,
        "amount_yi": r1(r["amount"] / 1e8),
        "pct_mkt": r2(r["amount"] / 1e8 / amount_today * 100) if amount_today else None,
        "vol_ratio": r2(r["amount"] / avg20) if avg20 else None,
        "net_yi": r1((r["tot"] or 0) * r["close"] / 1e8),
        "fs": streak_of(days, "f"), "ts": streak_of(days, "t")})
tv.sort(key=lambda x: -(x["amount_yi"] or 0))
turnover_top = tv[:20]

# --- ETF 資金流(依 config 分組)
td_shares_last, td_shares_prev = {}, {}
if tdcc_dates:
    td_shares_last = {r[0]: r[1] for r in q("SELECT stock_id,total_shares FROM tdcc WHERE date=?", tdcc_dates[-1])}
    if len(tdcc_dates) > 1:
        td_shares_prev = {r[0]: r[1] for r in q("SELECT stock_id,total_shares FROM tdcc WHERE date=?", tdcc_dates[-2])}

def etf_row(sid):
    days = hist.get(sid, {})
    r = days.get(LAST)
    if not r or r.get("close") is None:
        return None
    prev_close = (r["close"] - r["chg"]) if r["chg"] is not None else None
    a5 = [days[d]["amount"] for d in L5 if d in days and days[d].get("amount")]
    net5 = sum(((days.get(d, {}).get("tot") or 0) * (days.get(d, {}).get("close") or 0)) for d in L5) / 1e8
    mb, mp5 = r.get("mb"), days.get(prev5_anchor, {}).get("mb")
    u_now, u_prev = td_shares_last.get(sid), td_shares_prev.get(sid)
    return {
        "sid": sid, "name": r["name"], "close": r2(r["close"]),
        "chg_pct": r2(r["chg"] / prev_close * 100) if prev_close else None,
        "amount_yi": r1((r["amount"] or 0) / 1e8),
        "amt5_yi": r1(sum(a5) / len(a5) / 1e8) if a5 else None,
        "net_yi": r1((r["tot"] or 0) * r["close"] / 1e8), "net5_yi": r1(net5),
        "m_chg5": rint(mb - mp5) if (mb is not None and mp5 is not None) else None,
        "units_wow": r2((u_now / u_prev - 1) * 100) if (u_now and u_prev) else None}

etf_groups_out = []
for gname, sids in FG.items():
    rows = [x for x in (etf_row(s) for s in sids) if x]
    if not rows:
        continue
    etf_groups_out.append({
        "name": gname, "rows": rows,
        "sum": {"amount_yi": r1(sum(x["amount_yi"] or 0 for x in rows)),
                "amt5_yi": r1(sum(x["amt5_yi"] or 0 for x in rows)),
                "net_yi": r1(sum(x["net_yi"] or 0 for x in rows)),
                "net5_yi": r1(sum(x["net5_yi"] or 0 for x in rows))}})

def group_sum(gname):
    for g in etf_groups_out:
        if g["name"] == gname:
            return g["sum"]
    return {}

# --- 期貨
FID_LABEL = {"TX": "台指期", "MTX": "小型台指", "TMF": "微型台指"}
fut = {}
for d, fid, contract, session, close, sp, vol, oi in q("SELECT date,fid,contract,session,close,spread_per,volume,oi FROM fut_daily"):
    f = fut.setdefault(fid, {}).setdefault(d, {"vol": 0.0, "oi": 0.0, "months": {}})
    if session != "after_market":
        f["vol"] += vol or 0
        f["oi"] += oi or 0
        if re.fullmatch(r"\d{6}", contract or ""):
            f["months"][contract] = (close, sp)

def near_of(fid, d):
    m = fut.get(fid, {}).get(d, {}).get("months", {})
    if not m:
        return None, None
    c = min(m)
    return m[c]

finst = {}
for d, fid, inst, ld, sd, lo, so, loa, soa in q("SELECT date,fid,inst,long_deal,short_deal,long_oi,short_oi,long_oi_amt,short_oi_amt FROM fut_inst"):
    finst.setdefault((fid, inst), {})[d] = {"net": (lo or 0) - (so or 0), "amt": ((loa or 0) - (soa or 0)) / 1e5,
                                            "deal_net": (ld or 0) - (sd or 0)}

fut_dates = sorted(fut.get("TX", {}).keys())
tx_close60 = [ (near_of("TX", d)[0] if d in fut.get("TX", {}) else None) for d in D60 ]
tx_fnet60 = [ (finst.get(("TX", "外資"), {}).get(d, {}) or {}).get("net") for d in D60 ]

def fut_table_row(fid):
    d_have = [d for d in sorted(fut.get(fid, {}).keys()) if fut[fid][d]["months"]]   # 只取有一般時段的日期
    if not d_have:
        return None
    d0 = d_have[-1]
    close, sp = near_of(fid, d0)
    f = fut[fid][d0]
    fi = finst.get((fid, "外資"), {})
    fdays = sorted(fi.keys())
    fnet = fi[fdays[-1]]["net"] if fdays else None
    fchg = (fi[fdays[-1]]["net"] - fi[fdays[-2]]["net"]) if len(fdays) > 1 else None
    return {"fid": fid, "label": FID_LABEL.get(fid, fid), "close": r2(close), "chg_pct": r2(sp),
            "volume": rint(f["vol"]), "oi": rint(f["oi"]),
            "f_net": rint(fnet) if fnet is not None else None, "f_net_chg": rint(fchg) if fchg is not None else None}

fut_idx_table = [x for x in (fut_table_row(f) for f in CONFIG["futures"]["index"]) if x]

inst_tx_table = []
for inst in ("外資", "投信", "自營商"):
    m = finst.get(("TX", inst), {})
    dd = sorted(m.keys())
    if not dd:
        continue
    net = m[dd[-1]]["net"]
    chg = net - m[dd[-2]]["net"] if len(dd) > 1 else None
    inst_tx_table.append({"inst": inst, "net": rint(net), "chg": rint(chg) if chg is not None else None,
                          "amt_yi": r1(m[dd[-1]]["amt"])})

sf_date = (q("SELECT MAX(date) FROM stockfut_daily") or [(None,)])[0][0]
stockfut_top = []
if sf_date:
    fmap_names = {r[0]: (r[1], r[2]) for r in q("SELECT code || 'F', name, unit FROM fut_map")}
    for code, sid, vol, val, cn in q("SELECT code,stock_id,volume,value,close_near FROM stockfut_daily WHERE date=? ORDER BY value DESC LIMIT 10", sf_date):
        spot = hist.get(sid, {}).get(LAST, {})
        prev_close = (spot.get("close") - spot.get("chg")) if spot.get("close") is not None and spot.get("chg") is not None else None
        fm_name, fm_unit = fmap_names.get(code, (None, None))
        disp = (fm_name or spot.get("name") or sid) + ("(小型)" if fm_unit == 100 else "")
        stockfut_top.append({
            "code": code, "sid": sid, "name": disp,
            "close": r2(cn), "volume": rint(vol), "value_yi": r1(val / 1e8),
            "spot_chg_pct": r2(spot["chg"] / prev_close * 100) if prev_close else None,
            "spot_net_yi": r1((spot.get("tot") or 0) * (spot.get("close") or 0) / 1e8) if spot else None})

# --- 匯率
fx_mid = {r[0]: (r[1] + r[2]) / 2 for r in q("SELECT date,spot_buy,spot_sell FROM fx_daily") if r[1] and r[2]}
fx60 = [round(fx_mid[d], 3) if d in fx_mid else None for d in D60]
fx_days_sorted = sorted(fx_mid)
fx_recent5 = []
for d in reversed(L5):
    mid = fx_mid.get(d)
    prevs = [x for x in fx_days_sorted if x < d]
    chg = (mid - fx_mid[prevs[-1]]) if (mid and prevs) else None
    a = inst_by_date.get(d, {})
    fx_recent5.append({"date": d, "mid": round(mid, 3) if mid else None, "chg": round(chg, 3) if chg is not None else None,
                       "f_net_yi": r1(a.get("f", 0) / 1e8) if a else None})

usd_now = fx60[-1] if fx60 else None
usd_prev_days = [x for x in fx_days_sorted if x < LAST]
usd_chg = round(fx_mid[LAST] - fx_mid[usd_prev_days[-1]], 3) if (LAST in fx_mid and usd_prev_days) else None

# --- 現金停泊訊號
inv_sum, lev_sum, bond_sum = group_sum("反向"), group_sum("槓桿 2X"), group_sum("債券 ETF")
margin60_pct = r1((margin_money[-1] / margin_money[0] - 1) * 100) if (margin_money and margin_money[0] and margin_money[-1]) else None

# --- 類別淨流向(仿美股金流板)
FC = CONFIG.get("flow_categories", {})
cat_of = {}
for cname, sids in FC.items():
    for s in sids:
        cat_of[s] = cname

def net_of(sid, d=LAST):
    r = hist.get(sid, {}).get(d)
    if not r or r.get("tot") is None or r.get("close") is None:
        return None
    return r["tot"] * r["close"] / 1e8

stock_net = 0.0
stock_n = 0
for sid in hist:
    if is_etf(sid):
        continue
    v = net_of(sid)
    if v is not None:
        stock_net += v
        stock_n += 1

wl_set = set(CONFIG["watchlist"])
intruders = [x for x in turnover_top if x["sid"] not in wl_set]
intr_net = sum(x["net_yi"] or 0 for x in intruders)
intr_sids = {x["sid"] for x in intruders}

flow_cats = [{"name": "正股", "net": r1(stock_net), "n": stock_n}]
etf_cat_sum, etf_cat_n = 0.0, 0
for cname, sids in FC.items():
    vals = [(s, net_of(s)) for s in sids]
    vals = [(s, v) for s, v in vals if v is not None]
    if not vals:
        continue
    tot = sum(v for _, v in vals)
    etf_cat_sum += tot
    etf_cat_n += len(vals)
    flow_cats.append({"name": cname, "net": r1(tot), "n": len(vals)})
all_etf_net, all_etf_n = 0.0, 0
for sid in hist:
    if not is_etf(sid):
        continue
    v = net_of(sid)
    if v is not None:
        all_etf_net += v
        all_etf_n += 1
flow_cats.append({"name": "其他ETF(未分類)", "net": r1(all_etf_net - etf_cat_sum), "n": all_etf_n - etf_cat_n})
flow_cats.append({"name": "闖入(Top20非自選)", "net": r1(intr_net), "n": len(intruders), "intr": True})
residual = -(stock_net + all_etf_net)   # 闖入為正股子集合,不重複計入;殘差=法人在可觀測市場之外的淨部位

# --- Sankey:三大法人資金輪動(個股+ETF 實體層級)
ents = []
for sid, days in hist.items():
    r = days.get(LAST)
    if not r or (r.get("amount") or 0) < 1e8:
        continue
    v = net_of(sid)
    if v is None or abs(v) < 3:      # 淨買賣 ≥3 億才進輪動圖
        continue
    if is_etf(sid):
        cat = cat_of.get(sid, "其他ETF")
    else:
        cat = "闖入" if sid in intr_sids else "正股"
    ents.append({"sid": sid, "label": (r.get("name") or sid), "cat": cat, "v": r1(v)})

sk_out = sorted([e for e in ents if e["v"] < 0], key=lambda x: x["v"])
sk_in = sorted([e for e in ents if e["v"] > 0], key=lambda x: -x["v"])
TOP_SK = 14
sk_out_top, sk_out_rest = sk_out[:TOP_SK], sk_out[TOP_SK:]
sk_in_top, sk_in_rest = sk_in[:TOP_SK], sk_in[TOP_SK:]
sankey = {
    "out": sk_out_top, "in": sk_in_top,
    "out_other": {"n": len(sk_out_rest), "v": r1(sum(e["v"] for e in sk_out_rest))},
    "in_other": {"n": len(sk_in_rest), "v": r1(sum(e["v"] for e in sk_in_rest))},
}

# --- 持續性:今日金額最大的標的近 10 日淨流
D10 = dates_all[-10:]
pers_pool = sorted([e for e in ents], key=lambda x: -abs(x["v"]))[:20]
persist = []
for e in pers_pool:
    persist.append({**e, "series": [r1(net_of(e["sid"], d)) for d in D10]})

# --- 熱力圖 treemap:產業→個股(排除 ETF),面積=成交金額
hm_secs = {}
for sid, days in hist.items():
    if is_etf(sid):
        continue
    r = days.get(LAST)
    if not r or not r.get("amount") or not r.get("close"):
        continue
    ind = info.get(sid, (None, "其他", None))[1]
    prev_close = (r["close"] - r["chg"]) if r["chg"] is not None else None
    hm_secs.setdefault(ind, []).append({
        "sid": sid, "name": r["name"], "a": r1(r["amount"] / 1e8),
        "chg": r2(r["chg"] / prev_close * 100) if prev_close else None,
        "net": r1((r["tot"] or 0) * r["close"] / 1e8)})

def _hm_pack(ind, xs, per_sec=15):
    xs = sorted(xs, key=lambda x: -(x["a"] or 0))
    top, rest = xs[:per_sec], xs[per_sec:]
    if rest:
        ra = sum(x["a"] or 0 for x in rest)
        wc = (sum((x["chg"] or 0) * (x["a"] or 0) for x in rest) / ra) if ra else None
        top = top + [{"sid": "", "name": f"其他({len(rest)})", "a": r1(ra), "chg": r2(wc),
                      "net": r1(sum(x["net"] or 0 for x in rest))}]
    return {"ind": ind, "a": r1(sum(x["a"] or 0 for x in xs)), "stocks": top}

_hm_all = sorted(hm_secs.items(), key=lambda kv: -sum(x["a"] or 0 for x in kv[1]))
heat_secs = [_hm_pack(ind, xs) for ind, xs in _hm_all[:14]]
_rest_stocks = [x for _, xs in _hm_all[14:] for x in xs]
if _rest_stocks:
    heat_secs.append(_hm_pack("其他產業", _rest_stocks, per_sec=12))
_total_amt = sum(s["a"] or 0 for s in heat_secs)

# --- 自訂追蹤標的(存於 repo 的 custom_symbols.json;deploy_github.py --pull 會先同步)
_gh = CONFIG.get("github", {})
custom_syms = []
_cf = os.path.join(BASE_DIR, "repo_site", "custom_symbols.json")
if os.path.exists(_cf):
    try:
        custom_syms = [s for s in json.load(open(_cf, encoding="utf-8")) if isinstance(s, str)][:30]
        if custom_syms:
            print(f"自訂標的:{custom_syms}")
    except Exception as e:
        print("自訂標的讀取失敗(略過):", repr(e)[:100])
custom_set = set(custom_syms)

# --- 日頻資金流(照美股板 daily_flows 結構:{date:{sid:{m:機構(億), r:散戶(億), c:類別}}})
# 口徑:m=三大法人買賣超×收盤(官方盤後);r=(融資增減−融券增減)×收盤(官方盤後,信用散戶 proxy)
# 分類:config.stock_groups 自訂族群優先(電子細分),未列者依官方產業別歸入備援類別
sid2group = {}
for _g, _syms in CONFIG.get("stock_groups", {}).items():
    for _s in _syms:
        sid2group[_s] = _g

_G_IND = {
    "半導體業": "半導體其他", "電子零組件業": "零組件其他", "光電業": "面板/光學",
    "通信網路業": "網通", "電腦及週邊設備業": "電子其他", "電子通路業": "電子其他",
    "資訊服務業": "電子其他", "其他電子業": "電子其他", "其他電子類": "電子其他",
    "電子工業": "電子其他", "電子商務": "電子其他",
    "金融保險": "金融", "金融保險業": "金融", "金融業": "金融",
    "航運業": "航運", "生技醫療": "生技", "生技醫療業": "生技",
}

def stock_cat(sid):
    g = sid2group.get(sid)
    if g:
        return g
    ind = info.get(sid, (None, "其他", None))[1] or "其他"
    return _G_IND.get(ind, "傳產")

def retail_of(sid, d):
    """散戶 proxy:(Δ融資 − Δ融券)(張)×1000×收盤 → 億;無信用資料回 None"""
    row = hist.get(sid, {}).get(d)
    if not row:
        return None
    mb, mp, c = row.get("mb"), row.get("mp"), row.get("close")
    if mb is None or mp is None or c is None:
        return None
    v = (mb - mp) * 1000 * c / 1e8
    sb, sp = row.get("sb"), row.get("sp")
    if sb is not None and sp is not None:
        v -= (sb - sp) * 1000 * c / 1e8
    return v

# 期貨多空部位資金(億):三大法人「未平倉口數增減 × 每口市值(當日OI金額/口數)」
# —— 用 Δ口數計新增/減少部位的錢,排除既有部位的價格漂移;多單=+Δ多方,空單顯示 −Δ空方(加空=紅左)
_FLOW_IDX = set(CONFIG["futures"].get("flow_index", ["TX", "MTX"]))
_FLOW_STK = set(CONFIG["futures"].get("flow_stock", ["STF"]))
_fut_oi = {}
for _d, _fid, _in, _ol, _os, _al, _as in q(
        "SELECT date, fid, inst, long_oi, short_oi, long_oi_amt, short_oi_amt "
        "FROM fut_inst WHERE long_oi IS NOT NULL"):
    _fut_oi.setdefault((_fid, _in), {})[_d] = (_ol or 0, _os or 0, _al or 0, _as or 0)
fut_pos = {}
for (_fid, _in), _days in _fut_oi.items():
    grp = "idx" if _fid in _FLOW_IDX else ("stk" if _fid in _FLOW_STK else None)
    if not grp:
        continue
    _ds = sorted(_days)
    for _i in range(1, len(_ds)):
        _d, _p = _ds[_i], _ds[_i - 1]
        ol, os_, al, as_ = _days[_d]
        pol, pos_, pal, pas_ = _days[_p]
        pvL = (al / ol) if ol else ((pal / pol) if pol else None)   # 千元/口
        pvS = (as_ / os_) if os_ else ((pas_ / pos_) if pos_ else None)
        e = fut_pos.setdefault(_d, {"idxL": 0.0, "idxS": 0.0, "stkL": 0.0, "stkS": 0.0})
        if pvL is not None:
            e[grp + "L"] += (ol - pol) * pvL / 1e5
        if pvS is not None:
            e[grp + "S"] += (os_ - pos_) * pvS / 1e5

daily_flows = {}
for d in DFLOW:
    day_stocks = sorted(
        [(sid, days[d]["amount"]) for sid, days in hist.items()
         if d in days and not is_etf(sid) and (days[d].get("amount") or 0) > 0],
        key=lambda x: -x[1])
    intr_d = {sid for sid, _ in day_stocks[:20] if sid not in wl_set}
    dd = {}
    for sid, days in hist.items():
        v = net_of(sid, d)
        r = retail_of(sid, d)
        if ((v is None or abs(v) < 0.5) and (r is None or abs(r) < 0.5)
                and sid not in custom_set):        # 機構或散戶任一 ≥0.5 億才入日檔;自訂不受門檻
            continue
        cat = cat_of.get(sid, "其他ETF") if is_etf(sid) else ("闖入" if sid in intr_d else stock_cat(sid))
        e = {"m": round(v or 0.0, 1), "c": cat}
        if r is not None:
            e["r"] = round(r, 1)
        dd[sid] = e
    fp = fut_pos.get(d)
    if fp:
        for _k, _cat, _sg in (("idxL", "期貨多單(指數)", 1), ("idxS", "期貨空單(指數)", -1),
                              ("stkL", "期貨多單(個股)", 1), ("stkS", "期貨空單(個股)", -1)):
            _v = _sg * fp[_k]
            if abs(_v) >= 0.5:
                dd["_F" + _k] = {"m": round(_v, 1), "c": _cat}
    daily_flows[d] = dd

sym_names = {}
for d in daily_flows:
    for sid in daily_flows[d]:
        if sid not in sym_names:
            nm = None
            days = hist.get(sid, {})
            r = days.get(LAST) or next((days[x] for x in sorted(days, reverse=True)), None)
            if r:
                nm = r.get("name")
            sym_names[sid] = nm or info.get(sid, (sid,))[0] or sid
sym_names["_FidxL"] = "指數期貨多單(臺指+小臺+微臺,法人OI)"
sym_names["_FidxS"] = "指數期貨空單(臺指+小臺+微臺,法人OI)"
sym_names["_FstkL"] = "股票期貨多單(合計,法人OI)"
sym_names["_FstkS"] = "股票期貨空單(合計,法人OI)"

# 權證成交金額(上市)— 認購+牛證=偏多熱度、認售+熊證=偏空熱度;無買賣超,僅成交金額
_wk = {k: {d: a for d, a in q("SELECT date, amount FROM market_stat WHERE kind=? ORDER BY date", k)}
       for k in ("權證", "認購", "認售", "牛證", "熊證")}
warr_out = None
_wd = sorted(set(_wk["認購"]) & set(_wk["認售"]))
if _wd:
    def _cp(d):
        c = (_wk["認購"].get(d, 0) + _wk["牛證"].get(d, 0)) / 1e8
        p = (_wk["認售"].get(d, 0) + _wk["熊證"].get(d, 0)) / 1e8
        return c, p
    _c, _p = _cp(_wd[-1])
    _h5 = [_cp(x) for x in _wd[-6:-1]]
    warr_out = {"date": _wd[-1], "call": r1(_c), "put": r1(_p),
                "avg5c": r1(sum(x[0] for x in _h5) / len(_h5)) if _h5 else None,
                "avg5p": r1(sum(x[1] for x in _h5) / len(_h5)) if _h5 else None,
                "series": [[d, r1(_cp(d)[0]), r1(_cp(d)[1])] for d in _wd[-20:]]}
elif _wk["權證"]:
    _ws = sorted(_wk["權證"])
    _w5 = [_wk["權證"][x] / 1e8 for x in _ws[-6:-1]]
    warr_out = {"date": _ws[-1], "yi": r1(_wk["權證"][_ws[-1]] / 1e8),
                "avg5": r1(sum(_w5) / len(_w5)) if _w5 else None}

# --- 加權指數日收(供池水位圖疊圖對照;鍵=日期)
taiex_close = {d: r1(c) for d, c in q("SELECT date, close FROM index_daily WHERE index_id='TAIEX' AND close IS NOT NULL")}

# --- 期指結算週警語(每月第三個週三)
import calendar as _cal
_y, _m = int(LAST[:4]), int(LAST[5:7])
_weds = [d for d in range(1, _cal.monthrange(_y, _m)[1] + 1) if dt.date(_y, _m, d).weekday() == 2]
_settle = dt.date(_y, _m, _weds[2])
settle_note = abs((dt.date(_y, _m, int(LAST[8:])) - _settle).days) <= 3

flow = {
    "cats": flow_cats, "residual": r1(residual),
    "heat": {"sectors": heat_secs, "total_amt": r1(_total_amt)},
    "daily_flows": daily_flows, "sym_names": sym_names, "watchlist": CONFIG["watchlist"],
    "custom_symbols": custom_syms, "warrants": warr_out, "taiex": taiex_close,
    "github": {"user": _gh.get("user"), "repo": _gh.get("repo"), "branch": _gh.get("branch", "gh-pages")},
    "sankey": sankey, "persist": persist, "persist_dates": [D10[0], D10[-1]],
    "settle_note": settle_note, "settle_date": _settle.isoformat(),
    "kpi": {
        "amount_yi": r1(amount_today), "vs20": vs20,
        "usd": usd_now, "usd_chg": usd_chg,
        "tx_f_net": next((x["f_net"] for x in fut_idx_table if x["fid"] == "TX"), None),
        "tx_f_net_chg": next((x["f_net_chg"] for x in fut_idx_table if x["fid"] == "TX"), None),
        "inv_yi": inv_sum.get("amount_yi"), "inv_vs5": r2((inv_sum.get("amount_yi") / inv_sum.get("amt5_yi") - 1) * 100) if inv_sum.get("amt5_yi") else None,
        "lev_yi": lev_sum.get("amount_yi"), "lev_vs5": r2((lev_sum.get("amount_yi") / lev_sum.get("amt5_yi") - 1) * 100) if lev_sum.get("amt5_yi") else None,
        "bond_net5": bond_sum.get("net5_yi")},
    "turnover": turnover_top,
    "etf_groups": etf_groups_out,
    "futures": {"tx_close": tx_close60, "tx_fnet": tx_fnet60, "idx_table": fut_idx_table,
                "inst_tx": inst_tx_table, "stockfut": stockfut_top, "sf_date": sf_date},
    "fx": {"series": fx60, "recent5": fx_recent5},
    "cash": {"amt": amount_yi, "amt20": amt20_all[-60:], "amt60": amt60_all[-60:],
             "margin60_pct": margin60_pct,
             "bond5_net": bond_sum.get("net5_yi"), "bond5_amt": bond_sum.get("amt5_yi")},
}

# ---------------------------------------------------------------- 熱錢羅盤(spec v1.0/v1.1)
HM = CONFIG.get("hotmoney", {})
fx_days_all = sorted(fx_mid)

def fx_chg_of(d):
    """台幣升貶%:正 = 台幣升值 = 資金流入方向"""
    if d not in fx_mid:
        return None
    prevs = [x for x in fx_days_all if x < d]
    if not prevs:
        return None
    p = fx_mid[prevs[-1]]
    return (p - fx_mid[d]) / p * 100

cbc = {}
for m, item, v in q("SELECT month,item,value FROM cbc_monthly"):
    cbc.setdefault(item, {})[m] = v
spot_vol = cbc.get("fx_spot_musd", {})
vol_months = sorted(spot_vol)

def vol_of(d):
    """該日所屬月份之央行「日平均即期外匯交易量」(億美元);無當月則沿用最近一期"""
    m = d[:7]
    if m in spot_vol:
        return spot_vol[m] / 100.0
    prior = [x for x in vol_months if x <= m]
    return (spot_vol[prior[-1]] / 100.0) if prior else None

def S_of(d):
    c, v = fx_chg_of(d), vol_of(d)
    return None if (c is None or v is None) else c * v

# 月度校正:k = 金管會上月淨匯入 ÷ ΣS(上月)
fsc = HM.get("fsc_net_inflow_usd_100m", {})
cal_month = max(fsc) if fsc else None
k_coef, sigmaS, cal_note = None, None, None
if cal_month:
    svals = [s for s in (S_of(d) for d in dates_all if d[:7] == cal_month) if s is not None]
    if svals:
        sigmaS = sum(svals)
        if abs(sigmaS) >= 0.1 * sum(abs(s) for s in svals) and sigmaS != 0:
            k_coef = fsc[cal_month] / sigmaS
if k_coef is not None and k_coef <= 0:
    cal_note = f"{cal_month} 官方淨匯入(+{fsc[cal_month]})與匯率方向(ΣS={round(sigmaS,1)})背離 — 資金匯入但停泊未買股,k<0 無效 → 本月分級顯示。背離本身即重要訊號。"
    k_coef = None
graded = k_coef is None
if graded and cal_note is None:
    cal_note = "訊號不足無法校正 → 分級顯示"
try:
    json.dump({"month": cal_month, "N_M": fsc.get(cal_month), "sigma_S": sigmaS, "k": k_coef,
               "source": (HM.get("fsc_sources") or [None])[0], "graded": graded},
              open(os.path.join(BASE_DIR, "data", "calibration.json"), "w", encoding="utf-8"), ensure_ascii=False)
except Exception:
    pass

# 近 20 交易日氣泡
S60 = [abs(s) for s in (S_of(d) for d in D60) if s is not None]
S60_sorted = sorted(S60)
def s_grade(s):
    if s is None or not S60_sorted:
        return None
    import bisect
    p = bisect.bisect_left(S60_sorted, abs(s)) / max(1, len(S60_sorted))
    return "強" if p >= 0.85 else ("中" if p >= 0.5 else "弱")

vols60 = sorted(v for v in (vol_of(d) for d in D60) if v is not None)
def r_of(d):
    v = vol_of(d)
    if v is None or not vols60:
        return 10
    import bisect
    pct = bisect.bisect_left(vols60, v) / max(1, len(vols60))
    return min(22, round(6 + 12 * pct))

TH_NB = HM.get("judge_min_netbuy_yi", 50)
TH_FX = HM.get("judge_min_fxchg_pct", 0.05)
def quad_of(nb, c):
    if nb is None or c is None or abs(nb) < TH_NB or abs(c) < TH_FX:
        return "中性觀望"
    if nb > 0 and c > 0: return "熱錢流入買股"
    if nb < 0 and c > 0: return "賣股、錢停泊在台"
    if nb < 0 and c < 0: return "賣股+匯出境外"
    return "買股、資金仍外流"

HOT20 = dates_all[-20:]
hot_pts = []
for d in HOT20:
    nb = inst_by_date.get(d, {}).get("f")
    nb = nb / 1e8 if nb is not None else None
    c, s = fx_chg_of(d), S_of(d)
    hot_pts.append({"d": d, "x": r1(nb), "y": r2(c), "r": r_of(d),
                    "vol": r1(vol_of(d)), "S": r2(s),
                    "f": r2(k_coef * s) if (k_coef is not None and s is not None) else None,
                    "g": s_grade(s), "quad": quad_of(nb, c)})
max_nb60 = max([abs(inst_by_date.get(d, {}).get("f", 0) or 0) / 1e8 for d in D60] + [1])
max_fx60 = max([abs(fx_chg_of(d) or 0) for d in D60] + [0.01])
hot_xr = max(450, round(max_nb60 * 1.2))
hot_yr = max(0.3, round(max_fx60 * 1.2, 2))

# 外資買賣超連 N 日
f_streak = 0
_sig = 0
for d in reversed(dates_all):
    v = inst_by_date.get(d, {}).get("f")
    if v is None or v == 0:
        break
    s = 1 if v > 0 else -1
    if _sig == 0:
        _sig = s
    if s != _sig:
        break
    f_streak += 1
f_streak *= _sig   # 正=連買、負=連賣

# 現金池(月頻)
ftw = cbc.get("foreign_twd_yi", {})
ftw_m = sorted(ftw)[-24:]
draw = {m: v for m, v in sorted(HM.get("drawdown_deposits_yi", {}).items())}
draw_m = sorted(draw)
def with_chg(series_months, getv):
    out = []
    prev = None
    for m in series_months:
        v = getv(m)
        out.append({"m": m, "v": r1(v), "chg": r1(v - prev) if prev is not None else None})
        prev = v
    return out
pool_foreign = with_chg(ftw_m, lambda m: ftw[m])
pool_draw = with_chg(draw_m, lambda m: draw[m])

# 池 vs 指數 四組合判讀(以劃撥池最新月為準)
pool_read = None
if pool_draw and pool_draw[-1]["chg"] is not None:
    pm = pool_draw[-1]["m"]
    closes_in = [ (d, sget(idx,(d,"TAIEX"),0)) for d in dates_all if d[:7] == pm and sget(idx,(d,"TAIEX"),0) ]
    closes_prev = [ (d, sget(idx,(d,"TAIEX"),0)) for d in dates_all if d[:7] < pm and sget(idx,(d,"TAIEX"),0) ]
    if closes_in and closes_prev:
        chg_idx = closes_in[-1][1] - closes_prev[-1][1]
        up_pool, up_idx = pool_draw[-1]["chg"] > 0, chg_idx > 0
        pool_read = {"month": pm, "pool_chg": pool_draw[-1]["chg"], "idx_chg": r1(chg_idx),
                     "label": ("資金行情(池升+指數升)" if up_pool and up_idx else
                               "囤彈避險,潛在買盤(池升+指數跌)" if up_pool and not up_idx else
                               "最後進場的乾柴(池降+指數升)" if not up_pool and up_idx else
                               "錢正在離開股市系統(池降+指數跌)→ 看羅盤是否連台灣都離開")}

hot = {
    "pts": hot_pts, "xr": hot_xr, "yr": hot_yr,
    "today": {**hot_pts[-1], "usd": usd_now, "usd_chg": usd_chg, "streak": f_streak,
              "tx_oi_chg": flow["kpi"]["tx_f_net_chg"], "tx_oi": flow["kpi"]["tx_f_net"]},
    "graded": graded,
    "vol_latest": {"month": vol_months[-1] if vol_months else None,
                   "v_yi": r1(spot_vol[vol_months[-1]] / 100.0) if vol_months else None},
    "cal": {"month": cal_month, "N": fsc.get(cal_month), "sigmaS": r2(sigmaS),
            "k": round(k_coef, 4) if k_coef is not None else None, "note": cal_note,
            "src": (HM.get("fsc_sources") or [None])[0], "series": fsc},
    "pools": {"foreign": pool_foreign, "draw": pool_draw,
              "draw_note": HM.get("drawdown_note", ""), "read": pool_read},
    "flow_today": {"net_buy": hot_pts[-1]["x"], "f_hat": hot_pts[-1]["f"], "grade": hot_pts[-1]["g"],
                   "margin_chg": margin_chg[-1] if margin_chg else None},
}

# ---------------------------------------------------------------- 組 payload
payload = {
    "meta": {"last_date": LAST, "generated_at": dt.datetime.now(TPE).strftime("%Y-%m-%d %H:%M"),
             "snapshot_days": len(set(d for s in hist.values() for d in s)),
             "tdcc_dates": tdcc_dates[-4:], "watchlist": CONFIG["watchlist"]},
    "overview": overview, "sectors": sectors, "scanner": scanner, "watch": watch, "flow": flow, "hot": hot,
}

PAYLOAD_JSON = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")

TEMPLATE = open(os.path.join(BASE_DIR, "dashboard_template.html"), encoding="utf-8").read()
def _asset(name):
    return open(os.path.join(BASE_DIR, "assets", name), encoding="utf-8").read()
html = (TEMPLATE.replace("__PLOTLY__", _asset("plotly.min.js"))
        .replace("__CHARTJS__", _asset("chart.umd.js"))
        .replace("__ECHARTS__", _asset("echarts.min.js"))
        .replace("__PAYLOAD__", PAYLOAD_JSON))
with open(OUT_PATH, "w", encoding="utf-8") as f:
    f.write(html)
print(f"OK dashboard.html ({len(html)//1024} KB), 資料日期 {LAST}, 全市場 {len(universe)} 檔進掃描")
