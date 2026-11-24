import os

import redis
from dotenv import load_dotenv

load_dotenv()


def conectar_redis():
    url = os.getenv("REDIS_URL")
    if not url:
        raise SystemExit("Faltou o REDIS_URL no .env. Veja o .env.example.")
    # decode_responses=True faz o Redis devolver texto em vez de bytes
    r = redis.Redis.from_url(url, decode_responses=True)
    r.ping()
    return r
