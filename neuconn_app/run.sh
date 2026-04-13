#pkill -f "streamlit run app.py"
killall streamlit
streamlit run app.py --server.headless=true --server.port=8500 2>&1 &
