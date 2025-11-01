import psycopg2
from my_secrets import DB_CONN

def get_conn():
    return psycopg2.connect(DB_CONN)