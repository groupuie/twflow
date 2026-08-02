#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GitHub Pages 部署(git 協定版;此環境的 GitHub API 代理僅允許 git,故全走 git)
  python3 deploy_github.py --init   # 首次:clone/建 gh-pages 分支、推 index.html + custom_symbols.json
  python3 deploy_github.py --pull   # 更新前:同步遠端(取得瀏覽器寫入的最新自訂標的)
  python3 deploy_github.py --push   # 建置後:推最新 index.html
  python3 deploy_github.py --push-chips  # 籌碼分檔:force-push 到 chips 分支(單一 commit,不留歷史)
需 .env 內含 GITHUB_TOKEN=ghp_xxx(classic,repo 權限);config.json 的 github.user/repo 需已設定。
Pages 由 gh-pages 分支自動啟用,網址:https://{user}.github.io/{repo}/
"""
import json, os, shutil, subprocess, sys

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG = json.load(open(os.path.join(BASE, "config.json"), encoding="utf-8"))
GH = CONFIG.get("github", {})
USER, REPO = GH.get("user"), GH.get("repo") or "twflow"
BRANCH = GH.get("branch") or "gh-pages"
SITE = os.path.join(BASE, "repo_site")

def _token():
    # 本機 .env 優先(避免被沙盒/代理注入的佔位 GITHUB_TOKEN 蓋掉);CI 無 .env 時退回環境變數
    p = os.path.join(BASE, ".env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            if line.startswith("GITHUB_TOKEN="):
                return line.strip().split("=", 1)[1].strip()
    env = os.environ.get("GITHUB_TOKEN")
    if env:
        return env.strip()
    raise SystemExit("GITHUB_TOKEN 未設定(.env 或環境變數皆無)")

def git(*args, cwd=SITE, ok_fail=False):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=600)
    if r.returncode != 0 and not ok_fail:
        raise SystemExit(f"git {' '.join(args[:2])} 失敗: {r.stderr[-400:]}")
    return r

def remote_url():
    return f"https://x-access-token:{_token()}@github.com/{USER}/{REPO}.git"

def ensure_clone():
    if not USER:
        raise SystemExit("config.json github.user 未設定")
    if not os.path.isdir(os.path.join(SITE, ".git")):
        shutil.rmtree(SITE, ignore_errors=True)
        r = subprocess.run(["git", "clone", "--depth", "3", remote_url(), SITE],
                           capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            raise SystemExit(f"clone 失敗(repo 建立了嗎?): {r.stderr[-300:]}")
        git("config", "user.email", "twflow-bot@users.noreply.github.com")
        git("config", "user.name", "twflow-bot")
    git("remote", "set-url", "origin", remote_url())

def checkout_branch():
    r = git("ls-remote", "--heads", "origin", BRANCH)
    if BRANCH in r.stdout:
        git("fetch", "origin", BRANCH)
        git("checkout", "-B", BRANCH, f"origin/{BRANCH}")
    else:
        git("checkout", "--orphan", BRANCH, ok_fail=True)
        git("rm", "-rf", "--cached", ".", ok_fail=True)
        for f in os.listdir(SITE):
            if f != ".git":
                p = os.path.join(SITE, f)
                shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) else os.remove(p)

def stage_and_push(msg):
    shutil.copyfile(os.path.join(BASE, "dashboard.html"), os.path.join(SITE, "index.html"))
    cf = os.path.join(SITE, "custom_symbols.json")
    if not os.path.exists(cf):
        json.dump([], open(cf, "w"))
    open(os.path.join(SITE, ".nojekyll"), "w").close()
    git("add", "-A")
    r = git("commit", "-m", msg, ok_fail=True)
    if r.returncode != 0 and "nothing to commit" in (r.stdout + r.stderr):
        print("內容無變化,略過 commit")
    git("push", "-u", "origin", BRANCH)
    print(f"OK 已推送 {BRANCH};網址:https://{USER}.github.io/{REPO}/")

# ---------------------------------------------------------------- 籌碼分檔(chips 分支)
# 15 檔 × ~150KB × 每日更新 ≈ 2.2MB/天。放 gh-pages 一年會膨脹到 GB 級,
# 因此照 intraday 分支的做法:每次都在全新 repo force-push 單一 commit,分支永遠只有一個 commit。
CHIPS_BRANCH = GH.get("chips_branch") or "chips"
CHIPS_DIR = os.path.join(BASE, "chips")

def push_chips(msg="chips update"):
    import tempfile, glob
    files = sorted(glob.glob(os.path.join(CHIPS_DIR, "*.json")))
    if not files:
        raise SystemExit("chips/ 沒有檔案,請先跑 build_chips.py")
    tok = _token()
    tmp = tempfile.mkdtemp(prefix="twchips_")
    try:
        url = f"https://x-access-token:{tok}@github.com/{USER}/{REPO}.git"
        env = dict(os.environ, GIT_AUTHOR_NAME="twflow-bot", GIT_AUTHOR_EMAIL="bot@twflow",
                   GIT_COMMITTER_NAME="twflow-bot", GIT_COMMITTER_EMAIL="bot@twflow")
        subprocess.run(["git", "init", "-q", "-b", CHIPS_BRANCH, tmp], check=True)
        for f in files:
            shutil.copyfile(f, os.path.join(tmp, os.path.basename(f)))
        subprocess.run(["git", "-C", tmp, "add", "-A"], check=True, env=env)
        subprocess.run(["git", "-C", tmp, "commit", "-q", "-m", msg], check=True, env=env)
        r = subprocess.run(["git", "-C", tmp, "push", "-q", "-f", url, CHIPS_BRANCH],
                           env=env, capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            print("chips push 失敗:", (r.stderr or "")[-400:])
            return False
        total = sum(os.path.getsize(f) for f in files)
        print(f"OK 已 force-push {CHIPS_BRANCH} 分支({len(files)} 檔 / {total//1024} KB);"
              f"讀取:https://raw.githubusercontent.com/{USER}/{REPO}/{CHIPS_BRANCH}/<sid>.json")
        return True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

def do_init():
    ensure_clone()
    checkout_branch()
    stage_and_push("deploy dashboard")

def do_pull():
    ensure_clone()
    r = git("ls-remote", "--heads", "origin", BRANCH)
    if BRANCH not in r.stdout:
        print("遠端尚無分支,略過 pull")
        return
    git("fetch", "origin", f"+refs/heads/{BRANCH}:refs/remotes/origin/{BRANCH}")
    git("checkout", "-B", BRANCH, f"origin/{BRANCH}")
    print("OK 已同步遠端(含最新自訂標的)")

def do_push():
    ensure_clone()
    do_pull()
    stage_and_push("daily update")

if __name__ == "__main__":
    if "--init" in sys.argv:
        do_init()
    elif "--pull" in sys.argv:
        do_pull()
    elif "--push" in sys.argv:
        do_push()
    elif "--push-chips" in sys.argv:
        sys.exit(0 if push_chips() else 1)
    else:
        print(__doc__)
