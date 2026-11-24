# Estatísticas de uso do Zelo com estruturas probabilísticas do Redis.
#
# São estruturas que gastam pouquíssima memória em troca de uma resposta aproximada:
#
# - Bloom filter (bf:emails_sindicos): responde "esse e-mail é de algum síndico?".
#   Se ele disser NÃO, é certeza. Se disser SIM, pode ser engano (1% de chance), aí o Mongo confirma.
# - HyperLogLog (hll:visitantes:<dia> e hll:sindicos:<dia>): conta quantos visitantes
#   DIFERENTES usaram o sistema no dia, com uns 12 KB por dia, não importa quantos sejam.
# - Count-Min Sketch (cms:rotas): conta quantas vezes cada tela/rota da API foi usada.
#   Pode contar um pouco a mais, nunca a menos.

from datetime import date, timedelta

import redis

BF_EMAILS = "bf:emails_sindicos"
CMS_ROTAS = "cms:rotas"
ROTAS_VISTAS = "rotas_vistas"  # o CMS não sabe listar o que contou, então guardamos os nomes das rotas num SET
GUARDAR_POR = 90 * 24 * 3600     # os contadores de cada dia somem depois de 90 dias


def hll_visitantes(dia):
    return f"hll:visitantes:{dia.isoformat()}"


def hll_sindicos(dia):
    return f"hll:sindicos:{dia.isoformat()}"


def preparar(r, db):
    # cria o Bloom filter com os e-mails dos síndicos que estão no Mongo
    r.delete(BF_EMAILS)
    r.bf().reserve(BF_EMAILS, 0.01, 1000)  # 1% de erro, até 1000 e-mails
    emails = [s["email"] for s in db.sindicos.find({"ativo": True}, {"email": 1})]
    if emails:
        r.bf().madd(BF_EMAILS, *emails)

    if not r.exists(CMS_ROTAS):
        r.cms().initbydim(CMS_ROTAS, 2000, 5)  # 2000 colunas x 5 linhas
    return len(emails)


def adicionar_email(r, email):
    # chamar quando cadastrar um síndico novo
    r.bf().add(BF_EMAILS, email)


def email_pode_existir(r, email):
    try:
        return bool(r.bf().exists(BF_EMAILS, email))
    except redis.ResponseError:
        return True  # filtro ainda não foi criado: deixa o Mongo decidir


def registrar_acesso(r, rota, visitante, dia=None):
    dia = dia or date.today()
    chave = hll_visitantes(dia)
    r.pfadd(chave, visitante)
    r.expire(chave, GUARDAR_POR)

    try:
        r.cms().incrby(CMS_ROTAS, [rota], [1])
    except redis.ResponseError:  # o CMS ainda não existe
        r.cms().initbydim(CMS_ROTAS, 2000, 5)
        r.cms().incrby(CMS_ROTAS, [rota], [1])
    r.sadd(ROTAS_VISTAS, rota)
    r.incr("total_requisicoes")


def registrar_login(r, sindico_id, dia=None):
    dia = dia or date.today()
    chave = hll_sindicos(dia)
    r.pfadd(chave, sindico_id)
    r.expire(chave, GUARDAR_POR)


def _memoria(r, chave):
    try:
        return r.memory_usage(chave)
    except redis.ResponseError:
        return None


def resumo(r, dias=7):
    hoje = date.today()
    ultimos = [hoje - timedelta(days=i) for i in range(dias - 1, -1, -1)]

    por_dia = [{
        "dia": d.isoformat(),
        "visitantes": r.pfcount(hll_visitantes(d)),
        "sindicos": r.pfcount(hll_sindicos(d)),
    } for d in ultimos]

    # PFCOUNT com várias chaves conta a UNIÃO: quem veio em 3 dias diferentes conta 1 vez só
    visitantes_periodo = r.pfcount(*[hll_visitantes(d) for d in ultimos])
    sindicos_periodo = r.pfcount(*[hll_sindicos(d) for d in ultimos])

    rotas = sorted(r.smembers(ROTAS_VISTAS))
    contagens = r.cms().query(CMS_ROTAS, *rotas) if rotas else []
    mais_usadas = sorted(
        [{"rota": rota, "acessos": n} for rota, n in zip(rotas, contagens)],
        key=lambda x: -x["acessos"],
    )

    try:
        info = r.bf().info(BF_EMAILS)
        bloom = {"capacidade": info.capacity, "emails_no_filtro": info.insertedNum}
    except redis.ResponseError:
        bloom = None

    return {
        "por_dia": por_dia,
        "visitantes_no_periodo": visitantes_periodo,
        "sindicos_no_periodo": sindicos_periodo,
        "rotas_mais_usadas": mais_usadas,
        "total_requisicoes": int(r.get("total_requisicoes") or 0),
        "bloom_emails": bloom,
        "memoria_bytes": {
            "hll_visitantes_hoje": _memoria(r, hll_visitantes(hoje)),
            "cms_rotas": _memoria(r, CMS_ROTAS),
            "bf_emails": _memoria(r, BF_EMAILS),
        },
    }
