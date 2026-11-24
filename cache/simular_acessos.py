# Simula uma semana de uso do sistema para ter números nas estatísticas,
# e compara o que as estruturas probabilísticas estimam com a conta exata.
#   python -m cache.simular_acessos

import random
from collections import Counter
from datetime import date, timedelta

from cache.conexao_redis import conectar_redis
from cache import estatisticas as E

ROTAS = [  # as rotas de cima são mais usadas que as de baixo
    "GET /condominios/{condominio_id}/enquetes",
    "GET /enquetes/{enquete_id}/resultado",
    "POST /enquetes/{enquete_id}/votos",
    "GET /condominios/{condominio_id}/vencimentos",
    "GET /condominios/{condominio_id}/gastos",
    "POST /login",
    "POST /condominios/{condominio_id}/enquetes",
]
PESOS = [40, 25, 12, 10, 8, 4, 1]

if __name__ == "__main__":
    r = conectar_redis()
    random.seed(7)
    hoje = date.today()

    visitantes_por_dia = {}
    rotas_exato = Counter()
    for i in range(7):
        dia = hoje - timedelta(days=6 - i)
        pessoas = [f"visitante-{random.randint(1, 4000)}" for _ in range(random.randint(800, 1500))]
        visitantes_por_dia[dia] = set(pessoas)
        rotas_exato.update(random.choices(ROTAS, PESOS, k=len(pessoas)))
        # manda o dia inteiro de uma vez (a API registra um acesso por vez, mas aqui
        # seriam milhares de idas e voltas até o Redis Cloud)
        r.pfadd(E.hll_visitantes(dia), *pessoas)
        r.expire(E.hll_visitantes(dia), E.GUARDAR_POR)

    if not r.exists(E.CMS_ROTAS):
        r.cms().initbydim(E.CMS_ROTAS, 2000, 5)
    r.cms().incrby(E.CMS_ROTAS, list(rotas_exato), list(rotas_exato.values()))
    r.sadd(E.ROTAS_VISTAS, *rotas_exato)
    r.incrby("total_requisicoes", sum(rotas_exato.values()))

    print("HyperLogLog: visitantes diferentes por dia")
    print(f"  {'dia':12} {'exato':>6} {'HLL':>6}")
    for dia, pessoas in visitantes_por_dia.items():
        print(f"  {dia.isoformat():12} {len(pessoas):>6} {r.pfcount(E.hll_visitantes(dia)):>6}")
    semana_exato = len(set().union(*visitantes_por_dia.values()))
    semana_hll = r.pfcount(*[E.hll_visitantes(d) for d in visitantes_por_dia])
    print(f"  {'semana':12} {semana_exato:>6} {semana_hll:>6}")

    print("\nCount-Min Sketch: acessos por rota (inclui acessos de antes, se tiver)")
    for rota, n in rotas_exato.most_common():
        print(f"  {rota:45} simulados {n:>5}   CMS {r.cms().query(E.CMS_ROTAS, rota)[0]:>5}")

    # o filtro de verdade só tem 2 e-mails, então quase nunca erra. Para ver o erro de 1%
    # aparecer, enchemos um filtro de teste até a capacidade (1000) e testamos 10000 que não estão nele
    print("\nBloom filter de teste: 1000 e-mails dentro, 10000 de fora")
    r.delete("teste:bf")
    r.bf().reserve("teste:bf", 0.01, 1000)
    r.bf().madd("teste:bf", *[f"sindico{i}@predio.exemplo" for i in range(1000)])
    dentro = sum(r.bf().mexists("teste:bf", *[f"sindico{i}@predio.exemplo" for i in range(1000)]))
    falsos = sum(r.bf().mexists("teste:bf", *[f"outro{i}@nao.existe" for i in range(10000)]))
    print(f"  dos 1000 que estão dentro, achou {dentro} (nunca deixa passar nenhum)")
    print(f"  dos 10000 de fora, disse 'talvez exista' para {falsos} ({falsos / 100:.2f}%, o esperado é perto de 1%)")
    r.delete("teste:bf")
