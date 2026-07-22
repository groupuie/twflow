#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""台股資金流量追蹤系統 — 每日更新入口
執行:抓資料(增量)→ 若為交易日則重建儀表板 → 印出 FINAL JSON 摘要
"""
import json, os, subprocess, sys

BASE = os.path.dirname(os.path.abspath(__file__))

def run(script, arg=None, timeout=3600):
    cmd = [sys.executable, os.path.join(BASE, script)]
    if arg:
        cmd.append(arg)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    sys.stdout.write(r.stdout[-6000:])
    if r.returncode != 0:
        sys.stdout.write("\nSTDERR:\n" + r.stderr[-3000:])
    return r

r = run("fetch_data.py", "--update")
if r.returncode != 0:
    print("FINAL " + json.dumps({"ok": False, "stage": "fetch"}, ensure_ascii=False))
    sys.exit(1)

summary = {}
for line in r.stdout.splitlines():
    if line.startswith("SUMMARY "):
        summary = json.loads(line[8:])

try:
    HAS_GH = any(l.startswith("GITHUB_TOKEN=") for l in open(os.path.join(BASE, ".env"), encoding="utf-8"))
except Exception:
    HAS_GH = False

# 部署條件:資料日期有前進就重建+部署(涵蓋交易日,也能補回漏更新的日子),而非只看 today 是否為交易日
_marker = os.path.join(BASE, ".deployed_date")
_prev = None
try:
    _prev = open(_marker, encoding="utf-8").read().strip()
except Exception:
    pass
_last = summary.get("last_date")
should_deploy = bool(_last) and (_last != _prev or summary.get("trading_day"))

if should_deploy:
    if HAS_GH:
        run("deploy_github.py", "--pull", timeout=600)   # 先同步瀏覽器寫入的最新自訂標的
    b = run("build_dashboard.py")
    if b.returncode != 0:
        print("FINAL " + json.dumps({"ok": False, "stage": "build", **summary}, ensure_ascii=False))
        sys.exit(2)
    # 已設定 GitHub 部署 → 自動推送最新頁面(失敗不影響其他流程)
    if HAS_GH:
        g = run("deploy_github.py", "--push", timeout=900)
        summary["pages_push"] = (g.returncode == 0)
        if g.returncode == 0:
            gh = json.load(open(os.path.join(BASE, "config.json"), encoding="utf-8")).get("github", {})
            if gh.get("user"):
                summary["pages_url"] = f"https://{gh['user']}.github.io/{gh.get('repo','twflow')}/"
            try:
                open(_marker, "w", encoding="utf-8").write(_last)   # 記錄已部署到的資料日期
            except Exception:
                pass

summary["ok"] = True
summary["dashboard"] = os.path.join(BASE, "dashboard.html")
print("FINAL " + json.dumps(summary, ensure_ascii=False))
