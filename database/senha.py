# Senha do síndico: no banco fica só o hash, nunca a senha.
# PBKDF2 já vem no Python (hashlib), então não precisa instalar nada.

import hashlib
import hmac
import secrets

ITERACOES = 200_000


def gerar_hash(senha):
    sal = secrets.token_hex(16)  # sal aleatório: duas senhas iguais geram hashes diferentes
    h = hashlib.pbkdf2_hmac("sha256", senha.encode(), sal.encode(), ITERACOES).hex()
    return f"pbkdf2_sha256${ITERACOES}${sal}${h}"


def conferir_senha(senha, hash_salvo):
    try:
        _, iteracoes, sal, h = hash_salvo.split("$")
    except (AttributeError, ValueError):
        return False
    calculado = hashlib.pbkdf2_hmac("sha256", senha.encode(), sal.encode(), int(iteracoes)).hex()
    return hmac.compare_digest(calculado, h)  # compara sem dar pista pelo tempo de resposta
