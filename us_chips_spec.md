# 美股資金流量儀表板 —「個股籌碼追蹤」(`#sec-chips`) 完整技術規格

> 來源檔:`/tmp/us.html`(單檔 HTML,241,594 bytes / 3,538 行,所有 JS 內嵌於 `<script>` 253–3537 行)
> 圖表庫:**只有 Plotly.js 一個**(`https://cdnjs.cloudflare.com/ajax/libs/plotly.js/2.35.3/plotly.min.js`,line 7)。無 Chart.js / ECharts。
> 本文件目的:**照著重建 UI 與計算邏輯,不需回頭讀原始 HTML。**

---

## 0. 全域常數與環境(重建必備前置)

```js
const DATA_URL = "https://gist.githubusercontent.com/groupuie/147672e7493b26aec57f42f5e12cb524/raw/market_data.json";
const PUB_URL  = "https://raw.githubusercontent.com/groupuie/market-flow-dashboard/data/market_public.json";
const REFRESH_SEC = 20;        // 20s 輪詢主檔
const BUILD='2026-08-02T01:45Z';

const C={bg:'#1a1a19',ink:'#fff',ink2:'#c3c2b7',muted:'#898781',line:'#2c2c2a',
  blue:'#3987e5',green:'#0ca30c',red:'#d03b3b',amber:'#fab219',violet:'#9085e9',aqua:'#199e70'};

const TOUCH=(navigator.maxTouchPoints||0)>0||('ontouchstart' in window);
const PBASE={paper_bgcolor:C.bg,plot_bgcolor:C.bg,
  font:{color:C.ink,size:11,family:'system-ui,-apple-system,sans-serif'},
  margin:{l:50,r:14,t:8,b:34},...(TOUCH?{dragmode:false}:{})};
const CFG={displayModeBar:false,responsive:true,...(TOUCH?{doubleClick:false,scrollZoom:false}:{})};
```

CSS 變數(`:root`,line 9–13):
```css
--bg:#0d0d0d; --surface:#1a1a19; --surface2:#222220; --line:#2c2c2a;
--ink:#ffffff; --ink2:#c3c2b7; --muted:#898781;
--blue:#3987e5; --green:#0ca30c; --red:#d03b3b; --amber:#fab219; --violet:#9085e9; --aqua:#199e70;
```

### 0.1 駕駛艙色票 `CPAL`(line 618–641)— 改這一個物件 = 整個駕駛艙換裝

```js
const CPAL={
  up:'#4ade80', dn:'#f87171',                                            // K棒 漲/跌
  brake1:'#93c5fd', brake2:'#60a5fa', brake3:'#3b82f6',
  brake4:'rgba(226,232,240,.55)', brake4lab:'#cbd5e1',                    // 煞車線×4
  tdS:'#fb923c', tdS8:'rgba(251,146,60,.8)', tdS4:'rgba(251,146,60,.42)',  // TD 賣方計數
  tdB:'#22d3ee', tdB8:'rgba(34,211,238,.8)', tdB4:'rgba(34,211,238,.42)',  // TD 買方計數
  dia:'#e879f9', star:'#facc15',                                          // ◆減碼 ★抄底
  volHot:'#f59e0b', volUp:'rgba(74,222,128,.42)', volDn:'rgba(248,113,113,.38)',
  rv:'#c084fc', rvFill:'rgba(192,132,252,.07)', rsi:'#9aa6b8', sc:'#e6e9ef',
  poolA:'#fab219', poolM:'#c2703e', poolUp:'rgba(74,222,128,.5)', poolDn:'rgba(248,113,113,.45)',
  grid:'#1c2027', mut:'#8792a6', ttl:'#e6e9ef', edge:'#0d0d0d', bgc:'rgba(13,13,13,.68)',
  sup:'74,222,128', res:'248,113,113',                                   // rgb 三元組(供 rgba() 字串拼接)
  vbpUp:'rgba(74,222,128,.32)', vbpDn:'rgba(248,113,113,.30)',
  arc:'rgba(226,232,240,.62)', edge:'rgba(226,232,240,.66)',            // ⚠ edge 重複定義,後者勝(見 §G.6)
  halo:'rgba(248,113,113,.16)', haloLine:'rgba(248,113,113,.55)',
  fib:'rgba(250,204,21,.55)', vwapHi:'#38bdf8', vwapLo:'#f0abfc',
  wk:'rgba(148,163,184,.75)',
  bbUp:'rgba(186,200,220,.40)', bbMid:'rgba(186,200,220,.72)', bbFill:'rgba(148,163,184,.075)',
  idxSpy:'#2dd4bf', idxQqq:'#c084fc',
  bt: '#22c55e', btX:'#ef4444'
};
```

### 0.2 全域狀態變數(區塊專用)

| 變數 | 預設 | 說明 | 行 |
|---|---|---|---|
| `CHIP_SYM` | `''`(首次自動 = `'NVDA'` 若存在,否則 `syms[0]`) | 目前標的 | 406 |
| `CHIP_WIN` | `100` | 視窗天數;可為 `10/30/50/60/100/120/200/250` 或字串 `'max'` | 406 |
| `CHIPK` | `{}` | 日K快取 `{sym:{close:{date:c}, bars:[...]}}` + 旗標 `sym_none` / `sym_r` / `sym_t` | 407 |
| `CHIPKM` | `{}` | 全史月K快取 `{sym:{bars}}` + `sym_none`/`sym_r`/`sym_t` | 1612 |
| `EXTDF` / `EXTDF_req` | `null` / `0` | 擴充 ⑦ 日檔 + 節流時間戳 | 526 |
| `CHIPV` / `CHIPV_req` | `null` / `0` | 大戶/散戶 VWAP 日檔 | 546 |
| `SIG` / `SIG_req` | `null` / `0` | AI 訊號 signals.json | 565 |
| `SCAN`,`SCAN_req`,`SCAN_filter`,`SCAN_sort`,`SCAN_open` | `null,0,'all','score',false` | 掃描面板 | 1685 |
| `CHIP_IDX` | `{SPY:false,QQQ:false}` | 駕駛艙 K線疊加 | 573 |
| `CHIPF_IDX` | `{SPY:false,QQQ:false}` | **現金池圖專屬**疊加(獨立) | 582 |
| `CHIP_TL` | `true` | 自動趨勢線層 | 574 |
| `CHIP_VBP` | `true` | VbP 量價分佈 | 575 |
| `CHIP_PAT` | `false` | 古典型態層 | 576 |
| `CHIP_FIB` | `false` | Fibonacci | 577 |
| `CHIP_VWAP` | `false` | 錨定 VWAP | 578 |
| `CHIP_CTA` | `true` | CTA 煞車線 ×4 | 579 |
| `CHIP_BB` | `false` | 布林 BB(20,2) | 580 |
| `CHIP_ZOOM` | `false` | 滾輪縮放/拖曳模式 | 581 |
| `CHIP_IND` | `'rv'` | 副圖單槽:`rv/macd/adx/atr/cci/stoch` | 583 |
| `CHIP_OFF` | `{price:0,SPY:0,QQQ:0}` | 現金池圖趨勢線上下微調(%) | 1531 |
| `CHIP_TREND` | `{}` | `{key:{idx:traceIndex, base:[原始值], span}}` | 1531 |
| `CKC` | `{}` | `cockpitRows` 結果快取 | 1560 |
| `SPYK`,`QQQK` | `null` | `{date:close}` map | 2979,2987 |
| `BT_IN` | `{td9b:true,ctaUp:false,brk200:false,dc20:false,rvLow:false,cdlB:false}` | 回測進場條件 | 1832 |
| `BT_OUT` | `{td9s:true,ctaDn:true,lose200:false,dcl20:false,stopATR:true,maxHold:true}` | 回測出場條件 | 1833 |

---

## A. HTML 結構

### A.1 分頁鈕(line 76,`.tabs` 內)

```html
<div class="tab" data-sec="chips">個股籌碼</div>
```

分頁切換邏輯(line 3497–3504):
```js
// ⚠ 選擇器必須限定 .tab[data-sec] —— 舊版用 querySelectorAll('.tab') 會把「個股籌碼」的
//   10–250日/全史視窗鈕的 active 一併清掉。
document.querySelectorAll('.tab[data-sec]').forEach(t=>t.onclick=()=>{
  document.querySelectorAll('.tab[data-sec]').forEach(x=>x.classList.remove('active'));
  document.querySelectorAll('.sec').forEach(x=>x.classList.remove('active'));
  t.classList.add('active');
  document.getElementById('sec-'+t.dataset.sec).classList.add('active');
  setTimeout(()=>window.dispatchEvent(new Event('resize')),50);   // 讓 Plotly responsive 重排
});
```

### A.2 `<section id="sec-chips">` 完整 DOM 骨架(line 228–248,逐字)

```html
<section id="sec-chips" class="sec">
  <div class="card">
    <h2 style="display:flex;flex-wrap:wrap;align-items:center;gap:10px">個股籌碼追蹤 — 存量分解 · 現金池累積 · 成本分佈
      <span class="sub">標的</span>
      <select id="chipSym" style="background:#12141a;color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:3px 8px;font-size:13px"></select>
      <input id="chipInput" list="chipDL" placeholder="輸入任何代號 ↵" style="width:130px;background:#12141a;color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:3px 8px;font-size:13px;text-transform:uppercase">
      <datalist id="chipDL"></datalist>
      <span id="chipRange" style="display:inline-flex;gap:6px;flex-wrap:wrap"></span>
      <span id="chipidx" style="display:inline-flex;gap:6px;align-items:center;flex-wrap:wrap;font-size:11px;margin-left:4px"></span>
    </h2>
    <div id="cockpit" style="height:960px"></div>
    <div id="scanpanel" style="margin:10px 0 14px"></div>
    <div id="season" style="margin:10px 0 18px"></div>
    <div id="chipstock" style="margin:14px 0 22px"></div>
    <div id="chipfidx" style="display:flex;gap:8px;align-items:center;margin:0 0 4px 6px;font-size:11px;flex-wrap:wrap"></div>
    <div id="chipflow" style="height:440px"></div>
    <div id="chipoffs" style="display:flex;gap:10px;align-items:center;margin:4px 0 0 6px;font-size:11px;flex-wrap:wrap"></div>
    <div id="chipcost" style="height:460px;margin-top:8px"></div>
    <div id="chipnote" class="note"></div>
  </div>
</section>
```

**父子關係**:`section#sec-chips > div.card > { h2(含 chipSym/chipInput/chipDL/chipRange/chipidx), #cockpit, #scanpanel, #season, #chipstock, #chipfidx, #chipflow, #chipoffs, #chipcost, #chipnote }`。所有 12 個子容器都是 `.card` 的**直接子節點**(扁平,無巢狀)。

> 注意:題目未列的 `#chipfidx`(現金池圖疊加鈕列)與 `#chipoffs`(趨勢線上下微調滑桿列)也屬本區塊,不可漏。

### A.3 動態產生的工具列

#### (a) `#chipRange` — 視窗天數 + 縮放/復位(`renderChips`,line 2528–2536)

```js
const rb=document.getElementById('chipRange');
rb.innerHTML=[10,30,50,60,100,120,200,250].map(n=>{
    const dis=dates.length<Math.min(n,10);   // 資料日數不足 → 灰掉不可點
    const act=CHIP_WIN===n;
    return '<span class="tab '+(act?'active':'')+'" data-cn="'+n+'" style="padding:3px 10px;font-size:12px;'
      +(dis?'opacity:.35;pointer-events:none':'')+'">'+n+'日</span>';}).join('')
  +'<span class="tab '+(CHIP_WIN==='max'?'active':'')+'" data-cn="max" style="padding:3px 10px;font-size:12px">全史</span>'
  +'<span class="tab '+(CHIP_ZOOM?'active':'')+'" id="ckZoom" title="開啟後:滑鼠滾輪縮放、按住拖曳平移(關閉則滾輪照常捲頁)" style="padding:3px 10px;font-size:12px;margin-left:8px">⤢ 縮放拖曳</span>'
  +'<span class="tab" id="ckRst" title="回到目前視窗的原始畫面(視窗天數不變:看 30 日就回 30 日)" style="padding:3px 10px;font-size:12px">⟲ 復位</span>';
rb.querySelectorAll('.tab[data-cn]').forEach(t=>t.onclick=()=>{
  CHIP_WIN=(t.dataset.cn==='max')?'max':+t.dataset.cn; renderChips();});
rb.querySelector('#ckZoom').onclick=()=>{CHIP_ZOOM=!CHIP_ZOOM;cockpitReset(true);};
rb.querySelector('#ckRst') .onclick=()=>cockpitReset(false);
```
- 按鈕:`10日 30日 50日 60日 100日 120日 200日 250日 全史 ⤢縮放拖曳 ⟲復位`
- `data-cn` 屬性;class 一律 `tab`,選中加 `active`。
- **`#chipRange` 每次 `renderChips()` 都整列重建**(不做 sig 快取)。

#### (b) `#chipidx` — K線疊加/圖層切換(`buildChipIdx`,line 584–608)

| 元素 class | 標籤 | 綁定變數 | 邊框色 | 開啟時背景 |
|---|---|---|---|---|
| `.cidxchip[data-k=SPY]` | SPY | `CHIP_IDX.SPY` | `#2dd4bf` | `#2dd4bf26` |
| `.cidxchip[data-k=QQQ]` | QQQ | `CHIP_IDX.QQQ` | `#c084fc` | `#c084fc26` |
| `.cidxchip2` | 趨勢線 | `CHIP_TL` | `#4ade80` | `rgba(74,222,128,.15)` |
| `.cidxchip3` | VbP | `CHIP_VBP` | `#eab308` | `rgba(234,179,8,.15)` |
| `.cidxchip6` | 型態 | `CHIP_PAT` | `#a78bfa` | `rgba(167,139,250,.15)` |
| `.cidxchip8` | Fib | `CHIP_FIB` | `#facc15` | `rgba(250,204,21,.15)` |
| `.cidxchip9` | aVWAP | `CHIP_VWAP` | `#38bdf8` | `rgba(56,189,248,.15)` |
| `.cidxchipC` | CTA | `CHIP_CTA` | `CPAL.brake1` | `rgba(147,197,253,.15)` |
| `.cidxchipB` | 布林 | `CHIP_BB` | `CPAL.bbMid` | `rgba(148,163,184,.15)` |
| `select.cidxind` | 副圖 | `CHIP_IND` | — | — |

共同樣式:`cursor:pointer;padding:2px 10px;border-radius:10px;border:1px solid <色>`;關閉態 `color:var(--muted);opacity:.55`。
副圖下拉選項:`[['rv','RVPOS RSI'],['macd','MACD'],['adx','ADX'],['atr','ATR'],['cci','CCI'],['stoch','KD']]`。
所有 onclick 一律 `<flag>=!<flag>; renderChips();`;SPY/QQQ 額外先呼叫 `ensureSpyK()`/`ensureQQQK()`。

#### (c) `#chipfidx` — 現金池圖專屬疊加(`buildChipFIdx`,line 610–617)

```js
el.innerHTML='<span style="color:var(--muted)">現金池圖疊加</span> '
  +['SPY','QQQ'].map(k=>'<span class="fidxchip" data-k="'+k+'" ...>'+k+'</span>').join(' ')
  +' <span style="color:var(--muted);opacity:.75">(形狀對照:按可視幅度縮放對齊,hover 顯示真實 %)</span>';
```
色票同上(`SPY:#2dd4bf`,`QQQ:#c084fc`)。**與 `#chipidx` 的 SPY/QQQ 完全獨立**。

#### (d) `#chipoffs` — 趨勢線上下微調(`buildChipOffs` → `buildOffs`,line 1538–1555)

```js
function buildOffs(elId, chartId, TREND, OFF, defs, onReset){
  const el=document.getElementById(elId); if(!el)return;
  const keys=defs.filter(d=>TREND[d[0]]).map(d=>d[0]); const sig=keys.join(',');
  if(el.dataset.sig===sig && el.childElementCount)return;   // 同組不重建(60s 刷新不打斷拖動)
  el.dataset.sig=sig;
  if(!keys.length){el.innerHTML='';return;}
  el.innerHTML='<span style="color:var(--muted)">趨勢線上下微調</span> '+defs.map(d=>{
    var k=d[0],lab=d[1],c=d[2];
    if(!TREND[k])return '';
    return '<span style="display:inline-flex;align-items:center;gap:3px">'
      +'<span style="color:'+c+';font-size:11px">'+lab+'↕</span>'
      +'<input type="range" class="offsl" data-k="'+k+'" min="-140" max="140" step="1" value="'+(OFF[k]||0)
      +'" style="width:88px;accent-color:'+c+';vertical-align:middle"></span>';}).join(' ')
    +' <span class="offrs" style="cursor:pointer;color:var(--muted);font-size:11px;text-decoration:underline">歸零</span>';
  el.querySelectorAll('.offsl').forEach(sl=>sl.oninput=function(){
    var k=sl.dataset.k; OFF[k]=+sl.value; var t=TREND[k];
    if(t&&window.Plotly){var shift=(OFF[k]/100)*(t.span||1);
      Plotly.restyle(chartId,{y:[t.base.map(v=>v==null?null:+(v+shift).toFixed(3))]},[t.idx]);}});
  var rs=el.querySelector('.offrs'); if(rs)rs.onclick=onReset;
}
function buildChipOffs(){ buildOffs('chipoffs','chipflow',CHIP_TREND,CHIP_OFF,
  [['price','價','#8ab4f8'],['SPY','SPY','#2dd4bf'],['QQQ','QQQ','#c084fc']],
  function(){CHIP_OFF={price:0,SPY:0,QQQ:0};
    var e=document.getElementById('chipoffs'); if(e)e.dataset.sig='';
    renderChips();}); }
```
- slider 範圍 **−140 … +140,step 1**,單位是「y2 span 的百分比」。
- 位移量 `shift = value/100 × span`,以 `Plotly.restyle` 只改該 trace 的 y,**不重繪整張圖**。
- 歸零:重設 `CHIP_OFF`、清 `dataset.sig`、`renderChips()`。

### A.4 CSS class 與 RWD

相關 class(line 8–58):
```css
.card{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin-bottom:14px}
.tab{padding:6px 13px;border-radius:7px;background:var(--surface2);border:1px solid var(--line);cursor:pointer;font-size:13px;color:var(--ink2)}
.tab.active{background:var(--blue);color:#fff;border-color:var(--blue)}
.note{color:var(--muted);font-size:11.5px;margin-top:8px;line-height:1.5}
.sec{display:none}  .sec.active{display:block}
.miss{color:var(--muted);font-style:italic}
.chip{display:inline-block;padding:1px 6px;border-radius:4px;font-size:11px}
.sub{color:var(--muted);font-size:12px}
.wrap{max-width:1440px;margin:0 auto;padding:16px}
@media(max-width:900px){.g2,.g3{grid-template-columns:1fr}}
@media(pointer:coarse){
  .js-plotly-plot,.js-plotly-plot .plotly,.js-plotly-plot .draglayer,
  .js-plotly-plot .nsewdrag,.js-plotly-plot .drag{touch-action:pan-y !important}
}
```

**手機直立斷點(JS,非 CSS):`MB = (window.innerWidth||1024) < 680`**

| 位置 | MB 分支行為 |
|---|---|
| `renderCockpit` line 1929–1930 | `el.style.height = MB?'980px':'960px'` |
| `renderCockpit` line 2401 | `margin:{l:MB?40:52, r:MB?44:64, t:MB?50:34, b:30}` |
| `renderCockpit` line 2403 | `xaxis.nticks = MB?8:14` |
| `renderCockpit` line 2060–2062 | 標題:MB 用 `y:1.028,size:11.5` 只寫「SYM 駕駛艙 · N日」;桌機用 `y:1.022,size:12.5` 完整長圖例 |
| `renderCockpit` line 2093–2096 | MB 額外補「第二行圖例」annotation(`y:1.004,size:8.5`) |
| `renderCockpit` line 1959 | `dense = MB && win>60` → TD 計數 1–8 歷史段隱藏(僅留 9/13+ 與進行中段) |
| `renderCockpit` line 2087 / 2154 / 2371 | MB 時不畫 VbP 欄頭、不畫聚光燈文字標籤、不畫 Fib 左側標籤 |
| `renderCockpit` line 2295 | 型態標籤:MB 僅畫第一個型態(`!MB||pi===0`),字級 7.5(桌機 8.5) |
| `renderCockpitMax` line 1657 | `el.style.height = MB?'560px':'640px'` |
| `renderCockpitMax` line 1676–1678 | `margin:{l:MB?40:52,r:MB?44:64,t:MB?54:46,b:44}`;`nticks:MB?6:12`;標題 `size:MB?10.5:12` |
| `vbpGeom()` line 1506 | `<680 → {x0:0.878,w:0.114}`;否則 `{x0:0.855,w:0.142}` |

---

## B. 核心 JS 函式(逐一)

### B.1 `chipBars(sym)`(line 520–525)— 日K + 今日盤中K 合併

```js
function chipBars(sym){
  const K=CHIPK[sym]; if(!K||!K.bars||!K.bars.length)return null;
  const tb=((DATA&&DATA.kline_today)||{})[sym];
  if(tb&&tb.length>=6&&tb[0]>K.bars[K.bars.length-1][0])return K.bars.concat([tb]);
  return K.bars;
}
```
- 輸入:symbol。輸出:`bars` 陣列(見 §D.2)。
- 若 `DATA.kline_today[sym]` 存在、長度 ≥6、且其日期 **嚴格大於**日K最後一根 → 附加為今日這根。
- 消費者:`cockpitRows`、`renderChipCost`。

### B.2 `chipDaily()` / `chipSyms()`(line 534–545)

```js
function chipDaily(){   // 主 daily_flows ∪ 擴充 ext_flows(逐日 shallow merge)
  const A=DATA.daily_flows||{}; if(!EXTDF)return A;
  const out={}; new Set([...Object.keys(A),...Object.keys(EXTDF)]).forEach(d=>{
    out[d]=Object.assign({},A[d]||{},EXTDF[d]||{});});   // ⚠ EXTDF 覆蓋主檔
  return out;
}
function chipSyms(){   // 全追蹤宇宙
  const D=chipDaily(); const set=new Set();
  Object.keys(D).forEach(d=>Object.keys(D[d]||{}).forEach(s=>{
    if((D[d][s]||{}).c!=='現金')set.add(s);}));   // 排除類別=現金
  ((DATA&&DATA.ext_universe)||[]).forEach(s=>set.add(s));
  ((DATA&&DATA.custom_symbols)||[]).forEach(s=>set.add(s));
  return [...set].sort();
}
```

### B.3 `cockpitRows(sym)`(line 1561–1599)— **駕駛艙唯一資料來源**

**輸入**:symbol。**輸出**:`rows[]`(僅保留索引 ≥252 的部分),或 `null`。

**前置**:`bars = chipBars(sym)`;`bars.length < 260` → `return null`(硬門檻)。

**快取**:`CKC[sym] = {n:bars.length, last:+bars[last][4], rows}`;命中條件 = 根數與最後收盤都相同。

**演算法**(全部以完整序列計算,不切視窗):

```js
const n=bars.length, C=bars.map(b=>+b[4]), V=bars.map(b=>+(b[5]||0));
// 前綴和(O(1) 取任意期間均值)
const P=new Array(n+1).fill(0), PV=new Array(n+1).fill(0);
for(let i=0;i<n;i++){P[i+1]=P[i]+C[i]; PV[i+1]=PV[i]+V[i];}

// ① 20 日實現波動(年化 %)
const rv=new Array(n).fill(null);
for(let i=20;i<n;i++){
  const rets=[];
  for(let j=i-19;j<=i;j++) if(C[j-1]>0) rets.push(Math.log(C[j]/C[j-1]));   // 20 筆 log return
  if(rets.length<2)continue;
  const m=rets.reduce((a,b)=>a+b,0)/rets.length;
  const va=rets.reduce((a,x)=>a+(x-m)*(x-m),0)/(rets.length-1);             // 樣本變異數 (n-1)
  rv[i]=Math.sqrt(va)*Math.sqrt(252)*100;                                   // 年化 252、×100 成 %
}

// ② RVPOS:504 日 rolling 百分位(含當日,inclusive window,min_periods=60)
const rvp=new Array(n).fill(null);
for(let i=0;i<n;i++){
  if(rv[i]==null)continue;
  let c=0,t=0;
  for(let j=Math.max(0,i-504);j<=i;j++) if(rv[j]!=null){t++; if(rv[j]<=rv[i])c++;}
  if(t>=60) rvp[i]=Math.round(100*c/t);       // 視窗實際長度 = 505 根(i-504 .. i)
}

// ③ TD 神奇九轉 setup(比較 4 根前收盤)
const tds=new Array(n).fill(0), tdb=new Array(n).fill(0);
for(let i=4;i<n;i++){
  tds[i]=C[i]>C[i-4]?tds[i-1]+1:0;    // 賣方 setup:收盤 > 4 根前收盤
  tdb[i]=C[i]<C[i-4]?tdb[i-1]+1:0;    // 買方 setup:收盤 < 4 根前收盤
}
// ⚠ 不封頂(可數到 13、20…);斷 → 歸 0。

// ④ RSI(14),Wilder 平滑
const rsi=new Array(n).fill(null); let ag=null,al=null;
for(let i=1;i<n;i++){
  const ch=C[i]-C[i-1], g=Math.max(ch,0), l=Math.max(-ch,0);
  if(i<14){ag=ag==null?g:ag+g; al=al==null?l:al+l;
    if(i===13){ag/=14; al/=14; rsi[i]=100-100/(1+ag/(al||1e-9));}}
  else{ag=(ag*13+g)/14; al=(al*13+l)/14; rsi[i]=100-100/(1+ag/(al||1e-9));}
}
// ⚠ 種子期只累加 i=1..13 共 13 筆再 /14(非標準的 14 筆平均)。
```

**逐根輸出(從 `i=252` 起)**:
```js
for(let i=252;i<n;i++){
  const s50=(P[i+1]-P[i+1-50])/50, s100=..., s200=...;                 // 含當日的 SMA
  let sc=(C[i]>s50?1:-1)+(C[i]>s100?1:-1)+(C[i]>s200?1:-1)
        +(C[i]>C[i-63]?1:-1)+(C[i]>C[i-126]?1:-1)+(C[i]>C[i-252]?1:-1);
  const v60=(PV[i+1]-PV[i+1-60])/60, v5=(PV[i+1]-PV[i+1-5])/5;
  rows.push({
    d:bars[i][0], o:+bars[i][1], h:+bars[i][2], l:+bars[i][3], c:C[i], v:V[i],
    sc:Math.round(100*sc/6),        // 檔位 score:−100…+100,只會是 ±100/±67/±33/0 的整數捨入
    rv:rvp[i],                      // RVPOS 百分位 0..100
    rsi:rsi[i],
    t50 :(P[i]-P[i-49]) /49,        // ⚠ 煞車線 = 「不含當日」的 49/99/199 日均(shifted MA)
    t100:(P[i]-P[i-99]) /99,
    t200:(P[i]-P[i-199])/199,
    t63 :C[i-63],                   // 動能煞車線 = 63 日前收盤
    tds:Math.max(tds[i],tds[i-1],tds[i-2]),   // 「近 3 根最大 setup」→ 給 TOP/BOT 燈號用
    tdb:Math.max(tdb[i],tdb[i-1],tdb[i-2]),
    tds0:tds[i], tdb0:tdb[i],                 // 當根原始 setup → 給畫數字/TD9 用
    volr :v60>0?V[i]/v60:1,                   // 當日量 / 60日均量
    volr5:v60>0?v5 /v60:1,                    // 5日均量 / 60日均量
    c5:i>=5?C[i-5]:null
  });
}
```

> **關鍵**:`sc` 六項打分 = 3 條 SMA(50/100/200,**含當日**)+ 3 個動能(vs 63/126/252 日前收盤)。
> `t50/t100/t200` 是**「不含當日」的 49/99/199 日均**——刻意設計成「今天收在這個價位以上,50日均線就會被推上去」的 CTA 觸發價,**不是** 50/100/200 SMA 本身。

### B.4 `tdVis(cn)`(line 1600–1611)— TD 段顯示判定

```js
function tdVis(cn){
  // cn = 每根的 setup 計數(斷=0)。一「段」= 連續遞增的計數。
  // 顯示條件:該段最終數到 ≥9(含其 1-8 起數過程),或 段仍進行中(最後一根未斷)。
  // 過去數不到 9 就斷的段 → 整段隱藏。
  const n=cn.length, out=new Array(n).fill(false); let mx=0,lv=false;
  for(let i=n-1;i>=0;i--){
    const c=cn[i];
    if(c>0){
      if(i===n-1||cn[i+1]!==c+1){mx=c; lv=(i===n-1);}   // 偵測到「段尾」→ 記錄該段最大值
      out[i]=(mx>=9)||lv;
    }else{mx=0; lv=false;}
  }
  return out;
}
```
- **由右往左掃**。段尾判定:`i` 是最後一根,或 `cn[i+1] !== cn[i]+1`(下一根不是接續遞增)。
- `lv` 只在段尾恰為最後一根時為 true → 「進行中的段」全段顯示。

### B.5 `ensureChipK(sym)`(line 407–418)

```js
function ensureChipK(sym){
  if(!sym)return;
  if(CHIPK[sym+'_none']&&Date.now()-(CHIPK[sym+'_t']||0)>600e3){   // 10 分後重試
    delete CHIPK[sym+'_none']; delete CHIPK[sym+'_r'];}
  if(CHIPK[sym]||CHIPK[sym+'_r'])return;
  CHIPK[sym+'_r']=true; CHIPK[sym+'_t']=Date.now();
  fetch(DATA_URL.replace('market_data.json','kline_'+sym+'.json'),{cache:'no-store'})
    .then(r=>r.ok?r.json():null)
    .then(d=>{ if(d&&d.bars){const m={}; d.bars.forEach(b=>{m[b[0]]=b[4];});
        CHIPK[sym]={close:m,bars:d.bars}; renderChips();}
      else{CHIPK[sym+'_none']=true; renderChips();}})
    .catch(()=>{CHIPK[sym+'_none']=true; renderChips();});
}
```
- URL 組法:**字串取代** `DATA_URL.replace('market_data.json','kline_'+sym+'.json')`。
- **無 cache-buster**,僅 `{cache:'no-store'}`(與主檔 `load()` 的 `?t=floor(now/15000)` 不同)。
- 三態:`CHIPK[sym]`(有)/ `CHIPK[sym+'_r']`(飛行中)/ `CHIPK[sym+'_none']`(無檔,10 分後可重試)。

### B.6 `ensureChipKMax(sym)` + `aggMonthly(bars)`(line 1613–1628)

```js
function ensureChipKMax(sym){
  if(CHIPKM[sym+'_none']&&Date.now()-(CHIPKM[sym+'_t']||0)>600e3){delete CHIPKM[sym+'_none'];delete CHIPKM[sym+'_r'];}
  if(CHIPKM[sym]||CHIPKM[sym+'_r'])return; CHIPKM[sym+'_r']=true; CHIPKM[sym+'_t']=Date.now();
  fetch(DATA_URL.replace('market_data.json','kline_max_'+sym+'.json'),{cache:'no-store'})
    .then(r=>r.ok?r.json():null)
    .then(d=>{if(d&&d.bars&&d.bars.length>=24){CHIPKM[sym]={bars:d.bars};}
              else{CHIPKM[sym+'_none']=true;} renderChips();})
    .catch(()=>{CHIPKM[sym+'_none']=true;renderChips();});
}
function aggMonthly(bars){   // 日K→月K(降級來源)
  const out=[]; let cur=null,key='';
  bars.forEach(b=>{const k=String(b[0]).slice(0,7);      // 'YYYY-MM'
    if(k!==key){if(cur)out.push(cur);key=k;cur=[k+'-01',+b[1],+b[2],+b[3],+b[4],+(b[5]||0)];}
    else{cur[2]=Math.max(cur[2],+b[2]); cur[3]=Math.min(cur[3],+b[3]); cur[4]=+b[4]; cur[5]+=+(b[5]||0);}});
  if(cur)out.push(cur);
  return out;
}
```
- `kline_max_SYM.json` 需 **≥24 根月K**才採用,否則標 `_none`。
- 月K日期一律正規化為 `YYYY-MM-01`。

### B.7 `renderCockpitMax(el, MB)`(line 1629–1684)— 全史對數月K(獨立渲染路徑)

**觸發**:`CHIP_WIN==='max'` 時,`renderCockpit()` 第一步就跳過來(line 1934)。

**資料選擇**:
1. `CHIPKM[CHIP_SYM].bars`(全史月K檔),否則
2. `CHIPK[CHIP_SYM].bars.length>=60` → `aggMonthly()` 降級,`building=true`
3. `bars.length<12` → `chartMsg` 佔位,`el.style.height='auto'`,return。

**快取鍵**(line 1653):
```js
const sig='max:'+CHIP_SYM+':'+R.length+':'+R[R.length-1].c+(building?':b':'')+(MB?':m':':d')+(CHIP_TL?':t1':':t0');
if(el.dataset.sig===sig&&el.querySelector('.plot-container'))return;
```

**繪圖**:
- 高度 `MB?'560px':'640px'`;x 軸 `type:'category'`,標籤 `r.d.slice(0,7)`(`YYYY-MM`)。
- **y 軸 `type:'log'`**,`side:'right'`。
- 單一 candlestick trace + 趨勢線層。
- 趨勢線在 **log 空間**計算:`lnR = R.map(r=>({d,o:log(o),h:log(h),l:log(l),c:log(c)}))`,呼叫 `autoTrendlines(lnR,{tolmult:2, logspace:true})`,畫回時 `Math.exp(...)`。
- 觸線點:`marker{size:12,color:'rgba(245,158,11,.14)',line:{width:1.4,color:'rgba('+col+',.85)'}}`。
- 已突破線加 `✂` 文字標記,`textfont{size:12}`。
- `el._HL=null`(log 軸交給 Plotly autorange);只 `bindPinch('cockpit',()=>null)`,**不綁 wheel zoom**。
- 底部固定註記:`'全史模式:轉速/檔位/⑦現金池副圖無對應資料已隱藏(切回 10–250 日視窗恢復)'`。

### B.8 `renderCockpit()`(line 1927–2437)— 五軌駕駛艙(本區塊最大函式)

#### B.8.1 前置與早退

```js
const el=document.getElementById('cockpit');
const MB=(window.innerWidth||1024)<680;
el.style.height=MB?'980px':'960px';
el.dataset.unt='';                                       // 離開「未追蹤動作區」狀態
if(CHIPK[CHIP_SYM+'_none']){el.style.height='auto'; chartMsg(el,'日K輪補中(…)'); return;}
if(CHIP_WIN==='max'){renderCockpitMax(el,MB); return;}
const rows=cockpitRows(CHIP_SYM);
if(!rows||rows.length<10){el.style.height='auto'; chartMsg(el,'日K載入中,或歷史不足(駕駛艙需 ≥260 根日K)…'); return;}
const win=Math.max(30,Math.min(CHIP_WIN,250));           // ⚠ 視窗被夾在 [30,250]:選 10 日也畫 30 日
const R=rows.slice(-win);
```

#### B.8.2 ⑦ 現金池序列(第五軌)

```js
const D=chipDaily();
let fi7=R.findIndex(r=>((D[r.d]||{})[CHIP_SYM])!=null); if(fi7<0)fi7=R.length;   // ⑦ 覆蓋起點
let cm=0,ca=0; const pm=[],pa=[],pbar=[];
R.forEach((r,ri7)=>{
  if(ri7<fi7){pm.push(null);pa.push(null);pbar.push(null);return;}   // 起點前一律 null(不畫 0)
  const e=(D[r.d]||{})[CHIP_SYM];
  const m=e?(e.m||0):0, rr=(e&&e.r!=null)?e.r:0;
  cm+=m; ca+=m+rr;
  pm.push(+cm.toFixed(1));    // 大單累積(單位:百萬 M,**不乘 1e6**)
  pa.push(+ca.toFixed(1));    // 全單累積
  pbar.push(m+rr);            // 當日淨進出
});
```

#### B.8.3 **快取鍵 `sig`(§G.1 地雷核心)**(line 1944–1947)

```js
const sig = CHIP_SYM+':'+win+':'+R[R.length-1].d+':'+R[R.length-1].c.toFixed(3)+':'+(pa[pa.length-1]||0)
  +(MB?':m':':d')+(CHIP_TL?':t1':':t0')+(CHIP_VBP?':v1':':v0')+(CHIP_PAT?':p1':':p0')
  +(CHIP_FIB?':f1':':f0')+(CHIP_VWAP?':w1':':w0')+(CHIP_CTA?':c1':':c0')+':i'+CHIP_IND
  +(SIG&&SIG.updated_utc?':g'+SIG.updated_utc:'')
  +(CHIP_BB?':b1':':b0')+(CHIP_ZOOM?':z1':':z0')
  +(CHIP_IDX.SPY?(SPYK?':S1':':S0'):':S-')+(CHIP_IDX.QQQ?(QQQK?':Q1':':Q0'):':Q-');
if(el.dataset.sig===sig && el.querySelector('.plot-container')) return;
el.dataset.sig=sig;
```

**sig 欄位表**(順序即字串順序):

| # | 片段 | 來源 | 用意 |
|---|---|---|---|
| 1 | `SYM` | `CHIP_SYM` | 換股 |
| 2 | `:win` | `clamp(CHIP_WIN,30,250)` | 換視窗 |
| 3 | `:lastDate` | `R[last].d` | 新的一天 |
| 4 | `:lastClose.toFixed(3)` | `R[last].c` | 盤中價變 |
| 5 | `:lastPoolCum` | `pa[last]` (或 0) | ⑦ 累積變 |
| 6 | `:m`/`:d` | `MB` | 手機/桌機切換 |
| 7 | `:t1/:t0` | `CHIP_TL` | 趨勢線 |
| 8 | `:v1/:v0` | `CHIP_VBP` | VbP |
| 9 | `:p1/:p0` | `CHIP_PAT` | 型態 |
| 10 | `:f1/:f0` | `CHIP_FIB` | Fib |
| 11 | `:w1/:w0` | `CHIP_VWAP` | aVWAP |
| 12 | `:c1/:c0` | `CHIP_CTA` | CTA |
| 13 | `:i<ind>` | `CHIP_IND` | 副圖槽 |
| 14 | `:g<updated_utc>` | `SIG.updated_utc`(有才加) | 訊號更新 |
| 15 | `:b1/:b0` | `CHIP_BB` | 布林 |
| 16 | `:z1/:z0` | `CHIP_ZOOM` | 縮放模式 |
| 17 | `:S1/:S0/:S-` | `CHIP_IDX.SPY` + `SPYK` 是否已載入 | 疊加就緒才重畫 |
| 18 | `:Q1/:Q0/:Q-` | `CHIP_IDX.QQQ` + `QQQK` | 同上 |

**額外守門**:`el.querySelector('.plot-container')` — 若 DOM 內沒有 Plotly 容器(例如剛被 `chartMsg` 覆寫成 `<div class=miss>`)則**強制重繪**。

**未進入 sig 的狀態(改了不會重繪)**:`CHIP_OFF`(靠 restyle)、`CHIPF_IDX`(現金池圖狀態,故 `buildChipFIdx` 註解特別寫「駕駛艙 sig 未變會自行早退,不重繪」)、`SCAN_*`、`BT_IN/BT_OUT`(回測層已下架)。

#### B.8.4 版面幾何(位移常數)

```js
const x=R.map(r=>r.d.slice(5));                                   // 'MM-DD'
const rng=Math.max(...R.map(r=>r.h))-Math.min(...R.map(r=>r.l))||1;
const o1=rng*0.016, o2=rng*0.036, o3=rng*0.088;   // TD小字 / TD強調 / ◆★燈號 位移
const smallF=win>120?6.5:7.5, midF=win>120?8:9;   // 大區間縮字
const dense=MB&&win>60;                           // 手機長區間 → 稀疏化 TD 數字
```

#### B.8.5 五軌 y 軸 domain(line 2400–2413)

| 軌 | 軸 | domain | 內容 |
|---|---|---|---|
| 主圖 | `yaxis` | `[0.46, 1.0]` | K棒 + CTA×4 + TD 數字 + ◆★ + 趨勢線/通道 + BB + 型態 + Fib + aVWAP + SPY/QQQ 疊加 + 內部人徽章 + CTA 觸線圈 |
| 量 | `yaxis7` | `[0.375, 0.445]` | 成交量 bar,`tickformat:'~s'` |
| 副圖 | `yaxis8` | `[0.25, 0.36]` | RVPOS+RSI(預設)或 MACD/ADX/ATR/CCI/KD |
| 檔位 | `yaxis9` | `[0.165, 0.235]` | score,`range:[-110,110]`,`tickvals:[-100,-67,-33,0,33,67,100]` |
| ⑦池 | `yaxis10` | `[0, 0.15]` | 當日 bar + 全單累積線 + 大單累積線,`tickformat:'~s'` |

x 軸:`{type:'category', gridcolor:CPAL.grid, tickfont:{size:8.5}, nticks:MB?8:14, rangeslider:{visible:false}, anchor:'y10', domain:[0, XW]}`
其中 `XW = _vb ? (vbpGeom().x0 - 0.010) : 1`。

#### B.8.6 trace 順序(固定,`CHIP_OFF`/restyle 依賴索引)

```
0                       candlestick
1..4  (CHIP_CTA 時)     短50D / 中100D / 長200D / 動63D
5                       TD 賣方數字 (mode:'text', y=tsY)
6                       TD 買方數字 (mode:'text', y=tbY)
7                       ◆減碼 (markers+text, symbol:'diamond', size:11)
8                       ★抄底 (markers+text, symbol:'star',    size:12)
9                       成交量 bar → y7
10..11 (CHIP_IND==='rv') RVPOS 線(fill:'tozeroy') / RSI 線 → y8
12                      score 線 → y9,line{width:1.7, shape:'hv'}
13                      ⑦ 當日 bar → y10
14                      全單累積線 → y10, color CPAL.poolA, width 2
15                      大單累積線 → y10, color CPAL.poolM, width 1.7, dash 'dot'
之後依序 push:BB(3 條) → SPY/QQQ 疊加 → 趨勢線層(meta:'tl') → 內部人徽章(meta:'ins')
           → CTA 觸線圈(meta:'halo') → 型態層(meta:'pat') → 副圖指標(meta:'ind')
           → Fib(meta:'fib') → aVWAP(meta:'vwap')
```

#### B.8.7 TD 數字繪製規則(line 1972–1979)

```js
const s=r.tds0, b=r.tdb0, emS=(s===9||s>=13), emB=(b===9||b>=13);
if(s>=1 && visS[ri] && (emS || !dense || liveS2.has(ri))){
  tsY.push(r.h+(emS?o2:o1));
  tsT.push(String(s));
  tsS.push(s>=13?12.5 : s===9?11.5 : s>=7?midF : smallF);   // 字級
  tsC.push(emS?CPAL.tdS : s>=7?CPAL.tdS8 : CPAL.tdS4);      // 顏色三階
}else{tsY.push(null);tsT.push('');tsS.push(smallF);tsC.push('rgba(0,0,0,0)');}
// 買方對稱:y = r.l-(emB?o2:o1),色票換 tdB/tdB8/tdB4
```
`liveSeg(cn)`(line 1956):由最後一根往回,若 `cn[last]>0` 則沿著 `c, c-1, c-2 …` 收集索引 → 「進行中的段」集合。

#### B.8.8 CTA 煞車線與右緣價位標籤堆(line 2075–2084)

```js
const L=[];
if(CHIP_CTA)L.push(['短50D',R[li].t50,CPAL.brake1],['中100D',R[li].t100,CPAL.brake2],
                   ['長200D',R[li].t200,CPAL.brake3],['動63D',R[li].t63,CPAL.brake4lab]);
if(_chLv)_chLv.forEach(v=>{if(v.y==null||!isFinite(v.y))return; L.push([v.kind,v.y,'rgba('+v.col+',1)']);});
L.sort((a,b)=>a[1]-b[1]);
let pv=-Infinity;
L.forEach(p=>{let y=p[1]; if(y-pv<rng*0.052)y=pv+rng*0.052; pv=y;    // 防疊字:最小間距 5.2% 幅度
  ann.push({xref:'paper',x:XR,xanchor:'right',yref:'y',y:y,yanchor:'middle',showarrow:false,
    text:p[0]+' '+(p[1]>=1000?p[1].toFixed(0):p[1].toFixed(1)),
    font:{size:8.5,color:p[2]},bgcolor:CPAL.bgc});});
```
`XR = _vb ? (vbpGeom().x0-0.016) : 0.998`。`_chLv` 來自 `tlTraces()._lv`(通道上下界,見 §B.15)。

檔位標籤(line 2090):
```js
ann.push({xref:'paper',x:XR,xanchor:'right',yref:'y9',
  y:Math.max(-95,Math.min(95,R[li].sc)),yanchor:'middle',showarrow:false,
  text:'檔位 '+(R[li].sc>0?'+':'')+R[li].sc,
  font:{size:9.5,color:R[li].sc>0?CPAL.up:R[li].sc<0?CPAL.dn:CPAL.sc},bgcolor:CPAL.bgc});
```

#### B.8.9 CTA 觸線圈(只標 200D)(line 2162–2200)

```js
// 有意義的觸線 = 「先離開、再回測」
var _atrC=0,_cn=0;
for(var a7=Math.max(1,R.length-14);a7<R.length;a7++){
  _atrC+=Math.max(R[a7].h-R[a7].l,Math.abs(R[a7].h-R[a7-1].c),Math.abs(R[a7].l-R[a7-1].c)); _cn++;}
var _dep=Math.max(0.04, 1.5*(_cn?_atrC/_cn:0)/Math.max(R[R.length-1].c,1e-9));   // 離開門檻
var CL=[['t200','長期200D']];                                   // 只留 200D
CL.forEach(cc=>{
  var lastHit=-99, away=false;
  for(var k7=1;k7<R.length;k7++){
    var lv=R[k7][cc[0]]; if(lv==null)continue;
    if(Math.abs(R[k7].c-lv)/lv>=_dep) away=true;                // 已離開
    var touch=(R[k7].l<=lv && R[k7].h>=lv);                     // 高低範圍涵蓋線值
    var pv7=R[k7-1][cc[0]];
    var prevTouch=(pv7!=null && R[k7-1].l<=pv7 && R[k7-1].h>=pv7);
    if(!touch||prevTouch)continue;                              // 只標段首根
    if(k7-lastHit<10 || !away)continue;                         // 冷卻 10 根 + 必須曾離開
    lastHit=k7; away=false;
    var hasSig=!!_sigB[k7];                                     // 同日有 TD9/13 或 signals mark
    cx.push(x[k7]); cy.push(+lv.toFixed(3));
    csz.push(hasSig?26:20);
    ccol.push(hasSig?'rgba(250,204,21,.18)':'rgba(147,197,253,.14)');
    cline.push(hasSig?'rgba(250,204,21,.75)':'rgba(147,197,253,.5)');
  }
});
```
`_sigB[q]` 來源:`R[q].tds0===9||tdb0===9||tds0===13||tdb0===13`,或 `SIG.symbols[SYM].marks` 中 kind ∈ {buy,sell,alert} 的日期。

#### B.8.10 SPY/QQQ 疊加(相對強弱)(line 2020–2049)

```js
var _ovl=function(KM,on,col,nm){
  if(!on||!KM)return;
  var b=null,ys=[],has=false;
  for(var i9=0;i9<R.length;i9++){
    var v9=KM[R[i9].d];
    if(v9==null){ys.push(null);continue;}
    if(b==null)b={v:v9, p:R[i9].c};                    // 錨 = 視窗第一根共同日
    ys.push(+(b.p*(v9/b.v)).toFixed(3)); has=true;}    // price_i = 本股錨日收盤 × (指數_i/指數錨日)
  if(!has)return;
  var rel=(ys[last]!=null&&b)?((R[last].c/b.p)/(ys[last]/b.p)-1)*100:null;
  // 可讀性守門
  var vmax=max(ys), vmin=min(ys), span=vmax-vmin;
  var pHi=max(R.h), pLo=min(R.l);
  var fit=(span<rng*0.10)||(vmin<pLo)||(vmax>pHi);     // 三選一成立就啟動「形狀對照」
  var raw=ys.slice();
  if(fit&&span>1e-9){
    var pmid=(pHi+pLo)/2, mid=(vmax+vmin)/2, kk=rng*0.28/span;   // 目標幅度 = 主圖幅度的 28%
    ys=ys.map(q=>q==null?null:+(((q-mid)*kk)+pmid).toFixed(3));
  }
  traces.push({type:'scatter',mode:'lines',x:x,y:ys,meta:'idx',showlegend:false,connectgaps:true,
    customdata:raw, line:{color:col,width:1.5,dash:'dot'},
    hovertemplate:nm+' 同起點換算價 %{customdata:.2f}'+ampT+'<extra></extra>'});
  if(rel!=null)_ovlLeg.push('<span style="color:'+col+'">'+nm+(rel>=0?' 落後 ':' 領先 ')
    +Math.abs(rel).toFixed(1)+'%'+(fit?'·線=形狀對照':'')+'</span>');
};
```
> **注意 `rel` 的語意反轉**:`rel = (本股相對錨日漲幅) / (指數相對錨日漲幅) − 1`。`rel>=0`(本股較強)顯示的字是「**落後**」,`rel<0` 顯示「**領先**」。這是原始碼的既有寫法(可能是 bug,移植時要決定是否照抄)。

#### B.8.11 VbP 與 relayout 重算(line 2419–2434)

```js
el._vbp = _vb ? {R:R, base:_ckLay.shapes.slice(0,2)} : null;   // base = 前 2 個 shape(RVPOS 紅帶+80線)
if(!el._vbpBind && el.on){
  el._vbpBind=1;
  el.on('plotly_relayout',function(ev){
    if(!el._vbp||!CHIP_VBP||!ev)return;
    if(!('xaxis.range' in ev)&&!('xaxis.range[0]' in ev)&&!('xaxis.autorange' in ev))return;
    clearTimeout(el._vbpT);
    el._vbpT=setTimeout(function(){                    // 160ms 去抖
      var Rv=el._vbp.R;
      var r=ev['xaxis.range']||((ev['xaxis.range[0]']!=null)?[ev['xaxis.range[0]'],ev['xaxis.range[1]']]:null);
      var i0=0,i1=Rv.length-1;
      if(r&&!ev['xaxis.autorange']){
        i0=Math.max(0,Math.ceil(Math.min(+r[0],+r[1])));
        i1=Math.min(Rv.length-1,Math.floor(Math.max(+r[0],+r[1])));}
      if(i1-i0<5)return;
      var V2=vbpBins(Rv,i0,i1); if(!V2)return;
      try{Plotly.relayout('cockpit',{shapes:el._vbp.base.concat(vbpShapes(V2))});}catch(e){}
    },160);
  });
}
el._HL={h:R.map(r=>r.h), l:R.map(r=>r.l)};
bindPinch('cockpit',()=>el._HL);
bindWheelZoom('cockpit',()=>el._HL);
```
> ⚠ `base` 取 `_ckLay.shapes.slice(0,2)` — 只有在 `_y8shapes===true`(副圖 = rv)時前兩個 shape 才是 RVPOS 紅帶;切到 MACD 等模式時 `_y8shapes=false`,`shapes` 前兩個其實是 VbP shape → relayout 重算時會把兩個 VbP 條當背景保留。**已知瑕疵**。

#### B.8.12 Plotly config

```js
Plotly.react('cockpit', traces, _ckLay,
  CHIP_ZOOM ? {displayModeBar:false, responsive:true, scrollZoom:false, doubleClick:'reset'} : CFG);
// layout 額外:...(CHIP_ZOOM?{dragmode:'pan'}:{})
```
滾輪縮放**不用 Plotly 內建 scrollZoom**,一律由 `bindWheelZoom` 在 capture 階段自行攔截(見 §G.3)。

### B.9 `cockpitReset(modeChanged)`(line 1915–1922)

```js
function cockpitReset(modeChanged){
  const e=document.getElementById('cockpit'); if(!e)return;
  try{ if(window.Plotly&&(e._fullLayout||e.data))Plotly.purge(e); }catch(_){}
  if(modeChanged)e._vbpBind=0;      // purge 清掉 plotly_relayout 監聽 → 重置以便重綁
  e.dataset.sig=''; e.innerHTML='';
  try{renderCockpit();}catch(_){}
  try{buildChipIdxRangeActive();}catch(_){}
}
function buildChipIdxRangeActive(){
  const z=document.getElementById('ckZoom'); if(!z)return;
  z.className='tab'+(CHIP_ZOOM?' active':'');
}
```
- `purge` 是必要的:`Plotly.react` 不會套用變更後的 config。
- `_pinch` / `_wz` 是 **DOM 事件旗標**,purge 不影響 → **不可重置**,否則重複綁定。

### B.10 `renderChipStock()`(line 2438–2456)— 存量分解(純 HTML,無圖表庫)

**資料**:`DATA.chips_meta[CHIP_SYM]` = `{float, issued, inst_q, inst_n, inst_q_chg, inst_pct_chg, period}`

```js
const M=(DATA.chips_meta||{})[CHIP_SYM];
if(!M){el.innerHTML='<div class="note" style="opacity:.6">存量分解(流通股／13F 大戶持股)僅涵蓋主要追蹤股;<b>擴充清單標的暫不採集此項</b> —— ⑦ 現金池與成本分佈不受影響。(主要股若剛加入,約 15 分內產生)</div>';return;}
if(M.float==null){el.innerHTML='<div class="note" style="opacity:.6">'+CHIP_SYM+'：ETF／無個股持股結構（存量分解僅適用正股）</div>';return;}
const fl=M.float, iq=Math.max(0,M.inst_q||0);
const ipF = fl ? Math.min(100, iq/fl*100) : 0;      // 機構佔比 %(夾在 ≤100)
const npct = Math.max(0,100-ipF);
const nonInst = Math.max(0, fl-iq);
```
- 條狀圖:`<div style="height:20px;border-radius:4px;overflow:hidden;display:flex;border:1px solid var(--line)">`,兩段:機構 `#c2703e`、非機構 `#3a4358`。
- 季變:`qchg>0 ? '#4ade80' : '#f87171'`,文字 `機構季變 ▲ +<股數>(+x.xxpt)`。
- `fmtShares(n)`(line 419–423):`|n|≥1e8 → (n/1e8).toFixed(2)+'億股'`;`≥1e4 → (n/1e4).toFixed(0)+'萬股'`;否則 `Math.round(n)+'股'`。

### B.11 `renderChipCost()`(line 2457–2508)— 籌碼成本分佈(Plotly 水平長條)

**資料**:`chipBars(CHIP_SYM)`(含今日)+ `chipVwapFor()`。

```js
const all=chipBars(CHIP_SYM)||K.bars;
const bars=all.slice(-(CHIP_WIN==='max'?250:CHIP_WIN));     // 全史模式退回 250
if(bars.length<5){chartMsg(el,'此區間日K不足');return;}
let pmin=min(b[3]), pmax=max(b[2]);
const NB=Math.min(50, Math.max(24, Math.round(bars.length)));   // 分箱數:clamp(N,24,50)
const bs=(pmax-pmin)/NB;
// 量分配:每根 K 的量「平均攤到 low..high 覆蓋的所有箱」
bars.forEach(b=>{
  const lo=b[3],hi=b[2],c=b[4],v=b[5]||0;
  sTPV += ((hi+lo+c)/3)*v;  sV += v;                     // 典型價加權 → 區間 VWAP
  let k0=clamp(floor((lo-pmin)/bs),0,NB-1), k1=clamp(floor((hi-pmin)/bs),0,NB-1);
  const each=v/(k1-k0+1);
  for(let k=k0;k<=k1;k++) vol[k]+=each;
});
const centers=vol.map((_,k)=>pmin+(k+0.5)*bs);
let poc=argmax(vol);
// 70% 值區:自 POC 向外擴,每次挑相鄰兩側量較大者
const total=sum(vol)||1; let lo=poc,hi=poc,acc=vol[poc];
while(acc<0.7*total&&(lo>0||hi<NB-1)){
  const dn=lo>0?vol[lo-1]:-1, up=hi<NB-1?vol[hi+1]:-1;
  if(up>=dn){hi++;acc+=vol[hi];}else{lo--;acc+=vol[lo];}
}
const vaLo=pmin+lo*bs, vaHi=pmin+(hi+1)*bs, pocP=centers[poc], px=bars[last][4];
const vwapN=n=>{const bb=all.slice(-n); if(bb.length<Math.min(n,5))return null;
  let a=0,b=0; bb.forEach(x=>{a+=((x[2]+x[3]+x[4])/3)*(x[5]||0); b+=x[5]||0;}); return b?a/b:null;};
const vwW=sV?sTPV/sV:null, v60=vwapN(60), v120=vwapN(120);
```

**顏色**:`k===poc ? '#f59e0b' : (centers[k]<=px ? 'rgba(34,197,94,.5)' : 'rgba(239,68,68,.42)')`

**shapes / annotations**:
| 元素 | 顏色 | dash | 標籤位置 |
|---|---|---|---|
| 70% 值區 rect | `rgba(245,158,11,.07)` | — | layer:'below' |
| 現價 | `#e6e9ef` | solid | 右,`yanchor:'bottom'` |
| 均價`{N}`d(區間 VWAP) | `C.amber`=`#fab219` | dot | 右 |
| VWAP60 | `#8ab4f8` | dash | 右 |
| VWAP120 | `#b07de6` | dash | 右 |
| 大戶均 | `#f472b6` **width:3** | solid | 右,`yanchor:'bottom'`,前綴 ▲/▼ |
| 散戶均 | `#22d3ee` **width:2** | dash | 右,`yanchor:'top'`,前綴 ▲/▼ |
| POC | `#f59e0b` | — | **左**,`xanchor:'left'` |

標題 annotation(`x:0.01,y:1.055,size:11,color:'#9db4e0'`):
```
<b>SYM</b> 籌碼成本分佈 · 近 N 日 · POC x.x · 值區 lo–hi
  [· 價在均價上(獲利盤多·下檔支撐) | · 價在均價下(套牢盤多·上檔壓力)]
```

**layout**:
```js
{...PBASE, barmode:'overlay', bargap:0.05, margin:{l:46,r:58,t:30,b:36}, showlegend:false,
 xaxis:{gridcolor:C.line,tickformat:'~s',zeroline:false,title:{text:'累積成交量(量價分佈)',font:{size:10,color:C.ink2}}},
 yaxis:{gridcolor:C.line,tickfont:{size:9.5},title:{text:'價位 $',font:{size:10,color:C.ink2}}},
 shapes, annotations}
```
trace:`{type:'bar', orientation:'h', x:vol, y:centers, marker:{color:colors}, hovertemplate:'價 $%{y:.2f}<br>量 %{x:,.0f}<extra></extra>'}`

### B.12 `chipVwapFor(sym, dates)`(line 552–564)

```js
function chipVwapFor(sym, dates){
  const hist=CHIPV||{}, today=(DATA&&DATA.chips_vwap_today)||{}, td=DATA&&DATA.trade_date;
  const use={};
  dates.forEach(d=>{const e=(hist[d]||{})[sym]; if(e)use[d]=e;});
  if(td&&today[sym])use[td]=today[sym];            // 今日 VWAP 一定納入
  const es=Object.values(use); if(!es.length)return null;
  let bpv=0,bvol=0,bn=0,bnet=0, spv=0,svol=0,sn=0,snet=0;
  es.forEach(e=>{
    if(e.bvol){bpv+=(e.bvwap||0)*e.bvol; bvol+=e.bvol; bn+=e.bn||0; bnet+=e.bnet||0;}
    if(e.svol){spv+=(e.svwap||0)*e.svol; svol+=e.svol; sn+=e.sn||0; snet+=e.snet||0;}});
  if(!bvol&&!svol)return null;
  return {big:bvol?+(bpv/bvol).toFixed(2):null, small:svol?+(spv/svol).toFixed(2):null,
          bnet:bnet, snet:snet, bn:bn, sn:sn, days:es.length};
}
```

### B.13 `renderChips()`(line 2509–2633)— 本區塊總指揮

**執行順序**:
```
1  ensureExtDaily(); ensureChipVwap(); ensureSignals();
2  D=chipDaily(); dates=Object.keys(D).sort(); syms=chipSyms();
3  if(!syms.length) → chartMsg(chipflow,'個股日檔累積中(需採集器歷史回填)',30); return;
4  if(!CHIP_SYM) CHIP_SYM = syms.includes('NVDA')?'NVDA':syms[0];
5  重建 #chipSym <select>(用 dataset.built=syms.join() 當快取鍵)+ #chipDL <datalist>
6  綁定 #chipInput(dataset.bound 只綁一次;Enter/change → 轉大寫、CHIP_SYM=v、renderChips())
7  重建 #chipRange(每次都重建)
8  buildChipIdx()
9  if(!syms.includes(CHIP_SYM)) → 渲染「未追蹤動作區」到 #cockpit(見下),清空其他容器,return
10 ensureChipK(CHIP_SYM)
11 renderCockpit()
12 try{renderSeason()}
13 try{ensureScan(); renderScan()}
14 renderChipStock()
15 renderChipCost()
16 計算 ⑦ 現金池序列 → 繪 #chipflow
17 buildChipFIdx()   (在 shapeFit 之後、繪圖之前)
18 buildChipOffs()
19 寫入 #chipnote.innerHTML(每次都寫)
```

**未追蹤標的動作區**(line 2538–2568):
- 守門:`ck.dataset.unt===CHIP_SYM && document.getElementById('chipAddBtn')` → 只 `chartMsg(el,'—')` 並 return(**避免 20s 迴圈洗掉輸入中的 token**)。
- 按鈕:`#chipLkBtn`(⚡點播查詢,`chipLookup`)、`#chipAddBtn`(＋加入自訂追蹤,`chipAddCustom`)、`#chipTokIn`+`#chipTokBtn`(GitHub token,存 `localStorage['gh_token']`,長度需 ≥20)。
- 狀態文字容器 `#chipAddStat`。

**現金池序列**(line 2578–2584):
```js
const use=dates.slice(-(CHIP_WIN==='max'?250:CHIP_WIN));
let fi=use.findIndex(d=>((D[d]||{})[CHIP_SYM])!=null); if(fi<0)fi=use.length;
let cmM=0,cmA=0;
use.forEach((d,ui)=>{
  x.push(d.slice(5));
  if(ui<fi){barA.push(null);lineM.push(null);lineA.push(null);return;}
  const e=(D[d]||{})[CHIP_SYM]; const m=e?(e.m||0):0, r=(e&&e.r!=null)?e.r:0;
  const da=(m+r)*1e6;                       // ⚠ 這裡乘 1e6(換算成「元」),駕駛艙那條不乘
  cmM+=m*1e6; cmA+=da;
  barA.push(da); lineM.push(cmM); lineA.push(cmA);
});
if(x.length<2||fi>=use.length){chartMsg(el,'此標的 ⑦ 日檔還沒有(…)',30);return;}
```

**價格 % 與疊加**(line 2589–2612):
```js
const K=CHIPK[CHIP_SYM], cl=K&&K.close, _tb=((DATA&&DATA.kline_today)||{})[CHIP_SYM];
const praw=use.map(d=>{ if(cl&&cl[d]!=null)return cl[d]; if(_tb&&_tb[0]===d)return _tb[4]; return null;});
const pb=praw.find(v=>v!=null);
const ppct=(pb==null)?praw.map(()=>null):praw.map(v=>v!=null?+((v/pb-1)*100).toFixed(2):null);
const idxReb=(K)=>{if(!K)return use.map(()=>null);
  const raw=use.map(d=>K[d]!=null?K[d]:null); const b=raw.find(v=>v!=null);
  return b==null?raw.map(()=>null):raw.map(v=>v!=null?+((v/b-1)*100).toFixed(2):null);};

// 形狀對照(shapeFit):對齊中線、按可視幅度縮放,係數 0.85
const shapeFit=(arr)=>{
  if(!arr)return arr;
  const v=arr.filter(x=>x!=null), pv=ppct.filter(x=>x!=null);
  if(v.length<2||pv.length<2)return arr;
  const pmid=(max(pv)+min(pv))/2, pspan=Math.max(1e-9, max(pv)-min(pv));
  const mid =(max(v) +min(v)) /2, span =Math.max(1e-9, max(v) -min(v));
  const k=(pspan/span)*0.85;
  return arr.map(x=>x==null?null:+(((x-mid)*k)+pmid).toFixed(3));
};
const spyR=CHIPF_IDX.SPY?(ensureSpyK(),idxReb(SPYK)):null;
const qqqR=CHIPF_IDX.QQQ?(ensureQQQK(),idxReb(QQQK)):null;
const spyS=spyR?shapeFit(spyR):null, qqqS=qqqR?shapeFit(qqqR):null;
const bases=[]; if(ppct.some(v=>v!=null))bases.push(ppct);
                if(spyS&&spyS.some(v=>v!=null))bases.push(spyS);
                if(qqqS&&qqqS.some(v=>v!=null))bases.push(qqqS);
const y2=y2Range(bases); const S=y2?y2.span:1;
CHIP_TREND={};
const off=(base,k)=>base.map(v=>v==null?null:+(v+(CHIP_OFF[k]||0)/100*S).toFixed(3));
```

**traces**:
```js
[
 {type:'bar',    name:'當日淨進出', x, y:barA,
  marker:{color:barA.map(v=>v>=0?'rgba(34,197,94,.55)':'rgba(239,68,68,.5)'),line:{width:0}},
  hovertemplate:'%{x} 當日:%{y:,.0f}<extra></extra>'},
 {type:'scatter',mode:'lines',name:'全單累積',      x, y:lineA,
  line:{color:C.amber,width:2.2,shape:'spline'}},
 {type:'scatter',mode:'lines',name:'大單累積(機構)', x, y:lineM,
  line:{color:'#c2703e',width:2,dash:'dot'}},
 // 條件 push,並登錄到 CHIP_TREND
 價格%: yaxis:'y2', connectgaps:true, line:{color:'#8ab4f8',width:1.7}
 SPY  : yaxis:'y2', customdata:spyR, line:{color:'#2dd4bf',width:1.6,dash:'dot'}
 QQQ  : yaxis:'y2', customdata:qqqR, line:{color:'#c084fc',width:1.6,dash:'dot'}
]
```
**layout**:
```js
{...PBASE, barmode:'overlay', margin:{l:70,r:64,t:40,b:34}, showlegend:false,
 annotations:[{ text:'<b>SYM</b> 現金池累積 · 過去 N 日…', xref:'paper',yref:'paper',
                x:0.01,y:1.055,showarrow:false,font:{size:11.5,color:C.amber},xanchor:'left'}],
 xaxis:{type:'category',gridcolor:C.line,tickfont:{size:9}},
 yaxis:{gridcolor:C.line,zerolinecolor:'#777',tickformat:'~s',
        title:{text:'↑進場買貨(現金離池) / ↓了結(現金入池)',font:{size:10,color:C.ink2}}},
 yaxis2:{overlaying:'y',side:'right',showgrid:false,tickfont:{size:9,color:'#8ab4f8'},
         title:{text:'價 %',font:{size:10,color:'#8ab4f8'}}, range:y2.range}}
```
繪後:`bindPinch('chipflow',null)`(無 HL → 只縮 x)、`buildChipOffs()`。
`#chipflow` **無 sig 快取,每次 renderChips 都重繪**。

### B.14 `ensureScan()` / `renderScan()`(line 1685–1757)

```js
function ensureScan(){
  const n=Date.now()/1000; if(n-SCAN_req<300)return; SCAN_req=n;    // 5 分節流
  fetch('data/scan.json?t='+Math.floor(Date.now()/300000),{cache:'no-store'})   // ⚠ 相對路徑(Pages 同源)
    .then(r=>r.ok?r.json():null).then(j=>{if(j&&j.rows){SCAN=j;renderScan();}}).catch(()=>{});
}
```
Cache buster:`?t=floor(now/300000)`(5 分桶)。

**過濾器 `SCAN_F`**(line 1693–1704):
| key | 標籤 | 條件 |
|---|---|---|
| `all` | 全部 | `true` |
| `brk` | 趨勢線突破 | `!!r.trendline_break` |
| `pat` | 型態確認 | `(r.pattern_hits||[]).some(p=>p.state==='confirmed')` |
| `tri` | 三角收斂 | `(r.pattern_hits||[]).some(p=>/三角/.test(p.type||''))` |
| `vcp` | VCP | `(r.pattern_hits||[]).some(p=>/^VCP/.test(p.type||''))` |
| `near` | 近煞車線 | `r.near_line && Math.abs(r.near_line.dist_pct)<2` |
| `hl52` | 52週高/低 | `r.is_52w_high||r.is_52w_low` |
| `rv` | RV高位 | `(r.rv_pct||0)>=80` |
| `cta` | CTA翻轉區 | `r.cta_score!=null && Math.abs(r.cta_score)<=33` |
| `fib` | 貼近Fib | `!!r.fib_zone` |

**排序 `cmp`**:`score`(降)、`sym`(升,字串)、`chg1d`(降)、`rv`(`rv_pct` 降)、`cta`(`cta_score` 降)。

**sig 快取**:`'sc:'+SCAN.updated_utc+':'+SCAN_filter+':'+SCAN_sort+':'+(SCAN_open?1:0)+':'+CHIP_SYM`

**渲染**:純 HTML `<table>`;展開時列出 **前 60 列**;`max-height:320px;overflow-y:auto`。
- 標頭:`全市場掃描` + `{n} 檔 · {updated_utc.slice(0,16)} UTC · 視窗 {win}日` + 展開/收合。
- 欄:`標的 / 分數 / 當日% / CTA / RV%` + `觸發條件`(`(r.why||[]).slice(0,3).join(' · ')`)。
- 顏色:分數 `#fab219`;`chg1d>=0 → #4ade80` 否則 `#f87171`;`cta_score>0 → #4ade80`,`<0 → #f87171`,`=0 → #c3c2b7`;`rv_pct>=80 → #f59e0b` 否則 `#c3c2b7`。
- 當前標的列高亮 `background:rgba(167,139,250,.08)`。
- 點代號 → 若在 `#chipSym` 選項內則同步 select,否則直接設 `CHIP_SYM`;`ensureChipK(sy); renderChips(); cockpit.scrollIntoView({behavior:'smooth',block:'start'})`。
- 底部固定文案:`掃描=機械條件比對(趨勢線突破/型態/煞車線距離/52週高低/Fib/CTA分數/RV/擠壓);**score 僅供排序,非買賣建議**。代號可點擊直接載入上方駕駛艙。`

### B.15 `renderSeason()`(line 1758–1811)— 季節性年×月矩陣(純 HTML)

```js
if(CHIP_WIN==='max'){el.innerHTML='';el.dataset.sig='';return;}    // 全史模式不顯示
const KM=CHIPKM[CHIP_SYM];
let src=null,full=false;
if(KM&&KM.bars&&KM.bars.length>=36){src=KM.bars.map(b=>[b[0],+b[4]]); full=true;}
else{const K=CHIPK[CHIP_SYM];
     if(K&&K.bars&&K.bars.length>=250){src=aggMonthly(K.bars).map(b=>[b[0],+b[4]]);}}
const sig='se:'+CHIP_SYM+':'+(src?src.length:0)+(full?':F':':d');
if(el.dataset.sig===sig)return; el.dataset.sig=sig;
if(!src||src.length<24){el.innerHTML='<div class="note" style="opacity:.75">季節性:'+CHIP_SYM+' 月資料不足(需 ≥24 個月)</div>';return;}
// 月報酬 = 當月收盤 / 前月收盤 − 1
for(let i=1;i<src.length;i++){
  const y=+src[i][0].slice(0,4), m=+src[i][0].slice(5,7);
  const r=src[i-1][1]>0?(src[i][1]/src[i-1][1]-1)*100:null;
  if(r==null)continue; cell[y+'-'+m]=r; if(!years.includes(y))years.push(y);
}
years.sort((a,b)=>b-a);                                   // 新年份在上
// 每月統計:平均、勝率
const stat=MN.map((_,mi)=>{ const v=years.map(y=>cell[y+'-'+(mi+1)]).filter(x=>x!=null);
  if(!v.length)return {n:0};
  return {n:v.length, avg:sum(v)/v.length, win:100*v.filter(x=>x>0).length/v.length};});
// 色階
const mx=Math.max(...Object.values(cell).map(Math.abs),1);
const col=v=>{ if(v==null)return 'transparent';
  const a=Math.min(1,Math.abs(v)/(mx*0.75))*0.62;
  return v>=0?'rgba(74,222,128,'+a.toFixed(2)+')':'rgba(248,113,113,'+a.toFixed(2)+')';};
```
- 顯示 **最近 14 年**(`years.slice(0,14)`)。
- 表尾兩列:`平均`(色:`avg>=0?'#4ade80':'#f87171'`)、`勝率`(整數 %)。
- 註腳:`月報酬=當月收盤/前月收盤−1;綠=正、紅=負,深淺依幅度。樣本 N 年,**統計描述非預測**;年數少時單月平均易被極端值主導。`

### B.16 輔助:`chartMsg` / `freshPlot` / `bindWheelZoom` / `bindPinch` / `xzApply`

```js
function chartMsg(el,msg,pad){ if(!el)return;
  try{ if(window.Plotly&&(el._fullLayout||el.data))Plotly.purge(el); }catch(e){}   // ⚠ 必須先 purge
  el.innerHTML='<div class="miss" style="padding:'+(pad||24)+'px">'+msg+'</div>'; }

function freshPlot(id){ const e=document.getElementById(id);
  if(e&&e.firstChild&&!e.querySelector('.plot-container'))e.innerHTML='';   // 清掉佔位訊息殘留
  return e; }

function xzN(gd){return Math.max(2,(((gd.data||[])[0]||{}).x||[]).length);}
function xzCur(gd){
  const fa=gd._fullLayout&&gd._fullLayout.xaxis;      // 優先讀 _fullLayout
  const r=(fa&&!fa.autorange&&fa.range)||(gd.layout&&gd.layout.xaxis&&gd.layout.xaxis.range);
  const n=xzN(gd);
  return (r&&r.length===2)?[+r[0],+r[1]]:[-0.5,n-0.5];
}
function xzApply(gd,getHL,lo,hi){
  const n=xzN(gd);
  lo=Math.max(-0.5,lo); hi=Math.min(n-0.5,hi);
  if(hi-lo<5){const c=(lo+hi)/2;lo=c-2.5;hi=c+2.5;}        // 最小可視 5 根
  const full=(lo<=-0.4&&hi>=n-0.6);
  // ⚠ 一律用「顯式數值範圍」,絕不用 autorange:true —— Plotly 2.35 在本圖(category 主軸 + y7~y10
  //   多軌 + paper shapes)對 xaxis.autorange 會在 doAutoRange 內丟
  //   TypeError: Cannot read properties of undefined (reading '_extremes')
  if(full){lo=-0.5;hi=n-0.5;}
  const upd={'xaxis.range':[lo,hi]};
  const HL=getHL&&getHL();
  if(HL&&HL.h&&HL.h.length){                               // 價格軸依可視K棒自適應
    const i0=full?0:Math.max(0,Math.ceil(lo)), i1=full?HL.h.length-1:Math.min(HL.h.length-1,Math.floor(hi));
    let mn=Infinity,mx=-Infinity;
    for(let i=i0;i<=i1;i++){if(HL.l[i]!=null&&HL.l[i]<mn)mn=HL.l[i]; if(HL.h[i]!=null&&HL.h[i]>mx)mx=HL.h[i];}
    if(mx>mn){const pad=(mx-mn)*0.08; upd['yaxis.range']=[mn-pad,mx+pad];}   // 上下留 8%
  }
  try{Plotly.relayout(gd,upd);}catch(e){}
}
```

`bindWheelZoom(id,getHL)`(line 464–492)重點:
- `gd._wz` 只綁一次;`addEventListener('wheel', fn, {passive:false, capture:true})`。
- `CHIP_ZOOM===false` → 直接 return(不攔截,滾輪照常捲頁)。
- 只在繪圖區內生效(`cx∈[xa._offset, xa._offset+xa._length]`,`cy∈[fl._size.t, fl._size.t+fl._size.h]`)。
- `deltaMode===1 → ×16`,`===2 → ×100`;`d=clamp(dy/100,-3,3)`;`k=Math.exp(d*0.32)`。
- `span=clamp(span0*k, 8, n)`(最小 8 根);以游標為錨 `fx=(cx-x0)/(x1-x0)`。
- `requestAnimationFrame` 合併連發(16ms)。

`bindPinch(id,getHL)`(line 493–519)重點:
- `gd._pinch` 只綁一次;僅 TOUCH 裝置。
- `touchstart` 兩指 → 記 `{d0:max(20,dist), x0:midX, r0:cur()}`。
- `touchmove`:`k=d0/max(20,dist)`(拉開→k<1=放大);`fx` 以捏合中點為錨;`dx=(midX-x0)/w*span0` 做平移。

---

## C. 指標函式群(完整演算法)

### C.1 `fibLevels(R, piv)`(line 1336–1359)
```js
function fibLevels(R,piv){
  var N=R.length; if(N<20)return null;
  var hi=null,lo=null;
  if(piv&&piv.length>=2){
    piv.forEach(p=>{ if(p.t==='H'&&(!hi||p.px>hi.px))hi=p;
                     if(p.t==='L'&&(!lo||p.px<lo.px))lo=p;});   // ZigZag 極值
  }
  if(!hi||!lo){                                                  // 退化:視窗真實極值
    var ih=0,il=0;
    for(var i=0;i<N;i++){if(R[i].h>R[ih].h)ih=i; if(R[i].l<R[il].l)il=i;}
    hi={i:ih,px:R[ih].h,d:R[ih].d}; lo={i:il,px:R[il].l,d:R[il].d};
  }
  var span=hi.px-lo.px; if(!(span>0))return null;
  var down=hi.i<lo.i;                     // true = 高在前(下跌波)
  var RAT=[0,0.236,0.382,0.5,0.618,0.786,1];
  return {hi,lo,down,startI:Math.min(hi.i,lo.i),
    levels:RAT.map(r=>({r, px:+(down?(hi.px-span*r):(lo.px+span*r)).toFixed(3),
      lab:(r===0?'0':(r===1?'100':(r*100).toFixed(1)))+'%'}))};
}
```
繪製:`line{color:CPAL.fib='rgba(250,204,21,.55)', width:(r===0||r===1)?1.3:1, dash:(r===0||r===1)?'solid':'dot'}`,x 從 `startI` 到最後一根;桌機在 `xref:'paper', x:0.062` 左側標 `fib xx%`;另標 `swing高`/`swing低`。

### C.2 `anchoredVwap(R, anchorI)`(line 1360–1369)
```js
function anchoredVwap(R,anchorI){
  var out=new Array(R.length).fill(null), pv=0, vv=0;
  for(var i=anchorI;i<R.length;i++){
    var tp=(R[i].h+R[i].l+R[i].c)/3, v=R[i].v||0;
    pv+=tp*v; vv+=v;
    out[i]=vv>0?+(pv/vv).toFixed(3):null;
  }
  return out;
}
```
**日K近似**(典型價 × 量累積),非逐筆 VWAP。繪製時取視窗最高 `ih5` 與最低 `il5` 兩個錨:
`[[il5, CPAL.vwapLo='#f0abfc','低錨'], [ih5, CPAL.vwapHi='#38bdf8','高錨']]`,`line{width:1.6}`,`connectgaps:false`。
底部固定註記(`x:0.5,y:1.001,size:7.5`):`aVWAP=日K近似(典型價×量累積),非逐筆 VWAP`。

### C.3 `weeklyAgg(R)` / `weeklyMA(R,n)`(line 1370–1398)
```js
function weeklyAgg(R){
  var wk=[],cur=null,key='';
  function isoWeek(ds){
    var t=new Date(String(ds)+'T00:00:00Z');
    if(isNaN(t.getTime()))return String(ds);        // 防禦:非 YYYY-MM-DD → 逐根一組
    var day=(t.getUTCDay()+6)%7;                    // 週一 = 0
    t.setUTCDate(t.getUTCDate()-day);
    return t.toISOString().slice(0,10);             // 該週週一日期
  }
  R.forEach((r,i)=>{ var k=isoWeek(r.d);
    if(k!==key){if(cur)wk.push(cur); key=k; cur={k,o:r.o,h:r.h,l:r.l,c:r.c,v:r.v||0,i0:i,i1:i};}
    else{cur.h=Math.max(cur.h,r.h); cur.l=Math.min(cur.l,r.l); cur.c=r.c; cur.v+=(r.v||0); cur.i1=i;}});
  if(cur)wk.push(cur);
  return wk;
}
function weeklyMA(R,n){
  var wk=weeklyAgg(R), out=new Array(R.length).fill(null);
  for(var w=0;w<wk.length;w++){
    if(w+1<n)continue;
    var s2=0; for(var q=w-n+1;q<=w;q++)s2+=wk[q].c;
    var ma=s2/n;
    for(var k=wk[w].i0;k<=wk[w].i1;k++)out[k]=+ma.toFixed(3);   // 階梯:整週同值
  }
  return {ma:out, wk:wk};
}
```
> **注意**:MTFA 週線疊加已於 2026-08-01 **下架**(line 2385 註解),`weeklyAgg/weeklyMA` 保留為工具函式,**目前無任何畫面消費者**。

### C.4 `bbands(rows,n,k)`(line 1399–1411)
```js
function bbands(rows,n,k){
  n=n||20; k=(k==null)?2:k;
  var up=[],mid=[],lo=[],s=0,s2=0;
  for(var i=0;i<rows.length;i++){
    var c=rows[i].c; s+=c; s2+=c*c;
    if(i>=n){var d=rows[i-n].c; s-=d; s2-=d*d;}       // 滑動視窗
    if(i<n-1){up.push(null);mid.push(null);lo.push(null);continue;}
    var m=s/n, va=Math.max(0,s2/n-m*m), sd=Math.sqrt(va);   // ⚠ 母體標準差(/n),非樣本(/n-1)
    mid.push(+m.toFixed(3)); up.push(+(m+k*sd).toFixed(3)); lo.push(+(m-k*sd).toFixed(3));
  }
  return {up,mid,lo,n,k};
}
```
**呼叫方式**:`bbands(rows, 20, 2)` 用**完整 rows**(非視窗切片),再 `slice(rows.length-R.length)` → 左緣不缺暖機段。
**繪製順序(fill 依賴)**:先 push 下軌 → 再 push 上軌(`fill:'tonexty', fillcolor:CPAL.bbFill`)→ 最後中軌(`dash:'longdashdot', width:1.15`)。上下軌 `line{color:CPAL.bbUp,width:0.9}`,全部 `connectgaps:false`。

### C.5 `indEMA(v,n)`(line 1412)
```js
function indEMA(v,n){var o=[],k=2/(n+1),e=null;
  for(var i=0;i<v.length;i++){e=(e==null)?v[i]:v[i]*k+e*(1-k); o.push(e);} return o;}
```
種子 = 第一個值本身(**無 SMA 暖機**)。

### C.6 `indMACD(R,f,sl,sg)`(line 1413–1422)
```js
function indMACD(R,f,sl,sg){
  f=f||12; sl=sl||26; sg=sg||9;
  var C=R.map(r=>r.c);
  var ef=indEMA(C,f), es=indEMA(C,sl);
  var dif=C.map((_,i)=>ef[i]-es[i]);
  var dea=indEMA(dif,sg);
  return {dif:dif.map(v=>+v.toFixed(4)),
          dea:dea.map(v=>+v.toFixed(4)),
          hist:dif.map((v,i)=>+((v-dea[i])*2).toFixed(4))};   // ⚠ 柱 = (DIF−DEA)×2(中國/通達信慣例)
}
```
繪製:柱 `rgba(74,222,128,.5)/rgba(248,113,113,.5)`;DIF `#38bdf8` w1.4;DEA `#fbbf24` w1.2。
y8 範圍:`[-max|v|*1.15, +max|v|*1.15]`,`zerolinecolor:'#39404d'`。
標籤:`MACD(12,26,9) <DIF>/<DEA>·柱=(DIF−DEA)×2`

### C.7 `indATR(R,n)`(line 1423–1432)
```js
function indATR(R,n){
  n=n||14; var tr=[],atr=[];
  for(var i=0;i<R.length;i++){
    tr.push(i===0?(R[0].h-R[0].l)
                 :Math.max(R[i].h-R[i].l, Math.abs(R[i].h-R[i-1].c), Math.abs(R[i].l-R[i-1].c)));
    if(i<n-1)atr.push(null);
    else if(i===n-1){var s3=0;for(var q=0;q<n;q++)s3+=tr[q]; atr.push(s3/n);}   // 種子=簡單平均
    else atr.push((atr[i-1]*(n-1)+tr[i])/n);                                    // Wilder 平滑
  }
  return atr.map(v=>v==null?null:+v.toFixed(4));
}
```
繪製(`CHIP_IND==='atr'`):轉成**佔價 %** `100*ATR/close`,`fill:'tozeroy'`,`line{color:'#fb923c',width:1.5}`,`fillcolor:'rgba(251,146,60,.08)'`。
y8:`[0, max*1.2]`。標籤:`ATR(14) 佔價% · 現值 X%(≈日均波動)`

### C.8 `indADX(R,n)` 與內嵌 `wilder(a)`(line 1433–1468)
```js
function indADX(R,n){
  n=n||14;
  var pdm=[],ndm=[],tr=[];
  for(var i=0;i<R.length;i++){
    if(i===0){pdm.push(0);ndm.push(0);tr.push(R[0].h-R[0].l);continue;}
    var up=R[i].h-R[i-1].h, dn=R[i-1].l-R[i].l;
    pdm.push(up>dn&&up>0?up:0);
    ndm.push(dn>up&&dn>0?dn:0);
    tr.push(Math.max(R[i].h-R[i].l, Math.abs(R[i].h-R[i-1].c), Math.abs(R[i].l-R[i-1].c)));
  }
  function wilder(a){                       // Wilder 累加平滑(回傳「和」而非「均」)
    var o=new Array(a.length).fill(null), s4=0;
    for(var i=1;i<a.length;i++){
      if(i<n){s4+=a[i]; if(i===n-1)o[i]=s4;}          // 前 n-1 筆累加,i===n-1 時輸出第一個和
      else if(i===n){s4+=a[i]; o[i]=s4;}              // ⚠ i===n 又加一次(共 n 筆),非標準
      else o[i]=o[i-1]-o[i-1]/n+a[i];                 // 標準 Wilder 遞推
    }
    return o;
  }
  var sp=wilder(pdm), sn=wilder(ndm), st=wilder(tr);
  var pdi=[],ndi=[],dx=[], adx=new Array(R.length).fill(null);
  for(var i=0;i<R.length;i++){
    if(sp[i]==null||st[i]==null||!st[i]){pdi.push(null);ndi.push(null);dx.push(null);continue;}
    var p=100*sp[i]/st[i], q2=100*sn[i]/st[i];
    pdi.push(p); ndi.push(q2);
    dx.push((p+q2)?100*Math.abs(p-q2)/(p+q2):null);
  }
  var acc=0,cnt=0,started=-1;
  for(var i=0;i<R.length;i++){
    if(dx[i]==null)continue;
    if(started<0){acc+=dx[i];cnt++; if(cnt===n){adx[i]=acc/n; started=i;}}   // 前 n 筆 DX 平均
    else adx[i]=(adx[i-1]*(n-1)+dx[i])/n;                                    // Wilder 平滑
  }
  return {adx:adx.map(v=>v==null?null:+v.toFixed(2)),
          pdi:pdi.map(v=>v==null?null:+v.toFixed(2)),
          ndi:ndi.map(v=>v==null?null:+v.toFixed(2))};
}
```
繪製:`+DI #4ade80 w1.1`、`−DI #f87171 w1.1`、`ADX #e6e9ef w1.7`。
y8:`[0, max(60, maxVal*1.1)]`,`tickvals:[0,20,25,40,60]`。標籤含 `(ADX>25=趨勢明確)`。

### C.9 `indCCI(R,n)`(line 1469–1480)
```js
function indCCI(R,n){
  n=n||20; var o=new Array(R.length).fill(null);
  var tp=R.map(r=>(r.h+r.l+r.c)/3);
  for(var i=n-1;i<R.length;i++){
    var s5=0; for(var q=i-n+1;q<=i;q++)s5+=tp[q];
    var m=s5/n, md=0;
    for(var q2=i-n+1;q2<=i;q2++)md+=Math.abs(tp[q2]-m);
    md/=n;                                        // 平均絕對離差
    o[i]=md?+((tp[i]-m)/(0.015*md)).toFixed(2):null;
  }
  return o;
}
```
繪製:`line{color:'#c084fc',width:1.5}`;y8 `[-cm*1.1, cm*1.1]` 其中 `cm=Math.max(220, max|CCI|)`;`tickvals:[-200,-100,0,100,200]`。標籤:`CCI(20)(±100 為常態帶、±200 為極端)`。

### C.10 `indStoch(R,n,k1,d1)` 與內嵌 `sma2`(line 1481–1505)
```js
function indStoch(R,n,k1,d1){
  n=n||14; k1=k1||3; d1=d1||3;
  var raw=new Array(R.length).fill(null);
  for(var i=n-1;i<R.length;i++){
    var hh=-Infinity, ll=Infinity;
    for(var q=i-n+1;q<=i;q++){hh=Math.max(hh,R[q].h); ll=Math.min(ll,R[q].l);}
    raw[i]=hh>ll?100*(R[i].c-ll)/(hh-ll):50;
  }
  function sma2(a,m){                        // 嚴格 m 筆(不足回 null)
    var o=new Array(a.length).fill(null);
    for(var i=0;i<a.length;i++){
      var s6=0,c=0;
      for(var q=i-m+1;q<=i;q++) if(q>=0&&a[q]!=null){s6+=a[q];c++;}
      if(c===m)o[i]=s6/m;
    }
    return o;
  }
  var K=sma2(raw,k1), D=sma2(K,d1);
  return {k:K.map(v=>v==null?null:+v.toFixed(2)),
          d:D.map(v=>v==null?null:+v.toFixed(2))};
}
```
即 **Slow Stochastic(14,3,3)**。繪製:`%K #38bdf8 w1.5`、`%D #fbbf24 w1.2`;y8 `[0,100]`,`tickvals:[0,20,50,80,100]`。

### C.11 `vbpBins(R,i0,i1)`(line 1318–1332)
```js
function vbpBins(R,i0,i1){
  var n=i1-i0+1; if(n<5)return null;
  var NB=Math.max(20, Math.min(50, Math.round(n/5)));      // 箱數 = clamp(round(N/5), 20, 50)
  var lo=min(R[i0..i1].l), hi=max(R[i0..i1].h);
  if(!(hi>lo))return null;
  var bs=(hi-lo)/NB, up=Array(NB).fill(0), dn=Array(NB).fill(0), ctr=[];
  for(var b=0;b<NB;b++)ctr.push(+(lo+(b+0.5)*bs).toFixed(4));
  for(k=i0;k<=i1;k++){
    var bi=clamp(Math.floor((R[k].c-lo)/bs),0,NB-1);       // ⚠ 只用「收盤」落箱(不像 renderChipCost 攤平)
    if(R[k].c>=R[k].o)up[bi]+=R[k].v; else dn[bi]+=R[k].v; // 依當根漲跌分紅綠
  }
  var mx=1; for(b=0;b<NB;b++)if(up[b]+dn[b]>mx)mx=up[b]+dn[b];
  return {ctr,up,dn,max:mx,bw:bs};
}
```

### C.12 `vbpGeom()` / `vbpShapes(vb)`(line 1506–1530)
```js
function vbpGeom(){return ((window.innerWidth||1024)<680)?{x0:0.878,w:0.114}:{x0:0.855,w:0.142};}

function vbpShapes(vb){
  var out=[], G=vbpGeom(), VBP_X0=G.x0, VBP_W=G.w;
  // 分隔細線(置於柱底外側)
  out.push({type:'rect',xref:'paper',yref:'paper',
    x0:VBP_X0+VBP_W+0.003, x1:VBP_X0+VBP_W+0.005, y0:0.46, y1:1,
    fillcolor:'rgba(148,163,184,.28)', line:{width:0}, layer:'below'});
  var poc=argmax(vb.up[b]+vb.dn[b]);
  for(var b=0;b<vb.ctr.length;b++){
    var g=VBP_W*vb.up[b]/vb.max, r=VBP_W*vb.dn[b]/vb.max;
    if(g<=0&&r<=0)continue;
    var y0=vb.ctr[b]-vb.bw*0.46, y1=vb.ctr[b]+vb.bw*0.46;   // 柱高 = 0.92 × 箱寬
    var X1=VBP_X0+VBP_W;                                     // 柱底靠右,向左長
    var isP=(b===poc);
    if(g>0)out.push({type:'rect',xref:'paper',yref:'y',x0:X1-g,    x1:X1,   y0,y1,
      fillcolor:isP?'rgba(74,222,128,.62)':CPAL.vbpUp, line:{width:0}, layer:'below'});
    if(r>0)out.push({type:'rect',xref:'paper',yref:'y',x0:X1-g-r,  x1:X1-g, y0,y1,
      fillcolor:isP?'rgba(248,113,113,.58)':CPAL.vbpDn, line:{width:0}, layer:'below'});
    if(isP)out.push({type:'rect',xref:'paper',yref:'y',x0:X1-g-r,  x1:X1,   y0,y1,
      fillcolor:'rgba(0,0,0,0)', line:{width:1.1,color:CPAL.volHot}, layer:'below'});   // POC 框
  }
  out._poc=(poc>=0)?vb.ctr[poc]:null;
  return out;
}
```
> **關鍵設計**:VbP 是 **paper-x shapes**,**不用 `xaxis2`**。註解明言:「overlaying 軸 + 事後 restyle/relayout 會讓 Plotly 2.35 把主類別軸重判成 date,已實測毒性,勿改回。」
> K線 x 軸 domain 收到 `[0, x0-0.010]`,VbP 佔 `[x0, x0+w]` → 零重疊。

### C.13 `y2Range(bases)`(line 1533–1537)
```js
function y2Range(bases){
  const v=[]; bases.forEach(a=>a&&a.forEach(x=>{if(x!=null)v.push(x);}));
  if(!v.length)return null;
  const mn=Math.min(...v), mx=Math.max(...v), S=Math.max(mx-mn, 2);   // span 最小 2(%)
  return {range:[mn-0.6*S, mx+0.6*S], span:S};   // 線佔中央 ~45%,上下各留 0.6 span 餘裕
}
```
**用途**:固定 `#chipflow` 的 `yaxis2.range`,讓 slider 拖動時線不壓扁、其它 trace 不動;`span` 供位移比例換算(`shift = slider%/100 × span`)。

---

## D. 資料契約

### D.1 資料來源總表

| 檔案 / 欄位 | 取得方式 | URL 組法 | Cache buster | 節流 | 消費者 |
|---|---|---|---|---|---|
| `market_data.json` | `load()` fetch | 硬編碼 `DATA_URL` | `?t=floor(now/15000)`(15s 桶) | 20s 輪詢 | 全域 `DATA` |
| `market_public.json` | `load()` fetch | 硬編碼 `PUB_URL` | 同上 | 同上 | `mergeSources` 備援 |
| `kline_<SYM>.json` | `ensureChipK` | `DATA_URL.replace('market_data.json','kline_'+sym+'.json')` | **無**(只 `cache:'no-store'`) | 三態旗標;`_none` 10 分後重試 | `CHIPK` |
| `kline_max_<SYM>.json` | `ensureChipKMax` | `.replace(...,'kline_max_'+sym+'.json')` | 無 | 同上 | `CHIPKM`(全史月K) |
| `kline_SPY.json` / `kline_QQQ.json` | `ensureSpyK/QQQK` | `.replace(...,'kline_SPY.json')` | 無 | 一次性(`SPYK_req`) | `SPYK`/`QQQK` |
| `ext_flows.json` | `ensureExtDaily` | `.replace(...,'ext_flows.json')` | 無 | **600 秒** | `EXTDF` |
| `chips_vwap.json` | `ensureChipVwap` | `.replace(...,'chips_vwap.json')` | 無 | **300 秒** | `CHIPV` |
| `daily_flows.json` | `ensureDeepDaily` | `.replace(...,'daily_flows.json')` | 無 | **15 分** | `DFULL` → `mergeDeep` |
| `data/signals.json` | `ensureSignals` | **相對路徑**(Pages 同源) | `?t=floor(now/300000)` | 300 秒 | `SIG` |
| `data/scan.json` | `ensureScan` | **相對路徑** | `?t=floor(now/300000)` | 300 秒 | `SCAN` |

**Loading 狀態處理**:全部走 `chartMsg(el, msg, pad)`(先 `Plotly.purge` 再寫 `<div class="miss">`),再由 `freshPlot(id)` 在轉回圖表時清除殘留。

### D.2 K線檔 schema(`kline_SYM.json` / `kline_max_SYM.json` / `kline_SPY.json`)

```jsonc
{
  "bars": [
    ["2025-01-02", 123.45, 126.00, 122.10, 125.30, 48213400 /*, …可能有更多欄位 */],
    …
  ]
}
```
- **陣列壓縮**(非物件),固定欄位順序:`[0]=date 'YYYY-MM-DD'(月K為 'YYYY-MM-01')`,`[1]=open`,`[2]=high`,`[3]=low`,`[4]=close`,`[5]=volume`。
- 程式只讀 `b[0]..b[5]`;`b[5]` 可缺(`+(b[5]||0)`)。後續欄位被忽略(`chipBars` 註解寫 `[[date,o,h,l,c,v,..]]`)。
- 日期**必須升冪排序**(所有 `slice(-N)` / `bars[bars.length-1]` 都假設如此)。
- 載入後另建 `close` map:`{date: close}`。
- `kline_max_*` 需 `bars.length>=24` 才採用;`renderCockpitMax` 需 `>=12`;`renderSeason` 需 `>=36`(全史)或日K `>=250`(降級)。

### D.3 `market_data.json` 中本區塊消費的欄位

| 欄位 | 型別 | 頻率 | 說明 |
|---|---|---|---|
| `trade_date` | `'YYYY-MM-DD'` | 每輪 | 今日交易日 |
| `daily_flows` | `{date: {sym: {m, r, c}}}` | 日 | ⑦ 日檔。`m`=大單淨流(**單位:百萬**),`r`=中小單淨流(百萬,可缺),`c`=類別字串(如 `'正股'`/`'現金'`) |
| `kline_today` | `{sym: [date,o,h,l,c,v,...]}` | 60s | 今日盤中K(單根,同 bars 格式) |
| `chips_meta` | `{sym: {float, issued, inst_q, inst_n, inst_q_chg, inst_pct_chg, period}}` | 季 | 存量分解;`float/issued/inst_q/nonInst` 單位=股數;`inst_pct_chg` 單位=百分點;`period` 例 `'2025Q4'` |
| `chips_vwap_today` | `{sym: {bvwap,bvol,bn,bnet,svwap,svol,sn,snet}}` | 盤中 | 今日大戶/散戶 VWAP |
| `custom_symbols` | `string[]`(上限 30) | — | 自訂追蹤 |
| `ext_universe` | `string[]` | — | 擴充清單(已入列、資料輪補中) |
| `capital_flow` | `{['US.'+sym]: {main_net, retail_net, cat}}` | 即時 | (本區塊不直接用,`flowMap` 用) |

### D.4 `ext_flows.json`
```jsonc
{ "daily_flows": { "2025-01-02": { "AVGO": {"m": 12.3, "r": -4.5, "c": "半導體"}, … }, … } }
```
與 `DATA.daily_flows` 逐日 `Object.assign` 合併,**`ext_flows` 覆蓋主檔同名 sym**。

### D.5 `chips_vwap.json`
```jsonc
{ "daily": { "2025-01-02": { "NVDA": {
      "bvwap": 128.34, "bvol": 12345678, "bn": 3210, "bnet":  4500000,
      "svwap": 128.90, "svol":  9876543, "sn": 88210, "snet": -1200000 }, … }, … } }
```
- `b*` = 大單(big);`s*` = 散戶(small)。`*vwap`=成交量加權均價,`*vol`=量,`*n`=筆數,`*net`=淨買賣(用於 ▲/▼ 方向)。
- 加總方式:量加權(`Σ vwap×vol / Σ vol`);`bn/sn/bnet/snet` 直接求和。

### D.6 `data/signals.json`
```jsonc
{ "updated_utc": "2026-08-02T01:30:00Z",
  "symbols": {
    "NVDA": {
      "insider_90d": { "last": [ {"d":"2026-07-15","act":"買","val":1250000,"who":"J. Doe"}, … ] },  // ≤5 筆
      "marks": [ {"d":"2026-07-20","kind":"buy|sell|alert","title":"…","conf":3} ],
      "next_earnings": "2026-08-20"
    } } }
```
消費:內部人徽章(同日同向聚合,買=綠 B 畫在 `low - o3*1.9`,賣=紅 S 畫在 `high + o3*1.9`,marker size 11,`who` 最多列 3 人)、事件聚光燈(`kind∈{buy,sell,alert}` + 財報日 `conf:3`;按 `conf` 降序、再按 index 降序;去重後 **取前 6**;畫成 `circle` shape `x0=q-2.2,x1=q+2.2,y0=c-rng*0.075,y1=c+rng*0.075`,`fillcolor:'rgba(245,158,11,.08)'`,`line:'rgba(245,158,11,.28)'`)。

### D.7 `data/scan.json`
```jsonc
{ "n": 240, "updated_utc": "2026-08-02T01:30", "win": 200,
  "rows": [ { "sym":"NVDA", "score": 8.4, "chg1d": 1.23, "cta_score": 67, "rv_pct": 84,
              "why": ["趨勢線突破","VCP confirmed","近 200D"],
              "trendline_break": true,
              "pattern_hits": [ {"type":"VCP 波動收縮","state":"confirmed"} ],
              "near_line": {"dist_pct": -1.2},
              "is_52w_high": false, "is_52w_low": false,
              "fib_zone": "0.618" }, … ] }
```

### D.8 駕駛艙五條軌道所需序列(移植檢核表)

| 軌 | 需要的序列 | 來自 |
|---|---|---|
| ① 主圖 | `o,h,l,c`(K棒);`t50,t100,t200,t63`(CTA×4);`tds0,tdb0`(TD 數字);`tds,tdb,sc,rv,volr,volr5,c5`(◆★ 燈號);`h,l`(TD/燈號位移基準) | `cockpitRows` 全部由日K算出 |
| ② 量 | `v`;`volr`(著色門檻 1.75) | 日K `b[5]` |
| ③ 副圖 | `rv`(RVPOS)、`rsi`;或 MACD/ADX/ATR/CCI/KD(全部只需 `o,h,l,c`) | `cockpitRows` + `ind*` |
| ④ score | `sc` | `cockpitRows` |
| ⑤ ⑦現金池 | `daily_flows[date][sym].m` 與 `.r` → `pbar / pa / pm` | `chipDaily()` |

**主圖可選圖層額外需要**:`SPYK/QQQK`(疊加)、`SIG`(徽章/聚光燈)、日K完整 `rows`(BB 用全長)。

---

## E. 訊號邏輯

### E.1 TOP / BOT 燈號(◆減碼 / ★抄底)(`renderCockpit` line 1961–1967)

```js
R.forEach((r,ri)=>{
  const TOP = (r.sc===100    ?1:0)    // ① 檔位滿檔(六項全咬合)
            + (r.rv>=90      ?1:0)    // ② RVPOS ≥ 90(波動百分位紅線區)
            + (r.tds>=9      ?1:0)    // ③ 近 3 根內 TD 賣方 setup ≥ 9
            + (r.volr5>=1.5  ?1:0);   // ④ 5日均量 / 60日均量 ≥ 1.5
  const dn = r.c5!=null && r.c<r.c5;  // 近 5 日下跌
  const BOT = (r.tdb>=9              ?1:0)   // ① 近 3 根內 TD 買方 setup ≥ 9
            + (r.rv>=80              ?1:0)   // ② RVPOS ≥ 80
            + ((r.volr>=1.75 && dn)  ?1:0)   // ③ 殺量竭盡:當日量 ≥1.75×60日均量 且 5日下跌
            + (r.sc<66               ?1:0);  // ④ 檔位 score < 66
  const isT = TOP>=3, isB = BOT>=3;           // ⚠ 4 選 3 才亮
  topY.push(isT ? r.h+o3 : null);  topT.push(isT&&!pT ? '減碼' : '');   // 連續齊發只標首日字樣
  botY.push(isB ? r.l-o3 : null);  botT.push(isB&&!pB ? '抄底' : '');
  pT=isT; pB=isB;
});
```

**畫法**:
```js
// ◆ 減碼:畫在最高價 + rng*0.088
{type:'scatter',mode:'markers+text',x,y:topY,text:topT,textposition:'top center',
 textfont:{size:8.5,color:CPAL.dia='#e879f9'},
 marker:{symbol:'diamond',size:11,color:CPAL.dia,line:{width:2,color:CPAL.edge}},
 name:'減碼',hovertemplate:'◆ TOP≥3 訊號齊發:強制減碼<extra></extra>'}
// ★ 抄底:畫在最低價 − rng*0.088
{type:'scatter',mode:'markers+text',x,y:botY,text:botT,textposition:'bottom center',
 textfont:{size:8.5,color:CPAL.star='#facc15'},
 marker:{symbol:'star',size:12,color:CPAL.star,line:{width:1.5,color:CPAL.edge}},
 name:'抄底',hovertemplate:'★ BOT≥3 訊號齊發:抄底階梯<extra></extra>'}
```
> `chipnote` 用 ▼/▲ 描述(▼=TOP、▲=BOT),但圖上實際符號是 **◆(diamond)= TOP/減碼**、**★(star)= BOT/抄底**。文案與符號不一致,移植時擇一。

### E.2 `score` 檔位六項打分(`cockpitRows`)

```js
sc_raw = (C[i] > SMA50(含當日)  ? +1 : −1)
       + (C[i] > SMA100(含當日) ? +1 : −1)
       + (C[i] > SMA200(含當日) ? +1 : −1)
       + (C[i] > C[i−63]        ? +1 : −1)     // 3 個月動能
       + (C[i] > C[i−126]       ? +1 : −1)     // 6 個月動能
       + (C[i] > C[i−252]       ? +1 : −1);    // 12 個月動能
sc = Math.round(100 * sc_raw / 6);             // → {−100,−67,−33,0,33,67,100}
```
`sc_raw ∈ {−6,−4,−2,0,2,4,6}` → `sc ∈ {−100,−67,−33,0,33,67,100}`。
y9 軸 `tickvals:[-100,-67,-33,0,33,67,100]`,`range:[-110,110]`,線 `shape:'hv'`(階梯)。

### E.3 RVPOS(轉速)

1. **20 日實現波動(年化 %)**:
   - 取 `i-19..i` 共 **20 筆** `log(C[j]/C[j-1])`(需 `C[j-1]>0`)。
   - **樣本變異數**(除以 `n-1`)→ `σ`。
   - `rv[i] = σ × √252 × 100`。
   - `i<20` 一律 `null`;有效樣本 `<2` 跳過。
2. **504 日百分位**:
   - 視窗 `j ∈ [max(0,i-504), i]`(**inclusive、含當日 → 實際最多 505 根**)。
   - 只計 `rv[j]!=null` 的樣本;`t` = 樣本數,`c` = 其中 `rv[j] <= rv[i]` 的數量。
   - **min_periods = 60**:`t>=60` 才輸出,否則 `null`。
   - `rvp[i] = Math.round(100*c/t)` → 整數 0..100。
   - 邊界:序列開頭因 `i-504<0` 自動縮短視窗;前 ~79 根(20 暖機 + 60 min_periods)必為 `null`。
3. **繪製**:`line{color:CPAL.rv='#c084fc',width:2}`,`fill:'tozeroy'`,`fillcolor:'rgba(192,132,252,.07)'`;
   背景 shape:紅帶 `y0:90,y1:104, fillcolor:'rgba(248,113,113,.10)'`;80 線 `line{color:'rgba(248,113,113,.4)',width:1}`。
   y8:`range:[0,104]`,`tickvals:[0,50,80,100]`。

### E.4 TD9 神奇九轉完整實作

**計數(`cockpitRows`)**:
```js
for(let i=4;i<n;i++){
  tds[i] = C[i] > C[i-4] ? tds[i-1]+1 : 0;   // 賣方 setup
  tdb[i] = C[i] < C[i-4] ? tdb[i-1]+1 : 0;   // 買方 setup
}
```
- 標準 TD Sequential Setup 的比較基準(收盤 vs 4 根前收盤)。
- **不封頂**(可到 13、20…),條件一破立刻歸 0。
- 另存 `tds/tdb = Math.max(當根, 前1根, 前2根)` 供 TOP/BOT 用(容許燈號在九轉完成後 2 根內仍成立)。

**顯示(`tdVis` + `renderCockpit`)**:
1. `tdVis(cn)` 決定「哪些段可見」:段最終 ≥9 → 全段(含 1–8)可見;段仍進行中(段尾 = 最後一根)→ 可見;過去不到 9 就斷的段 → 整段隱藏。
2. 強調判定:`em = (n===9 || n>=13)`。
3. 字級:`n>=13 → 12.5`;`n===9 → 11.5`;`n>=7 → midF(win>120?8:9)`;否則 `smallF(win>120?6.5:7.5)`。
4. 顏色三階:`em → CPAL.tdS/tdB`(不透明);`n>=7 → tdS8/tdB8`(0.8 alpha);否則 `tdS4/tdB4`(0.42 alpha)。
5. y 位置:賣方 `r.h + (em?o2:o1)`;買方 `r.l - (em?o2:o1)`,其中 `o1=rng*0.016`、`o2=rng*0.036`。
6. **手機稀疏化**:`dense = MB && win>60` 時,只有 `em || liveSeg 內` 的根會畫數字。

**TD 與 CTA 觸線圈聯動**:`_sigB[q]=1` 當 `tds0===9||tdb0===9||tds0===13||tdb0===13` → 該根若同時碰 200D,圈變琥珀且 size 26。

### E.5 `btFlags(rows)`(line 1835–1861)— 全歷史原子條件

```js
function btFlags(rows){
  var n=rows.length, F=[];
  var atr=[],tr=[];
  for(var i=0;i<n;i++){
    var pc=i?rows[i-1].c:rows[i].o;
    tr.push(Math.max(rows[i].h-rows[i].l, Math.abs(rows[i].h-pc), Math.abs(rows[i].l-pc)));
    var s=0,c=0; for(var k=Math.max(0,i-19);k<=i;k++){s+=tr[k];c++;}
    atr.push(s/c);                                   // ⚠ ATR20 = 「TR 的 20 根簡單平均」(非 Wilder)
  }
  var cdl={};
  try{candlePatterns(rows).forEach(p=>{if(!cdl[p.i]||p.dir)cdl[p.i]=(cdl[p.i]||0)+p.dir;});}catch(e){}
  for(var i2=0;i2<n;i2++){
    var r=rows[i2], p2=i2?rows[i2-1]:null;
    var hi20=max(rows[i2-19..i2].c), lo20=min(rows[i2-19..i2].c);   // 近 20 日「收盤」高低
    F.push({
      td9b:  (r.tdb0===9 || r.tdb0===13),
      td9s:  (r.tds0===9 || r.tds0===13),
      ctaUp: !!(p2 && r.sc>=0 && p2.sc<0),                                    // score 由 <0 轉 ≥0
      ctaDn: !!(p2 && r.sc<0  && p2.sc>=0),
      brk200:!!(p2 && r.t200!=null && p2.t200!=null && r.c> r.t200 && p2.c<=p2.t200),
      lose200:!!(p2&& r.t200!=null && p2.t200!=null && r.c< r.t200 && p2.c>=p2.t200),
      dc20:  (i2>=19 && r.c>=hi20),        // 收盤 = 近 20 日最高收盤
      dcl20: (i2>=19 && r.c<=lo20),
      rvLow: (r.rv!=null && r.rv<=25),     // RVPOS ≤ 25(壓縮)
      cdlB:  ((cdl[i2]||0)>0),             // 當日蠟燭型態 dir 淨和 > 0
      cdlS:  ((cdl[i2]||0)<0),
      atr:   atr[i2]
    });
  }
  return F;
}
```

### E.6 `backtest(rows)`(line 1862–1914)

**條件定義表**:
```js
const BT_INDEF=[     // 進場條件(AND —— 全部勾選項同日同時成立)
  ['td9b','TD買9/13 完成','TD 買方 setup 數到 9 或 13 的當日'],
  ['ctaUp','CTA 檔位翻正','score 由 <0 轉為 ≥0 的當日'],
  ['brk200','站上 200D 煞車線','收盤由 200D 下方升破至上方的當日'],
  ['dc20','突破 20 日新高','收盤 = 近 20 日最高收盤'],
  ['rvLow','RVPOS ≤ 25(壓縮)','波動百分位低檔(擠壓)'],
  ['cdlB','看多蠟燭型態','當日出現 dir=+1 的蠟燭型態']];
const BT_OUTDEF=[    // 出場條件(OR,先到先出)
  ['td9s','TD賣9/13 完成','TD 賣方 setup 數到 9 或 13 的當日'],
  ['ctaDn','CTA 檔位翻負','score 由 ≥0 轉為 <0 的當日'],
  ['lose200','跌破 200D 煞車線','收盤由 200D 上方跌破至下方的當日'],
  ['dcl20','跌破 20 日新低','收盤 = 近 20 日最低收盤'],
  ['stopATR','停損 −2×ATR20','收盤自進場價回落逾 2 倍 ATR20'],
  ['maxHold','持有滿 60 日','時間出場(避免無限持有)']];
const BT_MAXHOLD=60, BT_ATRK=2, BT_MINN=20;   // BT_MINN 以下標「樣本不足」
```

**主迴圈**:
```js
if(!rows||rows.length<60)return null;
var F=btFlags(rows);
var inK=Object.keys(BT_IN).filter(k=>BT_IN[k]);
var outK=Object.keys(BT_OUT).filter(k=>BT_OUT[k]);
if(!inK.length)return {trades:[],err:'未選任何進場條件'};
if(!outK.length)return {trades:[],err:'未選任何出場條件'};
var T=[], pos=null;
for(var i=1;i<rows.length;i++){
  if(pos){
    var why=null;
    for(var a=0;a<outK.length;a++){ var k=outK[a];
      if(k==='maxHold'){ if(i-pos.i>=BT_MAXHOLD) why='持有滿 60 日'; }
      else if(k==='stopATR'){ if(rows[i].c <= pos.px - BT_ATRK*pos.atr) why='停損 −2×ATR20'; }
      else if(F[i][k]) why=<BT_OUTDEF 對應標籤>;
      if(why)break;                       // ⚠ 檢查順序 = BT_OUT 的 key 順序(先到先出)
    }
    if(why){T.push({i0:pos.i,i1:i,d0:rows[pos.i].d,d1:rows[i].d,px0:pos.px,px1:rows[i].c,
                    hold:i-pos.i, ret:+((rows[i].c/pos.px-1)*100).toFixed(2), why});
            pos=null; continue;}
    continue;                             // ⚠ 持倉中不檢查進場 → 不重疊持倉、單一部位
  }
  var ok=true;
  for(var b=0;b<inK.length;b++) if(!F[i][inK[b]]){ok=false;break;}
  if(ok) pos={i:i, px:rows[i].c, atr:F[i].atr};   // 成交價 = 訊號日收盤
}
```

**統計 `st`**:
`n`、`open`(未平倉)、`first`/`last`、`win`(勝率 %,`ret>0`)、`avg`、`avgW`、`avgL`、`hold`(平均持有日)、`best`、`worst`、`pf`(獲利因子 = Σ盈 / |Σ虧|,無虧損則 `null`)、`eq`(逐筆複利總報酬 %)、`mdd`(最大回撤 %)、`bh`(同期買進持有:`rows[T[n-1].i1].c / rows[T[0].i0].c − 1`)。

> **重要**:P7 回測層的 **UI 已於 2026-08-01 下架**(line 2144–2147 註解)。`backtest()` / `btFlags()` / `candlePatterns()` **保留為純計算函式,不再有任何畫面產出**;`BT_IN/BT_OUT` 也沒有 UI 可改。`btFlags` 目前唯一的實際作用是被 `backtest` 呼叫(而 `backtest` 無呼叫者)。
> 但 `candlePatterns()` 仍被 `btFlags` 呼叫,而 CHIP_PAT 圖層用的是 `classicPatterns()`。

### E.7 型態辨識(`CHIP_PAT` 開啟時)— 參數速查

`zigzag(R,OPT)`(line 913–971):
- `dev = clamp(1.5*ATR14/px, 0.03, 0.08)`;`depth=5`;`backstep=3`;`minSep=max(depth,backstep)=5`。
- 兩道後處理迴圈(各 400 次上限):① 間隔 `<minSep` 移除較晚者 + `mergeSame`;② 保序安全網(H 必高於相鄰 L)。
- 尾端未確認轉折標 `tent:true`。

`classicPatterns(R,piv,OPT)`(line 972–1234)參數:
- `HEAD_MIN=0.03`(頭高於雙肩)、`SH_TOL=0.15`(雙肩高度差)、`DT_TOL=0.03`(雙頂/底差)、`DT_RETR=0.05`(中間回撤)、`MAXAGE=max(40, round(N*0.6))`。
- **頭肩頂/逆頭肩**:5 轉折 LS-T1-H-T2-RS;頸線兩點落差 ≤35%;`confirmed` = 右肩後收盤破頸線(×0.999 / ×1.001);創新極值 → invalidated(**不顯示**)。
- **雙重頂/底**:3 轉折 A-M-B;`confirmed` = 收盤破 M;超越 A/B ×1.01 / ×0.99 → invalidated。
- **三角/楔形/旗形**:候選 = 末端 3 個結束位置 × 視窗 4–7 轉折(≤12 組);`FLAT=0.0006`;`conv = w1 < w0*0.75`;閘① apex 落在 `[i1-2, i1+2*(i1-i0)]`;閘② 夾住率 ≥85%(收盤在兩邊線 ±1.5%/0.985 內);`confirmed` = 收盤破上邊線 ×1.01 或下邊線 ×0.99。型態名:`對稱三角/上升三角/下降三角/上升楔形/下降楔形/上升旗形/下降旗形`。
- **杯柄**:`rim≤5%`、`dep≥15%`、`dur≥30 根`、柄回檔 `≤杯深/3`、柄長 `≤杯長/3`。
- **VCP 波動收縮**(Minervini):基底 `min(140,N)` 根內 2–4 次「高→低」回檔;每次 `≤ 前次 80%`;末次 `≤15%`;基底頂齊平度 `hMin ≥ hMax*0.88`;量縮 `末次均量/首次均量 ≤ 0.85`;現價距基底高 `≤8%`;`confirmed` = 收盤 > 樞紐 ×1.001。
- **輸出**:按 `score` 降序,**同 `type:state` 去重,最多 4 個**。

`candlePatterns(R)`(line 1235–1317):約 30 種純規則型態,輸出 `{i,d,name,dir,why}`,`dir∈{-1,0,1}`。判定基準:`ar=avg(rng,i,14)`、`ab=avg(body,i,14)`(皆為 `i` 之前 14 根,不含當根)。

---

## F. `chipnote` 全文(逐字)

### F.1 原始 JS 賦值(`renderChips` 末,line 2632)

```js
const note=document.getElementById('chipnote');
if(note)note.innerHTML='<b>⓪駕駛艙</b>:K線疊<b>煞車線</b>(短/中/長期量化觸發價=CTA 部位翻轉位,碰線=機械賣壓啟動)、<b>TD9</b>(橘=賣方九轉/青=買方九轉)與<b>燈號</b>——▼=TOP≥3(score100+RVPOS≥90+TD賣9+爆量 湊3,回測:高beta股後10日續跌×2.0-2.3)強制減碼階梯;▲=BOT≥3(TD買9+RVPOS≥80+殺量竭盡+score&lt;66 湊3,回測:後10日反彈51%、20日69%)抄底階梯。副軌:量(琥珀=爆量)、轉速RVPOS(紅帶=紅線區,無餘裕)+RSI(灰=背景)、檔位score(降檔=訊號斷裂)、⑦現金池(與K線對齊看背離)。<b>①存量分解</b>:流通股(所有籌碼)=大戶(機構 13F 持股數)+非機構(散戶+內部人),季頻;機構季變=大戶加減碼。<b>②現金池累積</b>=該股 ⑦ 每日主動淨流自區間起點累加(大單≈機構、全單含中小單≈散戶);<b>+y=現金離池(進場買貨)、−y=現金入池(獲利了結)</b>→設計上與股價同向,<b>背離</b>(價漲·線降=⑦在撤/派發)=轉折觀察;柱=當日淨進出。<b>③籌碼成本分佈</b>=近 N 日日K量價分佈,<b>POC</b>=最大量價位(最厚套牢/支撐)、橘帶=70%價值區、綠=現價下方(獲利盤/支撐)紅=上方(套牢盤/壓力);<b>均價/VWAP60/120</b>=各期成交量加權平均成本。<b>大戶均(粉)/散戶均(青)</b>=逐筆成交按自動門檻(≥$10萬或當批前5%)分大單/散戶的成交量加權均價,<b>▲=該群淨買、▼=淨賣</b>;比較兩條與現價,可看誰的成本卡在哪、誰在追高/誰在派發。<b>誠實標注</b>:成本分佈/均價是「近期成交均價」近似、非個別持有成本;大戶/散戶均價的逐筆在熱門股是<b>抽樣估計</b>(NVDA 類約 15% 覆蓋、均價仍近似不偏,但股數不宣稱精確)、中低量股近完整;此兩線自建置日起逐日累積,頭幾天樣本少。';
```

### F.2 渲染後純文字(HTML 標籤剝除、實體還原)

> **⓪駕駛艙**:K線疊**煞車線**(短/中/長期量化觸發價=CTA 部位翻轉位,碰線=機械賣壓啟動)、**TD9**(橘=賣方九轉/青=買方九轉)與**燈號**——▼=TOP≥3(score100+RVPOS≥90+TD賣9+爆量 湊3,回測:高beta股後10日續跌×2.0-2.3)強制減碼階梯;▲=BOT≥3(TD買9+RVPOS≥80+殺量竭盡+score<66 湊3,回測:後10日反彈51%、20日69%)抄底階梯。副軌:量(琥珀=爆量)、轉速RVPOS(紅帶=紅線區,無餘裕)+RSI(灰=背景)、檔位score(降檔=訊號斷裂)、⑦現金池(與K線對齊看背離)。**①存量分解**:流通股(所有籌碼)=大戶(機構 13F 持股數)+非機構(散戶+內部人),季頻;機構季變=大戶加減碼。**②現金池累積**=該股 ⑦ 每日主動淨流自區間起點累加(大單≈機構、全單含中小單≈散戶);**+y=現金離池(進場買貨)、−y=現金入池(獲利了結)**→設計上與股價同向,**背離**(價漲·線降=⑦在撤/派發)=轉折觀察;柱=當日淨進出。**③籌碼成本分佈**=近 N 日日K量價分佈,**POC**=最大量價位(最厚套牢/支撐)、橘帶=70%價值區、綠=現價下方(獲利盤/支撐)紅=上方(套牢盤/壓力);**均價/VWAP60/120**=各期成交量加權平均成本。**大戶均(粉)/散戶均(青)**=逐筆成交按自動門檻(≥$10萬或當批前5%)分大單/散戶的成交量加權均價,**▲=該群淨買、▼=淨賣**;比較兩條與現價,可看誰的成本卡在哪、誰在追高/誰在派發。**誠實標注**:成本分佈/均價是「近期成交均價」近似、非個別持有成本;大戶/散戶均價的逐筆在熱門股是**抽樣估計**(NVDA 類約 15% 覆蓋、均價仍近似不偏,但股數不宣稱精確)、中低量股近完整;此兩線自建置日起逐日累積,頭幾天樣本少。

### F.3 其他嵌在本區塊的固定文案(非 chipnote 但屬判讀規則)

- 掃描面板註腳:`掃描=機械條件比對(趨勢線突破/型態/煞車線距離/52週高低/Fib/CTA分數/RV/擠壓);**score 僅供排序,非買賣建議**。代號可點擊直接載入上方駕駛艙。`
- 季節性註腳:`月報酬=當月收盤/前月收盤−1;綠=正、紅=負,深淺依幅度。樣本 N 年,**統計描述非預測**;年數少時單月平均易被極端值主導。`
- 全史模式底註:`全史模式:轉速/檔位/⑦現金池副圖無對應資料已隱藏(切回 10–250 日視窗恢復)`
- aVWAP 底註:`aVWAP=日K近似(典型價×量累積),非逐筆 VWAP`
- 現金池圖疊加說明:`(形狀對照:按可視幅度縮放對齊,hover 顯示真實 %)`
- 存量分解缺資料:`存量分解(流通股／13F 大戶持股)僅涵蓋主要追蹤股;擴充清單標的暫不採集此項 —— ⑦ 現金池與成本分佈不受影響。(主要股若剛加入,約 15 分內產生)`
- ETF:`{SYM}：ETF／無個股持股結構（存量分解僅適用正股）`
- 日K 缺:`日K輪補中(擴充/自訂標的由 Mac 每輪自動補 8 檔,新標的最快 ~10 分、全清單數小時內補齊;每 10 分自動重試)。若久候未出現=來源無此代號日K。下方 ⑦ 現金池圖不受影響。`
- 駕駛艙資料不足:`日K載入中,或歷史不足(駕駛艙需 ≥260 根日K)…`

---

## G. 已知地雷 / 快取 / 圖表庫細節

### G.1 `renderCockpit` 的 `el.dataset.sig` 快取(最大地雷)
- 完整組成見 §B.8.3(18 個片段)。
- **任何新增的互動狀態必須加進 sig**,否則按鈕點了畫面不動(原始碼註解:「P7:疊加/布林/縮放/回測 均入快取鍵(否則按鈕無反應)」)。
- `CHIPF_IDX`(現金池圖疊加)**故意不入 sig** → 點它時駕駛艙早退不重繪,只有 `#chipflow` 重畫。
- 逃生口:`el.querySelector('.plot-container')` 不存在時無條件重繪。
- `cockpitReset()` 用 `e.dataset.sig=''` 強制失效。

### G.2 其他 sig 快取
| 容器 | sig 內容 | 行 |
|---|---|---|
| `#cockpit`(全史) | `'max:'+SYM+':'+N+':'+lastClose+(building?':b':'')+(MB?':m':':d')+(TL?':t1':':t0')` | 1653 |
| `#season` | `'se:'+SYM+':'+srcLen+(full?':F':':d')` | 1766 |
| `#scanpanel` | `'sc:'+updated_utc+':'+filter+':'+sort+':'+open+':'+SYM` | 1712 |
| `#chipoffs`/`#pooloffs` | `keys.join(',')` + `el.childElementCount` | 1540 |
| `#chipSym` | `dataset.built = syms.join()` | 2518 |
| `#chipInput` | `dataset.bound='1'`(只綁一次) | 2523 |
| `#cockpit`(未追蹤動作區) | `dataset.unt = CHIP_SYM` + `#chipAddBtn` 存在 | 2539 |
| **`#chipflow` / `#chipcost` / `#chipstock`** | **無 sig,每次 renderChips 全量重繪** | — |

### G.3 節流 / 去抖 / 懶載入
| 機制 | 位置 | 參數 |
|---|---|---|
| `ensureExtDaily` 節流 | line 528 | 600 秒 |
| `ensureChipVwap` 節流 | line 548 | 300 秒 |
| `ensureSignals` 節流 | line 567 | 300 秒 |
| `ensureScan` 節流 | line 1687 | 300 秒 |
| `ensureDeepDaily` 節流 | line 3006 | 15 分 |
| `ensureChipK`/`ensureChipKMax` 重試 | line 409 / 1614 | `_none` 後 600 秒 |
| VbP relayout 重算去抖 | line 2426 | `setTimeout` 160ms |
| 滾輪縮放合併 | line 490 | `requestAnimationFrame`(fallback `setTimeout 16`) |
| 事件綁定去重 | — | `gd._wz` / `gd._pinch` / `el._vbpBind` / `inp.dataset.bound` / `btn._init` |
| 主資料輪詢 | line 3533 | 20 秒(`REFRESH_SEC`) |
| 版本偵測 | line 3529 | 150 秒 |

### G.4 Plotly 2.35 已知毒性(原始碼註解明載,移植務必保留對策)
1. **`xaxis.autorange:true` 會炸**:在「category 主軸 + y7~y10 多軌 + paper shapes」組合下,`doAutoRange` 丟 `TypeError: Cannot read properties of undefined (reading '_extremes')`,被 try/catch 吞掉 → 畫面完全不動。**對策:一律用顯式數值範圍**(`xzApply` line 447–452)。
2. **不可用 `xaxis2` overlaying 畫 VbP**:「overlaying 軸 + 事後 restyle/relayout 會讓 Plotly 2.35 把主類別軸重判成 date,已實測毒性,勿改回。」**對策:paper-x shapes**(§C.12)。
3. **`Plotly.react` 不套用新 config**:切 `CHIP_ZOOM` 必須先 `Plotly.purge`(`cockpitReset(true)`)。
4. **直接覆寫 `innerHTML` 會殘留 Plotly 狀態**:換股後 `Plotly.react` 失效 → 卡「載入中」。**對策:`chartMsg` 先 purge**。
5. **訊息 div 溢出**:訊息→圖轉場前必須 `freshPlot(id)` 清除,否則訊息殘留在圖下方、溢出固定高容器、疊到下一區塊。
6. **內建 `scrollZoom` 不穩**:多子圖 + category 主軸下「拖曳有效、滾輪無效」→ 改自行 capture 攔截 wheel。
7. **分頁切換要 `dispatchEvent(new Event('resize'))`**(50ms 後),否則 `responsive:true` 的圖在隱藏時尺寸為 0。

### G.5 圖表庫分配表

| 元件 | 圖表庫 | trace 類型 | 關鍵 config |
|---|---|---|---|
| `#cockpit`(日K) | **Plotly** | `candlestick` + `scatter`(lines/text/markers)+ `bar` | 5 軌 `yaxis/y7/y8/y9/y10` domain;`xaxis.type:'category'`,`anchor:'y10'`,`domain:[0,XW]`;VbP 用 paper shapes |
| `#cockpit`(全史) | **Plotly** | `candlestick` + `scatter` | `yaxis.type:'log'`,單軌 |
| `#chipflow` | **Plotly** | `bar` + `scatter` | `barmode:'overlay'`;`yaxis2` overlaying(這裡可以用,因為是單軌簡單圖);`y2Range()` 固定範圍 |
| `#chipcost` | **Plotly** | `bar` `orientation:'h'` | `barmode:'overlay'`,`bargap:0.05`;所有均價線走 `shapes` + `annotations` |
| `#chipstock` | **純 HTML**(flex div) | — | 兩色條 `#c2703e` / `#3a4358` |
| `#scanpanel` | **純 HTML** `<table>` | — | sticky header,`max-height:320px` |
| `#season` | **純 HTML** `<table>` | — | 背景色階 `rgba(...,α)`,`α = min(1,|v|/(mx*0.75))*0.62` |
| `#chipidx`/`#chipfidx`/`#chipoffs`/`#chipRange` | **純 HTML** | — | — |

### G.6 其他坑
- `CPAL.edge` **重複定義**(line 630 `'#0d0d0d'`,line 632 `'rgba(226,232,240,.66)'`)→ 物件字面值後者勝。所以 `marker.line.color:CPAL.edge`(◆★ 描邊)實際拿到的是**淺灰半透明**,不是原意的黑色描邊。
- `renderCockpit` 的 `win = Math.max(30, Math.min(CHIP_WIN, 250))` → **點「10日」按鈕,駕駛艙仍畫 30 日**(但 `#chipflow` / `#chipcost` 用的是原始 `CHIP_WIN=10`)。三張圖天數不一致。
- SPY/QQQ 疊加的 `rel` 標籤 **「領先/落後」語意與數值方向相反**(§B.8.10)。
- `el._vbp.base = _ckLay.shapes.slice(0,2)`:副圖非 `rv` 時 `_y8shapes=false`,前兩個 shape 其實是 VbP 分隔線與第一根柱 → relayout 重算會殘留(§B.8.11)。
- `chipDaily()` 每次呼叫都做全量 `Object.assign` 合併(日數 × 標的數),20s 迴圈中會被呼叫多次(`renderChips` 1 次 + `renderCockpit` 1 次)。
- `cockpitRows` 的 RVPOS 是 **O(n × 505)** 巢狀迴圈,`n` 可達數千 → 換股第一次會明顯卡頓;靠 `CKC` 快取避免每 20s 重算。
- `renderChips()` 每次都重寫 `#chipnote.innerHTML`(855 字元字串),雖便宜但無必要。

---

## H. 台股移植風險點(技術層面)

1. **`cockpitRows` 硬門檻 `bars.length < 260 → null`**,且輸出從 `i=252` 起。台股新上市/興櫃轉上市個股、或資料源只給 1 年日K 時,駕駛艙**永遠不會出現**,只顯示「歷史不足」。需要調降(例如 `sc` 的 252 日動能改為可選、門檻降到 130)。
2. **年化係數 `Math.sqrt(252)` 寫死**(`cockpitRows` RVPOS)。台股一年約 240–245 交易日,雖影響小但屬須明示的常數。
3. **`x` 軸標籤 `r.d.slice(5)` 假設 `YYYY-MM-DD`**;`weeklyAgg.isoWeek` 用 `new Date(ds+'T00:00:00Z')`。若台股資料源給民國年或 `YYYYMMDD`,`isoWeek` 會走防禦分支(逐根一組),`weeklyMA` 全失效;`x` 標籤也會亂。
4. **`chipInput` 強制 `toUpperCase()`**(line 2524)+ CSS `text-transform:uppercase`。台股代號是數字(`2330`)或含字母(`00631L`),`toUpperCase` 無害但 `renderCustomChips`/`initCustomUI` 的驗證 `/^[A-Z.]{1,10}$/`(line 2710)**會擋掉所有純數字代號**。
5. **`initCustomUI` 的 `.replace(/^US\./,'')`** 與 `flowMap` 的 `k.replace('US.','')`:美股 prefix 假設。台股需改 `TW.` / `TWSE.` 並同步 `capital_flow` key 規則。
6. **金額單位 `M`(百萬美元)寫死**:`fmtM`(`≥1e9→B`,否則 `M`)、`renderCockpit` 的 `⑦當日 %{y:.0f}M`、`+{pa}M` 標籤、`renderChips` 的 `(m+r)*1e6`。台股用「億元/千張」較自然,需全面換算層。
7. **`renderChipCost` 價格格式 `$` 與 `toFixed(1)`**:y 軸 title `'價位 $'`、hovertemplate `'價 $%{y:.2f}'`、標籤 `P.toFixed(1)`。台股價位到小數 2 位(<50 元的股票 tick 0.01),`toFixed(1)` 會把 `23.45` 顯示成 `23.5`,且 `p[1]>=1000?toFixed(0):toFixed(1)` 的分界對台股(大立光 2000+)行為不同。
8. **`renderChipCost` 分箱數 `NB=clamp(round(bars.length),24,50)`**:`Math.round(bars.length)` 就是 bars.length 本身,所以只要 ≥50 根就固定 50 箱。台股漲跌幅 10% 限制 → 價格區間比美股窄,50 箱在低價股(如 15 元股)每箱僅 0.0x 元,遠低於 tick size,會產生大量空箱。
9. **VbP `vbpBins` 只用「收盤」落箱**,而 `renderChipCost` 用「low..high 攤平」——同一份資料兩套量價分佈演算法,POC 會不一致。台股移植時容易被使用者質疑「兩張圖的 POC 不同」。
10. **`t50/t100/t200` 是「不含當日的 49/99/199 日均」**,不是 SMA50/100/200。這是刻意的 CTA 觸發價設計,但台股使用者普遍認知的「季線/半年線/年線」是標準 MA(且台股年線常用 240 日而非 200 日)。若不改,線位會與看盤軟體對不上;若改,`btFlags.brk200/lose200` 與 CTA 觸線圈都要同步。
11. **`chips_meta` 用 13F 語意**(`inst_q`=機構持股數、`inst_n`=家數、`period`=13F 期別)。台股無 13F,對應資料是「三大法人持股比率/集保戶股權分散表/董監持股」,**季頻 vs 週頻**不同,且「流通股 = 機構 + 非機構」這個二分法在台股要改成「外資/投信/自營 + 融資融券 + 一般」。`renderChipStock` 的兩段條需重新設計。
12. **`chips_vwap` 的大戶/散戶門檻是 `≥$10萬或當批前5%`**(chipnote 明載)。台股逐筆成交揭示規則不同(且盤中揭示為 5 秒撮合),$10 萬美元 ≈ 300 萬台幣的門檻不適用,需重新定義。此外台股有「零股盤」與「盤後定價」,`kline_today` 合併規則(`tb[0] > lastBarDate`)可能重複計入。
13. **SPY/QQQ 硬編碼**:`ensureSpyK`/`ensureQQQK` 是**獨立具名函式**,檔名 `kline_SPY.json`/`kline_QQQ.json` 寫死;`CHIP_IDX`/`CHIPF_IDX` 的 key 也是 `'SPY'`/`'QQQ'`;`CPAL.idxSpy/idxQqq`;`buildChipIdx`/`buildChipFIdx` 的 `['SPY','QQQ'].map`;`buildChipOffs` 的 defs。台股要換成 `0050`/`大盤TAIEX` 需改 **8 處以上**,建議先重構成資料驅動 `IDX_DEFS=[{key,file,color,label}]`。
14. **`renderCockpit` 的 `win` 被夾在 `[30,250]`,但 `#chipRange` 提供 10 日按鈕** → 三張圖(cockpit/chipflow/chipcost)天數不一致。台股若加「5日」按鈕會更明顯。
15. **`ensureScan`/`ensureSignals` 用相對路徑 `data/scan.json`**,其餘全走 gist 絕對路徑。若台股版部署到不同 base path(如 GitHub Pages 子目錄 `/tw/`),相對路徑會解析到 `/tw/data/scan.json`,**與 gist 來源分離** — 部署拓撲必須一起規劃。
16. **無 CORS/失敗 UI**:所有 `ensure*` 的 `.catch(()=>{})` 全部靜默。台股資料源(證交所/櫃買/券商 API)常有 CORS 與 rate limit,靜默失敗會讓使用者看到永久「載入中」而不知原因。
17. **`Math.max(...array)` spread 在長序列會爆 stack**:`renderCockpit` 的 `Math.max(...R.map(r=>r.h))`(最多 250 筆,安全)、但 `renderSeason` 的 `Math.max(...all.map(Math.abs))`(月數,安全)、`renderChips` 的 `Math.max(...pv)`(最多 250,安全)。**若台股版把視窗放大到 `max`(全史日K,數千筆)就會 RangeError**。
18. **台股漲跌停會讓 TD9 與 ATR 失真**:`indATR` 的 TR 在漲停鎖死日 = `h-l ≈ 0`,`btFlags.stopATR`(−2×ATR20)在連續漲跌停後門檻異常小;`zigzag` 的 `dev=clamp(1.5*ATR14/px,0.03,0.08)` 下限 3% 對台股(單日上限 10%)偏窄,會產生過多轉折。
19. **`classicPatterns` 的 `MAXAGE`、`HEAD_MIN=3%`、`DT_TOL=3%`** 全是以美股波動校準;台股 10% 漲跌幅限制下,3% 的頭肩門檻會過於寬鬆(誤判暴增)。
20. **`renderSeason` 的年份 `+src[i][0].slice(0,4)`** 假設西元 4 位;`years.slice(0,14)` 顯示 14 年。台股月報酬要注意**除權息**:若資料源給的是未還原價,1–9 月的除權息會系統性壓低該月報酬,季節性矩陣會產生假訊號。日K 也同理(`cockpitRows` 的所有 MA/動能都需**還原權值**)。
