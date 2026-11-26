# Vercel container service (see ../vercel.json). Build context = dashboard/.
FROM python:3.12.8-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py data_jobs.csv.gz market_by_province.csv vn_provinces.geojson ./
ENV STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    STREAMLIT_THEME_PRIMARY_COLOR="#2a78d6"
# Vercel sends traffic to $PORT (default 80).
CMD ["sh", "-c", "exec streamlit run app.py --server.address=0.0.0.0 --server.port=${PORT:-80}"]
