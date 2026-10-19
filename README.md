JobPilot — One-Tap Streamlit Deployment
A phone-friendly Streamlit app for:
public ATS job collection (Greenhouse, Lever, Ashby)
location/role filtering
resume-to-job match scoring
deterministic resume tailoring
application status tracking
CSV tracker backup
Deploy
Put these files in a GitHub repository.
Open Streamlit Community Cloud.
Choose Create app.
Select the repository, branch `main`, and entrypoint `streamlit\_app.py`.
Click Deploy.
No API key is required for the starter public ATS sources.
Privacy
Do not commit a personal resume into a public GitHub repository. Upload your resume from inside the app instead.
Important persistence note
The starter tracker uses the app runtime's SQLite database. Community Cloud deployments can restart/redeploy, so use Download tracker backup (CSV) regularly if you need a durable copy. For permanent cloud persistence, a later version can connect to Google Sheets, Supabase, or another database.
Scraping scope
This app uses published/public ATS endpoints. It does not bypass bot protection or scrape restricted/private pages, and it does not auto-submit applications.
