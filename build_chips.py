#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""籌碼駕駛艙分檔資料產生器 —— 每檔一個 chips/<sid>.json

為什麼獨立成檔而不 inline 進 index.html:
  15 檔 × ~1850 根日K × 15 條序列 ≈ 每檔 250KB raw。全部內嵌會讓 3.5MB 的頁面再漲 3MB+。
  照美股板 kline_max_SYM.json 的模式,推到專用 chips 分支(force-push 單一 commit),
  網頁端 fetch('https://raw.githubusercontent.com/<user>/<repo>/chips/<sid>.json?v=<buster>')。
  raw.githubusercontent.com 已驗證:CORS `*`、content-encoding: gzip、cache-control 300s。

編碼原則(為了體積,同時保持可讀):
  - 日期用 YYYYMMDD 整數
  - 價格存「未還原」原值(對得上看盤軟體),另給還原因子 af[](僅在除權息日改變 → 變化點編碼)
    前端:還原價 = c[i] * af[i];總表顯示價 = c[i]
  - 量還原因子 vf[] 只有配股/分割/減資才 ≠1;全 1 時整個欄位省略
  - 量統一「張」(1 張 = 1000 股),金額統一「百萬元」
用法:
  python3 build_chips.py            # 產出 chips/ 全部自選股 + _index.json
  python3 build_chips.py 2330       # 只產一檔(除錯用)
"""
import datetime as dt, hashlib, json, os, sqlite3, sys
from zoneinfo import ZoneInfo

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "data", "funds.db")
OUT_DIR = os.path.join(BASE, "chips")
CONFIG = json.load(open(os.path.join(BASE, "config.json"), encoding="utf-8"))
TPE = ZoneInfo("Asia/Taipei")
CHIP_INDEX = "TAIEX"
JSON_DAYS = int(CONFIG.get("chip_json_days", 900))

conn = sqlite3.connect(DB_PATH)


def di(d):
    return int(d.replace("-", ""))


def rd(v, n=2):
    return None if v is None else round(v, n)


def runs(vals, n=6):
    """變化點編碼:[[起始索引, 值], ...];全同值 → [[0, v]]"""
    out, prev = [], object()
    for i, v in enumerate(vals):
        v = None if v is None else round(v, n)
        if v != prev:
            out.append([i, v])
            prev = v
    return out


def series(table, cols, sid, dates):
    """把表拉成與 dates 對齊的 list-of-tuple(缺日補 None)"""
    m = {r[0]: r[1:] for r in
         conn.execute(f"SELECT date,{cols} FROM {table} WHERE stock_id=? ORDER BY date", (sid,))}
    k = len(cols.split(","))
    return [m.get(d, (None,) * k) for d in dates]


def col(rows, i, scale=1.0, nd=1):
    return [None if r[i] is None else round(r[i] * scale, nd) for r in rows]


# ---------------------------------------------------------------- 加權指數(全檔共用)
_idx_rows = conn.execute(
    "SELECT date,open,high,low,close,volume,amount FROM chip_price WHERE stock_id=? ORDER BY date",
    (CHIP_INDEX,)).fetchall()
IDX = {r[0]: r for r in _idx_rows}


def monthly(sid):
    """全史月K(供全史月K圖與季節性矩陣);用還原價,除權息不會製造假月報酬"""
    rows = conn.execute(
        "SELECT p.date,p.open,p.high,p.low,p.close,p.volume,COALESCE(a.adj_f,1.0) "
        "FROM chip_price p LEFT JOIN chip_adj a ON a.date=p.date AND a.stock_id=p.stock_id "
        "WHERE p.stock_id=? ORDER BY p.date", (sid,)).fetchall()
    out, cur = [], None
    for d, o, h, l, c, v, f in rows:
        ym = int(d[:4]) * 100 + int(d[5:7])
        if o is None or c is None:
            continue
        if not cur or cur[0] != ym:
            cur = [ym, o * f, h * f, l * f, c * f, v or 0]
            out.append(cur)
        else:
            cur[2] = max(cur[2], h * f); cur[3] = min(cur[3], l * f)
            cur[4] = c * f; cur[5] += (v or 0)
    return [[m[0], rd(m[1]), rd(m[2]), rd(m[3]), rd(m[4]), round(m[5] / 1e3, 1)] for m in out]


def build_one(sid, name):
    dates_all = [r[0] for r in conn.execute(
        "SELECT date FROM chip_price WHERE stock_id=? ORDER BY date", (sid,))]
    if len(dates_all) < 60:
        print(f"  {sid} 日K 僅 {len(dates_all)} 根,略過")
        return None
    # 日線只送最近 JSON_DAYS 根:250日視窗 + RVPOS 的 504 日百分位回看 + 252 日動能 ⇒ ~780 根就夠,
    # 取 900 留餘裕。更長的歷史(全史月K、季節性)走月K聚合,不必把日線全丟給瀏覽器。
    dates = dates_all[-JSON_DAYS:]
    km = monthly(sid)

    px = series("chip_price", "open,high,low,close,volume,amount", sid, dates)
    adj = series("chip_adj", "adj_f,vol_f", sid, dates)
    ins = series("chip_inst", "foreign_net,fdealer_net,trust_net,dealer_self,dealer_hedge", sid, dates)
    mg = series("chip_margin", "margin_bal,short_bal,margin_buy,margin_sell", sid, dates)
    fh = series("chip_foreign", "ratio,shares,issued", sid, dates)
    sb = series("chip_sbl", "sbl_bal,margin_short_bal", sid, dates)
    dtr = series("chip_daytrade", "dt_volume,dt_buy,dt_sell", sid, dates)

    af = [(a[0] if a[0] is not None else 1.0) for a in adj]
    vf = [(a[1] if a[1] is not None else 1.0) for a in adj]

    ev = [[di(d), k, rd(bp, 4), rd(ap, 4), rd((ap / bp) if (bp and ap) else None, 8), rd(c, 4), n]
          for d, k, bp, ap, c, n in conn.execute(
              "SELECT date,kind,before_price,after_price,cash,note FROM chip_event "
              "WHERE stock_id=? AND date>=? ORDER BY date", (sid, dates[0]))]

    # 集保股權分散(週頻,DB 逐週累積;有多少給多少)
    tdcc = [[di(d), rd(p4), rd(p10), rd(h, 0), rd(ts, 0)] for d, p4, p10, h, ts in conn.execute(
        "SELECT date,pct400,pct1000,holders,total_shares FROM tdcc WHERE stock_id=? ORDER BY date", (sid,))]

    idx_c = [rd(IDX[d][4]) if d in IDX else None for d in dates]

    out = {
        "sid": sid, "name": name,
        "gen": dt.datetime.now(TPE).strftime("%Y-%m-%d %H:%M"),
        "first": dates[0], "last": dates[-1], "n": len(dates),
        "hist_first": dates_all[0], "hist_n": len(dates_all),
        "km": km,        # 全史月K(還原價):[YYYYMM, o, h, l, c, vol張]
        "unit": {"vol": "張", "amt": "百萬元", "inst": "張", "margin": "張",
                 "sbl": "張", "fh_shares": "千股", "issued": "千股"},
        "d": [di(d) for d in dates],
        # 未還原 OHLC(顯示用;還原價 = 值 × af)
        "o": col(px, 0, 1, 2), "h": col(px, 1, 1, 2), "l": col(px, 2, 1, 2), "c": col(px, 3, 1, 2),
        "v": col(px, 4, 1e-3, 1),            # 股 → 張
        "am": col(px, 5, 1e-6, 1),           # 元 → 百萬元
        "af": runs(af, 8),
        "inst": {                             # 買賣超,股 → 張(綠=買超=流入)
            "f": col(ins, 0, 1e-3, 1), "fd": col(ins, 1, 1e-3, 1), "t": col(ins, 2, 1e-3, 1),
            "ds": col(ins, 3, 1e-3, 1), "dh": col(ins, 4, 1e-3, 1)},
        "mg": {"m": col(mg, 0, 1, 0), "s": col(mg, 1, 1, 0),      # 融資/融券餘額(張,官方即張)
               "mb": col(mg, 2, 1, 0), "ms": col(mg, 3, 1, 0)},   # 融資買進/賣出(張)
        "fh": {"r": col(fh, 0, 1, 2),                              # 外資持股率 %
               "sh": col(fh, 1, 1e-3, 0),                          # 外資持股數 千股
               "is": runs([r[2] / 1e3 if r[2] else None for r in fh], 0)},  # 發行股數 千股(變化點)
        "sbl": col(sb, 0, 1e-3, 1),                                # 借券賣出餘額 股 → 張
        "msb": col(sb, 1, 1e-3, 1),                                # 券商借券(融券)餘額 張
        "dt": {"v": col(dtr, 0, 1e-3, 1),                          # 當沖量 股 → 張
               "b": col(dtr, 1, 1e-6, 1), "s": col(dtr, 2, 1e-6, 1)},   # 當沖買/賣金額 百萬元
        "ev": ev,
        "idx": {"id": CHIP_INDEX, "c": idx_c},
        "tdcc": tdcc,
    }
    if any(abs(x - 1.0) > 1e-9 for x in vf):
        out["vf"] = runs(vf, 8)
        out["vf_note"] = "配股/分割/減資造成股數變動,量已可用 vf 還原"
    return out


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    names = {r[0]: r[1] for r in conn.execute("SELECT stock_id,name FROM stock_info")}
    only = sys.argv[1] if len(sys.argv) > 1 else None
    wl = [only] if only else list(CONFIG["watchlist"])
    index, total = [], 0
    for sid in wl:
        o = build_one(sid, names.get(sid, sid))
        if not o:
            continue
        s = json.dumps(o, ensure_ascii=False, separators=(",", ":"))
        p = os.path.join(OUT_DIR, f"{sid}.json")
        open(p, "w", encoding="utf-8").write(s)
        total += len(s)
        index.append({"sid": sid, "name": o["name"], "n": o["n"],
                      "first": o["first"], "last": o["last"], "kb": round(len(s) / 1024, 1),
                      "ev": len(o["ev"]), "tdcc": len(o["tdcc"])})
        print(f"  chips/{sid}.json  {len(s)/1024:7.1f} KB  {o['n']} 根  {o['first']}~{o['last']}  "
              f"事件 {len(o['ev'])}")
    meta = {"gen": dt.datetime.now(TPE).strftime("%Y-%m-%d %H:%M"),
            "chip_start": CONFIG.get("chip_history_start"), "items": index}
    if not only:
        open(os.path.join(OUT_DIR, "_index.json"), "w", encoding="utf-8").write(
            json.dumps(meta, ensure_ascii=False, separators=(",", ":")))
    fp = hashlib.sha1(json.dumps([(i["sid"], i["last"], i["n"]) for i in index]).encode()).hexdigest()[:16]
    print(f"CHIPSFP {fp}")
    print(f"OK chips/ 共 {len(index)} 檔,{total/1024:.0f} KB(gzip 後約 {total/1024/6:.0f} KB)")


if __name__ == "__main__":
    main()
