"""Conexão com o MongoDB Atlas, usada pelos outros scripts do Zelo.

A string de conexão NÃO fica no código (o repositório é público).
Ela é lida da variável de ambiente MONGODB_URI; se não existir,
o script pede para você colar a string ao rodar.
"""
import os
from getpass import getpass

from pymongo import MongoClient

NOME_BANCO = "zelo"


def obter_uri():
    uri = os.environ.get("MONGODB_URI")
    if not uri:
        print("Cole a string de conexão do Atlas e aperte Enter.")
        print("Exemplo: mongodb+srv://usuario:senha@cluster0.xxxxx.mongodb.net/")
        print("(o texto não aparece enquanto você cola, é normal)")
        uri = getpass("MONGODB_URI: ").strip()
    return uri


def conectar():
    client = MongoClient(obter_uri())
    client.admin.command("ping")  # falha aqui se usuário, senha ou IP estiverem errados
    return client[NOME_BANCO]
