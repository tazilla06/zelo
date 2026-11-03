"""Zelo — consultas de exemplo no MongoDB Atlas.

Rode depois do criar_banco.py:
    python consultas.py
"""
from datetime import datetime, timedelta, timezone
from pprint import pprint

from pymongo.errors import WriteError

from conexao import conectar


def reais(valor):
    """Formata no padrão brasileiro: 3020 -> 'R$ 3.020,00'."""
    return "R$ " + f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def titulo(texto):
    print(f"\n=== {texto} ===")


def main():
    db = conectar()
    hoje = datetime.now(timezone.utc).replace(tzinfo=None)  # UTC, como o pymongo grava
    em_30_dias = hoje + timedelta(days=30)
    acacias = db.condominios.find_one({"nome": "Residencial Jardim das Acácias"})

    # 1. Filtro por tipo: todos os elevadores do condomínio
    titulo("1. Elevadores do Residencial Jardim das Acácias")
    for e in db.equipamentos.find(
        {"condominio_id": acacias["_id"], "tipo": "elevador"},
        {"_id": 0, "identificacao": 1, "local": 1, "art": 1, "capacidade_pessoas": 1},
    ):
        pprint(e)

    # 2. Campo que só existe em um tipo: extintores com recarga vencida ou vencendo
    titulo("2. Extintores com recarga vencida ou vencendo em 30 dias")
    for e in db.equipamentos.find(
        {"tipo": "extintor", "validade_recarga": {"$lte": em_30_dias}},
        {"_id": 0, "identificacao": 1, "local": 1, "classe": 1, "validade_recarga": 1},
    ).sort("validade_recarga", 1):
        print(f"  {e['identificacao']:8} {e['local']:30} classe {e['classe']:4} "
              f"recarga até {e['validade_recarga']:%d/%m/%Y}")

    # 3. Alertas: laudos vencidos ou vencendo em 30 dias, com o nome do condomínio
    titulo("3. Laudos vencidos ou vencendo em 30 dias")
    for l in db.laudos.aggregate([
        {"$match": {"validade": {"$lte": em_30_dias}}},
        {"$lookup": {"from": "condominios", "localField": "condominio_id",
                     "foreignField": "_id", "as": "cond"}},
        {"$unwind": "$cond"},
        {"$project": {
            "_id": 0, "condominio": "$cond.nome", "tipo": 1, "validade": 1,
            "situacao": {"$cond": [{"$lt": ["$validade", hoje]}, "VENCIDO", "vence em breve"]},
        }},
        {"$sort": {"validade": 1}},
    ]):
        print(f"  {l['situacao']:15} {l['validade']:%d/%m/%Y}  {l['tipo']:20} {l['condominio']}")

    # 4. Agregação no histórico embutido: custo total de manutenção por equipamento
    titulo("4. Custo total de manutenção por equipamento")
    for c in db.equipamentos.aggregate([
        {"$unwind": "$manutencoes"},
        {"$group": {
            "_id": {"identificacao": "$identificacao", "local": "$local"},
            "total_gasto": {"$sum": "$manutencoes.custo"},
            "qtd_manutencoes": {"$sum": 1},
        }},
        {"$sort": {"total_gasto": -1}},
    ]):
        print(f"  {reais(c['total_gasto']):>11}  ({c['qtd_manutencoes']}x)  "
              f"{c['_id']['identificacao']} — {c['_id']['local']}")

    # 5. Custo por condomínio e por tipo de equipamento
    titulo("5. Custo por condomínio e tipo de equipamento")
    for c in db.equipamentos.aggregate([
        {"$unwind": "$manutencoes"},
        {"$group": {"_id": {"condominio_id": "$condominio_id", "tipo": "$tipo"},
                    "total": {"$sum": "$manutencoes.custo"}}},
        {"$lookup": {"from": "condominios", "localField": "_id.condominio_id",
                     "foreignField": "_id", "as": "cond"}},
        {"$project": {"_id": 0, "condominio": {"$first": "$cond.nome"},
                      "tipo": "$_id.tipo", "total": 1}},
        {"$sort": {"condominio": 1, "total": -1}},
    ]):
        print(f"  {c['condominio']:32} {c['tipo']:13} {reais(c['total']):>11}")

    # 6. Registrar uma nova manutenção (adiciona no array embutido)
    titulo("6. Registrar manutenção na bomba e voltar o status para operacional")
    resultado = db.equipamentos.update_one(
        {"condominio_id": acacias["_id"], "identificacao": "BMB-RECALQUE-01"},
        {
            "$push": {"manutencoes": {"data": hoje, "tipo": "corretiva",
                                      "descricao": "Troca do rolamento", "custo": 390}},
            "$set": {"status": "operacional"},
        },
    )
    print(f"  documentos modificados: {resultado.modified_count}")
    pprint(db.equipamentos.find_one(
        {"identificacao": "BMB-RECALQUE-01"},
        {"_id": 0, "identificacao": 1, "status": 1, "manutencoes": 1},
    ))

    # 7. A validação do banco recusa documentos incompletos
    titulo("7. Tentando inserir um extintor SEM o campo 'classe'")
    try:
        db.equipamentos.insert_one({
            "condominio_id": acacias["_id"], "tipo": "extintor", "identificacao": "TESTE",
            "local": "Teste", "status": "operacional", "manutencoes": [],
        })
        print("  inserido (a validação não está ativa!)")
    except WriteError as erro:
        print(f"  recusado pelo MongoDB: {erro.details.get('errmsg', erro)}")


if __name__ == "__main__":
    main()
