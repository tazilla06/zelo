"""Zelo — tela (frontend) com Streamlit.

Rodar (com a API já rodando em outro terminal):
    streamlit run app.py
"""
import os
from datetime import datetime

import pandas as pd
import requests
import streamlit as st

API_URL = os.environ.get("ZELO_API_URL", "http://localhost:8000")

st.set_page_config(page_title="Zelo", page_icon="🏢", layout="wide")


def reais(valor):
    return "R$ " + f"{valor or 0:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def data_br(texto):
    return datetime.fromisoformat(texto).strftime("%d/%m/%Y")


def api_get(caminho, **params):
    resposta = requests.get(f"{API_URL}{caminho}", params=params, timeout=15)
    resposta.raise_for_status()
    return resposta.json()


def api_post(caminho, dados):
    resposta = requests.post(f"{API_URL}{caminho}", json=dados, timeout=15)
    try:
        corpo = resposta.json()
    except ValueError:
        corpo = {}
    detalhe = corpo.get("detail", corpo)
    if isinstance(detalhe, list):  # erros de validação do Pydantic
        detalhe = "; ".join(e.get("msg", str(e)) for e in detalhe)
    return resposta.ok, (corpo if resposta.ok else detalhe)


# ---------------------------------------------------------------------
st.title("🏢 Zelo — Inventário e Manutenção Predial")

try:
    condominios = api_get("/condominios")
except requests.RequestException:
    st.error("Não consegui falar com a API. Abra outro terminal e rode:  `uvicorn api:app --reload`")
    st.stop()

nomes = {c["nome"]: c["_id"] for c in condominios}
nome_escolhido = st.sidebar.selectbox("Condomínio", list(nomes))
cid = nomes[nome_escolhido]
st.sidebar.caption(f"API: {API_URL}")

aba_enquete, aba_venc, aba_gastos, aba_nova = st.tabs(
    ["🗳️ Enquetes de compras", "⏰ Vencimentos", "💰 Gastos com manutenção", "➕ Nova enquete (síndico)"]
)

# ---------------------------------------------------------------------
# ENQUETES — o morador vota com o código do seu apartamento
# ---------------------------------------------------------------------
with aba_enquete:
    enquetes = api_get(f"/condominios/{cid}/enquetes")
    if not enquetes:
        st.info("Nenhuma enquete neste condomínio ainda.")
    for enq in enquetes:
        icone = {"aberta": "🟢", "encerrada": "⚪", "agendada": "🕒"}[enq["situacao"]]
        with st.container(border=True):
            st.subheader(f"{icone} {enq['titulo']}")
            if enq.get("descricao"):
                st.write(enq["descricao"])
            st.caption(f"{enq['situacao'].capitalize()} · encerra em {data_br(enq['encerramento'])}"
                       f" · criada por {enq.get('criada_por', 'síndico')}")

            col_voto, col_resultado = st.columns(2)

            with col_voto:
                if enq["situacao"] == "aberta":
                    with st.form(f"voto_{enq['_id']}", clear_on_submit=True):
                        rotulos = {
                            f"{o['codigo']}) {o['descricao']}"
                            + (f" — {reais(o['valor_estimado'])}" if o.get("valor_estimado") else ""): o["codigo"]
                            for o in enq["opcoes"]
                        }
                        escolha = st.radio("Sua escolha", list(rotulos), key=f"radio_{enq['_id']}")
                        codigo = st.text_input("Código de acesso do seu apartamento", type="password",
                                               help="Entregue pelo síndico. Exemplo: ACA-A101")
                        if st.form_submit_button("Votar"):
                            ok, retorno = api_post(f"/enquetes/{enq['_id']}/votos",
                                                   {"codigo_acesso": codigo, "opcao": rotulos[escolha]})
                            if ok:
                                st.success(retorno["mensagem"])
                            else:
                                st.error(retorno)
                else:
                    st.info("Votação fechada.")

            with col_resultado:
                res = api_get(f"/enquetes/{enq['_id']}/resultado")
                st.markdown(f"**Resultado {'parcial' if res['situacao'] == 'aberta' else 'final'}** — "
                            f"{res['total_votos']} de {res['total_apartamentos']} apartamentos "
                            f"votaram ({res['participacao']}%)")
                for o in res["opcoes"]:
                    st.progress(o["percentual"] / 100,
                                text=f"{o['opcao']}) {o['descricao']} — {o['votos']} voto(s) · {o['percentual']}%")
                if res["situacao"] == "encerrada" and res["vencedora"]:
                    st.success(f"Vencedora: {res['vencedora']['descricao']}")

# ---------------------------------------------------------------------
# FUNCIONALIDADE 1 — PAINEL DE VENCIMENTOS
# ---------------------------------------------------------------------
with aba_venc:
    st.write("Equipamentos e laudos do condomínio, organizados pelo que precisa de atenção primeiro.")
    grupos = api_get(f"/condominios/{cid}/vencimentos")
    cores = {"1": "🔴", "2": "🟠", "3": "🟡", "4": "🟢"}
    for g in grupos:
        st.subheader(f"{cores.get(g['_id'][0], '')} {g['_id'][3:]} ({g['quantidade']})")
        tabela = pd.DataFrame([{
            "Prazo": data_br(i["prazo"]),
            "Dias": i["dias_restantes"],
            "Tipo": i["origem"],
            "Item": i["item"],
            "Detalhe": i["detalhe"],
        } for i in g["itens"]])
        st.dataframe(tabela, hide_index=True, width="stretch")

# ---------------------------------------------------------------------
# FUNCIONALIDADE 2 — RELATÓRIO DE GASTOS
# ---------------------------------------------------------------------
with aba_gastos:
    meses = st.slider("Período (últimos N meses)", 3, 24, 12)
    rel = api_get(f"/condominios/{cid}/gastos", meses=meses)
    r = rel["resumo"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total gasto", reais(r["total"]))
    c2.metric("Serviços", r["quantidade"])
    c3.metric("Média por serviço", reais(r["media"]))
    c4.metric("Maior serviço", reais(r["maior"]))

    if rel.get("por_mes"):
        st.markdown("**Gastos por mês**")
        st.bar_chart(pd.DataFrame(rel["por_mes"]).rename(columns={"_id": "Mês", "total": "Total (R$)"})
                     .set_index("Mês")["Total (R$)"])

    col_a, col_b, col_c = st.columns(3)
    for coluna, titulo, chave in [(col_a, "Por prestador", "por_prestador"),
                                  (col_b, "Por tipo de serviço", "por_tipo_servico"),
                                  (col_c, "Equipamentos que mais custaram", "top_equipamentos")]:
        with coluna:
            st.markdown(f"**{titulo}**")
            linhas = rel.get(chave, [])
            st.dataframe(pd.DataFrame([{"": l["_id"], "Total": reais(l["total"])} for l in linhas]),
                         hide_index=True, width="stretch")

# ---------------------------------------------------------------------
# NOVA ENQUETE — usada pelo síndico
# ---------------------------------------------------------------------
with aba_nova:
    st.write("Crie uma enquete para os moradores decidirem uma compra.")
    qtd = st.number_input("Quantas opções?", min_value=2, max_value=8, value=3)
    with st.form("nova_enquete", clear_on_submit=True):
        titulo = st.text_input("Pergunta", placeholder="Ex.: Qual equipamento comprar para a academia?")
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
                "titulo": titulo, "descricao": descricao, "opcoes": preenchidas,
                "dias_duracao": int(dias), "criada_por": autor,
            })
            if ok:
                st.success(f"Enquete criada: {retorno['titulo']}. Ela já aparece na aba de enquetes.")
            else:
                st.error(retorno)
