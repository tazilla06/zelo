import os

from dotenv import load_dotenv
from pymongo import MongoClient

# a connection string fica no arquivo .env (que não vai pro GitHub)
load_dotenv()

NOME_BANCO = "zelo"


def conectar():
    uri = os.getenv("MONGODB_URI")
    if not uri:
        raise SystemExit("Faltou o MONGODB_URI. Copie o .env.example para .env e coloque a sua connection string.")

    client = MongoClient(uri)
    client.admin.command("ping")  # se a senha ou o IP estiverem errados, o erro aparece aqui
    return client[NOME_BANCO]
