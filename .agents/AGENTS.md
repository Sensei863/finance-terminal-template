# Custom Agent Rules

## Tool Execution and Diagnosing Rules
1. **Never Poll Background Tasks:** Do not write multiple wait/polling command cycles (`schedule`, `manage_task`) when waiting for background task results. Always wait for the system callback message.
2. **Do Not Duplicate Failing Network Commands:** If a database query or connection fails due to a timeout or connection limit error, do not launch multiple duplicate test commands or pings. Immediately inspect local client-side connection pools, thread safety, and orphaned processes instead.
3. **Verify Local Code Architecture Before Blaming Stale Processes:** Before assuming external databases or APIs are shared across all running services (like Streamlit), verify the exact file paths and local import paths (e.g., checking if SQLite is used instead of PostgreSQL).
4. **Verify Raw Database Data Before Debugging Application Logic:** When diagnosing issues with missing data or parsing logic (especially after a database migration), ALWAYS query the database directly first to check the raw state of the data before diving into application code and tearing apart logic.
