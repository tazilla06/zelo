# Cria o banco "zelo" no Atlas: coleções, regras de validação, índices e dados de exemplo.
# Rodar da pasta do projeto:  python database/criar_banco.py
# Obs: ele apaga o banco zelo antes de criar de novo, então pode rodar quantas vezes quiser.
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from pymongo import ASCENDING

from conexao import conectar


# as datas dos exemplos são contadas a partir de hoje (dias(-5) = 5 dias atrás),
# assim sempre tem coisa vencida e vencendo pra mostrar, não importa o dia que rodar
def dias(n):
    hoje = datetime.now(timezone.utc).replace(tzinfo=None, hour=0, minute=0, second=0, microsecond=0)
    return hoje + timedelta(days=n)


# Regras de validação ($jsonSchema) de cada coleção.
# Só os campos comuns são obrigatórios, o resto é livre. É isso que deixa
# cada tipo de equipamento ter os seus próprios campos.
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
    # extintor e elevador têm campos que a norma exige, os outros tipos ficam livres
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
    # coleções da enquete
    "moradores": {
        "bsonType": "object",
        "required": ["condominio_id", "nome", "bloco", "unidade", "codigo_acesso"],
        "properties": {
            "condominio_id": {"bsonType": "objectId"},
            "nome": {"bsonType": "string"},
            "bloco": {"bsonType": "string"},
            "unidade": {"bsonType": "string"},
            "codigo_acesso": {"bsonType": "string", "minLength": 4},
            "perfil": {"enum": ["proprietario", "inquilino"]},
        },
    },
    "enquetes": {
        "bsonType": "object",
        "required": ["condominio_id", "titulo", "opcoes", "abertura", "encerramento"],
        "properties": {
            "condominio_id": {"bsonType": "objectId"},
            "titulo": {"bsonType": "string"},
            "descricao": {"bsonType": "string"},
            "opcoes": {
                "bsonType": "array",
                "minItems": 2,
                "items": {
                    "bsonType": "object",
                    "required": ["codigo", "descricao"],
                    "properties": {
                        "codigo": {"bsonType": "string"},
                        "descricao": {"bsonType": "string"},
                        "valor_estimado": {"bsonType": ["double", "int", "long"], "minimum": 0},
                    },
                },
            },
            "abertura": {"bsonType": "date"},
            "encerramento": {"bsonType": "date"},
        },
    },
    "votos": {
        "bsonType": "object",
        "required": ["enquete_id", "morador_id", "condominio_id", "bloco", "unidade", "opcao", "data"],
        "properties": {
            "enquete_id": {"bsonType": "objectId"},
            "morador_id": {"bsonType": "objectId"},
            "condominio_id": {"bsonType": "objectId"},
            "bloco": {"bsonType": "string"},
            "unidade": {"bsonType": "string"},
            "opcao": {"bsonType": "string"},
            "data": {"bsonType": "date"},
        },
    },
}

# Índices das buscas mais usadas
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
    "moradores": [([("codigo_acesso", ASCENDING)], {"unique": True})],
    "enquetes": [([("condominio_id", ASCENDING), ("encerramento", ASCENDING)], {})],
    # índice único: cada apartamento só vota uma vez por enquete (o próprio banco recusa o segundo voto)
    "votos": [([("enquete_id", ASCENDING), ("bloco", ASCENDING), ("unidade", ASCENDING)], {"unique": True})],
}


# Dados de exemplo (tudo inventado)
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
        # Residencial Jardim das Acácias
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
            "local": "Casa de máquinas do bloco A", "status": "operacional",
            "classe": "BC", "agente": "CO2", "carga_kg": 6,
            "validade_recarga": dias(-5),  # vencido de propósito, pra aparecer no painel
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
                {"data": dias(-2), "tipo": "corretiva", "descricao": "Barulho alto, rolamento em análise",
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
        # Edifício Monte Azul
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
         "emissor": "Eng. Paula Reis (CREA 123456)", "data_emissao": dias(-375), "validade": dias(-10)},
        {"condominio_id": acacias, "equipamento_id": elev_social_a, "tipo": "Inspeção anual de elevador",
         "numero": "RIA-2026-0451", "emissor": "Elevar Manutenção de Elevadores",
         "data_emissao": dias(-200), "validade": dias(165)},
        {"condominio_id": monte_azul, "tipo": "AVCB", "numero": "AVCB-2024-112233",
         "emissor": "Corpo de Bombeiros", "data_emissao": dias(-600), "validade": dias(495)},
        {"condominio_id": monte_azul, "tipo": "Potabilidade da água", "numero": "LAB-2026-5521",
         "emissor": "Laboratório AquaTeste", "data_emissao": dias(-165), "validade": dias(15)},
    ]

    # moradores: um por apartamento. O código de acesso é o que o síndico entrega pra cada apartamento votar
    nomes = ["Ana Ribeiro", "Bruno Costa", "Carla Nunes", "Diego Alves", "Elisa Rocha", "Fábio Lima",
             "Gabriela Melo", "Henrique Dias", "Isabela Torres", "João Pires", "Karina Lopes", "Lucas Freitas",
             "Mariana Gomes", "Nicolas Prado", "Olívia Santos", "Paulo Teixeira", "Rafaela Cunha",
             "Sérgio Martins", "Tatiane Barros", "Vítor Araújo", "Yasmin Moura", "Wagner Reis"]
    unidades_acacias = [(b, f"{andar}0{apto}") for b in ("A", "B") for andar in (1, 2) for apto in (1, 2, 3, 4)]
    unidades_monte_azul = [("Único", f"{andar}{apto}") for andar in (1, 2, 3) for apto in (1, 2)]

    moradores = []
    for i, (bloco, unidade) in enumerate(unidades_acacias):
        moradores.append({"_id": ObjectId(), "condominio_id": acacias, "nome": nomes[i],
                          "bloco": bloco, "unidade": unidade, "codigo_acesso": f"ACA-{bloco}{unidade}",
                          "perfil": "inquilino" if i % 4 == 3 else "proprietario"})
    for i, (bloco, unidade) in enumerate(unidades_monte_azul):
        moradores.append({"_id": ObjectId(), "condominio_id": monte_azul, "nome": nomes[16 + i],
                          "bloco": bloco, "unidade": unidade, "codigo_acesso": f"MAZ-{unidade}",
                          "perfil": "proprietario"})

    # enquetes
    enq_lazer, enq_cameras, enq_interfone = ObjectId(), ObjectId(), ObjectId()
    enquetes = [
        {
            "_id": enq_lazer, "condominio_id": acacias,
            "titulo": "O que comprar para a área de lazer?",
            "descricao": "Temos R$ 7.000 no fundo de melhorias. Escolha uma opção (1 voto por apartamento).",
            "opcoes": [
                {"codigo": "A", "descricao": "Churrasqueira elétrica nova", "valor_estimado": 4500},
                {"codigo": "B", "descricao": "Esteira para a academia", "valor_estimado": 6800},
                {"codigo": "C", "descricao": "Brinquedos novos para o playground", "valor_estimado": 3200},
                {"codigo": "D", "descricao": "Não comprar agora e manter no fundo de reserva", "valor_estimado": 0},
            ],
            "abertura": dias(-5), "encerramento": dias(10), "criada_por": "Síndica Marina Souza",
        },
        {
            "_id": enq_cameras, "condominio_id": acacias,
            "titulo": "Instalar câmeras na garagem?",
            "descricao": "Orçamento aprovado em assembleia, falta a decisão dos moradores.",
            "opcoes": [
                {"codigo": "A", "descricao": "Sim, 8 câmeras com gravação em nuvem", "valor_estimado": 5200},
                {"codigo": "B", "descricao": "Não, manter como está", "valor_estimado": 0},
            ],
            "abertura": dias(-60), "encerramento": dias(-30), "criada_por": "Síndica Marina Souza",
        },
        {
            "_id": enq_interfone, "condominio_id": monte_azul,
            "titulo": "Troca do interfone",
            "descricao": "O interfone atual será substituído. Qual modelo você prefere?",
            "opcoes": [
                {"codigo": "A", "descricao": "Interfone por aplicativo no celular", "valor_estimado": 3900},
                {"codigo": "B", "descricao": "Interfone tradicional novo", "valor_estimado": 2600},
            ],
            "abertura": dias(-3), "encerramento": dias(12), "criada_por": "Síndico Carlos Lima",
        },
    ]

    # votos que já foram feitos
    def votos_de(enquete_id, condominio_id, escolhas, dia_do_voto):
        lista = [m for m in moradores if m["condominio_id"] == condominio_id]
        return [
            {"enquete_id": enquete_id, "morador_id": m["_id"], "condominio_id": condominio_id,
             "bloco": m["bloco"], "unidade": m["unidade"], "opcao": opcao, "data": dias(dia_do_voto)}
            for m, opcao in zip(lista, escolhas)
        ]

    votos = (
        # área de lazer: 11 dos 16 apartamentos votaram (ainda aberta)
        votos_de(enq_lazer, acacias, list("AABACBADBCA"), -2)
        # câmeras: 13 dos 16 votaram (já encerrada)
        + votos_de(enq_cameras, acacias, list("AABAAABABAAAB"), -45)
        # interfone: 4 dos 6 votaram (ainda aberta)
        + votos_de(enq_interfone, monte_azul, list("AABA"), -1)
    )

    return {
        "condominios": condominios,
        "prestadores": prestadores,
        "equipamentos": equipamentos,
        "laudos": laudos,
        "moradores": moradores,
        "enquetes": enquetes,
        "votos": votos,
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
