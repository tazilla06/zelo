"""Zelo — API (backend) com FastAPI.

Rodar:
    uvicorn api:app --reload
Documentação automática (para testar no navegador):
    http://localhost:8000/docs
"""
from datetime import datetime

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import funcionalidades as F

app = FastAPI(title="Zelo — Inventário e Manutenção Predial")

_db = None


def get_db():
    """Abre a conexão com o Atlas só uma vez (na primeira requisição)."""
    global _db
    if _db is None:
        from conexao import conectar
        _db = conectar()
    return _db


# ---------- utilitários ----------
def oid(texto):
    try:
        return ObjectId(texto)
    except (InvalidId, TypeError):
        raise HTTPException(400, f"Id inválido: {texto}")


def para_json(valor):
    """Converte ObjectId e datas para texto, para poder responder em JSON."""
    if isinstance(valor, ObjectId):
        return str(valor)
    if isinstance(valor, datetime):
        return valor.isoformat()
    if isinstance(valor, dict):
        return {k: para_json(v) for k, v in valor.items()}
    if isinstance(valor, list):
        return [para_json(v) for v in valor]
    return valor


@app.exception_handler(F.ErroEnquete)
def erro_enquete(request: Request, erro: F.ErroEnquete):
    return JSONResponse(status_code=erro.status, content={"detail": str(erro)})


# ---------- modelos de entrada (validados pelo Pydantic) ----------
class OpcaoNova(BaseModel):
    descricao: str = Field(min_length=1)
    valor_estimado: float = Field(0, ge=0)


class EnqueteNova(BaseModel):
    titulo: str = Field(min_length=3)
    descricao: str = ""
    opcoes: list[OpcaoNova] = Field(min_length=2, max_length=8)
    dias_duracao: int = Field(7, ge=1, le=60)
    criada_por: str = "Síndico"


class VotoNovo(BaseModel):
    codigo_acesso: str = Field(min_length=4)
    opcao: str = Field(min_length=1, max_length=1)


# ---------- rotas ----------
@app.get("/condominios")
def listar_condominios(db=Depends(get_db)):
    return para_json(list(db.condominios.find({}, {"nome": 1, "endereco.cidade": 1}).sort("nome", 1)))


@app.get("/condominios/{condominio_id}/vencimentos")
def vencimentos(condominio_id: str, db=Depends(get_db)):
    """Funcionalidade 1: painel de vencimentos (equipamentos + laudos)."""
    return para_json(F.painel_vencimentos(db, oid(condominio_id)))


@app.get("/condominios/{condominio_id}/gastos")
def gastos(condominio_id: str, meses: int = 12, db=Depends(get_db)):
    """Funcionalidade 2: relatório de gastos com manutenção."""
    return para_json(F.relatorio_gastos(db, oid(condominio_id), meses=meses))


@app.get("/condominios/{condominio_id}/enquetes")
def enquetes(condominio_id: str, db=Depends(get_db)):
    return para_json(F.listar_enquetes(db, oid(condominio_id)))


@app.post("/condominios/{condominio_id}/enquetes", status_code=201)
def nova_enquete(condominio_id: str, dados: EnqueteNova, db=Depends(get_db)):
    """O síndico cria uma enquete de compra."""
    enquete = F.criar_enquete(
        db, oid(condominio_id), dados.titulo, [o.model_dump() for o in dados.opcoes],
        dias_duracao=dados.dias_duracao, descricao=dados.descricao, criada_por=dados.criada_por,
    )
    return para_json(enquete)


@app.post("/enquetes/{enquete_id}/votos", status_code=201)
def votar(enquete_id: str, dados: VotoNovo, db=Depends(get_db)):
    """O morador vota (1 voto por apartamento)."""
    voto = F.votar(db, oid(enquete_id), dados.codigo_acesso, dados.opcao)
    return {"mensagem": f"Voto registrado para o apartamento {voto['unidade']} (bloco {voto['bloco']}).",
            "opcao": voto["opcao"]}


@app.get("/enquetes/{enquete_id}/resultado")
def resultado(enquete_id: str, db=Depends(get_db)):
    return para_json(F.resultado_enquete(db, oid(enquete_id)))
