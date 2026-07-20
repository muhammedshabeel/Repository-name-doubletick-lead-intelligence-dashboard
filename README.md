# DoubleTick Lead Intelligence

Streamlit dashboard that:
- Uploads a DoubleTick customer report.
- Uses customer phone numbers to fetch DoubleTick ad/referral data.
- Resolves ad IDs to Meta campaign, ad set and ad names.
- Ignores the unreliable agent-name column and maps assigned-agent phone to the correct name from a separate uploaded mapping file.
- Produces country-wise, vendor-wise, product-wise and agent-wise lead counts.
- Exports a detailed multi-sheet Excel report.

## Required customer report columns
The app auto-detects common names for:
- Customer phone / customer number
- Assigned agent phone / assigned user number

## Required agent mapping columns
- Agent phone
- Agent name

## Run locally
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Deploy on Streamlit Community Cloud
1. Push this folder to a GitHub repository.
2. In Streamlit Community Cloud, choose **Create app**.
3. Select the repository, branch and `app.py`.
4. Add secrets in **App settings > Secrets** using `.streamlit/secrets.toml.example` as the format.
5. Deploy.

Never commit real API keys or access tokens.
