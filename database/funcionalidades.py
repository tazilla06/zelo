# Funcionalidades do Zelo (os pipelines de agregação) e as regras da enquete.
# Rodando direto mostra o resultado no terminal:  python database/funcionalidades.py

from datetime import datetime, timedelta, timezone

from pymongo.errors import DuplicateKeyError


def agora_utc():
    # o pymongo grava as datas em UTC
    return datetime.now(timezone.utc).replace(tzinfo=None)


# Funcionalidade 1: painel de vencimentos
# Junta numa lista só os prazos dos equipamentos e a validade dos laudos,
# calcula quantos dias faltam e separa por urgência.
def pipeline_vencimentos(condominio_id, hoje):
    return [
        {"$match": {"condominio_id": condominio_id}},
        {"$project": {
            "_id": 0,
            "origem": "Equipamento",
            "item": {"$concat": ["$tipo", " ", "$identificacao"]},
            "detalhe": "$local",
            "prazo": "$proxima_manutencao",
        }},
        # traz os laudos (outra coleção) com os mesmos campos, pra ficar tudo na mesma lista
        {"$unionWith": {
            "coll": "laudos",
            "pipeline": [
                {"$match": {"condominio_id": condominio_id}},
                {"$project": {"_id": 0, "origem": "Laudo", "item": "$tipo", "detalhe": "$numero", "prazo": "$validade"}},
            ],
        }},
        # dias que faltam até o prazo (negativo quer dizer que já venceu)
        {"$addFields": {"dias_restantes": {"$dateDiff": {"startDate": hoje, "endDate": "$prazo", "unit": "day"}}}},
        {"$addFields": {"urgencia": {"$switch": {
            "branches": [
                {"case": {"$lt": ["$dias_restantes", 0]}, "then": "1. Vencido"},
                {"case": {"$lte": ["$dias_restantes", 7]}, "then": "2. Vence nesta semana"},
                {"case": {"$lte": ["$dias_restantes", 30]}, "then": "3. Vence neste mês"},
            ],
            "default": "4. Em dia",
        }}}},
        {"$sort": {"prazo": 1}},
        {"$group": {
            "_id": "$urgencia",
            "quantidade": {"$sum": 1},
            "itens": {"$push": {
                "origem": "$origem", "item": "$item", "detalhe": "$detalhe",
                "prazo": "$prazo", "dias_restantes": "$dias_restantes",
            }},
        }},
        {"$sort": {"_id": 1}},  # o número na frente do nome deixa na ordem certa
    ]


def painel_vencimentos(db, condominio_id, hoje=None):
    hoje = hoje or agora_utc()
    return list(db.equipamentos.aggregate(pipeline_vencimentos(condominio_id, hoje)))


# Funcionalidade 2: relatório de gastos com manutenção
# Abre o histórico de manutenções de cada equipamento e monta vários
# resumos de uma vez com o $facet.
def pipeline_gastos(condominio_id, desde):
    return [
        {"$match": {"condominio_id": condominio_id}},
        {"$unwind": "$manutencoes"},  # cada manutenção vira um documento
        {"$match": {"manutencoes.data": {"$gte": desde}}},
        {"$lookup": {
            "from": "prestadores",
            "localField": "manutencoes.prestador_id",
            "foreignField": "_id",
            "as": "prestador",
        }},
        {"$project": {
            "_id": 0,
            "equipamento": {"$concat": ["$tipo", " ", "$identificacao"]},
            "tipo_servico": "$manutencoes.tipo",
            "custo": {"$ifNull": ["$manutencoes.custo", 0]},
            "mes": {"$dateToString": {"format": "%Y-%m", "date": "$manutencoes.data"}},
            # algumas manutenções não têm prestador (foi o zelador que fez, por exemplo)
            "prestador": {"$ifNull": [{"$first": "$prestador.nome"}, "Sem prestador"]},
        }},
        {"$facet": {
            "resumo": [
                {"$group": {"_id": None, "total": {"$sum": "$custo"}, "quantidade": {"$sum": 1},
                            "media": {"$avg": "$custo"}, "maior": {"$max": "$custo"}}},
                {"$project": {"_id": 0}},
            ],
            "por_mes": [
                {"$group": {"_id": "$mes", "total": {"$sum": "$custo"}, "quantidade": {"$sum": 1}}},
                {"$sort": {"_id": 1}},
            ],
            "por_prestador": [
                {"$group": {"_id": "$prestador", "total": {"$sum": "$custo"}, "quantidade": {"$sum": 1}}},
                {"$sort": {"total": -1}},
            ],
            "por_tipo_servico": [
                {"$group": {"_id": "$tipo_servico", "total": {"$sum": "$custo"}, "quantidade": {"$sum": 1}}},
                {"$sort": {"total": -1}},
            ],
            "top_equipamentos": [
                {"$group": {"_id": "$equipamento", "total": {"$sum": "$custo"}}},
                {"$sort": {"total": -1}},
                {"$limit": 3},
            ],
        }},
    ]


def relatorio_gastos(db, condominio_id, meses=12, hoje=None):
    hoje = hoje or agora_utc()
    desde = hoje - timedelta(days=30 * meses)
    resultado = list(db.equipamentos.aggregate(pipeline_gastos(condominio_id, desde)))
    relatorio = resultado[0] if resultado else {}
    # se não tiver nenhuma manutenção no período o resumo vem vazio
    resumo = relatorio.get("resumo") or [{"total": 0, "quantidade": 0, "media": 0, "maior": 0}]
    relatorio["resumo"] = resumo[0]
    return relatorio


# Enquete de compras

class ErroEnquete(Exception):
    # status = código HTTP que a API devolve
    def __init__(self, mensagem, status=400):
        super().__init__(mensagem)
        self.status = status


def situacao_enquete(enquete, agora=None):
    agora = agora or agora_utc()
    if agora < enquete["abertura"]:
        return "agendada"
    if agora > enquete["encerramento"]:
        return "encerrada"
    return "aberta"


def listar_enquetes(db, condominio_id, agora=None):
    enquetes = list(db.enquetes.find({"condominio_id": condominio_id}).sort("encerramento", -1))
    for e in enquetes:
        e["situacao"] = situacao_enquete(e, agora)
        e["total_votos"] = db.votos.count_documents({"enquete_id": e["_id"]})
    return enquetes


def criar_enquete(db, condominio_id, titulo, opcoes, dias_duracao=7, descricao="", criada_por="Síndico"):
    # opcoes = lista de {"descricao": ..., "valor_estimado": ...}; as letras A, B, C... são colocadas aqui
    if not db.condominios.find_one({"_id": condominio_id}):
        raise ErroEnquete("Condomínio não encontrado.", 404)
    if len(opcoes) < 2:
        raise ErroEnquete("A enquete precisa de pelo menos 2 opções.")

    agora = agora_utc()
    enquete = {
        "condominio_id": condominio_id,
        "titulo": titulo,
        "descricao": descricao,
        "opcoes": [
            {"codigo": chr(ord("A") + i), "descricao": o["descricao"], "valor_estimado": o.get("valor_estimado", 0)}
            for i, o in enumerate(opcoes)
        ],
        "abertura": agora,
        "encerramento": agora + timedelta(days=dias_duracao),
        "criada_por": criada_por,
    }
    enquete["_id"] = db.enquetes.insert_one(enquete).inserted_id
    return enquete


def votar(db, enquete_id, codigo_acesso, opcao, agora=None):
    agora = agora or agora_utc()

    morador = db.moradores.find_one({"codigo_acesso": codigo_acesso.strip().upper()})
    if not morador:
        raise ErroEnquete("Código de acesso não encontrado. Confira com o síndico.", 403)

    enquete = db.enquetes.find_one({"_id": enquete_id})
    if not enquete:
        raise ErroEnquete("Enquete não encontrada.", 404)
    if enquete["condominio_id"] != morador["condominio_id"]:
        raise ErroEnquete("Esta enquete é de outro condomínio.", 403)

    situacao = situacao_enquete(enquete, agora)
    if situacao != "aberta":
        raise ErroEnquete(f"A enquete está {situacao}, não dá mais pra votar.", 409)

    # o banco não tem como saber quais letras existem em cada enquete, então essa conferência fica aqui
    opcao = opcao.strip().upper()
    if opcao not in [o["codigo"] for o in enquete["opcoes"]]:
        raise ErroEnquete(f"A opção {opcao} não existe nesta enquete.")

    voto = {
        "enquete_id": enquete["_id"],
        "morador_id": morador["_id"],
        "condominio_id": morador["condominio_id"],
        "bloco": morador["bloco"],
        "unidade": morador["unidade"],
        "opcao": opcao,
        "data": agora,
    }
    try:
        db.votos.insert_one(voto)
    except DuplicateKeyError:
        # quem barra o voto repetido é o índice único de votos (enquete_id + bloco + unidade)
        raise ErroEnquete(f"O apartamento {morador['unidade']} do bloco {morador['bloco']} já votou nesta enquete.", 409)
    return voto


# Resultado da enquete: começa pelas opções (pra opção sem voto aparecer com 0)
# e conta os votos de cada uma na coleção votos.
def pipeline_resultado_enquete(enquete_id):
    return [
        {"$match": {"_id": enquete_id}},
        {"$unwind": "$opcoes"},
        {"$lookup": {
            "from": "votos",
            "let": {"enquete": "$_id", "opcao": "$opcoes.codigo"},
            "pipeline": [
                {"$match": {"$expr": {"$and": [
                    {"$eq": ["$enquete_id", "$$enquete"]},
                    {"$eq": ["$opcao", "$$opcao"]},
                ]}}},
                {"$count": "n"},
            ],
            "as": "contagem",
        }},
        {"$project": {
            "_id": 0,
            "opcao": "$opcoes.codigo",
            "descricao": "$opcoes.descricao",
            "valor_estimado": "$opcoes.valor_estimado",
            "votos": {"$ifNull": [{"$first": "$contagem.n"}, 0]},
        }},
        # total de votos e colocação de cada opção sem precisar de outro $group
        {"$setWindowFields": {
            "sortBy": {"votos": -1},
            "output": {
                "total_votos": {"$sum": "$votos", "window": {"documents": ["unbounded", "unbounded"]}},
                "posicao": {"$rank": {}},
            },
        }},
        {"$addFields": {"percentual": {"$cond": [
            {"$eq": ["$total_votos", 0]},
            0,
            {"$round": [{"$multiply": [{"$divide": ["$votos", "$total_votos"]}, 100]}, 1]},
        ]}}},
        {"$sort": {"posicao": 1, "opcao": 1}},
    ]


def resultado_enquete(db, enquete_id, agora=None):
    enquete = db.enquetes.find_one({"_id": enquete_id})
    if not enquete:
        raise ErroEnquete("Enquete não encontrada.", 404)

    opcoes = list(db.enquetes.aggregate(pipeline_resultado_enquete(enquete_id)))
    total_votos = opcoes[0]["total_votos"] if opcoes else 0
    total_apartamentos = db.moradores.count_documents({"condominio_id": enquete["condominio_id"]})

    return {
        "enquete_id": enquete["_id"],
        "titulo": enquete["titulo"],
        "situacao": situacao_enquete(enquete, agora),
        "encerramento": enquete["encerramento"],
        "total_votos": total_votos,
        "total_apartamentos": total_apartamentos,
        "participacao": round(100 * total_votos / total_apartamentos, 1) if total_apartamentos else 0,
        "opcoes": opcoes,
        "vencedora": opcoes[0] if total_votos else None,
    }


def reais(valor):
    # 3020 -> R$ 3.020,00
    return "R$ " + f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


if __name__ == "__main__":
    from conexao import conectar

    db = conectar()
    cond = db.condominios.find_one({"nome": "Residencial Jardim das Acácias"})
    print("Condomínio:", cond["nome"])

    print("\n--- Funcionalidade 1: painel de vencimentos ---")
    for grupo in painel_vencimentos(db, cond["_id"]):
        print(f"\n{grupo['_id']} ({grupo['quantidade']})")
        for i in grupo["itens"]:
            print(f"  {i['prazo']:%d/%m/%Y}  ({i['dias_restantes']} dias)  {i['item']} - {i['detalhe']}")

    print("\n--- Funcionalidade 2: gastos com manutenção nos últimos 12 meses ---")
    rel = relatorio_gastos(db, cond["_id"])
    r = rel["resumo"]
    print(f"Total {reais(r['total'])} em {r['quantidade']} serviços, maior serviço {reais(r['maior'] or 0)}")
    for nome, chave in [("Por mês", "por_mes"), ("Por prestador", "por_prestador"),
                        ("Por tipo de serviço", "por_tipo_servico"), ("Os 3 mais caros", "top_equipamentos")]:
        print(f"\n{nome}:")
        for linha in rel.get(chave, []):
            print(f"  {str(linha['_id']):35} {reais(linha['total'])}")

    print("\n--- Enquete da área de lazer ---")
    enquete = db.enquetes.find_one({"condominio_id": cond["_id"], "titulo": {"$regex": "lazer"}})
    res = resultado_enquete(db, enquete["_id"])
    print(f"{res['titulo']} ({res['situacao']}): {res['total_votos']} de {res['total_apartamentos']} apartamentos votaram")
    for o in res["opcoes"]:
        print(f"  {o['posicao']}. {o['opcao']}) {o['descricao']}: {o['votos']} voto(s) ({o['percentual']}%)")
