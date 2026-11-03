"""Zelo — Inventário e Manutenção Predial para Condomínios

Cria no MongoDB Atlas o banco "zelo", as coleções (com validação),
os índices e insere documentos de exemplo.

Como rodar:
    pip install -r requirements.txt
    python criar_banco.py

ATENÇÃO: apaga e recria APENAS o banco "zelo", para que possa ser
executado várias vezes sem duplicar dados.
"""
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from pymongo import ASCENDING

from conexao import conectar


def dias(n):
    """Data a n dias de hoje (negativo = passado). Assim os alertas de
    vencimento sempre têm exemplos, em qualquer dia que o script rodar."""
    # datas em UTC "sem fuso" (padrão do pymongo, que as grava como UTC)
    hoje = datetime.now(timezone.utc).replace(tzinfo=None, hour=0, minute=0, second=0, microsecond=0)
    return hoje + timedelta(days=n)


# ---------------------------------------------------------------------
# 1. REGRAS DE VALIDAÇÃO ($jsonSchema)
#    Exigem só os campos comuns. Campos extras são aceitos, e é isso que
#    permite cada tipo de equipamento ter atributos próprios.
# ---------------------------------------------------------------------
VALIDACAO = {
    "condominios": {
        "bsonType": "object",
        "required": ["nome", "endereco", "sindico"],
        "properties": {
            "nome": {"bsonType": "string"},
            "cnpj": {"bsonType": "string"},
            "endereco": {
                "bsonType": "object",
                "required": ["logradouro", "cidade", "uf"],
                "properties": {
                    "logradouro": {"bsonType": "string"},
                    "cidade": {"bsonType": "string"},
                    "uf": {"bsonType": "string", "minLength": 2, "maxLength": 2},
                },
            },
            "sindico": {
                "bsonType": "object",
                "required": ["nome", "email"],
                "properties": {
                    "nome": {"bsonType": "string"},
                    "email": {"bsonType": "string"},
                },
            },
            "blocos": {"bsonType": "array", "items": {"bsonType": "string"}},
        },
    },
    "prestadores": {
        "bsonType": "object",
        "required": ["nome", "servicos"],
        "properties": {
            "nome": {"bsonType": "string"},
            "cnpj": {"bsonType": "string"},
            "servicos": {"bsonType": "array", "minItems": 1, "items": {"bsonType": "string"}},
        },
    },
    # Regras extras para os tipos com campos obrigatórios por norma.
    # Os demais tipos (bomba, portão, gerador...) ficam livres.
    "equipamentos": {
        "bsonType": "object",
        "required": ["condominio_id", "tipo", "identificacao", "local", "status", "manutencoes"],
        "properties": {
            "condominio_id": {"bsonType": "objectId"},
            "tipo": {"enum": ["extintor", "elevador", "bomba", "portao", "gerador", "reservatorio", "outro"]},
            "identificacao": {"bsonType": "string"},
            "local": {"bsonType": "string"},
            "status": {"enum": ["operacional", "em_manutencao", "inoperante"]},
            "proxima_manutencao": {"bsonType": "date"},
            "manutencoes": {
                "bsonType": "array",
                "items": {
                    "bsonType": "object",
                    "required": ["data", "tipo", "descricao"],
                    "properties": {
                        "data": {"bsonType": "date"},
                        "tipo": {"enum": ["preventiva", "corretiva", "recarga", "inspecao", "limpeza"]},
                        "descricao": {"bsonType": "string"},
                        "custo": {"bsonType": ["double", "int", "long"], "minimum": 0},
                        "prestador_id": {"bsonType": "objectId"},
                    },
                },
            },
        },
        "anyOf": [
            {"properties": {"tipo": {"enum": ["extintor"]}},
             "required": ["classe", "carga_kg", "validade_recarga"]},
            {"properties": {"tipo": {"enum": ["elevador"]}},
             "required": ["empresa_responsavel_id", "art", "capacidade_pessoas"]},
            {"properties": {"tipo": {"enum": ["bomba", "portao", "gerador", "reservatorio", "outro"]}}},
        ],
    },
    "laudos": {
        "bsonType": "object",
        "required": ["condominio_id", "tipo", "numero", "data_emissao", "validade"],
        "properties": {
            "condominio_id": {"bsonType": "objectId"},
            "equipamento_id": {"bsonType": "objectId"},
            "tipo": {"bsonType": "string"},
            "numero": {"bsonType": "string"},
            "emissor": {"bsonType": "string"},
            "data_emissao": {"bsonType": "date"},
            "validade": {"bsonType": "date"},
            "arquivo_url": {"bsonType": "string"},
        },
    },
}

# ---------------------------------------------------------------------
# 2. ÍNDICES (para as consultas mais frequentes do sistema)
# ---------------------------------------------------------------------
INDICES = {
    "condominios": [([("cnpj", ASCENDING)], {"unique": True})],
    "prestadores": [([("servicos", ASCENDING)], {})],
    "equipamentos": [
        ([("condominio_id", ASCENDING), ("tipo", ASCENDING)], {}),
        ([("proxima_manutencao", ASCENDING)], {}),
    ],
    "laudos": [
        ([("validade", ASCENDING)], {}),
        ([("condominio_id", ASCENDING), ("tipo", ASCENDING)], {}),
    ],
}


# ---------------------------------------------------------------------
# 3. DOCUMENTOS DE EXEMPLO (dados fictícios)
# ---------------------------------------------------------------------
def documentos_exemplo():
    acacias, monte_azul = ObjectId(), ObjectId()
    elevar, fogo_zero, hidro = ObjectId(), ObjectId(), ObjectId()
    elev_social_a, elev_monte_azul = ObjectId(), ObjectId()

    condominios = [
        {
            "_id": acacias,
            "nome": "Residencial Jardim das Acácias",
            "cnpj": "11.222.333/0001-44",
            "endereco": {"logradouro": "Rua das Acácias, 120", "bairro": "Vila Mariana",
                         "cidade": "São Paulo", "uf": "SP"},
            "sindico": {"nome": "Marina Souza", "email": "sindico@acacias.exemplo",
                        "telefone": "(11) 90000-0001"},
            "blocos": ["A", "B"],
            "unidades": 64,
        },
        {
            "_id": monte_azul,
            "nome": "Edifício Monte Azul",
            "cnpj": "55.666.777/0001-88",
            "endereco": {"logradouro": "Av. Brasil, 2450", "cidade": "Campinas", "uf": "SP"},
            "sindico": {"nome": "Carlos Lima", "email": "sindico@monteazul.exemplo"},
            "blocos": ["Único"],
            "unidades": 30,
        },
    ]

    prestadores = [
        {"_id": elevar, "nome": "Elevar Manutenção de Elevadores", "cnpj": "22.333.444/0001-55",
         "servicos": ["elevador"],
         "contato": {"telefone": "(11) 4000-1000", "email": "contato@elevar.exemplo"}},
        {"_id": fogo_zero, "nome": "FogoZero Extintores", "cnpj": "33.444.555/0001-66",
         "servicos": ["extintor", "laudo_avcb"], "contato": {"telefone": "(11) 4000-2000"}},
        {"_id": hidro, "nome": "HidroServ Bombas e Reservatórios", "cnpj": "44.555.666/0001-77",
         "servicos": ["bomba", "reservatorio"], "contato": {"email": "atendimento@hidroserv.exemplo"}},
    ]

    equipamentos = [
        # ----- Residencial Jardim das Acácias -----
        {
            "condominio_id": acacias, "tipo": "extintor", "identificacao": "EXT-01",
            "local": "Garagem G1", "status": "operacional",
            "classe": "ABC", "agente": "pó químico", "carga_kg": 6,
            "validade_recarga": dias(25), "proxima_manutencao": dias(25),
            "manutencoes": [
                {"data": dias(-340), "tipo": "recarga", "descricao": "Recarga anual",
                 "custo": 120, "prestador_id": fogo_zero},
            ],
        },
        {
            "condominio_id": acacias, "tipo": "extintor", "identificacao": "EXT-02",
            "local": "Casa de máquinas — Bloco A", "status": "operacional",
            "classe": "BC", "agente": "CO2", "carga_kg": 6,
            "validade_recarga": dias(-5),  # já vencido: deve aparecer nos alertas
            "proxima_manutencao": dias(-5),
            "manutencoes": [
                {"data": dias(-370), "tipo": "recarga", "descricao": "Recarga anual",
                 "custo": 150, "prestador_id": fogo_zero},
            ],
        },
        {
            "_id": elev_social_a,
            "condominio_id": acacias, "tipo": "elevador", "identificacao": "ELV-A-SOCIAL",
            "local": "Bloco A", "status": "operacional",
            "fabricante": "ElevaTech", "empresa_responsavel_id": elevar,
            "art": "SP-2026-0451", "capacidade_pessoas": 8, "paradas": 12,
            "proxima_manutencao": dias(12),
            "manutencoes": [
                {"data": dias(-48), "tipo": "preventiva", "descricao": "Manutenção mensal",
                 "custo": 850, "prestador_id": elevar},
                {"data": dias(-18), "tipo": "preventiva", "descricao": "Manutenção mensal",
                 "custo": 850, "prestador_id": elevar},
                {"data": dias(-9), "tipo": "corretiva", "descricao": "Troca do sensor da porta do 7º andar",
                 "custo": 1320, "prestador_id": elevar, "pecas": ["sensor de porta"]},
            ],
        },
        {
            "condominio_id": acacias, "tipo": "bomba", "identificacao": "BMB-RECALQUE-01",
            "local": "Subsolo", "status": "em_manutencao",
            "funcao": "recalque", "potencia_cv": 3, "vazao_m3h": 12,
            "proxima_manutencao": dias(3),
            "manutencoes": [
                {"data": dias(-2), "tipo": "corretiva", "descricao": "Ruído excessivo — rolamento em análise",
                 "custo": 480, "prestador_id": hidro},
            ],
        },
        {
            "condominio_id": acacias, "tipo": "portao", "identificacao": "PRT-GARAGEM",
            "local": "Entrada da garagem", "status": "operacional",
            "acionamento": "motor deslizante", "controles_cadastrados": 58,
            "proxima_manutencao": dias(60),
            "manutencoes": [],
        },
        {
            "condominio_id": acacias, "tipo": "gerador", "identificacao": "GER-01",
            "local": "Área técnica", "status": "operacional",
            "potencia_kva": 80, "combustivel": "diesel", "autonomia_horas": 6,
            "proxima_manutencao": dias(40),
            "manutencoes": [
                {"data": dias(-140), "tipo": "preventiva", "descricao": "Troca de óleo e filtros", "custo": 1100},
            ],
        },
        # ----- Edifício Monte Azul -----
        {
            "_id": elev_monte_azul,
            "condominio_id": monte_azul, "tipo": "elevador", "identificacao": "ELV-01",
            "local": "Hall principal", "status": "operacional",
            "empresa_responsavel_id": elevar, "art": "SP-2026-0987",
            "capacidade_pessoas": 6, "paradas": 8,
            "proxima_manutencao": dias(20),
            "manutencoes": [
                {"data": dias(-10), "tipo": "preventiva", "descricao": "Manutenção mensal",
                 "custo": 700, "prestador_id": elevar},
            ],
        },
        {
            "condominio_id": monte_azul, "tipo": "extintor", "identificacao": "EXT-01",
            "local": "Hall do térreo", "status": "operacional",
            "classe": "A", "agente": "água pressurizada", "carga_kg": 10,
            "validade_recarga": dias(200), "proxima_manutencao": dias(200),
            "manutencoes": [
                {"data": dias(-165), "tipo": "recarga", "descricao": "Recarga anual",
                 "custo": 90, "prestador_id": fogo_zero},
            ],
        },
        {
            "condominio_id": monte_azul, "tipo": "reservatorio", "identificacao": "CX-SUPERIOR",
            "local": "Cobertura", "status": "operacional",
            "capacidade_litros": 20000, "periodicidade_limpeza_meses": 6,
            "proxima_manutencao": dias(15),
            "manutencoes": [
                {"data": dias(-165), "tipo": "limpeza", "descricao": "Limpeza e desinfecção semestral",
                 "custo": 650, "prestador_id": hidro},
            ],
        },
    ]

    laudos = [
        {"condominio_id": acacias, "tipo": "AVCB", "numero": "AVCB-2023-778899",
         "emissor": "Corpo de Bombeiros", "data_emissao": dias(-1075), "validade": dias(20),
         "arquivo_url": "https://exemplo.com/laudos/avcb-acacias.pdf"},
        {"condominio_id": acacias, "tipo": "SPDA (para-raios)", "numero": "SPDA-2025-0102",
         "emissor": "Eng. Paula Reis — CREA 123456", "data_emissao": dias(-375), "validade": dias(-10)},
        {"condominio_id": acacias, "equipamento_id": elev_social_a, "tipo": "Inspeção anual de elevador",
         "numero": "RIA-2026-0451", "emissor": "Elevar Manutenção de Elevadores",
         "data_emissao": dias(-200), "validade": dias(165)},
        {"condominio_id": monte_azul, "tipo": "AVCB", "numero": "AVCB-2024-112233",
         "emissor": "Corpo de Bombeiros", "data_emissao": dias(-600), "validade": dias(495)},
        {"condominio_id": monte_azul, "tipo": "Potabilidade da água", "numero": "LAB-2026-5521",
         "emissor": "Laboratório AquaTeste", "data_emissao": dias(-165), "validade": dias(15)},
    ]

    return {
        "condominios": condominios,
        "prestadores": prestadores,
        "equipamentos": equipamentos,
        "laudos": laudos,
    }


def main():
    db = conectar()
    db.client.drop_database(db.name)

    for nome, schema in VALIDACAO.items():
        db.create_collection(nome, validator={"$jsonSchema": schema})

    for nome, indices in INDICES.items():
        for chaves, opcoes in indices:
            db[nome].create_index(chaves, **opcoes)

    for nome, docs in documentos_exemplo().items():
        db[nome].insert_many(docs)

    print(f"Banco '{db.name}' criado com sucesso:")
    for nome in VALIDACAO:
        print(f"  - {nome}: {db[nome].count_documents({})} documento(s)")


if __name__ == "__main__":
    main()
