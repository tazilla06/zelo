# Tela do Zelo (Streamlit). A API precisa estar rodando em outro terminal.
#   streamlit run frontend/app.py

import os
from datetime import datetime

import pandas as pd
import requests
import streamlit as st

API_URL = os.getenv("ZELO_API_URL", "http://localhost:8000")

st.set_page_config(page_title="Zelo", layout="wide")


def reais(valor):
    return "R$ " + f"{valor or 0:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def data_br(texto):
    return datetime.fromisoformat(texto).strftime("%d/%m/%Y")


def api_get(caminho, **params):
    resposta = requests.get(API_URL + caminho, params=params, timeout=15)
    resposta.raise_for_status()
    return resposta.json()


def api_post(caminho, dados):
    resposta = requests.post(API_URL + caminho, json=dados, timeout=15)
    corpo = resposta.json()
    if resposta.ok:
        return True, corpo
    erro = corpo.get("detail", corpo)
    if isinstance(erro, list):  # erro de validação do pydantic vem como lista
        erro = "; ".join(e.get("msg", str(e)) for e in erro)
    return False, erro


st.title("Zelo")
st.caption("Inventário e manutenção predial")

try:
    condominios = api_get("/condominios")
except requests.RequestException:
    st.error("A API não está rodando. Abra outro terminal e rode: uvicorn api.main:app --reload")
    st.stop()

nomes = {c["nome"]: c["_id"] for c in condominios}
escolhido = st.sidebar.selectbox("Condomínio", list(nomes))
cid = nomes[escolhido]

aba_enquetes, aba_vencimentos, aba_gastos, aba_nova = st.tabs(
    ["Enquetes", "Vencimentos", "Gastos", "Nova enquete (síndico)"]
)

# Enquetes: o morador vota com o código do apartamento
with aba_enquetes:
    enquetes = api_get(f"/condominios/{cid}/enquetes")
    if not enquetes:
        st.info("Esse condomínio ainda não tem enquete.")

    for enq in enquetes:
        with st.container(border=True):
            st.subheader(enq["titulo"])
            if enq.get("descricao"):
                st.write(enq["descricao"])
            st.caption(f"Situação: {enq['situacao']} | encerra em {data_br(enq['encerramento'])} | "
                       f"criada por {enq.get('criada_por', 'síndico')}")

            col_voto, col_resultado = st.columns(2)

            with col_voto:
                if enq["situacao"] == "aberta":
                    with st.form(f"voto_{enq['_id']}", clear_on_submit=True):
                        rotulos = {}
                        for o in enq["opcoes"]:
                            texto = f"{o['codigo']}) {o['descricao']}"
                            if o.get("valor_estimado"):
                                texto += f" ({reais(o['valor_estimado'])})"
                            rotulos[texto] = o["codigo"]
                        escolha = st.radio("Sua escolha", list(rotulos), key=f"radio_{enq['_id']}")
                        codigo = st.text_input("Código do apartamento", type="password",
                                               help="O síndico entrega um código por apartamento, ex: ACA-A101")
                        if st.form_submit_button("Votar"):
                            ok, retorno = api_post(f"/enquetes/{enq['_id']}/votos",
                                                   {"codigo_acesso": codigo, "opcao": rotulos[escolha]})
                            if ok:
                                st.success(retorno["mensagem"])
                            else:
                                st.error(retorno)
                else:
                    st.info("Votação encerrada.")

            with col_resultado:
                res = api_get(f"/enquetes/{enq['_id']}/resultado")
                tipo = "parcial" if res["situacao"] == "aberta" else "final"
                st.write(f"**Resultado {tipo}:** {res['total_votos']} de {res['total_apartamentos']} "
                         f"apartamentos votaram ({res['participacao']}%)")
                for o in res["opcoes"]:
                    st.progress(o["percentual"] / 100,
                                text=f"{o['opcao']}) {o['descricao']}: {o['votos']} voto(s), {o['percentual']}%")
                if res["situacao"] == "encerrada" and res["vencedora"]:
                    st.success(f"Ganhou: {res['vencedora']['descricao']}")

# Funcionalidade 1
with aba_vencimentos:
    st.write("Prazos dos equipamentos e laudos, do mais urgente para o menos urgente.")
    for grupo in api_get(f"/condominios/{cid}/vencimentos"):
        nome_grupo = grupo["_id"][3:]  # tira o "1. " da frente
        st.subheader(f"{nome_grupo} ({grupo['quantidade']})")
        tabela = pd.DataFrame([{
            "Prazo": data_br(i["prazo"]),
            "Dias": i["dias_restantes"],
            "Tipo": i["origem"],
            "Item": i["item"],
            "Detalhe": i["detalhe"],
        } for i in grupo["itens"]])
        st.dataframe(tabela, hide_index=True, width="stretch")

# Funcionalidade 2
with aba_gastos:
    meses = st.slider("Últimos quantos meses?", 3, 24, 12)
    rel = api_get(f"/condominios/{cid}/gastos", meses=meses)
    r = rel["resumo"]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total gasto", reais(r["total"]))
    c2.metric("Serviços", r["quantidade"])
    c3.metric("Média por serviço", reais(r["media"]))
    c4.metric("Maior serviço", reais(r["maior"]))

    if rel.get("por_mes"):
        st.write("**Gastos por mês**")
        por_mes = pd.DataFrame(rel["por_mes"]).rename(columns={"_id": "Mês", "total": "Total (R$)"})
        st.bar_chart(por_mes.set_index("Mês")["Total (R$)"])

    col_a, col_b, col_c = st.columns(3)
    tabelas = [(col_a, "Por prestador", "por_prestador"),
               (col_b, "Por tipo de serviço", "por_tipo_servico"),
               (col_c, "Equipamentos mais caros", "top_equipamentos")]
    for coluna, titulo, chave in tabelas:
        with coluna:
            st.write(f"**{titulo}**")
            linhas = [{"": l["_id"], "Total": reais(l["total"])} for l in rel.get(chave, [])]
            st.dataframe(pd.DataFrame(linhas), hide_index=True, width="stretch")

# Síndico cria uma enquete nova
with aba_nova:
    qtd = st.number_input("Quantas opções?", min_value=2, max_value=8, value=3)
    with st.form("nova_enquete", clear_on_submit=True):
        titulo = st.text_input("Pergunta", placeholder="Ex: Qual aparelho comprar para a academia?")
        descricao = st.text_area("Explicação (opcional)")
        opcoes = []
        for i in range(int(qtd)):
            c1, c2 = st.columns([3, 1])
            desc = c1.text_input(f"Opção {chr(65 + i)}", key=f"op_{i}")
            valor = c2.number_input("Valor estimado (R$)", min_value=0.0, step=100.0, key=f"val_{i}")
            opcoes.append({"descricao": desc, "valor_estimado": valor})
        dias = st.number_input("Dias de votação", min_value=1, max_value=60, value=7)
        autor = st.text_input("Criada por", value="Síndico")

        if st.form_submit_button("Criar enquete"):
            preenchidas = [o for o in opcoes if o["descricao"].strip()]
            ok, retorno = api_post(f"/condominios/{cid}/enquetes", {
                "titulo": titulo,
                "descricao": descricao,
                "opcoes": preenchidas,
                "dias_duracao": int(dias),
                "criada_por": autor,
            })
            if ok:
                st.success(f"Enquete criada: {retorno['titulo']}")
            else:
                st.error(retorno)
