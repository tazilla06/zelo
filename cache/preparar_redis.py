# Prepara o Redis: cria o Bloom filter com os e-mails dos síndicos (vindos do MongoDB)
# e o Count-Min Sketch das rotas. Rodar da pasta do projeto, depois do criar_banco.py:
#   python -m cache.preparar_redis

from database.conexao import conectar
from cache.conexao_redis import conectar_redis
from cache import estatisticas as E

if __name__ == "__main__":
    db = conectar()
    r = conectar_redis()

    # apaga sessões e caches antigos (o banco foi recriado, os ids mudaram)
    for padrao in ("sessao:*", "cache:sindico:*", "tentativas:*"):
        for chave in r.scan_iter(padrao):
            r.delete(chave)

    n = E.preparar(r, db)
    print(f"Bloom filter criado com {n} e-mail(s) de síndico.")
    print("Count-Min Sketch das rotas pronto.")

    for email in ("sindico@acacias.exemplo", "fulano@nao.existe"):
        resposta = "talvez exista" if E.email_pode_existir(r, email) else "com certeza não existe"
        print(f"  {email}: {resposta}")
