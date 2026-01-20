# BGG Analytics (Streamlit)

這是一個以 **BoardGameGeek (BGG)** 資料為基礎的分析專案：

- 使用 Python 抓取 BGG 遊戲資料並建立 `SQLite` 資料庫（`bgg.db`）
- 使用 `Streamlit` 提供可互動的分析介面：
  - **Mechanics**：遊戲機制年度趨勢 + drill-down
  - **Categories**：各 rank 類型（subdomain）年度趨勢 + 類型內 Top mechanics
  - **Ranking**：依多條件篩選遊戲、並依 overall rank 排序

> 主要入口：`app.py`

---

## 1) 環境需求

- Python 3.10+（建議）
- Chrome（Selenium 會用到）

Python 套件（至少會用到）：
- streamlit
- pandas
- altair
- streamlit-option-menu
- requests
- beautifulsoup4
- selenium
- webdriver-manager（用於 `save_bgg_cookies.py`）

---

## 2) 快速開始（只跑 App）

安裝套件：

```bash
pip install -r requirements.txt
```

確保同一個資料夾內至少有以下檔案：

**必要**
- `app.py`
- `app_mechanic_trends.py`
- `app_category_trends.py`
- `app_game_search.py`
- `bgg.db`

啟動：

```bash
streamlit run app.py
```

---

## 3) App 功能說明

### Mechanics（`app_mechanic_trends.py`）
- 資料來源：`bgg.db`（tables: `games`, `mechanics`, `ranks`）
- 可依 **overall rank 範圍**、**年份區間**、**指標(Popularity/Quality/Impact)** 觀察趨勢
- 支援選取圖上的點做 drill-down：顯示該年該 mechanic 的遊戲列表
- 介紹文字來源：`bgg.db`（table: `mechanic_descriptions`；若不存在/無資料則顯示「（無介紹文字）」）

### Categories（`app_category_trends.py`）
- 資料來源：`bgg.db`（tables: `games`, `ranks`, `mechanics`）
- 將 `ranks.domain != overall` 視為各類型（例如 strategic / family…）
- 顯示各 domain 在每年的趨勢，並可在下方選擇特定 domain 查看：
  - Top 20 mechanics
  - 遊戲列表（依 overall rank / rating 排序）

### Ranking（`app_game_search.py`）
- 資料來源：`bgg.db`（tables: `games`, `ranks`, `mechanics`, `categories`）
- 依以下條件篩選：
  - Mechanics（`mechanics.name`）
  - Categories（`ranks.domain`，含 overall 與各 subdomain）
  - Themes（`categories.name`）
  - Year（`games.year_published`，並把 <=0 統一顯示為 `<0`）

---

## 4) 從零開始：抓資料並建立資料庫（可選）

> 這部分會涉及爬蟲、登入 cookies、Selenium，且可能受 BGG 反爬/頁面改版影響。

### Step 0. 取得登入 cookies（讓 Selenium 抓 browse IDs）

```bash
python save_bgg_cookies.py
```

會產生：`bgg_cookies.pkl`

### Step 1. 抓取 browse 頁的 BGG IDs

```bash
python fetch_bgg_browse_ids.py --start 1 --end 300 --headless --checkpoint 20 --sleep 2
```

會產生類似：`bgg_browse_ids_1_300.json`

### Step 2. 建立 SQLite（抓遊戲頁、解析 geekitemPreload、寫入 DB）

```bash
python ingest_bgg_games_sqlite.py --ids bgg_browse_ids_1_300.json --db bgg.db --sleep 1.0 --checkpoint 50
```

### Step 3. 抓 categories / mechanics 清單（可選，但建議）

```bash
python fetch_bgg_mechanics.py
python fetch_bgg_categories.py
```

會產生：
- `bgg_mechanics.json`
- `bgg_categories.json`

### Step 4. 補齊 mechanics / categories 的描述（可選）

```bash
python enrich_bgg_mechanics_description.py
python enrich_bgg_categories_description.py
```

會產生：
- `bgg_mechanics_with_description.json`
- `bgg_categories_with_description.json`

> 注意：目前 **Mechanics 頁面不直接讀 JSON**，而是讀 `bgg.db` 的 `mechanic_descriptions` table。

如果你想把 `bgg_mechanics_with_description.json` 的內容用在 App 內，請先把資料匯入資料庫：

1) 建立 table（只要做一次）：

```sql
CREATE TABLE IF NOT EXISTS mechanic_descriptions (
  mechanic TEXT PRIMARY KEY,
  description TEXT,
  url TEXT
);
```

2) 匯入 JSON → SQLite（範例做法，會覆蓋同名 mechanic）：

```bash
python -c "import json,sqlite3; db='bgg.db'; js='bgg_mechanics_with_description.json';\
data=json.load(open(js,'r',encoding='utf-8')).get('mechanics',[]);\
con=sqlite3.connect(db); cur=con.cursor();\
cur.execute('CREATE TABLE IF NOT EXISTS mechanic_descriptions (mechanic TEXT PRIMARY KEY, description TEXT, url TEXT)');\
cur.executemany('INSERT OR REPLACE INTO mechanic_descriptions(mechanic,description,url) VALUES (?,?,?)',\
[(m.get('name'), (m.get('description') or ''), (m.get('url') or '')) for m in data if m.get('name')]);\
con.commit(); con.close(); print('Imported', len([m for m in data if m.get('name')]), 'mechanics')"
```

---

## 5) 檔案與資料說明（哪些需要保留）

### App 執行必需
- `app.py`
- `app_mechanic_trends.py`
- `app_category_trends.py`
- `app_game_search.py`
- `bgg.db`

### App 執行（部分頁面）會用到

Mechanics 頁的介紹文字改由 `bgg.db` 內的 `mechanic_descriptions` table 提供。

> 如果你的資料庫沒有 `mechanic_descriptions`，App 仍可執行，但 Mechanics 頁面會顯示「（無介紹文字）」。

### 可再生（generated / cache / output）
以下檔案可由腳本重新產生；是否保留取決於你是否要節省重跑時間：
- `bgg_browse_ids_*.json`
- `bgg_mechanics.json`, `bgg_categories.json`
- `bgg_categories_with_description.json`（可再生，但重跑較久）
- `bgg_*.json`（例如 `bgg_224517.json`，單筆輸出示例）

### 敏感資料（建議不要 commit / 不要分享）
- `bgg_cookies.pkl`：包含登入 cookies（等同 session）

---

## 6) 注意事項

- BGG 有反爬策略：請控制抓取速度（sleep/jitter），避免短時間大量請求。
- Selenium 會依賴 Chrome 與相容的 driver；若遇到版本問題，請更新 Chrome 或 driver。
- 此專案的資料表結構由 `ingest_bgg_games_sqlite.py` 建立；App 預期存在 tables：
  - `games`, `ranks`, `mechanics`, `categories`, `designers`, `publishers`

另外，Mechanics 頁面會嘗試讀取以下 table（可選）：
- `mechanic_descriptions (mechanic TEXT, description TEXT, url TEXT)`
