#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""籌碼駕駛艙 / 回測標的池:自選股 15 檔 + 近 120 日成交金額前 N 大個股(排除 ETF)
理由:0050 成分股清單在 register 等級拿不到,用「流動性前 50 大」當代理,
      口徑可重現、且與 0050 高度重疊。歷史成分股變動未回溯 → 有存活者偏誤,報告中會註明。"""
import json, os, sqlite3, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_data as F

N = int(sys.argv[1]) if len(sys.argv) > 1 else 100
conn = F.db()
days = [r[0] for r in conn.execute("SELECT DISTINCT date FROM mkt_daily ORDER BY date DESC LIMIT 120")]
rows = conn.execute(
    "SELECT stock_id, AVG(amount) a FROM mkt_daily WHERE date>=? AND stock_id NOT LIKE '00%' "
    "GROUP BY stock_id ORDER BY a DESC LIMIT ?", (days[-1], N)).fetchall()
uni = [r[0] for r in rows]
wl = list(F.CONFIG["watchlist"])
have = {r[0] for r in conn.execute("SELECT DISTINCT stock_id FROM chip_price")}
todo = [s for s in dict.fromkeys(wl + uni) if s not in have]
F.log(f"回測池 {len(set(wl+uni))} 檔(自選 {len(wl)} + 流動性前 {N}),待抓 {len(todo)} 檔")
json.dump({"watchlist": wl, "universe": uni, "start": F.CHIP_START},
          open(os.path.join(F.BASE_DIR, "bt_pool.json"), "w"), ensure_ascii=False, indent=1)
if todo:
    F.chip_history_all(conn, todo)
F.log("回測池長史完成")
