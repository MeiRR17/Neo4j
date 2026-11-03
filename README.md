> **Script consolidation (2026-11-03):** Selected utility scripts from this repository were integrated into [Learning_Modules/tools/neo4j-sefaria](https://github.com/MeiRR17/Learning_Modules/tree/main/tools/neo4j-sefaria), via [PR #4](https://github.com/MeiRR17/Learning_Modules/pull/4). The import includes source provenance and CI syntax/content checks. The original repository remains accessible, may contain additional data or configuration, and has **not been archived or deleted**. Consult the consolidated README for exclusions and portability changes.

---

# רשת ידע פילוסופיה יהודית — Neo4j Knowledge Graph

פרויקט זה בונה גרף ידע של קשרי ציטוט בין חיבורים פילוסופיים יהודיים, מבוסס על נתוני Sefaria ומנותח עם Neo4j.

---

## ארכיטקטורה

```
C:\neo4j\
    ├── data\        ← בסיס הנתונים של Neo4j (volume mount)
    ├── import\      ← קבצי CSV לייבוא (sefaria_links.csv)
    └── logs\        ← לוגים של Neo4j

scripts\
    ├── 01_setup_directories.ps1   ← יצירת תיקיות
    ├── 02_acquire_sefaria_data.py ← הורדת נתוני Sefaria
    └── 05_verify_container.ps1    ← בדיקת תקינות

cypher\
    ├── 03_import_to_neo4j.cypher  ← ייבוא CSV לגרף
    └── 04_analytics_queries.cypher ← 5 שאילתות אנליטיות

docker-compose.yml  ← הגדרת קונטיינר Neo4j
```

---

## שלב 1: הכנת הסביבה

### 1.1 הרצת הסקריפט להכנת תיקיות
```powershell
.\scripts\01_setup_directories.ps1
```

### 1.2 הפעלת Neo4j עם Docker
```powershell
# אפשרות א: Docker Compose (מומלץ)
docker-compose up -d

# אפשרות ב: Docker ישיר
docker run `
    --name neo4j-project10 `
    -p 7474:7474 -p 7687:7687 `
    -d `
    -v C:\neo4j\data:/data `
    -v C:\neo4j\import:/var/lib/neo4j/import `
    -v C:\neo4j\logs:/logs `
    -e NEO4J_AUTH=neo4j/password `
    -e "NEO4J_dbms_memory_heap_max__size=4G" `
    neo4j:latest
```

### 1.3 אימות תקינות
```powershell
.\scripts\05_verify_container.ps1
```
גישה לממשק: **http://localhost:7474** | שם משתמש: `neo4j` | סיסמה: `password`

---

## שלב 2: רכישת נתונים מ-Sefaria

```powershell
pip install requests pandas tqdm
python scripts\02_acquire_sefaria_data.py
```

הסקריפט:
1. מנסה להוריד את ה-dump המלא מ-`Sefaria-Export` ב-GitHub
2. אם נכשל — משתמש ב-Sefaria REST API לרשימת טקסטי ליבה
3. שומר את הפלט כ-`C:\neo4j\import\sefaria_links.csv`

**פורמט ה-CSV:**
```
Source_Text,Target_Text,Connection_Type
Moreh Nevukhim,Emunot VeDeot,PHILOSOPHICAL_REF
Tanya,Moreh Nevukhim,CHASIDIC_REF
...
```

---

## שלב 3: ייבוא לגרף

פתח **Neo4j Browser** → http://localhost:7474 והרץ בלוקים מתוך:

```
cypher\03_import_to_neo4j.cypher
```

**סדר הרצה:**
1. `CREATE CONSTRAINT` + `CREATE INDEX`
2. `LOAD CSV` עם transactions בפי 1,000 שורות
3. שאילתות אימות (`count(t)`, `count(r)`)

---

## שלב 4: 5 השאלות האנליטיות

קובץ: `cypher\04_analytics_queries.cypher`

| # | שאלה | אלגוריתם גרפי |
|---|------|---------------|
| 1 | **Shortest Path** — מסלול בין רס"ג ל"נפש החיים" | BFS / `shortestPath()` |
| 2 | **Authority Hub** — המחבר המצוטט ביותר | In-Degree Centrality |
| 3 | **Echo Chamber** — ציטוטים דו-כיווניים בתוך קבוצה | Cycle Detection |
| 4 | **Dependency Tree** — עץ התלויות של מורה נבוכים | Multi-hop BFS (depth 1..3) |
| 5 | **Co-Citation Outliers** — זיקה נסתרת בין טקסטים ללא קשר ישיר | Co-citation + Negative Pattern |

---

## דגשים טכניים

- ה-APOC plugin מופעל דרך `docker-compose.yml` לתמיכה באלגוריתמי גרף מתקדמים
- `CREATE CONSTRAINT ... IF NOT EXISTS` מונע שגיאות בהרצה חוזרת
- `:auto LOAD CSV ... IN TRANSACTIONS OF 1000 ROWS` נחוץ לקבצים גדולים (מעל 100k שורות)
- השאילתה השלישית משתמשת ב-`WHERE a.title < b.title` לביטול כפילויות סימטריות
- השאילתה החמישית משתמשת ב-`NOT (textA)-[:CITES]-(textB)` לסינון קשרים ישירים

---

## פתרון בעיות נפוצות

| בעיה | פתרון |
|------|--------|
| `Neo.ClientError.Schema.ConstraintAlreadyExists` | תקין — Constraint קיים מהרצה קודמת |
| `Cannot load CSV` | ודא ש-CSV נמצא ב-`C:\neo4j\import\` ושם הקובץ תואם בדיוק |
| קונטיינר לא עולה | `docker logs neo4j-project10` לאבחון |
| `shortestPath` לא מוצא תוצאה | הטקסטים לא מחוברים בגרף — בדוק שייבוא הושלם |
