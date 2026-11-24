# API do Zelo (FastAPI). Rodar da pasta do projeto:
#   uvicorn api.main:app --reload
# Dá pra testar as rotas em http://localhost:8000/docs

from datetime import datetime

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from database import funcionalidades as F
from cache import estatisticas as E
from cache import login as L

app = FastAPI(title="Zelo")

_db = None
_redis = None


def get_db():
    # conecta no Atlas só na primeira requisição
    global _db
    if _db is None:
        from database.conexao import conectar
        _db = conectar()
    return _db


def get_redis():
    global _redis
    if _redis is None:
        from cache.conexao_redis import conectar_redis
        _redis = conectar_redis()
    return _redis


# toda requisição passa por aqui: conta a rota no Count-Min Sketch e o visitante no HyperLogLog
@app.middleware("http")
async def contar_acesso(request: Request, call_next):
    resposta = await call_next(request)
    rota = request.scope.get("route")
    if rota is not None and not request.url.path.startswith(("/docs", "/openapi")):
        try:
            visitante = request.client.host if request.client else "desconhecido"
            E.registrar_acesso(get_redis(), f"{request.method} {rota.path}", visitante)
        except Exception:
            pass  # se o Redis cair, o sistema continua funcionando, só não conta
    return resposta


def oid(texto):
    try:
        return ObjectId(texto)
    except (InvalidId, TypeError):
        raise HTTPException(400, f"Id inválido: {texto}")


def para_json(valor):
    # ObjectId e datetime não viram JSON sozinhos
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


@app.exception_handler(L.ErroLogin)
def erro_login(request: Request, erro: L.ErroLogin):
    return JSONResponse(status_code=erro.status, content={"detail": str(erro)})


def sindico_logado(authorization: str | None = Header(None), r=Depends(get_redis)):
    # a tela manda o token no cabeçalho:  Authorization: Bearer <token>
    token = (authorization or "").removeprefix("Bearer ").strip()
    sessao = L.sessao_atual(r, token)
    if not sessao:
        raise HTTPException(401, "Faça login como síndico.")
    sessao["token"] = token
    return sessao


class Login(BaseModel):
    email: str = Field(min_length=3)
    senha: str = Field(min_length=1)


class OpcaoNova(BaseModel):
    descricao: str = Field(min_length=1)
    valor_estimado: float = Field(0, ge=0)


class EnqueteNova(BaseModel):
    titulo: str = Field(min_length=3)
    descricao: str = ""
    opcoes: list[OpcaoNova] = Field(min_length=2, max_length=8)
    dias_duracao: int = Field(7, ge=1, le=60)


class VotoNovo(BaseModel):
    codigo_acesso: str = Field(min_length=4)
    opcao: str = Field(min_length=1, max_length=1)


@app.post("/login")
def login(dados: Login, db=Depends(get_db), r=Depends(get_redis)):
    return L.fazer_login(db, r, dados.email, dados.senha)


@app.post("/logout")
def logout(sindico=Depends(sindico_logado), r=Depends(get_redis)):
    L.sair(r, sindico["token"])
    return {"mensagem": "Até logo!"}


@app.get("/eu")
def quem_sou_eu(sindico=Depends(sindico_logado)):
    return {k: v for k, v in sindico.items() if k != "token"}


@app.get("/estatisticas")
def estatisticas(dias: int = 7, sindico=Depends(sindico_logado), r=Depends(get_redis)):
    return E.resumo(r, dias)


@app.get("/condominios")
def listar_condominios(db=Depends(get_db)):
    return para_json(list(db.condominios.find({}, {"nome": 1, "endereco.cidade": 1}).sort("nome", 1)))


@app.get("/condominios/{condominio_id}/vencimentos")
def vencimentos(condominio_id: str, db=Depends(get_db)):
    return para_json(F.painel_vencimentos(db, oid(condominio_id)))


@app.get("/condominios/{condominio_id}/gastos")
def gastos(condominio_id: str, meses: int = 12, db=Depends(get_db)):
    return para_json(F.relatorio_gastos(db, oid(condominio_id), meses=meses))


@app.get("/condominios/{condominio_id}/enquetes")
def enquetes(condominio_id: str, db=Depends(get_db)):
    return para_json(F.listar_enquetes(db, oid(condominio_id)))


@app.post("/condominios/{condominio_id}/enquetes", status_code=201)
def nova_enquete(condominio_id: str, dados: EnqueteNova, db=Depends(get_db),
                 sindico=Depends(sindico_logado)):
    # só o síndico do próprio prédio cria enquete
    if sindico["condominio_id"] != condominio_id:
        raise HTTPException(403, "Você é síndico de outro condomínio.")
    opcoes = [o.model_dump() for o in dados.opcoes]
    enquete = F.criar_enquete(db, oid(condominio_id), dados.titulo, opcoes,
                              dias_duracao=dados.dias_duracao, descricao=dados.descricao,
                              criada_por=sindico["nome"])
    return para_json(enquete)


@app.post("/enquetes/{enquete_id}/votos", status_code=201)
def votar(enquete_id: str, dados: VotoNovo, db=Depends(get_db)):
    voto = F.votar(db, oid(enquete_id), dados.codigo_acesso, dados.opcao)
    return {"mensagem": f"Voto registrado para o apartamento {voto['unidade']} do bloco {voto['bloco']}.",
            "opcao": voto["opcao"]}


@app.get("/enquetes/{enquete_id}/resultado")
def resultado(enquete_id: str, db=Depends(get_db)):
    return para_json(F.resultado_enquete(db, oid(enquete_id)))
