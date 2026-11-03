// =====================================================================
// Zelo — Script 02: consultas de exemplo
// Rode depois do 01_criar_banco.js:
//   mongosh "mongodb+srv://<seu-cluster>.mongodb.net/" --username <usuario> --file scripts/02_consultas.js
// =====================================================================

db = db.getSiblingDB("zelo"); // equivale a "use zelo"
const hoje = new Date();
const em30dias = new Date(Date.now() + 30 * 24 * 60 * 60 * 1000);
const acacias = db.condominios.findOne({ nome: "Residencial Jardim das Acácias" });

function titulo(t) { print("\n=== " + t + " ==="); }

// 1. Filtro por tipo: todos os elevadores do condomínio
titulo("1. Elevadores do Residencial Jardim das Acácias");
printjson(
  db.equipamentos
    .find({ condominio_id: acacias._id, tipo: "elevador" },
          { _id: 0, identificacao: 1, local: 1, art: 1, capacidade_pessoas: 1 })
    .toArray()
);

// 2. Campo que só existe em um tipo: extintores com recarga vencida ou vencendo
titulo("2. Extintores com recarga vencida ou vencendo em 30 dias");
printjson(
  db.equipamentos
    .find({ tipo: "extintor", validade_recarga: { $lte: em30dias } },
          { _id: 0, identificacao: 1, local: 1, classe: 1, validade_recarga: 1 })
    .sort({ validade_recarga: 1 })
    .toArray()
);

// 3. Alertas: laudos vencidos ou vencendo em 30 dias, com o nome do condomínio
titulo("3. Laudos vencidos ou vencendo em 30 dias");
printjson(
  db.laudos.aggregate([
    { $match: { validade: { $lte: em30dias } } },
    { $lookup: { from: "condominios", localField: "condominio_id", foreignField: "_id", as: "cond" } },
    { $unwind: "$cond" },
    { $project: {
        _id: 0, condominio: "$cond.nome", tipo: 1, numero: 1, validade: 1,
        situacao: { $cond: [{ $lt: ["$validade", hoje] }, "VENCIDO", "vence em breve"] },
    } },
    { $sort: { validade: 1 } },
  ]).toArray()
);

// 4. Agregação no histórico embutido: custo total de manutenção por equipamento
titulo("4. Custo total de manutenção por equipamento");
printjson(
  db.equipamentos.aggregate([
    { $unwind: "$manutencoes" },
    { $group: {
        _id: { condominio_id: "$condominio_id", identificacao: "$identificacao", tipo: "$tipo" },
        total_gasto: { $sum: "$manutencoes.custo" },
        qtd_manutencoes: { $sum: 1 },
    } },
    { $sort: { total_gasto: -1 } },
  ]).toArray()
);

// 5. Custo por condomínio e por tipo de equipamento
titulo("5. Custo por condomínio e tipo de equipamento");
printjson(
  db.equipamentos.aggregate([
    { $unwind: "$manutencoes" },
    { $group: { _id: { condominio_id: "$condominio_id", tipo: "$tipo" }, total: { $sum: "$manutencoes.custo" } } },
    { $lookup: { from: "condominios", localField: "_id.condominio_id", foreignField: "_id", as: "cond" } },
    { $project: { _id: 0, condominio: { $first: "$cond.nome" }, tipo: "$_id.tipo", total: 1 } },
    { $sort: { condominio: 1, total: -1 } },
  ]).toArray()
);

// 6. Registrar uma nova manutenção (adiciona no array embutido)
titulo("6. Registrar manutenção na bomba de recalque e voltar o status para operacional");
const resultado = db.equipamentos.updateOne(
  { condominio_id: acacias._id, identificacao: "BMB-RECALQUE-01" },
  {
    $push: { manutencoes: { data: hoje, tipo: "corretiva", descricao: "Troca do rolamento", custo: 390 } },
    $set: { status: "operacional" },
  }
);
printjson({ modificados: resultado.modifiedCount });
printjson(
  db.equipamentos.findOne(
    { identificacao: "BMB-RECALQUE-01" },
    { _id: 0, identificacao: 1, status: 1, manutencoes: 1 }
  )
);
