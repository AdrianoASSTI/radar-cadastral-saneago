// Processamento: envia lotes de UCs para coleta e análise e acompanha o andamento.
import { useCallback, useEffect, useState } from "react";
import { api, fmt, useSessao } from "../api";
import { Aviso, Botao, Cabecalho, Campo, Carregando, estiloEntrada, Secao, Selo, Vazio } from "../componentes/ui";

const ESTADO = {
  PENDENTE: ["neutro", "Na fila"], EM_PROCESSAMENTO: ["agua", "Processando"], CONCLUIDO: ["bom", "Concluído"],
  CONCLUIDO_COM_FALHAS: ["atencao", "Concluído com falhas"], FALHOU: ["critico", "Falhou"],
};

export default function Processamento() {
  const { sessao } = useSessao();
  const podeEnviar = ["ANALISTA", "SUPERVISOR"].includes(sessao.usuario.perfil);
  const [lotes, setLotes] = useState(null);
  const [erro, setErro] = useState(null);
  const [limite, setLimite] = useState(50);
  const [modo, setModo] = useState("PARALELO");
  const [msg, setMsg] = useState(null);

  const ler = useCallback(() => api("/lotes?limite=30").then(setLotes).catch((e) => setErro(e.message)), []);
  useEffect(() => { ler(); }, [ler]);
  const ativo = lotes?.some((l) => ["PENDENTE", "EM_PROCESSAMENTO"].includes(l.status));
  useEffect(() => {
    if (!ativo) return;
    const t = setInterval(ler, 2000);
    return () => clearInterval(t);
  }, [ativo, ler]);

  async function enviar(e) {
    e.preventDefault(); setMsg(null);
    try {
      const r = await api("/lotes", { metodo: "POST", corpo: { limite, modo } });
      setMsg({ tom: "bom", texto: `Lote enviado: ${r.ucs} UC(s) na fila ${r.fila}.` });
      ler();
    } catch (x) { setMsg({ tom: "critico", texto: x.message }); }
  }

  return (
    <>
      <Cabecalho titulo="Processamento"
        descricao="Cada UC do lote passa pela coleta (fotos e bases públicas) e pela análise (detecção na fachada, modelo preditivo e ganho esperado). Os workers trabalham em paralelo; o modo sequencial existe para medir o ganho do paralelismo." />
      {podeEnviar && (
        <Secao titulo="Analisar UCs residenciais" className="mb-6">
          <form onSubmit={enviar} className="flex flex-wrap items-end gap-3">
            <Campo rotulo="Quantidade de UCs">
              <input type="number" min="1" max="200000" value={limite} onChange={(e) => setLimite(+e.target.value)} className={`${estiloEntrada} w-28`} />
            </Campo>
            <Campo rotulo="Modo">
              <select value={modo} onChange={(e) => setModo(e.target.value)} className={estiloEntrada}>
                <option value="PARALELO">Paralelo (todos os workers)</option>
                <option value="SEQUENCIAL">Sequencial (um worker por vez)</option>
              </select>
            </Campo>
            <Botao type="submit">Enviar lote para análise</Botao>
          </form>
          {msg && <div className="mt-3"><Aviso tom={msg.tom}>{msg.texto}</Aviso></div>}
        </Secao>
      )}

      {erro && <Aviso>{erro}</Aviso>}
      {!lotes && !erro && <Carregando />}
      {lotes && !lotes.length && <Vazio titulo="Nenhum lote enviado ainda">Envie um lote para gerar a fila de vistoria.</Vazio>}
      {lotes?.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-linha bg-superficie">
          <table className="w-full text-sm">
            <thead className="border-b border-linha text-left text-xs text-tinta-3">
              <tr>{["Enviado", "Por", "Modo", "Andamento", "Situação", "Duração", "Workers", "Etiqueta"].map((h) => <th key={h} className="px-4 py-2 font-medium">{h}</th>)}</tr>
            </thead>
            <tbody className="divide-y divide-linha">
              {lotes.map((l) => {
                const [tom, nome] = ESTADO[l.status] ?? ["neutro", l.status];
                const pct = l.progresso_pct ?? 0;
                return (
                  <tr key={l.id}>
                    <td className="whitespace-nowrap px-4 py-2.5">{fmt.dataHora(l.criado_em)}</td>
                    <td className="px-4 py-2.5">{l.solicitado_por}</td>
                    <td className="px-4 py-2.5">{l.modo === "PARALELO" ? "Paralelo" : "Sequencial"}</td>
                    <td className="px-4 py-2.5">
                      <span className="flex items-center gap-2">
                        <span className="h-1.5 w-24 overflow-hidden rounded-full bg-fundo">
                          <span className="block h-full rounded-full bg-agua" style={{ width: `${pct}%` }} />
                        </span>
                        <span className="tabular-nums">{l.processadas + l.falhas}/{l.total_ucs}</span>
                      </span>
                    </td>
                    <td className="px-4 py-2.5"><Selo tom={tom}>{nome}</Selo></td>
                    <td className="px-4 py-2.5 tabular-nums">{l.duracao_s != null ? `${fmt.num(l.duracao_s, 1)} s` : "—"}</td>
                    <td className="px-4 py-2.5 tabular-nums">{l.n_workers ?? "—"}</td>
                    <td className="px-4 py-2.5 text-tinta-3">{l.etiqueta ?? ""}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
