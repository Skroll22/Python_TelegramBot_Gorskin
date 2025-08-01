import psycopg2
from secrets import DB_CONN

def get_conn():
    return psycopg2.connect(DB_CONN)