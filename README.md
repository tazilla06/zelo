# Zelo

Trabalho da disciplina de Banco de Dados NoSQL.
Integrantes: Gabriel e Tarsila

O Zelo é um sistema para ajudar o síndico a cuidar da manutenção do prédio. Ele guarda os equipamentos do condomínio (extintor, elevador, bomba d'água, portão, gerador, caixa d'água), o histórico de manutenção de cada um e os laudos que têm data de validade, como o AVCB dos bombeiros. Também tem uma enquete para os moradores votarem no que o condomínio vai comprar.

## 1. Descrição do sistema

### O problema

A ideia veio de ver como funciona em condomínio pequeno: o síndico controla tudo numa planilha, ou nem isso, e só descobre que o extintor venceu quando aparece a vistoria. Cada equipamento tem um prazo diferente (recarga de extintor é anual, elevador tem manutenção todo mês, caixa d'água é limpa a cada 6 meses) e quando troca o síndico o histórico costuma se perder. Também é difícil saber quanto o prédio gasta com manutenção e com qual empresa.

### O que o sistema faz

- cadastro dos equipamentos, cada tipo com os seus campos
- histórico das manutenções de cada equipamento, com custo e empresa
- controle dos laudos e das datas de validade
- painel com o que está vencido ou vai vencer (funcionalidade 1)
- relatório de quanto foi gasto com manutenção (funcionalidade 2)
- enquete de compras: o síndico cria, cada apartamento vota uma vez e todo mundo vê o resultado

### Por que MongoDB

O principal motivo é que os equipamentos são muito diferentes entre si. Um extintor tem classe, carga e validade da recarga. Um elevador tem ART, capacidade e número de paradas. Uma bomba tem potência e vazão. Num banco relacional a gente teria que fazer uma tabela para cada tipo ou uma tabela enorme com várias colunas vazias. No MongoDB todos ficam na coleção `equipamentos` e cada documento tem só os campos que fazem sentido para ele.

O segundo motivo é o histórico de manutenção. Ele é sempre lido junto com o equipamento, então faz sentido guardar dentro do próprio documento, num array.

Mesmo sendo flexível, a gente colocou regras de validação com `$jsonSchema`: todo equipamento precisa ter tipo, local e status, extintor precisa ter classe e validade da recarga, e elevador precisa ter ART. Se faltar alguma coisa o banco não deixa inserir.

## 2. Modelagem

O banco se chama `zelo` e tem 7 coleções: `condominios`, `equipamentos`, `prestadores`, `laudos`, `moradores`, `enquetes` e `votos`. As ligações entre elas são feitas pelo `_id` (por exemplo, cada equipamento guarda o `condominio_id` do prédio dele).

### O que ficou embutido e o que ficou separado

| O quê | Onde | Por quê |
|---|---|---|
| endereço e síndico | dentro de `condominios` | são poucos dados e sempre lidos junto com o condomínio |
| manutenções | dentro de `equipamentos` | pertencem a um equipamento só e aparecem na ficha dele |
| prestadores | coleção separada | a mesma empresa atende vários equipamentos e vários prédios |
| laudos | coleção separada | o AVCB é do prédio e não de um equipamento, e a gente precisa buscar laudos por validade |
| opções da enquete | dentro de `enquetes` | são 2 a 8 opções que não mudam depois de criadas |
| votos | coleção separada | crescem com o número de apartamentos e precisam do índice único (explicado na seção 5) |

Um exemplo de equipamento (um elevador):

```json
{
  "condominio_id": "ObjectId(...)",
  "tipo": "elevador",
  "identificacao": "ELV-A-SOCIAL",
  "local": "Bloco A",
  "status": "operacional",
  "art": "SP-2026-0451",
  "capacidade_pessoas": 8,
  "paradas": 12,
  "empresa_responsavel_id": "ObjectId(...)",
  "proxima_manutencao": "2026-11-24",
  "manutencoes": [
    { "data": "2026-10-16", "tipo": "preventiva", "descricao": "Manutenção mensal", "custo": 850 },
    { "data": "2026-10-25", "tipo": "corretiva", "descricao": "Troca do sensor da porta do 7º andar", "custo": 1320 }
  ]
}
```

Os dados de exemplo são inventados: 2 condomínios, 3 empresas de manutenção, 9 equipamentos, 5 laudos, 22 moradores, 3 enquetes e 28 votos. As datas são calculadas a partir do dia em que o script roda, então sempre tem algo vencido e alguma enquete aberta para mostrar.

## 3. Estrutura do repositório

```
zelo/
├── README.md
├── requirements.txt
├── .env.example            modelo do .env (onde vai a connection string)
├── .gitignore              não deixa o .env subir pro GitHub
├── database/
│   ├── conexao.py          conecta no Atlas lendo o .env
│   ├── criar_banco.py      cria as coleções, validações, índices e dados de exemplo
│   ├── consultas.py        consultas básicas (primeira entrega)
│   └── funcionalidades.py  os pipelines das 2 funcionalidades e as regras da enquete
├── api/
│   └── main.py             API com FastAPI
├── frontend/
│   └── app.py              tela com Streamlit
└── prints/
```

## 4. Funcionalidades

As duas funcionalidades estão em `database/funcionalidades.py`. A gente tentou fazer pipelines que trabalham de jeitos bem diferentes: o primeiro junta duas coleções numa lista só e trabalha com datas, e o segundo desmonta um array embutido e calcula valores.

### Funcionalidade 1: painel de vencimentos

Mostra para o síndico tudo que tem prazo (manutenção dos equipamentos e validade dos laudos) separado por urgência: vencido, vence nesta semana, vence neste mês e em dia.

1. `$match` pega os equipamentos do condomínio
2. `$project` deixa só os campos que importam e renomeia para um formato comum (item, detalhe, prazo)
3. `$unionWith` traz os laudos da outra coleção no mesmo formato, para ficar tudo numa lista só
4. `$addFields` com `$dateDiff` calcula quantos dias faltam (negativo quer dizer que já venceu)
5. `$addFields` com `$switch` classifica a urgência pelos dias que faltam
6. `$sort` e `$group` agrupam por urgência, com os itens em ordem de prazo

![Painel de vencimentos](prints/vencimentos.jpg)

### Funcionalidade 2: relatório de gastos

Mostra quanto foi gasto com manutenção no período escolhido (12 meses por padrão): total, por mês, por empresa, por tipo de serviço e os 3 equipamentos que mais custaram.

1. `$match` pega os equipamentos do condomínio
2. `$unwind` no array `manutencoes`, assim cada manutenção vira um documento
3. `$match` deixa só as manutenções do período
4. `$lookup` busca o nome da empresa na coleção `prestadores`
5. `$project` com `$dateToString` transforma a data em mês (`2026-11`)
6. `$facet` faz os 5 resumos de uma vez, cada um com seu `$group` e `$sort`

A gente usou o `$facet` para a tela não precisar fazer 5 consultas separadas.

![Relatório de gastos](prints/gastos.jpg)

| | Painel de vencimentos | Relatório de gastos |
|---|---|---|
| como junta dados | `$unionWith` (soma linhas de outra coleção) | `$lookup` (completa cada linha com dado de outra coleção) |
| usa o array embutido | não | sim, `$unwind` em `manutencoes` |
| o que calcula | dias até o prazo | soma, média e maior valor |
| resultado | um grupo por urgência | um documento com 5 relatórios |

## 5. Enquete de compras

Essa parte foi uma ideia nossa a mais. O síndico cria uma pergunta, por exemplo "O que comprar para a área de lazer?", com as opções e o valor de cada uma. Cada apartamento recebe um código (tipo `ACA-B203`) e vota pela tela.

A regra mais importante é que cada apartamento só pode votar uma vez. Isso não ficou só no código: a coleção `votos` tem um índice único em `(enquete_id, bloco, unidade)`, então se o mesmo apartamento tentar votar de novo o próprio MongoDB recusa. A gente usou bloco e unidade em vez do morador porque quem vota é o apartamento, e se o morador mudar o voto continua sendo daquele apartamento.

O resto das regras fica na função `votar()`: o código precisa existir, ser do mesmo condomínio da enquete, a enquete precisa estar aberta e a opção precisa existir.

O resultado sai de um terceiro pipeline: `$unwind` nas opções, `$lookup` com sub-pipeline para contar os votos de cada opção (assim opção sem voto aparece com 0) e `$setWindowFields` para calcular o total e a colocação sem perder as linhas. A tela mostra só os totais, ninguém vê em quem cada apartamento votou.

![Enquete](prints/enquetes.jpg)

### Limitações

- o código do apartamento funciona como uma senha simples, não tem login de verdade
- qualquer um que abrir a tela consegue criar enquete, não separamos o acesso do síndico
- a conferência de que a opção existe na enquete é feita no Python, porque o `$jsonSchema` não consegue comparar com outro documento

## 6. Como rodar

Precisa do Python 3.10 ou mais novo e de uma conta no [MongoDB Atlas](https://www.mongodb.com/cloud/atlas/register).

1. No Atlas, crie um cluster gratuito (M0), crie um usuário do banco e libere o seu IP em Network Access.
2. Em Connect > Drivers, copie a connection string e troque `<db_password>` pela senha do usuário.
3. No terminal, dentro da pasta do projeto:

```bash
pip install -r requirements.txt
cp .env.example .env        # no Windows: copy .env.example .env
```

4. Abra o `.env` e cole a sua connection string no `MONGODB_URI`.
5. Crie o banco e, se quiser, veja as funcionalidades no terminal:

```bash
python database/criar_banco.py
python database/funcionalidades.py
```

6. Para abrir a tela, rode a API num terminal e o Streamlit em outro:

```bash
uvicorn api.main:app --reload
```

```bash
streamlit run frontend/app.py
```

Para testar o voto dá para usar o código `ACA-B203` (Residencial Jardim das Acácias) ou `MAZ-31` (Edifício Monte Azul). As rotas da API podem ser testadas em http://localhost:8000/docs.

O `criar_banco.py` apaga o banco `zelo` e cria de novo, então pode rodar várias vezes.
