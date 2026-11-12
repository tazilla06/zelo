"""Zelo — funcionalidades do sistema (pipelines de agregação).

1. Painel de vencimentos  -> junta equipamentos e laudos numa agenda única,
                              classificada por urgência
                              ($unionWith, $dateDiff, $switch, $group/$push)
2. Relatório de gastos    -> "abre" o histórico de manutenções e monta vários
                              resumos de uma vez
                              ($unwind, $lookup, $dateToString, $facet)
3. Enquete de compras     -> moradores votam (1 voto por apartamento) e o
                              resultado sai de um pipeline
                              ($unwind, $lookup com sub-pipeline, $setWindowFields)

Este arquivo também pode ser rodado direto para ver as 3 funcionalidades:
    python funcionalidades.py
"""
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from pymongo.errors import DuplicateKeyError


def agora_utc():
    # datas em UTC "sem fuso" (padrão do pymongo)
    return datetime.now(timezone.utc).replace(tzinfo=None)


# =====================================================================
# FUNCIONALIDADE 1 — PAINEL DE VENCIMENTOS
# Pergunta que responde: "o que o síndico precisa resolver e quando?"
# =====================================================================
def pipeline_vencimentos(condominio_id, hoje):
    return [
        # 1) Prazos dos equipamentos (próxima manutenção / recarga)
        {"$match": {"condominio_id": condominio_id}},
        {"$project": {
            "_id": 0,
            "origem": "Equipamento",
            "item": {"$concat": ["$tipo", " ", "$identificacao"]},
            "detalhe": "$local",
            "prazo": "$proxima_manutencao",
        }},
        # 2) Junta, no mesmo resultado, os prazos dos laudos (outra coleção)
        {"$unionWith": {
            "coll": "laudos",
            "pipeline": [
                {"$match": {"condominio_id": condominio_id}},
                {"$project": {
                    "_id": 0,
                    "origem": "Laudo",
                    "item": "$tipo",
                    "detalhe": "$numero",
                    "prazo": "$validade",
                }},
            ],
        }},
        # 3) Quantos dias faltam (negativo = já venceu)
        {"$addFields": {
            "dias_restantes": {"$dateDiff": {"startDate": hoje, "endDate": "$prazo", "unit": "day"}},
        }},
        # 4) Classifica a urgência
        {"$addFields": {
            "urgencia": {"$switch": {
                "branches": [
                    {"case": {"$lt": ["$dias_restantes", 0]}, "then": "1. Vencido"},
                    {"case": {"$lte": ["$dias_restantes", 7]}, "then": "2. Vence nesta semana"},
                    {"case": {"$lte": ["$dias_restantes", 30]}, "then": "3. Vence neste mês"},
                ],
                "default": "4. Em dia",
            }},
        }},
        # 5) Agrupa por urgência, com os itens em ordem de prazo
        {"$sort": {"prazo": 1}},
        {"$group": {
            "_id": "$urgencia",
            "quantidade": {"$sum": 1},
            "itens": {"$push": {
                "origem": "$origem", "item": "$item", "detalhe": "$detalhe",
                "prazo": "$prazo", "dias_restantes": "$dias_restantes",
            }},
        }},
        {"$sort": {"_id": 1}},
    ]


def painel_vencimentos(db, condominio_id, hoje=None):
    hoje = hoje or agora_utc()
    return list(db.equipamentos.aggregate(pipeline_vencimentos(condominio_id, hoje)))


# =====================================================================
# FUNCIONALIDADE 2 — RELATÓRIO DE GASTOS COM MANUTENÇÃO
# Pergunta que responde: "para onde foi o dinheiro da manutenção?"
# =====================================================================
def pipeline_gastos(condominio_id, desde):
    return [
        {"$match": {"condominio_id": condominio_id}},
        # 1) Cada manutenção embutida vira um documento
        {"$unwind": "$manutencoes"},
        {"$match": {"manutencoes.data": {"$gte": desde}}},
        # 2) Busca o nome do prestador na outra coleção
        {"$lookup": {
            "from": "prestadores",
            "localField": "manutencoes.prestador_id",
            "foreignField": "_id",
            "as": "prestador",
        }},
        {"$project": {
            "_id": 0,
            "equipamento": {"$concat": ["$tipo", " ", "$identificacao"]},
            "tipo_equipamento": "$tipo",
            "tipo_servico": "$manutencoes.tipo",
            "custo": {"$ifNull": ["$manutencoes.custo", 0]},
            "mes": {"$dateToString": {"format": "%Y-%m", "date": "$manutencoes.data"}},
            "prestador": {"$ifNull": [{"$first": "$prestador.nome"}, "Equipe própria / sem prestador"]},
        }},
        # 3) Vários resumos diferentes numa única consulta
        {"$facet": {
            "resumo": [
                {"$group": {"_id": None, "total": {"$sum": "$custo"},
                            "quantidade": {"$sum": 1}, "media": {"$avg": "$custo"},
                            "maior": {"$max": "$custo"}}},
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
    resumo = relatorio.get("resumo") or [{"total": 0, "quantidade": 0, "media": 0, "maior": 0}]
    relatorio["resumo"] = resumo[0]
    return relatorio


# =====================================================================
# ENQUETE DE COMPRAS — moradores votam no que o condomínio vai comprar
# =====================================================================
class ErroEnquete(Exception):
    """Erro de regra de negócio da enquete (com o código HTTP sugerido)."""

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
    """opcoes: lista de dicts {"descricao": str, "valor_estimado": número} (o código A, B, C... é gerado)."""
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
            {"codigo": chr(ord("A") + i), "descricao": o["descricao"],
             "valor_estimado": o.get("valor_estimado", 0)}
            for i, o in enumerate(opcoes)
        ],
        "abertura": agora,
        "encerramento": agora + timedelta(days=dias_duracao),
        "criada_por": criada_por,
    }
    enquete["_id"] = db.enquetes.insert_one(enquete).inserted_id
    return enquete


def votar(db, enquete_id, codigo_acesso, opcao, agora=None):
    """Registra o voto de um apartamento. Regras:
    - o código de acesso precisa existir e ser do mesmo condomínio da enquete;
    - a enquete precisa estar aberta;
    - a opção precisa existir na enquete;
    - cada apartamento vota uma única vez (garantido pelo índice único em `votos`)."""
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
        raise ErroEnquete(f"A enquete está {situacao}; não é possível votar.", 409)

    opcao = opcao.strip().upper()
    if opcao not in {o["codigo"] for o in enquete["opcoes"]}:
        raise ErroEnquete(f"Opção '{opcao}' não existe nesta enquete.")

    voto = {
        "enquete_id": enquete["_id"], "morador_id": morador["_id"],
        "condominio_id": morador["condominio_id"], "bloco": morador["bloco"],
        "unidade": morador["unidade"], "opcao": opcao, "data": agora,
    }
    try:
        db.votos.insert_one(voto)
    except DuplicateKeyError:
        raise ErroEnquete(
            f"O apartamento {morador['unidade']} (bloco {morador['bloco']}) já votou nesta enquete.", 409
        )
    return voto


def pipeline_resultado_enquete(enquete_id):
    return [
        {"$match": {"_id": enquete_id}},
        # 1) Uma linha por opção (inclusive as que ainda não têm voto)
        {"$unwind": "$opcoes"},
        # 2) Conta os votos de cada opção na coleção `votos`
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
        # 3) Total geral e colocação de cada opção, sem perder as linhas
        {"$setWindowFields": {
            "sortBy": {"votos": -1},
            "output": {
                "total_votos": {"$sum": "$votos", "window": {"documents": ["unbounded", "unbounded"]}},
                "posicao": {"$rank": {}},
            },
        }},
        {"$addFields": {
            "percentual": {"$cond": [
                {"$eq": ["$total_votos", 0]}, 0,
                {"$round": [{"$multiply": [{"$divide": ["$votos", "$total_votos"]}, 100]}, 1]},
            ]},
        }},
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


# =====================================================================
# Demonstração no terminal
# =====================================================================
def reais(valor):
    return "R$ " + f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def main():
    from conexao import conectar

    db = conectar()
    cond = db.condominios.find_one({"nome": "Residencial Jardim das Acácias"})
    print(f"Condomínio: {cond['nome']}")

    print("\n=== FUNCIONALIDADE 1: Painel de vencimentos ===")
    for grupo in painel_vencimentos(db, cond["_id"]):
        print(f"\n{grupo['_id']} ({grupo['quantidade']})")
        for i in grupo["itens"]:
            print(f"  {i['prazo']:%d/%m/%Y}  ({i['dias_restantes']:+d} dias)  {i['item']} — {i['detalhe']}")

    print("\n=== FUNCIONALIDADE 2: Gastos com manutenção (últimos 12 meses) ===")
    rel = relatorio_gastos(db, cond["_id"])
    r = rel["resumo"]
    print(f"Total: {reais(r['total'])} em {r['quantidade']} serviços "
          f"(média {reais(r['media'] or 0)}, maior {reais(r['maior'] or 0)})")
    for titulo, chave in [("Por mês", "por_mes"), ("Por prestador", "por_prestador"),
                          ("Por tipo de serviço", "por_tipo_servico"), ("Top 3 equipamentos", "top_equipamentos")]:
        print(f"\n{titulo}:")
        for linha in rel.get(chave, []):
            print(f"  {str(linha['_id']):40} {reais(linha['total']):>12}")

    print("\n=== ENQUETE: resultado parcial ===")
    enquete = db.enquetes.find_one({"condominio_id": cond["_id"], "titulo": {"$regex": "lazer"}})
    res = resultado_enquete(db, enquete["_id"])
    print(f"{res['titulo']} — {res['situacao']}, {res['total_votos']} de {res['total_apartamentos']} "
          f"apartamentos votaram ({res['participacao']}%)")
    for o in res["opcoes"]:
        barra = "█" * o["votos"]
        palavra = "voto " if o["votos"] == 1 else "votos"
        print(f"  {o['posicao']}º  {o['opcao']}) {o['descricao']:48} {o['votos']:>2} {palavra} "
              f"({o['percentual']:>5}%) {barra}")


if __name__ == "__main__":
    main()
