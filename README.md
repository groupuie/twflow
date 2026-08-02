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

# 籌碼駕駛艙(自選股頁)
python3 bt_pool.py 100                     # 選出標的池(自選 + 流動性前 100)並補齊長史
python3 fetch_data.py --chips              # 籌碼長史增量(2013 起;--sid 2330 可單檔)
python3 bt_signals.py                      # 燈號門檻校準與回測 → BACKTEST.md
python3 build_chips.py                     # 產 chips/<sid>.json
python3 deploy_github.py --push-chips      # force-push 到 chips 分支(單一 commit)
python3 qa_adj.py 2330                     # 除權息還原驗證(恆等式殘差應 ~1e-8%)

# 改完程式要讓網頁跟著更新(一鍵)
python3 deploy_page.py                     # 前端改動:線上 payload + 新樣板 → 推 gh-pages
python3 deploy_page.py --native            # 資料層也重算(需本機 DB 完整)
python3 deploy_page.py --chips             # 順便重建並推 chips 分支
```

> `deploy_page.py` 預設**移植線上 payload**而不是本機重建:沙盒 DB 的 `tdcc`(集保股權分散)
> 只抓得到當週,本機重建會讓「大戶 400 張+」的週變化消失,且 `generated_at` 會在沒有新盤後
> 資料時謊報更新時間。前端改動只需換樣板,payload 原封搬移最安全。腳本內建結構比對,
> 若本機 payload 多出線上沒有的欄位會擋下並要求 `--native`。

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
| `dashboard_template.html` | 前端模板(圖表引擎、金流視覺化、個股籌碼駕駛艙) |
| `build_chips.py` | 讀 SQLite `chip_*` 長史 → 產 `chips/<sid>.json`(每檔一個,gzip 後約 57KB) |
| `deploy_page.py` | 一鍵部署(改完程式讓網頁跟著更新) |
| `qa_adj.py` | 除權息/減資/分割還原正確性驗證 |
| `deploy_github.py` | 以 git 推送 gh-pages |
| `run_daily.py` | 每日更新入口(串接上述) |
| `collector_mis.py` | (選用)本機盤中即時採集器,在你自己的電腦執行 |
| `config.json` | 自選股、族群、ETF 分類、現金池等設定 |
| `assets/` | 內嵌用的圖表函式庫(plotly/echarts/chart.js) |

## 個股籌碼駕駛艙(自選股頁)

自選股頁最上方為駕駛艙,五軌對齊:①還原K + 季線60/半年線120/年線240 + 動能60D + TD9 + 除權息標記
+ 年線觸線圈 + (可選)趨勢線/Fibonacci/型態/加權指數疊加/燈號、②量(暗=總量、亮=可切換總量或扣當沖真實換手、
琥珀=量比≥1.75×)、③RVPOS 轉速 + RSI14、④檔位 score、⑤籌碼池累積(法人 vs 信用戶)。
下方另有 ②籌碼池累積(5 軌 + 加權指數疊加)、①存量分解、③成本分佈,以及全史月K(對數軸、還原價,回溯 2013)。

**標的**:自選股 15 檔 + 流動性前 100 大,共 103 檔,附搜尋框與下拉選單;輸入清單外的代號可「＋加入」,
寫進自訂追蹤後由下一輪後端抓取。清單直接讀 `chips` 分支的 `_index.json`,永遠與實際有資料的檔案同步。

**縮放**:開啟「🖱 滾輪縮放/拖曳」後,滾輪為**連續**縮放(1.14×/格,10 日一路到 900 日無段差),
以游標所在那根為錨;可拖曳平移,「↺ 復原」回到 120 日。不使用 Plotly 內建 scrollZoom
(多子圖 + category 主軸下滾輪無效),改為自行在 capture 階段攔截 wheel。

**指標在伺服器端預算**:RVPOS 需 504 日回看、score 需 240 日回看,若在瀏覽器算,送過去的 900 根
前面約 524 根會是 null、可視窗口被壓到 376 天;改由 `build_chips.py` 用全史算好再隨 JSON 送出,
每一根都有效,同時省掉換股時 O(n×505) 的 JS 迴圈卡頓。

- **價格一律用自建還原序列**:除權息 `TaiwanStockDividendResult`、分割 `TaiwanStockSplitPrice`、
  減資 `TaiwanStockCapitalReductionReferencePrice`,因子 `f = 參考價/前日收盤` 由今往回累乘,錨定今天=1.0。
  量的股數乘數優先用官方 `NumberOfSharesIssued` 實測。副標顯示的收盤是**未還原**原值(對得上看盤軟體)。
- **score 用相對加權指數的超額動能**(不是絕對動能):台積電權重近 30%,個股絕對動能會被指數綁架、集體同向。
- **資料走 `chips` 分支分檔懶載入**,不 inline 進 `index.html`(頁面不增肥);
  `raw.githubusercontent.com` 有 CORS `*` 與 gzip,但 `cache-control: max-age=300` 且查詢字串穿不透,
  資料更新後最多 5 分鐘生效(日更資料無影響)。
- **買賣燈號(▲▼)標示為「觀察用」,不是交易訊號**。已完成回測(見 `BACKTEST.md`):
  抄底訊號樣本內領先隨機基準 +1.04%,但樣本外掉到 +0.27%(p=0.12)→ 過度配適;
  減碼訊號的超額報酬在樣本內外**都是正的**,代表「高檔位+高RVPOS+爆量」在台股是動能延續、不是反轉。
  台股單次來回交易成本約 0.585%,兩者都撐不過,因此只標示、不建議依此交易。
- ZigZag/型態門檻已按台股放寬(dev 下限 3%→4%、型態 3%→4.5–5%):台股單日可走 10%,
  照搬美股門檻會讓誤判暴增。

資料為公開盤後資訊、僅供研究參考,非投資建議。
