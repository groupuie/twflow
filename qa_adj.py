#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 1 驗收:除權息還原正確性檢查(還原前 vs 還原後)"""
import sqlite3, sys, os, json
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "funds.db")
SID = sys.argv[1] if len(sys.argv) > 1 else "2330"
c = sqlite3.connect(DB)

rows = c.execute("""SELECT p.date,p.open,p.high,p.low,p.close,p.volume,a.adj_f,a.vol_f
                    FROM chip_price p LEFT JOIN chip_adj a ON a.date=p.date AND a.stock_id=p.stock_id
                    WHERE p.stock_id=? ORDER BY p.date""", (SID,)).fetchall()
ev = {r[0]: r for r in c.execute(
    "SELECT date,kind,before_price,after_price,cash,note FROM chip_event WHERE stock_id=? ORDER BY date", (SID,))}
print(f"=== {SID}  {rows[0][0]} ~ {rows[-1][0]}  共 {len(rows)} 根日K,{len(ev)} 個價格不連續事件 ===\n")

idx = {r[0]: i for i, r in enumerate(rows)}
print(f"{'除權息日':<12}{'類型':<7}{'配':>6}  {'前日收':>9}{'當日收':>9}{'原始跳空':>9}  "
      f"{'還原前收':>10}{'還原當收':>10}{'還原跳空':>9}  {'adj_f':>9}")
worst_raw = worst_adj = 0.0
for d, e in sorted(ev.items()):
    if d not in idx or idx[d] == 0:
        print(f"{d:<12}{e[1]:<7} (不在日K區間內)"); continue
    i = idx[d]; p0, p1 = rows[i-1], rows[i]
    raw = p1[4] / p0[4] - 1
    a0, a1 = p0[4] * (p0[6] or 1), p1[4] * (p1[6] or 1)
    adj = a1 / a0 - 1
    # 「假跳空」= 除權息/減資造成的機械式價格斷點 = after/before - 1
    # 還原後應精確滿足 (1+raw)/f - 1 = adj(非線性,不可用 raw-mech 近似)
    f = e[3] / e[2] if (e[2] and e[3]) else 1.0
    mech = f - 1
    worst_raw = max(worst_raw, abs(mech))
    worst_adj = max(worst_adj, abs(adj - ((1 + raw) / f - 1)))
    print(f"{d:<12}{e[1]:<7}{(e[4] or 0):>6.2f}  {p0[4]:>9.2f}{p1[4]:>9.2f}{raw*100:>8.2f}%  "
          f"{a0:>10.2f}{a1:>10.2f}{adj*100:>8.2f}%  {p1[6]:>9.6f}")

print(f"\n最大機械式跳空(未還原,除權息/減資造成): {worst_raw*100:.2f}%")
print(f"還原恆等式殘差 |adj - ((1+raw)/f-1)| 最大值(應 ≈0): {worst_adj*100:.8f}%")

f0, fl = rows[0][6], rows[-1][6]
print(f"\n還原因子:最早 {rows[0][0]} = {f0:.6f} → 最新 {rows[-1][0]} = {fl:.6f}(錨定今天=1.0)")
print(f"未還原漲幅 {rows[0][4]} → {rows[-1][4]} = {(rows[-1][4]/rows[0][4]-1)*100:.1f}%")
print(f"還原後漲幅 {rows[0][4]*f0:.2f} → {rows[-1][4]*fl:.2f} = "
      f"{(rows[-1][4]*fl)/(rows[0][4]*f0)*100-100:.1f}%(含息報酬,應高於未還原)")

# 均線平滑度:還原前後 60D MA 的一階差分標準差(除權息日附近)
def ma(vals, n=60):
    out, s = [], 0.0
    for i, v in enumerate(vals):
        s += v
        if i >= n: s -= vals[i-n]
        out.append(s / min(i+1, n))
    return out
raws = [r[4] for r in rows]
adjs = [r[4] * (r[6] or 1) for r in rows]
mr, ma_ = ma(raws), ma(adjs)
def jump_at_events(series):
    js = []
    for d in ev:
        if d in idx and idx[d] > 0:
            i = idx[d]
            js.append(abs(series[i] / series[i-1] - 1))
    return js
jr, ja = jump_at_events(raws), jump_at_events(adjs)
print(f"\n除權息日當日價格跳動 |Δ%| 平均:未還原 {sum(jr)/len(jr)*100:.3f}% / 還原後 {sum(ja)/len(ja)*100:.3f}%")

# TD9 / 動能受影響檢查:63 日動能在除權息日前後的差異
def mom(vals, n=63):
    return [None if i < n else vals[i]/vals[i-n]-1 for i in range(len(vals))]
m_raw, m_adj = mom(raws), mom(adjs)
dif = [abs(m_raw[i]-m_adj[i]) for i in range(len(rows)) if m_raw[i] is not None]
print(f"63日動能:未還原 vs 還原 平均絕對差 {sum(dif)/len(dif)*100:.3f}pp,最大 {max(dif)*100:.3f}pp")

out = {"sid": SID, "n": len(rows), "first": rows[0][0], "last": rows[-1][0],
       "events": len(ev), "adj_f_first": f0,
       "series": [[r[0], r[4], round(r[4]*(r[6] or 1), 4)] for r in rows]}
json.dump(out, open(f"qa_adj_{SID}.json", "w"), separators=(",", ":"))
print(f"\n序列已存 qa_adj_{SID}.json")
