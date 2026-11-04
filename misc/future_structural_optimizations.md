# Future Structural Optimizations

While the Multi-Page Application (MPA) migration drastically reduced the footprint of the script and eliminated cross-tab processing lag, there are still two advanced optimization pathways available to push the app's performance into enterprise territory:

### 1. Pre-Calculate Heavy Workflows (Decoupling UI from Engine)
Currently, if there is no cache for a specific account, visiting the Dashboard forces the `calculate_twr_series` engine to run live on the main UI thread. This blocks the interface while `yfinance` fetches and pandas crunches the TWR series.

**The Solution:**
Ensure your UI strictly reads the SQLite `.db` output of background runs for the Dashboard tab.
- Instead of executing `calculate_twr_series` live on the main thread, rely exclusively on `storage.load_latest_portfolio()`.
- If no data is found, show a placeholder asking the user to press "Recalculate", but trigger this recalculation asynchronously via a background daemon thread (similar to how the scheduler works) instead of blocking the `st.rerun()`.
- This ensures the UI is **always** instantly responsive and strictly acts as a read-only client of the database.

### 2. Decouple Initialization from Execution
The background daemon thread checks (`_ensure_auto_refresh_running()`) and locking mechanisms were running during every rerun of the old monolithic `app.py`. Even outside of the monolith, managing threading logic alongside Streamlit's execution model can cause micro-stutters as Streamlit re-evaluates lock states on every UI interaction.

**The Solution:**
- Move the `_ensure_auto_refresh_running()` daemon thread checks into a completely separate initialization script or wrap them inside an `@st.cache_resource` block.
- By mounting the scheduler thread inside a cached resource exactly once during server startup, you avoid checking threading locks entirely on subsequent button clicks or dropdown changes. This keeps the execution path as clean as possible.
