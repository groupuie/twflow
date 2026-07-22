# 台股資金流量追蹤系統

每交易日盤後自動抓取台股全市場資金流(三大法人買賣超、融資融券、期貨多空、權證、匯率、現金池等),
重建互動式儀表板並發佈到 GitHub Pages。

**線上儀表板:** https://groupuie.github.io/twflow/

## 自動更新(GitHub Actions,零維護)

`.github/workflows/daily.yml` 於**每交易日台北 22:05(14:05 UTC)**自動執行:
抓當日盤後資料 → 重算全市場資金流 → 重建 `index.html` → 推送 gh-pages。
全程跑在 GitHub 免費 CI 上,不需本機開著、也不消耗任何對話額度。

資料庫(`data/funds.db`,含約一年歷史)以 Actions cache 保存於執行間;
首次執行(無快取)會自動全量回補歷史,約 30–40 分鐘,之後每日為增量、約 1–2 分鐘。

### 一次性設定(只需做一次)

1. 到 repo 的 **Settings → Secrets and variables → Actions → New repository secret**
2. 名稱填 `FINMIND_TOKEN`,值填你的 FinMind API 金鑰,存檔。
3. 完成。(推送 gh-pages 用的是 GitHub 內建的 `GITHUB_TOKEN`,不需另外設定。)

之後可到 **Actions** 分頁按 **Run workflow** 手動觸發一次驗證。

## 手動/本機執行

```bash
python3 fetch_data.py --backfill   # 首次:回補歷史
python3 fetch_data.py --update     # 每日:增量抓取
python3 build_dashboard.py         # 重建 dashboard.html
python3 deploy_github.py --push    # 推送 gh-pages
python3 run_daily.py               # = update →(資料有更新則)build → deploy
```

本機執行需在專案根目錄放 `.env`:
```
FINMIND_TOKEN=你的FinMind金鑰
GITHUB_TOKEN=你的GitHubPAT(repo權限)
```

## 檔案

| 檔案 | 說明 |
|---|---|
| `fetch_data.py` | 資料抓取管線(FinMind/證交所/櫃買/期交所/集保/央行 → SQLite) |
| `build_dashboard.py` | 讀 SQLite → 產出單檔互動式 `dashboard.html` |
| `dashboard_template.html` | 前端模板(圖表引擎、金流視覺化) |
| `deploy_github.py` | 以 git 推送 gh-pages |
| `run_daily.py` | 每日更新入口(串接上述) |
| `collector_mis.py` | (選用)本機盤中即時採集器,在你自己的電腦執行 |
| `config.json` | 自選股、族群、ETF 分類、現金池等設定 |
| `assets/` | 內嵌用的圖表函式庫(plotly/echarts/chart.js) |

資料為公開盤後資訊、僅供研究參考,非投資建議。
