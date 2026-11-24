# Login do síndico usando o Redis como cache.
#
# - cache do síndico: depois do primeiro login os dados dele ficam 10 min no Redis,
#   então os próximos logins nem consultam o MongoDB
# - sessão: o login gera um token que fica no Redis com prazo de 30 min (TTL).
#   Cada requisição só confere o token no Redis, sem ir no MongoDB
# - limite de tentativas: 5 senhas erradas bloqueiam o e-mail por 15 min
# - Bloom filter: se o e-mail com certeza não existe, nem consulta o MongoDB

import json
import math
import secrets
from datetime import datetime

from database.senha import conferir_senha
from cache import estatisticas as E

TEMPO_SESSAO = 30 * 60   # segundos
TEMPO_CACHE = 10 * 60
MAX_TENTATIVAS = 5
TEMPO_BLOQUEIO = 15 * 60


class ErroLogin(Exception):
    def __init__(self, mensagem, status=401):
        super().__init__(mensagem)
        self.status = status


def buscar_sindico(db, r, email):
    # padrão "cache-aside": olha primeiro no Redis, se não tiver busca no Mongo e guarda no Redis
    chave = f"cache:sindico:{email}"
    guardado = r.get(chave)
    if guardado:
        return json.loads(guardado), "cache"

    doc = db.sindicos.find_one({"email": email, "ativo": True})
    if not doc:
        return None, "banco"
    sindico = {
        "id": str(doc["_id"]),
        "nome": doc["nome"],
        "email": doc["email"],
        "condominio_id": str(doc["condominio_id"]),
        "senha_hash": doc["senha_hash"],
    }
    r.set(chave, json.dumps(sindico), ex=TEMPO_CACHE)
    return sindico, "banco"


def _senha_errada(r, chave_tentativas):
    tentativas = r.incr(chave_tentativas)
    if tentativas == 1:
        r.expire(chave_tentativas, TEMPO_BLOQUEIO)  # o contador some sozinho depois de 15 min
    # mesma mensagem pra e-mail errado e senha errada, pra não entregar quais e-mails existem
    raise ErroLogin("E-mail ou senha incorretos.")


def fazer_login(db, r, email, senha):
    email = email.strip().lower()
    chave_tentativas = f"tentativas:{email}"

    if int(r.get(chave_tentativas) or 0) >= MAX_TENTATIVAS:
        minutos = math.ceil(max(r.ttl(chave_tentativas), 1) / 60)
        raise ErroLogin(f"Muitas tentativas erradas. Tente de novo em {minutos} min.", 429)

    # Bloom filter: "não" é certeza, "sim" é só talvez. Se for "não", nem vai no Mongo
    if not E.email_pode_existir(r, email):
        _senha_errada(r, chave_tentativas)

    sindico, origem = buscar_sindico(db, r, email)
    if not sindico or not conferir_senha(senha, sindico["senha_hash"]):
        _senha_errada(r, chave_tentativas)

    r.delete(chave_tentativas)

    token = secrets.token_urlsafe(32)
    chave_sessao = f"sessao:{token}"
    r.hset(chave_sessao, mapping={
        "sindico_id": sindico["id"],
        "nome": sindico["nome"],
        "email": sindico["email"],
        "condominio_id": sindico["condominio_id"],
        "entrou_em": datetime.now().isoformat(timespec="seconds"),
    })
    r.expire(chave_sessao, TEMPO_SESSAO)

    E.registrar_login(r, sindico["id"])

    return {
        "token": token,
        "nome": sindico["nome"],
        "condominio_id": sindico["condominio_id"],
        "expira_em_minutos": TEMPO_SESSAO // 60,
        "dados_vieram_do": origem,  # "banco" no primeiro login, "cache" nos próximos
    }


def sessao_atual(r, token):
    # devolve os dados do síndico logado, ou None se o token não existe ou já expirou
    if not token:
        return None
    chave = f"sessao:{token}"
    dados = r.hgetall(chave)
    if not dados:
        return None
    r.expire(chave, TEMPO_SESSAO)  # enquanto o síndico usa, a sessão vai sendo renovada
    dados["expira_em_segundos"] = TEMPO_SESSAO
    return dados


def sair(r, token):
    r.delete(f"sessao:{token}")
