# Zelo — Inventário e Manutenção Predial para Condomínios

Aplicação web com banco de dados NoSQL documental (**MongoDB**) para síndicos e administradoras controlarem os equipamentos do condomínio, os laudos obrigatórios e o histórico de manutenções.

> Trabalho da disciplina de Banco de Dados NoSQL.
> **Integrantes:** Gabriel e Tarsila

---

## 1. Descrição do sistema

### O problema
Síndicos precisam controlar dezenas de equipamentos (extintores, elevadores, bombas, portões, geradores, caixas d'água) e laudos com prazo de validade (AVCB, para-raios/SPDA, inspeção de elevador, potabilidade da água). Na prática esse controle fica em **planilhas soltas**, papéis e e-mails das empresas de manutenção. Com isso:

- recargas de extintor e laudos **vencem sem ninguém perceber**, o que gera multa e risco à segurança;
- o histórico de manutenção de um equipamento se perde quando troca o síndico ou a empresa;
- não há como saber **quanto se gasta** com cada equipamento.

### A solução
O **Zelo** centraliza o inventário do condomínio em um só lugar:

| Funcionalidade | O que faz |
|---|---|
| Cadastro de equipamentos | Cada tipo com seus próprios atributos (classe do extintor, ART do elevador, potência da bomba...) |
| Histórico de manutenções | Registro de preventivas, corretivas, recargas e limpezas, com custo e prestador |
| Controle de laudos | AVCB, SPDA, inspeção de elevador etc., com data de emissão e validade |
| Alertas de vencimento | Lista do que está vencido ou vence nos próximos 30 dias |
| Relatórios de custo | Gasto por equipamento, por tipo e por condomínio |

**Usuários:** síndicos, administradoras de condomínio e zeladores.

### Por que um banco NoSQL documental?
1. **Cada equipamento tem atributos diferentes.** O extintor tem `classe`, `carga_kg` e `validade_recarga`; o elevador tem `art`, `capacidade_pessoas` e empresa responsável; a bomba tem `potencia_cv` e `vazao_m3h`. Em um banco relacional seria preciso uma tabela por tipo ou uma tabela com dezenas de colunas quase sempre vazias. No MongoDB todos ficam na mesma coleção `equipamentos`, cada documento com os seus campos.
2. **Novos tipos sem alterar o schema.** Se o condomínio passar a controlar câmeras ou painéis solares, basta inserir documentos com `tipo: "outro"` e os campos necessários. Não precisa de `ALTER TABLE`.
3. **O histórico faz parte do equipamento.** As manutenções ficam **embutidas** em um array dentro do documento do equipamento. Abrir a ficha do elevador traz todo o histórico em uma única leitura, sem JOIN.
4. **Flexível, mas com regras.** A coleção usa validação `$jsonSchema`: exige os campos comuns, exige `classe` e `validade_recarga` em extintores e `art` em elevadores, e aceita campos extras nos demais tipos.

---

## 2. Modelo de dados

Banco: **`zelo`**, com 4 coleções.

```
 condominios  1 ──── N  equipamentos  (manutencoes[] embutidas)
      │                     │      └── manutencoes[].prestador_id ──► prestadores
      └──── 1 ──── N  laudos ┘ (equipamento_id opcional)
```

| Coleção | Conteúdo | Relacionamentos |
|---|---|---|
| `condominios` | Nome, CNPJ, endereço e síndico (embutidos), blocos | — |
| `prestadores` | Empresas de manutenção e os serviços que prestam | — |
| `equipamentos` | Inventário com campos variáveis por tipo e **histórico de manutenções embutido** | `condominio_id` → condominios; `manutencoes[].prestador_id` → prestadores |
| `laudos` | Laudos e certificados com validade | `condominio_id` → condominios; `equipamento_id` (opcional) → equipamentos |

### Embutir ou referenciar?

| Dado | Decisão | Motivo |
|---|---|---|
| Endereço e síndico | **Embutido** em `condominios` | Sempre lidos junto com o condomínio |
| Manutenções | **Embutidas** em `equipamentos` | Pertencem a um único equipamento e são lidas na ficha dele; o volume por equipamento é pequeno |
| Prestadores | **Referenciados** (`prestador_id`) | A mesma empresa atende vários equipamentos e condomínios; os dados dela mudam (telefone, contato) |
| Laudos | **Coleção própria** | São consultados por validade em todos os condomínios (alertas) e alguns não pertencem a um equipamento (AVCB do prédio) |

### Exemplos de documentos
Mesma coleção `equipamentos`, campos diferentes:

```js
{
  tipo: "extintor",
  identificacao: "EXT-01",
  local: "Garagem G1",
  status: "operacional",
  classe: "ABC",
  agente: "pó químico",
  carga_kg: 6,
  validade_recarga: ISODate("2026-11-28"),
  condominio_id: ObjectId("..."),
  manutencoes: [
    { data: ISODate("2025-11-28"), tipo: "recarga", descricao: "Recarga anual",
      custo: 120, prestador_id: ObjectId("...") }
  ]
}
```

```js
{
  tipo: "elevador",
  identificacao: "ELV-A-SOCIAL",
  local: "Bloco A",
  status: "operacional",
  art: "SP-2026-0451",
  capacidade_pessoas: 8,
  paradas: 12,
  empresa_responsavel_id: ObjectId("..."),
  condominio_id: ObjectId("..."),
  manutencoes: [
    { data: ISODate("2026-10-25"), tipo: "corretiva",
      descricao: "Troca do sensor da porta do 7º andar", custo: 1320,
      pecas: ["sensor de porta"], prestador_id: ObjectId("...") }
  ]
}
```

---

## 3. Estrutura do repositório

```
zelo/
├── README.md          ← descrição do sistema e modelo de dados
├── requirements.txt   ← dependência: pymongo
├── conexao.py         ← conexão com o MongoDB Atlas (lê a string de conexão, sem senha no código)
├── criar_banco.py     ← cria o banco, as coleções (com validação), os índices e os documentos de exemplo
└── consultas.py       ← consultas de exemplo: filtros, alertas de vencimento, agregações, update e validação
```

Os scripts são em **Python** com a biblioteca **pymongo**. O `criar_banco.py` insere dados fictícios: **2 condomínios, 3 prestadores, 9 equipamentos de 6 tipos e 5 laudos**. As datas são calculadas a partir do dia da execução, então sempre há itens vencidos e vencendo para demonstrar os alertas.

---

## 4. Como executar no MongoDB Atlas (online)

1. Crie uma conta gratuita em <https://www.mongodb.com/cloud/atlas> e crie um **cluster gratuito (M0)**.
2. Em **Database Access**, crie um usuário e uma senha para o banco.
3. Em **Network Access**, libere o seu IP (para o trabalho, pode liberar `0.0.0.0/0`).
4. No cluster, clique em **Connect → Drivers → Python** e copie a string de conexão (`mongodb+srv://usuario:<password>@...`), trocando `<password>` pela senha do usuário.
5. Instale o [Python](https://www.python.org/downloads/) e, na pasta do repositório, rode:

   ```bash
   pip install -r requirements.txt
   python criar_banco.py
   python consultas.py
   ```

   Os scripts pedem a string de conexão ao rodar. Para não precisar colar toda vez, defina a variável de ambiente `MONGODB_URI`:

   ```bash
   # Windows (PowerShell)
   $env:MONGODB_URI = "mongodb+srv://usuario:senha@cluster0.xxxxx.mongodb.net/"
   # Linux / macOS
   export MONGODB_URI="mongodb+srv://usuario:senha@cluster0.xxxxx.mongodb.net/"
   ```

6. Confira o resultado no Atlas, em **Data Explorer**. O banco `zelo` deve aparecer com as 4 coleções.

> **Nunca coloque a senha no código nem no GitHub.** Por isso a conexão fica na variável `MONGODB_URI`.
> O `criar_banco.py` apaga e recria **somente** o banco `zelo`, então pode ser executado várias vezes.
> O `consultas.py` registra uma manutenção nova (exemplo de `$push`); rodar de novo adiciona outra.

### Consultas incluídas em `consultas.py`

1. Elevadores de um condomínio (filtro por tipo)
2. Extintores com recarga vencida ou vencendo, usando um campo que só existe nesse tipo
3. Laudos vencidos ou vencendo em 30 dias, com o nome do condomínio (`$lookup`)
4. Custo total de manutenção por equipamento (`$unwind` + `$group` no array embutido)
5. Custo por condomínio e tipo de equipamento
6. Registro de uma nova manutenção (`$push`) e atualização de status (`$set`)
7. Tentativa de inserir um extintor sem `classe`, recusada pela validação do banco
