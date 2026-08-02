#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 4 — 買賣燈號門檻校準與回測(台股口徑)

協議(照專案規格):
  標的池       自選股 15 檔 + 近 120 日成交金額前 50 大個股(0050 的可重現代理)
  Walk-forward 2013-01-01~2023-12-31 定門檻(IS) / 2024-01-01~2026-07-31 樣本外驗證(OOS)
  事件研究     訊號日後 +5 / +10 / +20 交易日,**相對加權指數的超額報酬**
  隨機基準     從同一標的池、同一期間隨機抽同樣天數 → 給出 p 值
  判定         贏不了隨機基準就不上這個訊號,或標「觀察用,非交易訊號」

台股與美股的三個結構性差異(所以門檻不能照搬):
  1) 10% 漲跌幅限制 → 漲停鎖死是「零量」不是「爆量」,爆量竭盡的分佈完全不同
  2) 當沖佔量中位數約 21%、極端 80% → 量比一律用「扣當沖後的真實換手量」
  3) 台積電權重近 30% → 個股絕對動能被指數綁架,score 改用相對加權指數的超額動能

效能註記:
  網格搜尋階段的 p 值用解析式(不放回抽樣之平均數分佈,CLT + 有限母體修正)。
  每格都跑 2000 次重抽樣要數小時,而 k 動輒上千、CLT 收斂很好。
  最終選定的組合會再跑真正的重抽樣交叉驗證,確認解析式沒騙人。
  統計量一律用純算術,不用 statistics 模組(它對十萬筆用 Fraction 精確運算,慢兩個數量級)。

用法:python3 bt_signals.py [輸出.md]
"""
import datetime as dtm, json, math, os, random, sqlite3, sys

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "data", "funds.db")
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE, "BACKTEST.md")
IS_END = "2023-12-31"
HORIZONS = [5, 10, 20]
NRAND = 2000
BOOT_CAP = 8000          # 重抽樣的單次抽樣上限(k 太大時抽樣本身比統計還貴)
TWY = 244
MIN_N = 60
random.seed(20260802)    # 固定種子:報告可重現

conn = sqlite3.connect(DB)
T0 = dtm.datetime.now()


def log(m):
    print(f"[{(dtm.datetime.now()-T0).seconds:>4}s] {m}", flush=True)


def fmean(v):
    return sum(v) / len(v)


def fsd(v):
    m = fmean(v)
    return math.sqrt(sum((x - m) * (x - m) for x in v) / len(v))


# ---------------------------------------------------------------- 資料
def load(sid):
    rows = conn.execute(
        "SELECT p.date,p.high,p.low,p.close,p.volume,COALESCE(a.adj_f,1.0) "
        "FROM chip_price p LEFT JOIN chip_adj a ON a.date=p.date AND a.stock_id=p.stock_id "
        "WHERE p.stock_id=? ORDER BY p.date", (sid,)).fetchall()
    rows = [r for r in rows if r[3] and r[3] > 0]          # 丟掉停牌/無收盤
    if len(rows) < 600:
        return None
    dt = {r[0]: r[1] for r in conn.execute(
        "SELECT date,dt_volume FROM chip_daytrade WHERE stock_id=?", (sid,))}
    d = [r[0] for r in rows]
    C = [r[3] * r[5] for r in rows]
    V = [r[4] or 0.0 for r in rows]
    VN = [max(0.0, V[i] - (dt.get(d[i]) or 0.0)) for i in range(len(d))]
    return dict(d=d, C=C, V=V, VN=VN)


def indicators(S, IX):
    """與前端 ckRows 同定義:60/120/240 SMA、相對指數超額動能 score、RVPOS、TD9、扣當沖量比"""
    d, C, V, VN = S["d"], S["C"], S["V"], S["VN"]
    n = len(C)
    P = [0.0] * (n + 1); PV = [0.0] * (n + 1); PN = [0.0] * (n + 1)
    for i in range(n):
        P[i + 1] = P[i] + C[i]; PV[i + 1] = PV[i] + V[i]; PN[i + 1] = PN[i] + VN[i]

    # 20 日實現波動(年化 %)——用 O(n) 滾動和,不要每根重算 20 筆
    lg = [0.0] * n
    for i in range(1, n):
        lg[i] = math.log(C[i] / C[i - 1]) if (C[i] > 0 and C[i - 1] > 0) else 0.0
    s1 = s2 = 0.0
    rv = [None] * n
    for i in range(1, n):
        s1 += lg[i]; s2 += lg[i] * lg[i]
        if i >= 20:
            s1 -= lg[i - 20]; s2 -= lg[i - 20] * lg[i - 20]
        if i >= 20:
            var = (s2 - s1 * s1 / 20) / 19
            rv[i] = math.sqrt(var) * math.sqrt(TWY) * 100 if var > 0 else 0.0

    # RVPOS:504 日滾動百分位(min_periods 60)。O(n×505) 是這支程式最貴的一段。
    rvp = [None] * n
    for i in range(n):
        if rv[i] is None:
            continue
        lo = max(0, i - 504)
        t = c = 0
        cur = rv[i]
        for j in range(lo, i + 1):
            x = rv[j]
            if x is not None:
                t += 1
                if x <= cur:
                    c += 1
        if t >= 60:
            rvp[i] = round(100 * c / t)

    tds = [0] * n; tdb = [0] * n
    for i in range(4, n):
        tds[i] = tds[i - 1] + 1 if C[i] > C[i - 4] else 0
        tdb[i] = tdb[i - 1] + 1 if C[i] < C[i - 4] else 0

    out = []
    for i in range(240, n):
        s60 = (P[i + 1] - P[i + 1 - 60]) / 60
        s120 = (P[i + 1] - P[i + 1 - 120]) / 120
        s240 = (P[i + 1] - P[i + 1 - 240]) / 240
        sc = (1 if C[i] > s60 else -1) + (1 if C[i] > s120 else -1) + (1 if C[i] > s240 else -1)
        for k in (60, 120, 240):
            a, b = IX.get(d[i]), IX.get(d[i - k])
            if a and b:
                sc += 1 if (C[i] / C[i - k] - 1) > (b and a / b - 1) else -1
            else:
                sc += 1 if C[i] > C[i - k] else -1
        v60 = (PV[i + 1] - PV[i + 1 - 60]) / 60
        n60 = (PN[i + 1] - PN[i + 1 - 60]) / 60
        chg = C[i] / C[i - 1] - 1 if C[i - 1] else 0.0
        out.append((i, d[i],
                    round(100 * sc / 6),                       # 2 sc
                    rvp[i],                                    # 3 RVPOS
                    max(tds[i], tds[i - 1], tds[i - 2]) >= 9,   # 4 TD 賣9
                    max(tdb[i], tdb[i - 1], tdb[i - 2]) >= 9,   # 5 TD 買9
                    (VN[i] / n60 if n60 > 0 else 1.0),          # 6 扣當沖量比
                    (C[i] / C[i - 5] - 1) if i >= 5 else 0.0,   # 7 5 日報酬
                    abs(chg) >= 0.095))                         # 8 漲跌停鎖死
    return out


def fwd_excess(C, d, IX, i, h):
    j = i + h
    if j >= len(C):
        return None
    a, b = IX.get(d[i]), IX.get(d[j])
    if not a or not b:
        return None
    return ((C[j] / C[i] - 1) - (b / a - 1)) * 100


def stats(v):
    if not v:
        return None
    v = sorted(v)
    n = len(v)
    return dict(n=n, mean=fmean(v), med=v[n // 2],
                win=100 * sum(1 for x in v if x > 0) / n,
                p10=v[max(0, int(n * 0.10) - 1)], worst=v[0], best=v[-1])


_PS = {}


def pool_mean(pool, key):
    if key not in _PS:
        _PS[key] = (len(pool), fmean(pool), fsd(pool))
    return _PS[key][1]


def pval(pool, key, k, obs, side):
    """解析式:不放回抽樣的樣本平均 ~ N(mu, sd/√k × √((N−k)/(N−1)))。
    **方向很重要**:抄底(BOT)是做多訊號,檢定「是否比隨機更強」→ 右尾;
    減碼(TOP)是賣出訊號,檢定「是否比隨機更弱」→ 左尾。
    用錯邊會把『訊號後續漲』誤判成有效的賣出訊號。"""
    if key not in _PS:
        _PS[key] = (len(pool), fmean(pool), fsd(pool))
    N, mu, sd = _PS[key]
    if k <= 1 or k >= N or sd <= 0:
        return None
    se = sd / math.sqrt(k) * math.sqrt((N - k) / (N - 1))
    z = (obs - mu) / se
    if side == "left":
        z = -z
    return 0.5 * math.erfc(z / math.sqrt(2))


def bootstrap_p(pool, k, obs, side, nrand=NRAND):
    """真正的重抽樣,只對最終選定的組合跑,用來驗證解析式"""
    if k <= 0 or len(pool) < k:
        return None
    kk = min(k, BOOT_CAP)
    hit = 0
    for _ in range(nrand):
        m = fmean(random.sample(pool, kk))
        if (m >= obs) if side == "right" else (m <= obs):
            hit += 1
    return hit / nrand, kk


def main():
    uni = json.load(open(os.path.join(BASE, "bt_pool.json"), encoding="utf-8"))
    sids = list(dict.fromkeys(uni["watchlist"] + uni["universe"]))
    IX = {r[0]: r[1] for r in conn.execute(
        "SELECT date,close FROM chip_price WHERE stock_id='TAIEX' AND close>0")}
    log(f"標的池 {len(sids)} 檔,加權指數 {len(IX)} 日")

    # 攤平成 tuple 陣列:網格有上百種組合,每種都重掃 dict 會慢兩個數量級
    FLAT = []
    pool = {h: {True: [], False: []} for h in HORIZONS}
    nok = 0
    for s in sids:
        S = load(s)
        if not S:
            continue
        nok += 1
        R = indicators(S, IX)
        C, d = S["C"], S["d"]
        for (i, dd, sc, rvp, td9s, td9b, volrn, r5, lim) in R:
            es = tuple(fwd_excess(C, d, IX, i, h) for h in HORIZONS)
            isseg = dd <= IS_END
            FLAT.append((isseg, td9b, rvp, volrn, r5, sc, td9s, lim, es))
            for k, h in enumerate(HORIZONS):
                if es[k] is not None:
                    pool[h][isseg].append(es[k])
        if nok % 10 == 0:
            log(f"  已處理 {nok} 檔,FLAT {len(FLAT)} 列")
    log(f"可用 {nok} 檔,FLAT {len(FLAT)} 列")
    for h in HORIZONS:
        log(f"  母體 h={h}: IS {len(pool[h][True])} / OOS {len(pool[h][False])}")

    HI = {h: k for k, h in enumerate(HORIZONS)}

    def evaluate(kind, pr, need, isseg, h):
        rv_th, sc_th, vt = pr
        hi, vals = HI[h], []
        for f in FLAT:
            if f[0] is not isseg:
                continue
            if kind == "BOT":
                c = f[1] + (f[2] is not None and f[2] >= rv_th) \
                    + (f[3] <= vt and f[4] <= -0.05) + (f[5] <= sc_th)
            else:
                c = f[6] + (f[2] is not None and f[2] >= rv_th) \
                    + (f[3] >= vt and not f[7]) + (f[5] >= sc_th)
            if c >= need:
                e = f[8][hi]
                if e is not None:
                    vals.append(e)
        return vals

    # side:BOT 是做多訊號 → 檢定「比隨機更強」(右尾);TOP 是賣出訊號 → 檢定「比隨機更弱」(左尾)
    grids = {
        "BOT": ([(rv, sc, vt) for rv in (70, 80, 90) for sc in (-33, 0, 33) for vt in (0.7, 0.85)],
                (2, 3), "right"),
        "TOP": ([(rv, sc, vt) for rv in (80, 90) for sc in (67, 100) for vt in (1.5, 1.75)],
                (2, 3), "left"),
    }

    md = ["# 台股個股燈號 — 門檻校準與回測報告", "",
          f"產生於 {dtm.datetime.now().strftime('%Y-%m-%d %H:%M')} · 標的池 {nok} 檔 · "
          f"IS ≤ {IS_END} / OOS ≥ 2024-01-01 · 隨機基準種子固定,報告可重現", "",
          "## 協議", "",
          "- 超額報酬 = 個股(**還原價**)報酬 − 加權指數報酬,單位 %。",
          "- 量比一律用**扣當沖後的真實換手量**(台股當沖佔量中位數約 21%、極端可到 80%)。",
          "- 爆量條件排除漲跌停鎖死日(台股鎖死是零量、不是爆量)。",
          "- score 用**相對加權指數的超額動能**(台積電權重近 30%,絕對動能會集體同向)。",
          "- 隨機基準:從**同一標的池、同一期間**隨機抽同樣天數。",
          "  `p` = 隨機抽樣的平均超額 ≥ 訊號平均超額的機率。**p ≥ 0.05 視為贏不了隨機。**",
          f"- 最低樣本數 {MIN_N};網格用解析式 p,最終組合再跑 {NRAND} 次重抽樣交叉驗證。", ""]

    verdicts = {}
    for name, (grid, needs, side) in grids.items():
        log(f"{name} 網格 {len(grid)}×{len(needs)}×{len(HORIZONS)}")
        md += [f"## {name} 燈號({'▲ 抄底' if name=='BOT' else '▼ 減碼'})", "",
               "原子條件:" + ("TD買9 / RVPOS≥門檻 / 殺量竭盡(扣當沖量比≤門檻 且 5日跌幅≤−5%) / score≤門檻"
                             if name == "BOT" else
                             "TD賣9 / RVPOS≥門檻 / 爆量(扣當沖量比≥門檻 且非漲跌停鎖死) / score≥門檻"), "",
               "### IS 網格搜尋(2013–2023)", "",
               "`edge` = 訊號平均超額 − **同期隨機基準**平均超額。這才是真正的優勢;"
               "直接看「平均超額」會被標的池的存活者偏誤灌水。", "",
               "| 湊分 | RVPOS | score | 量比 | h | 樣本 | 平均超額% | 隨機基準% | **edge%** | 命中率% | p |",
               "|---|---|---|---|---|---|---|---|---|---|---|"]
        best = None
        for need in needs:
            for pr in grid:
                for h in HORIZONS:
                    v = evaluate(name, pr, need, True, h)
                    s = stats(v)
                    if not s or s["n"] < MIN_N:
                        continue
                    p = pval(pool[h][True], ("is", h), s["n"], s["mean"], side)
                    if p is None:
                        continue
                    mu = pool_mean(pool[h][True], ("is", h))
                    edge = s["mean"] - mu
                    md.append(f"| ≥{need} | {pr[0]} | {pr[1]} | {pr[2]} | +{h} | {s['n']} | "
                              f"{s['mean']:+.2f} | {mu:+.2f} | **{edge:+.2f}** | {s['win']:.1f} | {p:.4f} |")
                    if best is None or p < best["p"]:
                        best = dict(need=need, pr=pr, h=h, s=s, p=p, edge=edge)
        if not best:
            md += ["", f"IS 沒有任何組合達到最低樣本數({MIN_N}),**不上這個訊號**。", ""]
            verdicts[name] = dict(status="no_sample")
            continue

        vo = evaluate(name, best["pr"], best["need"], False, best["h"])
        so = stats(vo)
        po = (pval(pool[best["h"]][False], ("oos", best["h"]), so["n"], so["mean"], side)
              if (so and so["n"] >= 20) else None)
        bi = bootstrap_p(pool[best["h"]][True], best["s"]["n"], best["s"]["mean"], side)
        bo = (bootstrap_p(pool[best["h"]][False], so["n"], so["mean"], side)
              if (so and so["n"] >= 20) else None)
        base_is, base_oos = stats(pool[best["h"]][True]), stats(pool[best["h"]][False])
        edge_oos = (so["mean"] - base_oos["mean"]) if so else None

        md += ["", f"### IS 最佳(依 p 值):湊分 ≥{best['need']}、RVPOS {best['pr'][0]}、"
                   f"score {best['pr'][1]}、量比 {best['pr'][2]}、視野 +{best['h']} 日", "",
               "| 區間 | 樣本 | 平均超額% | 隨機基準% | **edge%** | 中位數% | 命中率% | 第10百分位% | 最差單次% | p |",
               "|---|---|---|---|---|---|---|---|---|---|",
               f"| IS 2013–2023 | {best['s']['n']} | {best['s']['mean']:+.2f} | {base_is['mean']:+.2f} | "
               f"**{best['edge']:+.2f}** | {best['s']['med']:+.2f} | {best['s']['win']:.1f} | "
               f"{best['s']['p10']:+.2f} | {best['s']['worst']:+.2f} | {best['p']:.4f} |"]
        if so:
            md.append(f"| **OOS 2024–2026** | {so['n']} | {so['mean']:+.2f} | {base_oos['mean']:+.2f} | "
                      f"**{edge_oos:+.2f}** | {so['med']:+.2f} | {so['win']:.1f} | "
                      f"{so['p10']:+.2f} | {so['worst']:+.2f} | "
                      f"{('%.4f' % po) if po is not None else '樣本不足'} |")
        else:
            md.append("| **OOS 2024–2026** | 0 | — | — | — | — | — | — | — | 樣本不足 |")
        md += ["", f"檢定方向:**{'右尾(訊號後應比隨機更強)' if side=='right' else '左尾(訊號後應比隨機更弱)'}**。"
                   f"重抽樣交叉驗證({NRAND} 次):IS p={bi[0] if bi else 'n/a'}"
                   f"{f'(抽樣上限 {bi[1]})' if bi and bi[1] != best['s']['n'] else ''}、"
                   f"OOS p={bo[0] if bo else 'n/a'} —— 與上表解析式 p 值應相近。", ""]

        # 通過條件:IS 與 OOS 都顯著、且 **edge 的方向與大小** 都撐得住交易成本(0.585% 來回)
        need_edge = (lambda e: e > 0.6) if side == "right" else (lambda e: e < -0.6)
        ok = (best["p"] < 0.05 and so and so["n"] >= 20 and po is not None and po < 0.05
              and need_edge(best["edge"]) and need_edge(edge_oos))
        verdicts[name] = dict(status="pass" if ok else "fail", side=side,
                              best={"need": best["need"], "pr": list(best["pr"]), "h": best["h"],
                                    "p_is": best["p"], "mean_is": best["s"]["mean"],
                                    "edge_is": best["edge"], "n_is": best["s"]["n"]},
                              p_oos=po, mean_oos=(so or {}).get("mean"), edge_oos=edge_oos,
                              n_oos=(so or {}).get("n"))
        if ok:
            md += ["**判定:通過** —— IS 與 OOS 都顯著,且 edge 方向正確、大小撐得過交易成本,可上線為交易訊號。", ""]
        else:
            why = []
            if best["p"] >= 0.05: why.append("IS 不顯著")
            if po is None or po >= 0.05: why.append("OOS 不顯著")
            if not need_edge(best["edge"]): why.append(f"IS edge {best['edge']:+.2f}% 方向/大小不合格")
            if edge_oos is not None and not need_edge(edge_oos): why.append(f"OOS edge {edge_oos:+.2f}% 方向/大小不合格")
            md += [f"**判定:未通過**({'、'.join(why)})。依專案原則,**不上這個燈號**;"
                   "若要顯示只能標成「觀察用,非交易訊號」。", ""]
            if side == "left" and best["edge"] > 0:
                md += ["> ⚠ **反向發現**:這組「減碼」條件在事後看是**續漲**條件(edge 為正)。",
                       "> 高檔位 + 高 RVPOS + 爆量在台股是**動能延續**的特徵,不是反轉。",
                       "> 這正是為什麼美股門檻不能直接搬——也是為什麼這個燈號不會上線。", ""]

    md += ["## 已知限制(必讀,不要跳過)", "",
           "- **存活者偏誤**:標的池用「當前」成交金額前 50 大,沒有回溯歷史成分股。",
           "  2013 年還不是大型股的公司會被納入,等於偷看未來 → 結果偏樂觀。",
           "- **交易成本**:台股手續費 0.1425%×2 + 證交稅 0.3%,單次來回約 **0.585%**。",
           "  任何平均超額低於 0.6% 就等於白做,判定門檻已納入這一項。",
           "- **重疊樣本**:同一檔股票相鄰訊號日的持有期會重疊,樣本非獨立,p 值偏樂觀。",
           "- **多重比較**:IS 網格搜尋了上百種組合再挑最好的,IS 的 p 值本身就有選擇偏誤;",
           "  這正是為什麼判定要看 **OOS**。",
           "- **看不到的錢**:台股主力/大戶現股不在任何官方每日揭露口徑內,本回測只能用",
           "  三大法人 + 融資券 + 借券,看不到真正的大戶。",
           "- 本專案已驗證池流量對指數是**同日高相關(r ≈ −0.91)、隔日近乎零預測力**",
           "  (lag k+1 r ≈ −0.046),法人甚至略微落後指數(k−1 r = −0.154)。個股層級沒有理由更好。",
           ""]

    open(OUT, "w", encoding="utf-8").write("\n".join(md))
    json.dump(verdicts, open(os.path.join(BASE, "bt_verdict.json"), "w"),
              ensure_ascii=False, indent=1)
    log("寫出 " + OUT)
    for k, v in verdicts.items():
        log(f"  {k}: {v['status']}")


if __name__ == "__main__":
    main()
