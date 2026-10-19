
import streamlit as st
import sqlite3, json, re, hashlib, html
from datetime import datetime, timezone
from pathlib import Path
import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

APP_DIR = Path(__file__).parent
DB = APP_DIR / "data" / "jobs.db"
PROFILE = APP_DIR / "data" / "profile.txt"
BOARDS = APP_DIR / "data" / "boards.json"

DEFAULT_PROFILE = ""
DEFAULT_BOARDS = [
    {"company":"Atlassian","type":"greenhouse","slug":"atlassian"},
    {"company":"Databricks","type":"greenhouse","slug":"databricks"},
    {"company":"Stripe","type":"greenhouse","slug":"stripe"},
    {"company":"Airbnb","type":"greenhouse","slug":"airbnb"},
    {"company":"Coinbase","type":"ashby","slug":"coinbase"},
    {"company":"Notion","type":"ashby","slug":"notion"},
    {"company":"OpenAI","type":"ashby","slug":"openai"},
    {"company":"Netflix","type":"lever","slug":"netflix"},
]

st.set_page_config(page_title="JobPilot — Job Scraper & Tracker", page_icon="💼", layout="wide")

def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE IF NOT EXISTS jobs(
        id TEXT PRIMARY KEY, company TEXT, title TEXT, location TEXT,
        employment TEXT, posted TEXT, salary TEXT, description TEXT,
        url TEXT, source TEXT, match_score INTEGER DEFAULT 0,
        status TEXT DEFAULT 'New', notes TEXT DEFAULT '',
        saved_at TEXT, updated_at TEXT
    )""")
    con.execute("""CREATE TABLE IF NOT EXISTS applications(
        job_id TEXT PRIMARY KEY, status TEXT, applied_at TEXT, notes TEXT
    )""")
    con.commit()
    return con

def clean(s):
    return re.sub(r"\s+", " ", BeautifulSoup(str(s or ""), "html.parser").get_text(" ")).strip()

def job_id(company, title, url):
    return hashlib.sha1(f"{company}|{title}|{url}".encode()).hexdigest()[:20]

def score_job(title, desc, location, profile):
    text = (title + " " + desc + " " + location).lower()
    prof = profile.lower()
    keywords = {
        "sql": 14, "python": 14, "power bi": 14, "data analyst": 12,
        "business analyst": 10, "tableau": 7, "excel": 6, "pandas": 5,
        "analytics": 5, "bi analyst": 9, "it support": 5
    }
    score = 0
    for k, pts in keywords.items():
        if k in text and k in prof:
            score += pts
    if any(x in text for x in ["fresher", "entry level", "0-1", "0 - 1", "junior", "graduate", "intern"]):
        score += 10
    if any(x in location.lower() for x in ["coimbatore", "tirupur", "chennai", "bangalore", "bengaluru", "tamil nadu"]):
        score += 10
    return min(100, score)

def normalize_greenhouse(board):
    slug = board["slug"]
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    r = requests.get(url, timeout=20, headers={"User-Agent":"JobPilot/1.0"})
    r.raise_for_status()
    out=[]
    for j in r.json().get("jobs", []):
        out.append({
            "company": board.get("company", slug),
            "title": j.get("title",""),
            "location": (j.get("location") or {}).get("name",""),
            "employment": "",
            "posted": datetime.fromtimestamp(j["updated_at"]/1000, timezone.utc).isoformat() if isinstance(j.get("updated_at"), (int,float)) else "",
            "salary": "",
            "description": clean(j.get("content","")),
            "url": j.get("absolute_url",""),
            "source": "Greenhouse"
        })
    return out

def normalize_lever(board):
    slug = board["slug"]
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    r = requests.get(url, timeout=20, headers={"User-Agent":"JobPilot/1.0"})
    r.raise_for_status()
    out=[]
    for j in r.json():
        cats=j.get("categories") or {}
        desc=j.get("descriptionPlain") or clean(j.get("description",""))
        out.append({
            "company": board.get("company", slug),
            "title": j.get("text",""),
            "location": cats.get("location",""),
            "employment": cats.get("commitment",""),
            "posted": datetime.fromtimestamp(j["createdAt"]/1000, timezone.utc).isoformat() if isinstance(j.get("createdAt"), (int,float)) else "",
            "salary": clean((j.get("salaryRange") or {}).get("currencySymbol","")) if j.get("salaryRange") else "",
            "description": desc,
            "url": j.get("hostedUrl") or j.get("applyUrl",""),
            "source": "Lever"
        })
    return out

def normalize_ashby(board):
    slug = board["slug"]
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true"
    r = requests.get(url, timeout=20, headers={"User-Agent":"JobPilot/1.0"})
    r.raise_for_status()
    out=[]
    for j in r.json().get("jobs", []):
        locs=j.get("location") or j.get("locations") or []
        if isinstance(locs,list): loc="; ".join([x if isinstance(x,str) else x.get("name","") for x in locs])
        else: loc=str(locs)
        comp=j.get("compensation") or {}
        out.append({
            "company": board.get("company", slug),
            "title": j.get("title",""),
            "location": loc,
            "employment": j.get("employmentType",""),
            "posted": j.get("publishedAt",""),
            "salary": clean(comp),
            "description": clean(j.get("descriptionHtml") or j.get("description","")),
            "url": j.get("jobUrl") or j.get("applyUrl",""),
            "source": "Ashby"
        })
    return out

def scrape_all(boards, profile):
    jobs=[]
    errors=[]
    for b in boards:
        try:
            if b["type"].lower()=="greenhouse": got=normalize_greenhouse(b)
            elif b["type"].lower()=="lever": got=normalize_lever(b)
            elif b["type"].lower()=="ashby": got=normalize_ashby(b)
            else: raise ValueError("Unsupported ATS")
            for j in got:
                j["id"]=job_id(j["company"],j["title"],j["url"])
                j["match_score"]=score_job(j["title"],j["description"],j["location"],profile)
            jobs.extend(got)
        except Exception as e:
            errors.append(f'{b.get("company",b.get("slug",""))}: {e}')
    return jobs, errors

def save_jobs(jobs):
    con=db()
    now=datetime.now().isoformat()
    for j in jobs:
        con.execute("""INSERT INTO jobs(id,company,title,location,employment,posted,salary,description,url,source,match_score,status,saved_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET company=excluded.company,title=excluded.title,location=excluded.location,
        employment=excluded.employment,posted=excluded.posted,salary=excluded.salary,description=excluded.description,
        url=excluded.url,source=excluded.source,match_score=excluded.match_score,updated_at=excluded.updated_at""",
        (j["id"],j["company"],j["title"],j["location"],j["employment"],j["posted"],j["salary"],j["description"],j["url"],j["source"],j["match_score"],"New",now,now))
    con.commit(); con.close()

def query_jobs(status=None):
    con=db()
    if status and status!="All":
        rows=con.execute("SELECT * FROM jobs WHERE status=? ORDER BY match_score DESC, posted DESC",(status,)).fetchall()
    else:
        rows=con.execute("SELECT * FROM jobs ORDER BY match_score DESC, posted DESC").fetchall()
    con.close(); return rows

def update_status(jid,status,notes=""):
    con=db(); con.execute("UPDATE jobs SET status=?,notes=?,updated_at=? WHERE id=?",(status,notes,datetime.now().isoformat(),jid)); con.commit(); con.close()

def tailor(title, desc, profile):
    # Safe, deterministic tailoring: only uses skills already present in the profile.
    pskills = re.findall(r'\b(?:SQL|Python|Power BI|Tableau|Excel|Pandas|NumPy|Matplotlib|Seaborn|scikit-learn|DAX|Jupyter Notebook|Data Visualization|KPI Reporting|Data Cleaning and Preprocessing|Exploratory Data Analysis|Statistical Analysis|Business Intelligence|Stakeholder Reporting|Requirements Gathering)\b', profile, flags=re.I)
    unique=[]
    for x in pskills:
        if x.lower() not in [u.lower() for u in unique]: unique.append(x)
    jd=(title+" "+desc).lower()
    relevant=[x for x in unique if x.lower() in jd]
    relevant= relevant[:12]
    lines=[
        f"# Tailored Resume — {title}",
        "",
        "## Professional Summary",
        f"Data Analyst with hands-on experience in data cleaning, exploratory analysis, dashboard development and stakeholder reporting. Core strengths relevant to this role: {', '.join(relevant) if relevant else ', '.join(unique[:8])}.",
        "",
        "## Relevant Skills",
        ", ".join(relevant if relevant else unique[:12]),
        "",
        "## Tailoring Notes",
        "This version prioritizes skills already present in the base resume and found in the job description. No new qualifications or employers are invented.",
    ]
    return "\n".join(lines)

# ---------- UI ----------
st.title("💼 JobPilot")
st.caption("Job scraper • Resume matching • Tailoring • Application tracker")
st.info("Upload your resume from the sidebar. Your personal resume is not bundled into this public deployment package.")

profile = st.session_state.get("profile", DEFAULT_PROFILE)
with st.sidebar:
    st.header("Resume")
    uploaded = st.file_uploader("Upload your resume (PDF/TXT)", type=["pdf","txt"])
    if uploaded is not None:
        if uploaded.name.lower().endswith(".pdf"):
            try:
                reader = PdfReader(uploaded)
                profile = "\n".join((p.extract_text() or "") for p in reader.pages)
            except Exception as e:
                st.error(f"Could not read PDF: {e}")
        else:
            profile = uploaded.getvalue().decode("utf-8", errors="ignore")
        st.session_state["profile"] = profile
    profile = st.text_area("Resume text", value=profile, height=260)
    st.session_state["profile"] = profile
    st.divider()
    st.header("Filters")
    locations=st.multiselect("Location",["Coimbatore","Chennai","Bangalore","Bengaluru","Tirupur","Tamil Nadu"],default=["Coimbatore","Chennai","Bangalore"])
    roles=st.multiselect("Role",["Data Analyst","Business Analyst","BI Analyst","Junior Data Analyst","SQL","Python","Power BI","IT Support"],default=["Data Analyst","Business Analyst","BI Analyst"])
    min_score=st.slider("Minimum match score",0,100,25)
    status=st.selectbox("Application status",["All","New","Saved","Applied","Interview","Rejected","Offer"])

tabs=st.tabs(["🔎 Jobs","📋 Tracker","✍️ Resume Tailor","⚙️ Sources"])

with tabs[0]:
    c1,c2=st.columns([1,3])
    with c1:
        if st.button("🚀 Scrape jobs now", type="primary"):
            try:
                boards_to_use = json.loads(source_json) if "source_json" in locals() else DEFAULT_BOARDS
                jobs, errors=scrape_all(boards_to_use,profile)
            except Exception as e:
                jobs, errors = [], [f"Invalid board JSON: {e}"]
            save_jobs(jobs)
            st.success(f"Collected {len(jobs)} jobs.")
            if errors:
                st.warning("Some boards could not be read:\n\n" + "\n".join(errors))
    rows=query_jobs(status)
    filtered=[]
    for r in rows:
        blob=(r["title"]+" "+r["description"]+" "+r["location"]).lower()
        loc_ok=not locations or any(x.lower() in r["location"].lower() for x in locations)
        role_ok=not roles or any(x.lower() in blob for x in roles)
        if loc_ok and role_ok and r["match_score"]>=min_score:
            filtered.append(r)
    st.write(f"**{len(filtered)} matching jobs**")
    for r in filtered:
        with st.container(border=True):
            a,b,c=st.columns([5,1,1])
            with a:
                st.subheader(r["title"])
                st.write(f"**{r['company']}** · {r['location'] or 'Location not listed'} · {r['source']}")
                st.caption(f"Match: {r['match_score']}% · {r['employment'] or 'Type not listed'} · {r['posted'][:10] if r['posted'] else 'Date not listed'}")
            with b:
                if st.button("Save", key="s"+r["id"]):
                    update_status(r["id"],"Saved"); st.rerun()
            with c:
                if r["url"]: st.link_button("Apply",r["url"])
            with st.expander("Job description"):
                st.write(r["description"][:5000] or "No description available.")
            with st.expander("Update status"):
                ns=st.selectbox("Status",["New","Saved","Applied","Interview","Rejected","Offer"],index=["New","Saved","Applied","Interview","Rejected","Offer"].index(r["status"]),key="st"+r["id"])
                note=st.text_input("Notes",r["notes"] or "",key="nt"+r["id"])
                if st.button("Update",key="u"+r["id"]):
                    update_status(r["id"],ns,note); st.rerun()

with tabs[1]:
    rows=query_jobs("All")
    if rows:
        import pandas as pd
        export_df = pd.DataFrame([dict(r) for r in rows])
        st.download_button(
            "⬇️ Download tracker backup (CSV)",
            export_df.to_csv(index=False),
            file_name="jobpilot_tracker_backup.csv",
            mime="text/csv"
        )
    counts={}
    for r in rows: counts[r["status"]]=counts.get(r["status"],0)+1
    cols=st.columns(6)
    for i,s in enumerate(["New","Saved","Applied","Interview","Rejected","Offer"]):
        cols[i].metric(s,counts.get(s,0))
    st.divider()
    for r in rows:
        if r["status"]!="New":
            st.write(f"**{r['title']}** — {r['company']} — `{r['status']}` — {r['match_score']}%")
            if r["url"]: st.link_button("Open application",r["url"],key="open"+r["id"])

with tabs[2]:
    rows=query_jobs("All")
    if rows:
        opts={f"{r['title']} — {r['company']}":r for r in rows}
        chosen=st.selectbox("Choose a job",list(opts))
        r=opts[chosen]
        st.markdown(tailor(r["title"],r["description"],profile))
        st.download_button("Download tailored text",tailor(r["title"],r["description"],profile),file_name="tailored_resume.md")
    else:
        st.info("Scrape jobs first.")

with tabs[3]:
    st.subheader("ATS board sources")
    st.write("The starter list uses public Greenhouse, Lever, and Ashby board endpoints. Add more by editing the JSON below, then restart the app.")
    source_json = st.text_area("Board JSON", json.dumps(DEFAULT_BOARDS, indent=2), height=300)
    st.download_button("Download board list", source_json, "boards.json", "application/json")

st.divider()
st.caption("JobPilot stores data locally in data/jobs.db. It does not auto-submit applications.")
