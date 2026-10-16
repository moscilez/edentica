import os
import uvicorn
from .app import app

# psycopg uses synchronous pooled connections in asyncio.to_thread, retaining
# the Windows Proactor loop needed for non-blocking Node/Python subprocesses.
uvicorn.run(app, host=os.getenv("HOST") or "127.0.0.1", port=int(os.getenv("PORT") or "3000"),
            workers=1, proxy_headers=False, timeout_graceful_shutdown=30)
