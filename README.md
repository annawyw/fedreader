# Fed Reader

A Streamlit app for following the Federal Reserve: the next FOMC meeting and market expectations,
statement redlines, speaker tone, the dot plot and projections, policy-rule estimates, and the minutes.
Data comes from federalreserve.gov and FRED (and CME FedWatch if you add keys).

## Run locally

    pip install -r requirements.txt
    streamlit run app.py

## Deploy on Streamlit Community Cloud

1. Put these files in a GitHub repository (public or private).
2. Go to https://share.streamlit.io, sign in with GitHub, and click **Create app**.
3. Choose the repository, branch `main`, and main file `app.py`. Pick Python 3.12 under Advanced settings.
4. Optional: under **Advanced settings → Secrets**, paste

       FRED_API_KEY = "your key"

   (free from https://fred.stlouisfed.org/docs/api/api_key.html). Without it the app uses FRED's public CSV download.
5. Click **Deploy**. Pushes to the repository redeploy the app automatically.
