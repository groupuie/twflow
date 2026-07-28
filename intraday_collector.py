#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""台股盤中大盤採集器 — 供 GitHub Actions 於交易日 08:50(台北)啟動長跑
================================================================================
目的:讓靜態網頁(GitHub Pages)也能看「盤中」大盤與推估池流量。
     瀏覽器無法直連證交所 MIS(無 CORS),因此由本程式在伺服器端輪詢,
     把極小的 intraday.json force-push 到 repo 的 `intraday` 分支(單一 commit,
     不膨脹歷史),網頁再從 raw.githubusercontent.com(有 CORS)每分鐘輪詢。

資料源(皆免費、免金鑰):
  - 證交所 MIS  https://mis.twse.com.tw/stock/api/getStockInfo.jsp
      tse_t00.tw = 加權指數(約5秒更新)  otc_o00.tw = 櫃買指數
      欄位:z=最新 y=昨收 o=開 h=高 l=低 t=時間 m/r=量能原始值(單位待官方對帳)
  - 期交所     https://mis.taifex.com.tw/futures/api/getQuoteList
      TXF-S=臺指現貨、TXF*-F=臺指期各月(近月成交價→基差;期貨至13:45)
  - 收盤後回補 https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_INDEX?date=今天
      (每5秒指數,收盤後才發布;用來把當日曲線補完整、驗證盤中序列)
      https://www.twse.com.tw/rwd/zh/afterTrading/MI_5MINS → 累積成交金額(百萬)

執行模式:
  --session  (預設)整場長跑:輪詢至13:48 → 嘗試官方回補至14:40 → 最終推送
  --once     單次輪詢+推送(測試用)
  --minutes N 只跑 N 分鐘後就走收尾流程(本機測試用)
"""
import datetime as dt
import json, os, shutil, subprocess, sys, tempfile, time, urllib.request, urllib.parse

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG = json.load(open(os.path.join(BASE, "config.json"), encoding="utf-8"))
GH = CONFIG.get("github", {})
GH_USER, GH_REPO = GH.get("user", "groupuie"), GH.get("repo", "twflow")
BRANCH = "intraday"
FILE = "intraday.json"
POLL_SEC = 20          # MIS 輪詢間隔(官方約5秒一筆,20秒對站方客氣)
PUSH_SEC = 60          # 推送間隔(有新資料才推)
RAW_URL = f"https://raw.githubusercontent.com/{GH_USER}/{GH_REPO}/{BRANCH}/{FILE}"

MIS = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_t00.tw|otc_o00.tw&json=1&delay=0"
TAIFEX = "https://mis.taifex.com.tw/futures/api/getQuoteList"
TAIFEX_BODY = json.dumps({"MarketType": "0", "SymbolType": "F", "KindID": "1", "CID": "TXF",
                          "ExpireMonth": "", "RowSize": "全部", "PageNo": "", "SortColumn": "", "AscDesc": "A"}).encode()

def now_tp():
    return dt.datetime.utcnow() + dt.timedelta(hours=8)

def http_json(url, data=None, timeout=15, headers=None):
    h = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    if headers:
        h.update(headers)
    if data is not None:
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))

def f(x):
    try:
        v = float(str(x).replace(",", ""))
        return v if v > 0 else None
    except Exception:
        return None

# ---------------- 資料抓取 ----------------
def poll_mis(state):
    d = http_json(MIS)
    for x in d.get("msgArray", []):
        c, z, t = x.get("c"), f(x.get("z")), (x.get("t") or x.get("%") or "")
        if not z or len(t) < 5:
            continue
        key = "tw" if c == "t00" else "ot" if c == "o00" else None
        if not key:
            continue
        st = state.setdefault(key, {})
        st.update({"z": z, "t": t, "y": f(x.get("y")), "o": f(x.get("o")),
                   "h": f(x.get("h")), "l": f(x.get("l")), "m": f(x.get("m"))})
        state["date"] = x.get("d") or state.get("date")
        hm = t[:5]
        state.setdefault("series", {}).setdefault(hm, {})[key] = z
        if key == "tw" and st.get("m"):
            state["series"][hm]["m"] = st["m"]

def poll_taifex(state):
    d = http_json(TAIFEX, data=TAIFEX_BODY)
    rows = (d.get("RtData") or {}).get("QuoteList") or []
    fut = [r for r in rows if str(r.get("SymbolID", "")).endswith("-F") and f(r.get("CLastPrice"))]
    if not fut:
        return
    near = fut[0]  # API 依到期月排序,首筆=近月
    z, t = f(near.get("CLastPrice")), str(near.get("CTime") or "")
    if not z or len(t) < 5:
        return
    hm = f"{t.zfill(6)[:2]}:{t.zfill(6)[2:4]}"
    state["fu"] = {"z": z, "t": hm + ":" + t.zfill(6)[4:6], "id": near.get("SymbolID"),
                   "name": near.get("DispCName"), "y": f(near.get("CRefPrice")), "v": f(near.get("CTotalVolume"))}
    state.setdefault("series", {}).setdefault(hm, {})["fu"] = z

def backfill_official(state, date_str):
    """收盤後用官方『每5秒指數』回補/覆核加權指數曲線;成交金額用官方值收尾。"""
    ds = date_str.replace("-", "")
    try:
        d = http_json(f"https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_INDEX?response=json&date={ds}")
        rows = d.get("data") or []
        if d.get("stat") == "OK" and rows:
            for r in rows:
                hm, v = str(r[0])[:5], f(r[1])
                if v:
                    state.setdefault("series", {}).setdefault(hm, {})["tw"] = v
            state["official_tw"] = True
    except Exception as e:
        print("回補 MI_5MINS_INDEX 失敗:", e)
    try:
        d = http_json(f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_5MINS?response=json&date={ds}")
        rows = d.get("data") or []
        if d.get("stat") == "OK" and rows:
            amt = f(str(rows[-1][-1]))          # 累積成交金額(百萬元)
            if amt:
                state["amt_final_mn"] = amt     # 官方口徑,供對帳與顯示
    except Exception as e:
        print("回補 MI_5MINS 失敗:", e)
    return bool(state.get("official_tw"))

# ---------------- 輸出與推送 ----------------
def build_payload(state, complete=False):
    ser = state.get("series", {})
    rows = [[hm, v.get("tw"), v.get("ot"), v.get("fu"), v.get("m")] for hm, v in sorted(ser.items())]
    tw, ot, fu = state.get("tw", {}), state.get("ot", {}), state.get("fu", {})
    return {
        "date": ("%s-%s-%s" % (state.get("date", "")[:4], state.get("date", "")[4:6], state.get("date", "")[6:8]))
                if len(state.get("date", "")) == 8 else state.get("date", ""),
        "updated": now_tp().strftime("%Y-%m-%d %H:%M:%S"),
        "complete": complete,
        "official_tw": bool(state.get("official_tw")),
        "amt_final_mn": state.get("amt_final_mn"),
        "y": {"tw": tw.get("y"), "ot": ot.get("y"), "fu": fu.get("y")},
        "cur": {"tw": tw.get("z"), "tw_t": tw.get("t"), "tw_h": tw.get("h"), "tw_l": tw.get("l"), "tw_o": tw.get("o"),
                "ot": ot.get("z"), "fu": fu.get("z"), "fu_t": fu.get("t"), "fu_name": fu.get("name")},
        "series": rows,
        "note": "指數:證交所MIS約5秒快照(收盤後以官方每5秒指數回補);期貨:期交所近月;推估池流量由網頁端依近90日迴歸反推,非官方數據",
    }

def _token():
    try:
        for l in open(os.path.join(BASE, ".env"), encoding="utf-8"):
            if l.startswith("GITHUB_TOKEN="):
                return l.split("=", 1)[1].strip()
    except Exception:
        pass
    return (os.environ.get("GITHUB_TOKEN") or "").strip() or None

def push(payload):
    tok = _token()
    if not tok:
        print("無 GITHUB_TOKEN,略過推送")
        return False
    tmp = tempfile.mkdtemp(prefix="twintra_")
    try:
        url = f"https://x-access-token:{tok}@github.com/{GH_USER}/{GH_REPO}.git"
        subprocess.run(["git", "init", "-q", "-b", BRANCH, tmp], check=True)
        open(os.path.join(tmp, FILE), "w", encoding="utf-8").write(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        env = dict(os.environ, GIT_AUTHOR_NAME="twflow-bot", GIT_AUTHOR_EMAIL="bot@twflow",
                   GIT_COMMITTER_NAME="twflow-bot", GIT_COMMITTER_EMAIL="bot@twflow")
        subprocess.run(["git", "-C", tmp, "add", FILE], check=True, env=env)
        subprocess.run(["git", "-C", tmp, "commit", "-q", "-m", "intraday " + payload["updated"]], check=True, env=env)
        r = subprocess.run(["git", "-C", tmp, "push", "-q", "-f", url, BRANCH], env=env,
                           capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            print("push 失敗:", (r.stderr or "")[-300:])
            return False
        return True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

def skip_reason():
    """備援排程防重:分支上已是今天的資料且(3分鐘內有更新=另一採集器在跑,或已標記完成)→ 不重複跑。"""
    try:
        d = http_json(RAW_URL + "?guard=" + str(int(time.time())), timeout=10)
        if d.get("date") == now_tp().strftime("%Y-%m-%d"):
            if d.get("complete"):
                return "今日資料已完成"
            ts = dt.datetime.strptime(d.get("updated", ""), "%Y-%m-%d %H:%M:%S")
            if (now_tp() - ts).total_seconds() < 180:
                return "另一採集器運作中"
    except Exception:
        pass
    return None

# ---------------- 主流程 ----------------
def main():
    once = "--once" in sys.argv
    minutes = None
    if "--minutes" in sys.argv:
        minutes = float(sys.argv[sys.argv.index("--minutes") + 1])
    t0 = now_tp()
    if t0.weekday() >= 5:
        print("週末,不採集");  return
    if not once:
        why = skip_reason()
        if why:
            print("退出:" + why);  return

    state = {}
    end_poll = t0.replace(hour=13, minute=48, second=0, microsecond=0)
    hard_dead = t0.replace(hour=14, minute=40, second=0, microsecond=0)
    if minutes is not None:
        end_poll = min(end_poll, t0 + dt.timedelta(minutes=minutes))
    last_push, n_poll, n_err = 0.0, 0, 0
    print(f"盤中採集啟動 {t0:%F %T}(台北)輪詢至 {end_poll:%H:%M} / 收尾期限 {hard_dead:%H:%M}")

    while True:
        t = now_tp()
        if t >= end_poll or (once and n_poll > 0):
            break
        if t.hour * 60 + t.minute < 8 * 60 + 55:   # 08:55 前暖機等待
            time.sleep(30);  continue
        try:
            poll_mis(state);  n_poll += 1
            if n_poll % 2 == 1:
                try:
                    poll_taifex(state)
                except Exception as e:
                    print("taifex:", e)
            n_err = 0
        except Exception as e:
            n_err += 1
            print(f"MIS 失敗({n_err}):", e)
            if n_err >= 20:
                print("連續失敗過多,提前收尾");  break
        if state.get("series") and time.time() - last_push >= PUSH_SEC:
            if push(build_payload(state)):
                last_push = time.time()
                tw = state.get("tw", {})
                print(f"{t:%H:%M:%S} 已推送 · 加權 {tw.get('z')}({tw.get('t')})· {len(state['series'])} 分鐘點")
        if once:
            break
        time.sleep(POLL_SEC)

    # 晚啟動救援:錯過盤中(如排程延遲)仍抓收盤快照,官方回補後照樣能產出完整當日曲線
    if not state.get("series") and not once and minutes is None \
            and now_tp().hour * 60 + now_tp().minute >= 13 * 60 + 48:
        try:
            poll_mis(state);  poll_taifex(state)
            print("晚啟動:已抓收盤快照,轉入官方回補")
        except Exception as e:
            print("晚啟動快照失敗:", e)

    # 收盤收尾:等官方每5秒資料發布→回補→最終推送(測試模式亦嘗試一次)
    if state.get("series"):
        date_str = build_payload(state)["date"]
        ok = False
        if minutes is not None or once:
            ok = backfill_official(state, date_str)   # 測試:立即試一次,未發布無妨
        else:
            while True:
                t = now_tp()
                hm = t.hour * 60 + t.minute
                if hm >= 13 * 60 + 50:
                    ok = backfill_official(state, date_str)
                    if ok or t >= hard_dead:
                        break
                    time.sleep(120)
                elif t >= hard_dead:
                    break
                else:
                    time.sleep(60)
        payload = build_payload(state, complete=(now_tp().hour * 60 + now_tp().minute >= 13 * 60 + 45) or ok)
        push(payload)
        print("最終推送完成 official_tw=", payload["official_tw"], "amt_mn=", payload.get("amt_final_mn"))
    print("採集結束", now_tp().strftime("%F %T"))

if __name__ == "__main__":
    main()
