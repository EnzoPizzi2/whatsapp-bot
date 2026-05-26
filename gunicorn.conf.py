import os


bind = f"0.0.0.0:{os.getenv('PORT', '8000')}"

# Keep one process while SQLite is the database. Threads are enough for this bot
# and avoid multiple workers writing to the same local database file.
workers = 1
threads = 4
timeout = 120

accesslog = "-"
errorlog = "-"
