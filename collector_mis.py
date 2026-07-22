#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""台股盤中本機採集器(免費版)— 在你自己的電腦執行,像你美股板的 Mac 採集器
================================================================================
用途:盤中每 POLL_SEC 秒抓「證交所 MIS 免費即時快照」,估算自選股的
     內外盤成交金額(主動買/主動賣)與「爆量單」(單一輪詢區間 Δ金額特別大,
     疑似大單掃盤),每分鐘聚合後推送 intraday.json 到你的 GitHub repo,
     dashboard 網頁(https://groupuie.github.io/twflow/)偵測到檔案就會顯示盤中區塊。

安裝與執行(你的電腦,Mac/Windows 皆可):
  1. 安裝 Python 3.9+,然後:pip install requests
  2. 把下方 GITHUB_TOKEN 換成你的 token(跟 dashboard 用的同一顆即可)
  3. python3 collector_mis.py
  4. 非交易時段會自動睡眠;Ctrl+C 結束。

方法說明(與盤後大小單分類器同一套邏輯的即時簡化版):
  - MIS 快照約 5 秒更新:累計成交量 v、成交價 z、最佳五檔 a/b
  - Δ量 = 本次 v − 上次 v;方向:z ≥ 最佳賣價 → 外盤(主動買),z ≤ 最佳買價 → 內盤(主動賣),
    夾中間用 tick rule(比前價)
  - Δ金額 = Δ量(張)×1000×z;單一輪詢 Δ金額 ≥ BURST_WAN 萬 → 記為爆量單(疑似大單)
  - 誠實聲明:5 秒快照看不到逐筆,爆量單是「區間集中成交」的 proxy,
    真正逐筆大小單要 FinMind sponsor 的 tick 資料(dashboard 後台已內建,升級即自動啟用)
================================================================================
"""
import base64, datetime as dt, json, time, sys
try:
    import requests
except ImportError:
    sys.exit("請先安裝:pip install requests")

# ====== 設定(只需要改這裡)======
GITHUB_TOKEN = "ghp_把你的token貼在這裡"
GH_USER, GH_REPO, GH_BRANCH = "groupuie", "twflow", "gh-pages"
WATCHLIST = [  # (市場, 代號)市場:tse=上市 / otc=上櫃
    ("tse", "2330"), ("tse", "2317"), ("tse", "2454"), ("tse", "2308"), ("tse", "2382"),
    ("tse", "2303"), ("tse", "3231"), ("tse", "3008"), ("tse", "3034"), ("tse", "2379"),
    ("tse", "2412"), ("tse", "2881"), ("tse", "2882"), ("tse", "2603"), ("tse", "1216"),
]
POLL_SEC = 10          # 輪詢間隔(秒);MIS 約 5 秒一筆,10 秒夠用且客氣
PUSH_SEC = 60          # 推送 GitHub 間隔(秒)
BURST_WAN = 500        # 爆量單門檻(萬元/單一輪詢區間)
# ================================

MIS = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "application/json"})

def taipei_now():
    return dt.datetime.utcnow() + dt.timedelta(hours=8)

def in_session(t):
    if t.weekday() >= 5:
        return False
    hm = t.hour * 100 + t.minute
    return 855 <= hm <= 1335   # 8:55 暖機 ~ 13:35 收盤後緩衝

def fetch_snapshot():
    ex = "|".join(f"{m}_{s}.tw" for m, s in WATCHLIST)
    r = S.get(MIS, params={"ex_ch": ex, "json": "1", "delay": "0", "_": int(time.time() * 1000)}, timeout=15)
    r.raise_for_status()
    return {x["c"]: x for x in r.json().get("msgArray", []) if x.get("c")}

def best(px_str):
    try:
        return float(px_str.split("_")[0])
    except Exception:
        return None

def push_github(payload):
    api = f"https://api.github.com/repos/{GH_USER}/{GH_REPO}/contents/intraday.json"
    h = {"Authorization": "token " + GITHUB_TOKEN, "Accept": "application/vnd.github+json"}
    sha = None
    g = requests.get(api, params={"ref": GH_BRANCH}, headers=h, timeout=30)
    if g.ok:
        sha = g.json().get("sha")
    body = {"message": "intraday update", "branch": GH_BRANCH,
            "content": base64.b64encode(json.dumps(payload, ensure_ascii=False).encode()).decode()}
    if sha:
        body["sha"] = sha
    p = requests.put(api, headers=h, json=body, timeout=60)
    p.raise_for_status()

def main():
    prev = {}                 # sid -> (v累計, z前價, dir前方向)
    agg = {}                  # sid -> {"buy":元,"sell":元,"bursts":[...], "mins":{hhmm:net元}}
    last_push, day = 0, taipei_now().strftime("%Y-%m-%d")
    print(f"採集器啟動 {day} — 自選 {len(WATCHLIST)} 檔,{POLL_SEC}s 輪詢/{PUSH_SEC}s 推送,爆量門檻 {BURST_WAN} 萬")
    while True:
        t = taipei_now()
        if not in_session(t):
            if agg and last_push:
                print("收盤,最後推送一次後睡眠")
                try:
                    push_github(build_payload(agg, t, day, final=True))
                except Exception as e:
                    print("推送失敗:", e)
                agg, prev, last_push = {}, {}, 0
            time.sleep(60)
            if taipei_now().strftime("%Y-%m-%d") != day:
                day = taipei_now().strftime("%Y-%m-%d")
            continue
        try:
            snap = fetch_snapshot()
        except Exception as e:
            print("MIS 抓取失敗:", e)
            time.sleep(POLL_SEC)
            continue
        hhmm = t.strftime("%H:%M")
        for sid, x in snap.items():
            try:
                v = float(x.get("v") or 0)        # 累計量(張)
                z = float(x.get("z") or 0)        # 成交價
            except ValueError:
                continue
            if z <= 0:
                continue
            a, b = best(x.get("a", "")), best(x.get("b", ""))
            pv, pz, pd = prev.get(sid, (None, None, 1))
            prev[sid] = (v, z, pd)
            if pv is None or v <= pv:
                continue
            dv = v - pv
            if a and z >= a:
                d = 1
            elif b and z <= b:
                d = -1
            else:
                d = pd if (pz is None or z == pz) else (1 if z > pz else -1)
            prev[sid] = (v, z, d)
            amt = dv * 1000 * z
            g = agg.setdefault(sid, {"name": x.get("n", sid), "buy": 0.0, "sell": 0.0, "bursts": [], "mins": {}})
            g["buy" if d > 0 else "sell"] += amt
            g["mins"][hhmm] = g["mins"].get(hhmm, 0.0) + d * amt
            if amt >= BURST_WAN * 1e4:
                g["bursts"].append({"t": t.strftime("%H:%M:%S"), "d": "買" if d > 0 else "賣",
                                    "wan": round(amt / 1e4), "px": z, "zh": round(dv)})
        if time.time() - last_push >= PUSH_SEC and agg:
            try:
                push_github(build_payload(agg, t, day))
                last_push = time.time()
                tot = sum(g["buy"] - g["sell"] for g in agg.values()) / 1e8
                print(f"{hhmm} 已推送 · 自選合計淨流 {tot:+.1f} 億")
            except Exception as e:
                print("推送失敗:", e)
        time.sleep(POLL_SEC)

def build_payload(agg, t, day, final=False):
    return {"ts": t.strftime("%Y-%m-%d %H:%M:%S"), "date": day, "final": final,
            "note": "內外盤為 5 秒快照估算;爆量單=單一輪詢區間 Δ金額 ≥ %d 萬(疑似大單,非逐筆)" % BURST_WAN,
            "stocks": {sid: {"name": g["name"], "buy_yi": round(g["buy"] / 1e8, 2),
                             "sell_yi": round(g["sell"] / 1e8, 2),
                             "net_yi": round((g["buy"] - g["sell"]) / 1e8, 2),
                             "bursts": sorted(g["bursts"], key=lambda x: -x["wan"])[:8],
                             "mins": [[k, round(v / 1e6, 1)] for k, v in sorted(g["mins"].items())]}
                       for sid, g in agg.items()}}

if __name__ == "__main__":
    main()
