#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""台股資金流量追蹤系統 — 更新入口(供 GitHub Actions 盤後每 30 分呼叫)
流程:抓資料(增量)→ 重建(取得資料指紋)→ 只有『指紋改變=有新資訊』才部署,
      避免無新資料時空推、把更新時間戳弄得像有更新卻沒更新。
"""
import json, os, subprocess, sys, sqlite3

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "data", "funds.db")

def run(script, arg=None, timeout=3600):
    cmd = [sys.executable, os.path.join(BASE, script)]
    if arg:
        cmd.append(arg)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    sys.stdout.write(r.stdout[-6000:])
    if r.returncode != 0:
        sys.stdout.write("\nSTDERR:\n" + r.stderr[-3000:])
    return r

# 1) 抓當下最新盤後資料(FinMind/證交所/櫃買/期交所/央行…;自癒補缺口)
r = run("fetch_data.py", "--update")
if r.returncode != 0:
    print("FINAL " + json.dumps({"ok": False, "stage": "fetch"}, ensure_ascii=False))
    sys.exit(1)

summary = {}
for line in r.stdout.splitlines():
    if line.startswith("SUMMARY "):
        summary = json.loads(line[8:])

# 是否具備部署權杖:本機 .env 有 GITHUB_TOKEN,或處於 GitHub Actions 環境(用內建 token)
def _env_has_gh():
    try:
        return any(l.startswith("GITHUB_TOKEN=") for l in open(os.path.join(BASE, ".env"), encoding="utf-8"))
    except Exception:
        return False
HAS_GH = _env_has_gh() or os.environ.get("GITHUB_ACTIONS") == "true"

# 2) 先同步瀏覽器寫入的自訂標的,再重建(每次都建,以算出資料指紋)
if HAS_GH:
    run("deploy_github.py", "--pull", timeout=600)
b = run("build_dashboard.py")
if b.returncode != 0:
    print("FINAL " + json.dumps({"ok": False, "stage": "build", **summary}, ensure_ascii=False))
    sys.exit(2)

fp = None
for line in b.stdout.splitlines():
    if line.startswith("DATAFP "):
        fp = line.split(None, 1)[1].strip()

# 2b) 籌碼駕駛艙分檔(chips/<sid>.json)—— 獨立指紋、獨立分支,與 index.html 解耦。
#     即使 index.html 沒變(DATAFP 相同),籌碼長史有新資料仍要推;反之亦然。
def _meta_get(k):
    try:
        c = sqlite3.connect(DB); v = c.execute("SELECT value FROM meta WHERE key=?", (k,)).fetchone(); c.close()
        return v[0] if v else None
    except Exception:
        return None

def _meta_set(k, v):
    try:
        c = sqlite3.connect(DB); c.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (k, v)); c.commit(); c.close()
    except Exception:
        pass

cfp = None
cb = run("build_chips.py", timeout=900)
for line in cb.stdout.splitlines():
    if line.startswith("CHIPSFP "):
        cfp = line.split(None, 1)[1].strip()
summary["chips_built"] = (cb.returncode == 0)
if HAS_GH and cb.returncode == 0 and cfp and cfp != _meta_get("chips_fp"):
    ch = run("deploy_github.py", "--push-chips", timeout=900)
    summary["chips_push"] = (ch.returncode == 0)
    if ch.returncode == 0:
        _meta_set("chips_fp", cfp)
elif cfp:
    summary["chips_skipped"] = "no_new_data"

# 3) 讀上次已部署的指紋(存在 DB meta,經 Actions 快取跨次保存)
prev_fp = None
try:
    c = sqlite3.connect(DB)
    row = c.execute("SELECT value FROM meta WHERE key='deployed_fp'").fetchone()
    prev_fp = row[0] if row else None
    c.close()
except Exception:
    pass

changed = (fp is None) or (fp != prev_fp)   # 指紋不同=有新資訊;算不出指紋時保守部署
summary["data_changed"] = changed

# 4) 只有『有新資訊』才部署 → 更新時間戳才代表真的有新資料
if HAS_GH and changed:
    g = run("deploy_github.py", "--push", timeout=900)
    summary["pages_push"] = (g.returncode == 0)
    if g.returncode == 0:
        gh = json.load(open(os.path.join(BASE, "config.json"), encoding="utf-8")).get("github", {})
        if gh.get("user"):
            summary["pages_url"] = f"https://{gh['user']}.github.io/{gh.get('repo','twflow')}/"
        try:
            c = sqlite3.connect(DB)
            c.execute("INSERT OR REPLACE INTO meta VALUES('deployed_fp', ?)", (fp,))
            c.commit()
            c.close()
        except Exception:
            pass
elif not changed:
    summary["skipped"] = "no_new_data"   # 無新資訊 → 不動網頁、不更新時間戳

summary["ok"] = True
summary["dashboard"] = os.path.join(BASE, "dashboard.html")
print("FINAL " + json.dumps(summary, ensure_ascii=False))
