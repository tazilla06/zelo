# Zelo — Inventário e Manutenção Predial para Condomínios

Aplicação web com banco de dados NoSQL documental (**MongoDB**) para síndicos e administradoras controlarem os equipamentos do condomínio, os laudos obrigatórios e o histórico de manutenções, e para os moradores votarem em enquetes sobre compras do condomínio.

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
| Relatórios de custo | Gasto por mês, por prestador, por tipo de serviço e por equipamento |
| Enquetes de compras | O síndico cria a enquete, cada apartamento vota uma vez e todos acompanham o resultado |

**Usuários:** síndicos, administradoras de condomínio, zeladores e moradores.

### Por que um banco NoSQL documental?
1. **Cada equipamento tem atributos diferentes.** O extintor tem `classe`, `carga_kg` e `validade_recarga`; o elevador tem `art`, `capacidade_pessoas` e empresa responsável; a bomba tem `potencia_cv` e `vazao_m3h`. Em um banco relacional seria preciso uma tabela por tipo ou uma tabela com dezenas de colunas quase sempre vazias. No MongoDB todos ficam na mesma coleção `equipamentos`, cada documento com os seus campos.
2. **Novos tipos sem alterar o schema.** Se o condomínio passar a controlar câmeras ou painéis solares, basta inserir documentos com `tipo: "outro"` e os campos necessários. Não precisa de `ALTER TABLE`.
3. **O histórico faz parte do equipamento.** As manutenções ficam **embutidas** em um array dentro do documento do equipamento. Abrir a ficha do elevador traz todo o histórico em uma única leitura, sem JOIN.
4. **Flexível, mas com regras.** A coleção usa validação `$jsonSchema`: exige os campos comuns, exige `classe` e `validade_recarga` em extintores e `art` em elevadores, e aceita campos extras nos demais tipos.

---

## 2. Modelo de dados

Banco: **`zelo`**, com 7 coleções.

```
 condominios  1 ──── N  equipamentos  (manutencoes[] embutidas)
      │                     │      └── manutencoes[].prestador_id ──► prestadores
      ├──── 1 ──── N  laudos ┘ (equipamento_id opcional)
      │
      ├──── 1 ──── N  moradores ───────────┐
      └──── 1 ──── N  enquetes (opcoes[] embutidas)
                          └──── 1 ──── N  votos (1 por apartamento) ◄┘
```

| Coleção | Conteúdo | Relacionamentos |
|---|---|---|
| `condominios` | Nome, CNPJ, endereço e síndico (embutidos), blocos | — |
| `prestadores` | Empresas de manutenção e os serviços que prestam | — |
| `equipamentos` | Inventário com campos variáveis por tipo e **histórico de manutenções embutido** | `condominio_id` → condominios; `manutencoes[].prestador_id` → prestadores |
| `laudos` | Laudos e certificados com validade | `condominio_id` → condominios; `equipamento_id` (opcional) → equipamentos |
| `moradores` | Um morador por apartamento, com o **código de acesso** usado para votar | `condominio_id` → condominios |
| `enquetes` | Pergunta, prazo de votação e **opções embutidas** (com valor estimado) | `condominio_id` → condominios |
| `votos` | Um documento por voto: apartamento, opção e data | `enquete_id` → enquetes; `morador_id` → moradores |

### Embutir ou referenciar?

| Dado | Decisão | Motivo |
|---|---|---|
| Endereço e síndico | **Embutido** em `condominios` | Sempre lidos junto com o condomínio |
| Manutenções | **Embutidas** em `equipamentos` | Pertencem a um único equipamento e são lidas na ficha dele; o volume por equipamento é pequeno |
| Prestadores | **Referenciados** (`prestador_id`) | A mesma empresa atende vários equipamentos e condomínios; os dados dela mudam (telefone, contato) |
| Laudos | **Coleção própria** | São consultados por validade em todos os condomínios (alertas) e alguns não pertencem a um equipamento (AVCB do prédio) |
| Opções da enquete | **Embutidas** em `enquetes` | São poucas, fixas e sempre exibidas junto com a pergunta |
| Votos | **Coleção própria** (não embutidos na enquete) | Crescem com o número de apartamentos, chegam ao mesmo tempo e precisam de um **índice único** `(enquete_id, bloco, unidade)` que garante 1 voto por apartamento direto no banco |

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
├── README.md            ← descrição do sistema e modelo de dados
├── requirements.txt     ← bibliotecas: pymongo, fastapi, uvicorn, streamlit, requests
├── conexao.py           ← conexão com o MongoDB Atlas (sem senha no código)
├── criar_banco.py       ← cria o banco, as 7 coleções (com validação), os índices e os documentos de exemplo
├── consultas.py         ← consultas básicas: filtros, alertas, agregações simples, update e validação
├── funcionalidades.py   ← as 2 funcionalidades (pipelines) + regras da enquete
├── api.py               ← backend (FastAPI): rotas para as funcionalidades e para votar
└── app.py               ← tela (Streamlit): enquetes, vencimentos, gastos e criação de enquete
```

O `criar_banco.py` insere dados fictícios: **2 condomínios, 3 prestadores, 9 equipamentos de 6 tipos, 5 laudos, 22 moradores, 3 enquetes e 28 votos**. As datas são calculadas a partir do dia da execução, então sempre há itens vencidos, vencendo e enquetes abertas para demonstrar.

---

## 4. Funcionalidades (pipelines de agregação)

As duas funcionalidades usam pipelines **com estruturas bem diferentes**: a primeira **junta duas coleções** numa linha do tempo; a segunda **desmonta um array embutido** e calcula **vários relatórios numa única consulta**.

### Funcionalidade 1 — Painel de vencimentos
**Pergunta que responde:** "o que o síndico precisa resolver, e com que urgência?"
Junta os prazos dos **equipamentos** (próxima manutenção/recarga) com a validade dos **laudos**, calcula quantos dias faltam e agrupa por urgência: *Vencido*, *Vence nesta semana*, *Vence neste mês* e *Em dia*.

| Etapa | O que faz |
|---|---|
| `$match` | Filtra os equipamentos do condomínio |
| `$project` | Padroniza os campos: origem, item, detalhe, prazo |
| **`$unionWith`** | **Traz os laudos** (outra coleção) para o mesmo resultado, com os mesmos campos |
| **`$dateDiff`** | Calcula os dias restantes até o prazo (negativo = vencido) |
| **`$switch`** | Classifica a urgência a partir dos dias restantes |
| `$sort` + `$group` + `$push` | Agrupa por urgência, com os itens em ordem de prazo |

### Funcionalidade 2 — Relatório de gastos com manutenção
**Pergunta que responde:** "para onde foi o dinheiro da manutenção?"
Abre o histórico de manutenções embutido em cada equipamento e devolve, de uma vez, o resumo geral e os gastos por mês, por prestador, por tipo de serviço e os 3 equipamentos que mais custaram.

| Etapa | O que faz |
|---|---|
| `$match` | Filtra os equipamentos do condomínio |
| **`$unwind`** | Transforma **cada manutenção do array** em um documento separado |
| `$match` | Mantém só o período escolhido (ex.: últimos 12 meses) |
| **`$lookup`** | Busca o **nome do prestador** na coleção `prestadores` |
| `$project` + **`$dateToString`** | Monta o mês (`2026-11`) e trata manutenções sem prestador |
| **`$facet`** | Roda **5 sub-pipelines em paralelo**: resumo, por mês, por prestador, por tipo de serviço e top 3 equipamentos |

### Diferença entre os dois pipelines

| | Painel de vencimentos | Relatório de gastos |
|---|---|---|
| Como combina dados | `$unionWith`: **soma linhas** de 2 coleções | `$lookup`: **completa cada linha** com dados de outra coleção |
| Trata arrays embutidos? | Não | Sim, `$unwind` em `manutencoes` |
| Cálculo principal | Datas: `$dateDiff` + `$switch` | Valores: `$sum`, `$avg`, `$max` |
| Formato da saída | Uma lista por urgência | Um documento com 5 relatórios (`$facet`) |

---

## 5. Enquete de compras para os moradores

O síndico cria uma enquete (por exemplo, "O que comprar para a área de lazer?") com as opções e o valor estimado de cada uma. Cada apartamento vota usando o **código de acesso** que recebe do síndico (ex.: `ACA-A101`), e todos acompanham o resultado.

**Regras garantidas pelo sistema:**
- só vota quem tem um código de acesso válido **do mesmo condomínio** da enquete;
- só é possível votar enquanto a enquete está **aberta** (entre a abertura e o encerramento);
- **1 voto por apartamento**: garantido pelo **índice único** `(enquete_id, bloco, unidade)` na coleção `votos`. Se o apartamento tentar votar de novo, o próprio MongoDB recusa;
- o resultado mostra só os totais, nunca em quem cada apartamento votou.

**Pipeline do resultado:** `$match` → `$unwind` das opções → `$lookup` com **sub-pipeline** (`let` + `$expr` + `$count`) para contar os votos de cada opção, inclusive as que ainda não têm voto → **`$setWindowFields`** para calcular o total geral e a colocação (`$rank`) sem perder as linhas → percentual de cada opção.

---

## 6. Como executar

### 6.1 Preparar o MongoDB Atlas (online)
1. Crie uma conta gratuita em <https://www.mongodb.com/cloud/atlas> e crie um **cluster gratuito (M0)**.
2. Em **Database Access**, crie um usuário e uma senha para o banco.
3. Em **Network Access**, libere o seu IP (para o trabalho, pode liberar `0.0.0.0/0`).
4. No cluster, clique em **Connect → Drivers → Python** e copie a string de conexão (`mongodb+srv://usuario:<password>@...`), trocando `<password>` pela senha do usuário.

### 6.2 Instalar e criar o banco
Instale o [Python](https://www.python.org/downloads/) e, na pasta do repositório, rode:

```bash
pip install -r requirements.txt
python criar_banco.py          # cria o banco com os dados de exemplo
python consultas.py            # consultas básicas
python funcionalidades.py      # as 2 funcionalidades e o resultado da enquete, no terminal
```

Os scripts pedem a string de conexão ao rodar. Para não precisar colar toda vez, defina a variável de ambiente `MONGODB_URI` antes:

```bash
# Windows (PowerShell)
$env:MONGODB_URI = "mongodb+srv://usuario:senha@cluster0.xxxxx.mongodb.net/"
# Linux / macOS
export MONGODB_URI="mongodb+srv://usuario:senha@cluster0.xxxxx.mongodb.net/"
```

### 6.3 Abrir o sistema (API + tela)
Em um terminal, suba a API:

```bash
uvicorn api:app --reload
```

Em **outro terminal** (com a mesma `MONGODB_URI`), abra a tela:

```bash
streamlit run app.py
```

A tela abre no navegador com 4 abas: **Enquetes de compras** (o morador vota), **Vencimentos** (funcionalidade 1), **Gastos com manutenção** (funcionalidade 2) e **Nova enquete** (o síndico cria). Para testar o voto, use um código de exemplo, como `ACA-B203` (Residencial Jardim das Acácias) ou `MAZ-31` (Edifício Monte Azul).

A API também tem uma página de testes automática em <http://localhost:8000/docs>.

| Rota | O que faz |
|---|---|
| `GET /condominios` | Lista os condomínios |
| `GET /condominios/{id}/vencimentos` | Funcionalidade 1 |
| `GET /condominios/{id}/gastos?meses=12` | Funcionalidade 2 |
| `GET /condominios/{id}/enquetes` | Lista as enquetes e a situação de cada uma |
| `POST /condominios/{id}/enquetes` | Síndico cria uma enquete |
| `POST /enquetes/{id}/votos` | Morador vota (`codigo_acesso` + `opcao`) |
| `GET /enquetes/{id}/resultado` | Resultado da enquete |

> **Nunca coloque a senha no código nem no GitHub.** Por isso a conexão fica na variável `MONGODB_URI`.
> O `criar_banco.py` apaga e recria **somente** o banco `zelo`, então pode ser executado várias vezes.
