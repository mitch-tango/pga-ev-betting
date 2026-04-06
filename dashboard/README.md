# PGA +EV Dashboard

Streamlit-based dashboard for monitoring active golf bets and tournament P&L.

## Streamlit Cloud Deployment

1. Create a [Streamlit Cloud](https://streamlit.io) account using GitHub login.
2. Click **New app** from the Streamlit Cloud dashboard.
3. Select the `pga-ev-betting` repository.
4. Set the main file path to `dashboard/app.py`.
5. Under **Advanced settings**, paste the secrets TOML block:
   ```toml
   SUPABASE_URL = "https://xxxx.supabase.co"
   SUPABASE_KEY = "your-anon-key"
   ```
   Replace the placeholder values with your Supabase project credentials (use the anon/public key, not the service role key).
6. Click **Deploy**. Streamlit Cloud reads `dashboard/requirements.txt` and installs dependencies automatically.

### Access Control

Deploy as a **Private App** (Streamlit Cloud free tier allows one private app). This requires viewers to authenticate via GitHub or Google before accessing the dashboard. The dashboard shows sensitive financial data (stakes, bankroll, P&L), so URL obscurity alone is insufficient.

To toggle private/public, go to your app's settings in the Streamlit Cloud dashboard under **Sharing**.

## Local Development

```bash
cd dashboard
pip install -r requirements.txt
streamlit run app.py
```

Create `dashboard/.streamlit/secrets.toml` with your Supabase credentials (this file is gitignored):

```toml
SUPABASE_URL = "https://your-project.supabase.co"
SUPABASE_KEY = "your-anon-key-here"
```

## Running Tests

```bash
cd dashboard
pytest tests/ -v
```
