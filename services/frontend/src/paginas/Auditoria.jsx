// Auditoria: trilha imutável de eventos (ninguém, nem o administrador do banco, apaga).
import { useEffect, useState } from "react";
import { api, fmt } from "../api";
import { Aviso, Cabecalho, Campo, Carregando, estiloEntrada, Vazio } from "../componentes/ui";

const ENTIDADES = {
  "": "Todos os eventos", "cadastro.unidade_consumidora": "Mudanças de categoria", "fiscalizacao.laudo_vistoria": "Laudos",
  "fiscalizacao.ordem_vistoria": "Ordens de vistoria", "social.alerta_tarifa_social": "Tarifa Social", "analise.lote_processamento": "Lotes",
};
const ACAO = { INSERT: "Criou", UPDATE: "Alterou", DELETE: "Removeu", RECLASSIFICACAO: "Reclassificou", INCLUSAO_TARIFA_SOCIAL: "Incluiu na Tarifa Social" };
const OBJETO = { "cadastro.unidade_consumidora": "a categoria da UC", "fiscalizacao.laudo_vistoria": "laudo",
                 "fiscalizacao.ordem_vistoria": "ordem de vistoria", "social.alerta_tarifa_social": "alerta da Tarifa Social",
                 "analise.lote_processamento": "lote de análise" };

export default function Auditoria() {
  const [entidade, setEntidade] = useState("");
  const [eventos, setEventos] = useState(null);
  const [erro, setErro] = useState(null);
  useEffect(() => {
    setEventos(null);
    api(`/auditoria?limite=300${entidade ? `&entidade=${entidade}` : ""}`).then(setEventos).catch((e) => setErro(e.message));
  }, [entidade]);

  return (
    <>
      <Cabecalho titulo="Auditoria"
        descricao="Toda criação e alteração de ordens, laudos, alertas e categorias fica registrada com autor e horário. O registro não pode ser editado nem apagado." >
        <Campo rotulo="Mostrar">
          <select value={entidade} onChange={(e) => setEntidade(e.target.value)} className={estiloEntrada}>
            {Object.entries(ENTIDADES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </Campo>
      </Cabecalho>
      {erro && <Aviso>{erro}</Aviso>}
      {!eventos && !erro && <Carregando />}
      {eventos && !eventos.length && <Vazio titulo="Nenhum evento registrado" />}
      {eventos?.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-linha bg-superficie">
          <table className="w-full text-sm">
            <thead className="border-b border-linha text-left text-xs text-tinta-3">
              <tr>{["Quando", "Quem", "O quê", "Registro", "Detalhe"].map((h) => <th key={h} className="px-4 py-2 font-medium">{h}</th>)}</tr>
            </thead>
            <tbody className="divide-y divide-linha align-top">
              {eventos.map((e) => (
                <tr key={e.id}>
                  <td className="whitespace-nowrap px-4 py-2.5">{fmt.dataHora(e.ocorrido_em)}</td>
                  <td className="px-4 py-2.5">{e.ator}</td>
                  <td className="px-4 py-2.5">{["RECLASSIFICACAO", "INCLUSAO_TARIFA_SOCIAL"].includes(e.acao) ? `${ACAO[e.acao]} a UC` : `${ACAO[e.acao] ?? e.acao} ${OBJETO[e.entidade] ?? e.entidade}`}</td>
                  <td className="px-4 py-2.5 text-xs text-tinta-3">{e.entidade_id?.slice(0, 8)}</td>
                  <td className="max-w-md px-4 py-2.5 text-xs text-tinta-2">{resumo(e)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

function resumo(e) {
  const d = e.detalhes ?? {};
  if (e.acao === "RECLASSIFICACAO" || e.acao === "INCLUSAO_TARIFA_SOCIAL") return `De ${d.de} para ${d.para}`;
  const x = d.depois ?? d.antes ?? {};
  return ["status", "resultado", "decisao", "origem", "categoria_constatada"].filter((k) => x[k]).map((k) => `${k}: ${x[k]}`).join("; ");
}
