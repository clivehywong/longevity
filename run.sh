#pkill -f "streamlit run app.py"
killall streamlit
cd neuconn_app
streamlit run app.py --server.headless=true --server.port=8501 2>&1 &
