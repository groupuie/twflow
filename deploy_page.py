#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一鍵部署:改完程式 → 網頁跟著更新。

    python3 deploy_page.py             # 樣板/前端改動(預設):線上 payload + 本機新樣板 → 推 gh-pages
    python3 deploy_page.py --native    # 資料層也要重算:本機 build_dashboard.py 產 payload → 推
    python3 deploy_page.py --chips     # 另外重建並 force-push chips 分支(籌碼分檔)
    python3 deploy_page.py --dry       # 只建置不推,檢查用

為什麼預設是「移植線上 payload」而不是本機重建:
  沙盒的 data/funds.db 是臨時重建的,`tdcc`(集保股權分散)只抓得到**當週**,
  正式環境的 DB 靠 GitHub Actions 快取逐週累積。本機重建會讓「大戶 400 張+」的
  週變化 ▲▼ 整片消失;而且 generated_at 會變成「現在」,在沒有新盤後資料的情況下
  謊報更新時間 —— run_daily.py 的 DATAFP 指紋機制正是為了避免這件事。
  前端改動只需要換樣板,payload 原封不動搬過來最安全,資料與線上完全一致。
  盤後資料本身仍由 GitHub Actions 每 30 分自動更新(CI 是自主的,不依賴這個沙盒)。

安全檢查:移植前會比對「本機建置的 payload 結構」與「線上 payload 結構」。
  若本機新增了線上沒有的欄位(代表 build_dashboard.py 的 schema 變了),
  會擋下來要求改用 --native,避免前端讀到不存在的欄位。
"""
import json, os, subprocess, sys, urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG = json.load(open(os.path.join(BASE, "config.json"), encoding="utf-8"))
GH = CONFIG.get("github", {})
LIVE = f"https://{GH.get('user','groupuie')}.github.io/{GH.get('repo','twflow')}/"
ANCHOR = "const DATA = "


def run(script, *args, timeout=1800):
    r = subprocess.run([sys.executable, os.path.join(BASE, script), *args],
                       capture_output=True, text=True, timeout=timeout)
    sys.stdout.write(r.stdout[-4000:])
    if r.returncode != 0:
        sys.stdout.write("\nSTDERR:\n" + r.stderr[-2000:])
        raise SystemExit(f"{script} 失敗")
    return r.stdout


def payload_of(html):
    i = html.index(ANCHOR)
    j = html.index("\n", i)
    return html[i + len(ANCHOR):j].rstrip().rstrip(";")


def shape(p):
    """payload 結構指紋:頂層鍵 + meta 鍵(不比對值)"""
    d = json.loads(p)
    return set(d.keys()), set(d.get("meta", {}).keys())


def main():
    native = "--native" in sys.argv
    dry = "--dry" in sys.argv
    out = os.path.join(BASE, "dashboard.html")

    if native:
        print("== 本機重建 payload(--native)==")
        run("build_dashboard.py")
    else:
        print(f"== 移植線上 payload:{LIVE} ==")
        live = urllib.request.urlopen(LIVE, timeout=90).read().decode("utf-8", "replace")
        pl = payload_of(live)
        # 安全檢查:本機 build 是否新增了線上沒有的欄位
        try:
            run("build_dashboard.py")
            lt, lm = shape(payload_of(open(out, encoding="utf-8").read()))
            rt, rm = shape(pl)
            miss = (lt - rt) | {"meta." + k for k in (lm - rm)}
            if miss:
                print(f"⚠ 本機 payload 多出欄位 {sorted(miss)} —— 線上 payload 沒有這些欄位。")
                print("  前端若依賴新欄位會讀到 undefined。請改用:python3 deploy_page.py --native")
                if "--force" not in sys.argv:
                    raise SystemExit("已中止(要略過檢查請加 --force)")
        except SystemExit:
            raise
        except Exception as e:
            print(f"  (結構比對略過:{repr(e)[:80]})")
        tpl = open(os.path.join(BASE, "dashboard_template.html"), encoding="utf-8").read()
        html = tpl.replace("__PAYLOAD__", pl)
        if "__PAYLOAD__" in html:
            raise SystemExit("樣板沒有 __PAYLOAD__ 佔位符")
        open(out, "w", encoding="utf-8").write(html)
        print(f"OK dashboard.html ({len(html)//1024} KB,payload 與線上完全一致)")

    if "--chips" in sys.argv:
        run("build_chips.py")
        if not dry:
            run("deploy_github.py", "--push-chips")

    if dry:
        print("--dry:未推送")
        return
    run("deploy_github.py", "--push")
    print(f"完成 → {LIVE}(GitHub Pages CDN 約 1–2 分鐘生效)")


if __name__ == "__main__":
    main()
