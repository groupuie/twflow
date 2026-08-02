#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 1 驗收報告產生器 → qa_phase1.html(自帶資料,Plotly CDN)"""
import json, os, sqlite3
BASE = os.path.dirname(os.path.abspath(__file__))
conn = sqlite3.connect(os.path.join(BASE, "data", "funds.db"))
SIDS = ["2330", "2603", "2881", "3231"]
KIND = {"div": "除權息", "reduce": "減資", "split": "分割/面額變更"}

names = {r[0]: r[1] for r in conn.execute("SELECT stock_id,name FROM stock_info")}
pack = {}
for sid in SIDS:
    rows = conn.execute(
        "SELECT p.date,p.close,p.volume,COALESCE(a.adj_f,1.0),COALESCE(a.vol_f,1.0) "
        "FROM chip_price p LEFT JOIN chip_adj a ON a.date=p.date AND a.stock_id=p.stock_id "
        "WHERE p.stock_id=? ORDER BY p.date", (sid,)).fetchall()
    ev = conn.execute("SELECT date,kind,before_price,after_price,cash,note FROM chip_event "
                      "WHERE stock_id=? ORDER BY date", (sid,)).fetchall()
    idx = {d: i for i, (d, *_) in enumerate(rows)}
    evs = []
    for d, k, bp, ap, cash, note in ev:
        if d not in idx or idx[d] == 0:
            continue
        i = idx[d]
        raw = rows[i][1] / rows[i - 1][1] - 1
        f = (ap / bp) if (bp and ap) else 1.0
        evs.append({"d": d, "k": KIND.get(k, k), "cash": cash, "f": round(f, 6),
                    "raw": round(raw * 100, 2), "adj": round(((1 + raw) / f - 1) * 100, 2),
                    "note": note, "bp": bp, "ap": ap})
    pack[sid] = {
        "name": names.get(sid, sid),
        "d": [r[0] for r in rows],
        "raw": [round(r[1], 2) for r in rows],
        "adj": [round(r[1] * r[3], 3) for r in rows],
        "vraw": [round((r[2] or 0) / 1000, 1) for r in rows],
        "vadj": [round((r[2] or 0) / 1000 * r[4], 1) for r in rows],
        "ev": evs,
        "vf_used": any(abs(r[4] - 1) > 1e-9 for r in rows),
    }

# chips JSON 樣本(最後 3 個交易日,全欄位)
sample = {}
p = os.path.join(BASE, "chips", "2330.json")
if os.path.exists(p):
    o = json.load(open(p, encoding="utf-8"))
    def tail(a, n=3):
        return a[-n:] if isinstance(a, list) else a
    sample = {
        "檔案": "chips/2330.json", "體積": f"{os.path.getsize(p)//1024} KB (gzip 後 ~57 KB)",
        "涵蓋": f"{o['first']} ~ {o['last']}({o['n']} 根日線) / 月K {len(o['km'])} 個月回溯至 {o['hist_first']}",
        "d 交易日": tail(o["d"]), "o 開": tail(o["o"]), "h 高": tail(o["h"]),
        "l 低": tail(o["l"]), "c 收(未還原)": tail(o["c"]),
        "af 還原因子(變化點編碼)": o["af"][-3:],
        "v 成交量(張)": tail(o["v"]), "am 成交額(百萬)": tail(o["am"]),
        "inst.f 外資買賣超(張)": tail(o["inst"]["f"]),
        "inst.fd 外資自營(張)": tail(o["inst"]["fd"]),
        "inst.t 投信(張)": tail(o["inst"]["t"]),
        "inst.ds 自營自行(張)": tail(o["inst"]["ds"]),
        "inst.dh 自營避險(張)": tail(o["inst"]["dh"]),
        "mg.m 融資餘額(張)": tail(o["mg"]["m"]), "mg.s 融券餘額(張)": tail(o["mg"]["s"]),
        "fh.r 外資持股率(%)": tail(o["fh"]["r"]), "fh.sh 外資持股(千股)": tail(o["fh"]["sh"]),
        "fh.is 發行股數(千股,變化點)": o["fh"]["is"][-2:],
        "sbl 借券賣出餘額(張)": tail(o["sbl"]),
        "dt.v 當沖量(張)": tail(o["dt"]["v"]),
        "dt.b/s 當沖買賣額(百萬)": [tail(o["dt"]["b"]), tail(o["dt"]["s"])],
        "idx.c 加權指數收盤": tail(o["idx"]["c"]),
        "km 月K(最後1筆)": o["km"][-1],
        "ev 事件(最後1筆)": o["ev"][-1],
        "tdcc 集保週資料": f"{len(o['tdcc'])} 筆(沙盒新建 DB 尚未累積;正式環境由 GH Actions 快取逐週累加)",
    }

html = open(os.path.join(BASE, "qa_template.html"), encoding="utf-8").read()
html = html.replace("__PACK__", json.dumps(pack, ensure_ascii=False, separators=(",", ":")))
html = html.replace("__SAMPLE__", json.dumps(sample, ensure_ascii=False, indent=1))
open(os.path.join(BASE, "qa_phase1.html"), "w", encoding="utf-8").write(html)
print(f"OK qa_phase1.html ({len(html)//1024} KB)")
