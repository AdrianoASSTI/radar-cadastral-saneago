// Vistorias: ordens de campo (fiscal), decisão e aplicação (supervisor), histórico.
// Cegamento: o fiscal NÃO vê a origem da ordem nem a probabilidade do modelo, para que
// o laudo não seja influenciado (vale para ordens do Radar, do controle e da amostra).
import { useCallback, useEffect, useState } from "react";
import { api, AVISO_LOCALIZACAO, DADOS_DEMONSTRACAO, fmt, NOME_CATEGORIA, useSessao } from "../api";
import { Aviso, Botao, Cabecalho, Campo, Carregando, estiloEntrada, Selo, Vazio } from "../componentes/ui";

const ORIGEM = { RADAR: "Radar", METODO_ATUAL: "Método atual (controle)", AMOSTRA_ALEATORIA: "Amostra aleatória" };
const RESULTADO = {
  IRREGULARIDADE_CONFIRMADA: { nome: "Uso diferente do cadastro", tom: "atencao" },
  CADASTRO_CORRETO: { nome: "Cadastro correto", tom: "bom" },
  INCONCLUSIVO: { nome: "Inconclusivo", tom: "neutro" },
  IMOVEL_FECHADO: { nome: "Imóvel fechado", tom: "neutro" },
};

export default function Vistorias() {
  const { sessao } = useSessao();
  const perfil = sessao.usuario.perfil;
  const abas = [
    ["ordens", perfil === "FISCAL" ? "Minhas ordens" : "Ordens abertas"],
    ...(perfil === "SUPERVISOR" ? [["decisoes", "Decisões pendentes"], ["aplicacao", "Aguardando aplicação"]] : []),
    ...(perfil !== "FISCAL" ? [["historico", "Histórico de laudos"]] : []),
  ];
  const [aba, setAba] = useState(abas[0][0]);
  return (
    <>
      <Cabecalho titulo="Vistorias"
        descricao={perfil === "FISCAL"
          ? "Visite o imóvel e registre o que encontrou. Você não decide a categoria: laudos com uso diferente do cadastro seguem para a supervisão."
          : "Ordens de campo, laudos e a decisão sobre a categoria. Toda reclassificação exige um supervisor diferente do fiscal e respeita o prazo de contestação."} />
      <div role="tablist" className="mb-5 flex gap-1 border-b border-linha">
        {abas.map(([id, nome]) => (
          <button key={id} role="tab" aria-selected={aba === id} onClick={() => setAba(id)}
                  className={`-mb-px border-b-2 px-3 py-2 text-sm ${aba === id ? "border-agua font-semibold text-agua-escura" : "border-transparent text-tinta-2 hover:text-tinta"}`}>
            {nome}
          </button>
        ))}
      </div>
      {aba === "ordens" && <Ordens perfil={perfil} />}
      {aba === "decisoes" && <Decisoes />}
      {aba === "aplicacao" && <Aplicacao />}
      {aba === "historico" && <Historico />}
    </>
  );
}

function useCarga(caminho) {
  const [dados, setDados] = useState(null);
  const [erro, setErro] = useState(null);
  const recarregar = useCallback(() => {
    setErro(null);
    api(caminho).then(setDados).catch((e) => setErro(e.message));
  }, [caminho]);
  useEffect(() => { recarregar(); }, [recarregar]);
  return { dados, erro, recarregar };
}

/* ------------------------------------------------------------------ ordens */
function Ordens({ perfil }) {
  const { dados, erro, recarregar } = useCarga("/ordens?status=AGUARDANDO&limite=200");
  const [aberta, setAberta] = useState(null);
  const cego = perfil === "FISCAL";
  const podeLaudo = ["FISCAL", "SUPERVISOR"].includes(perfil);
  if (erro) return <Aviso>{erro}</Aviso>;
  if (!dados) return <Carregando />;
  if (!dados.length) return <Vazio titulo="Nenhuma ordem aguardando vistoria">As ordens geradas na fila aparecem aqui.</Vazio>;
  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <ul className="divide-y divide-linha rounded-lg border border-linha bg-superficie">
        {dados.map((o) => (
          <li key={o.id}>
            <button onClick={() => setAberta(o)} className={`w-full px-4 py-3 text-left ${aberta?.id === o.id ? "bg-agua-clara/50" : "hover:bg-fundo"}`}>
              <span className="block text-sm font-medium">{o.logradouro}, {o.numero}</span>
              <span className="block text-xs text-tinta-2">
                {o.bairro}, matrícula {o.matricula}{!cego && <> — {ORIGEM[o.origem]}{o.posicao_ranking ? `, posição ${o.posicao_ranking}` : ""}</>}
              </span>
            </button>
          </li>
        ))}
      </ul>
      <div>
        {aberta ? (podeLaudo ? <FormLaudo ordem={aberta} aoSalvar={() => { setAberta(null); recarregar(); }} />
                             : <Vazio titulo="Somente fiscais e supervisores registram laudos" />)
                : <Vazio titulo="Escolha uma ordem para registrar o laudo" />}
      </div>
    </div>
  );
}

function FormLaudo({ ordem, aoSalvar }) {
  const [resultado, setResultado] = useState("CADASTRO_CORRETO");
  const [categoria, setCategoria] = useState("COMERCIAL_I");
  const [atividade, setAtividade] = useState("");
  const [obs, setObs] = useState("");
  const [erro, setErro] = useState(null);
  const [enviando, setEnviando] = useState(false);
  const irregular = resultado === "IRREGULARIDADE_CONFIRMADA";

  async function enviar(e) {
    e.preventDefault();
    setEnviando(true); setErro(null);
    try {
      await api(`/ordens/${ordem.id}/laudo`, { metodo: "POST", corpo: {
        resultado, categoria_constatada: irregular ? categoria : null,
        atividade_observada: atividade || null, observacoes: obs || null } });
      aoSalvar();
    } catch (x) { setErro(x.message); } finally { setEnviando(false); }
  }

  const mapa = `https://www.google.com/maps/search/?api=1&query=${ordem.latitude},${ordem.longitude}`;
  return (
    <form onSubmit={enviar} className="space-y-4 rounded-lg border border-linha bg-superficie p-5">
      <div>
        <h2 className="expandida text-lg font-semibold">{ordem.logradouro}, {ordem.numero}</h2>
        <p className="text-sm text-tinta-2">{ordem.bairro}, matrícula {ordem.matricula}.{" "}
          <a href={mapa} target="_blank" rel="noreferrer" className="text-agua hover:underline">Abrir no mapa</a></p>
        {DADOS_DEMONSTRACAO && <p className="mt-1 text-xs text-tinta-3">{AVISO_LOCALIZACAO}</p>}
      </div>
      <fieldset>
        <legend className="text-sm font-medium text-tinta-2">O que você encontrou no imóvel?</legend>
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          {Object.entries(RESULTADO).map(([k, v]) => (
            <label key={k} className={`flex cursor-pointer items-center gap-2 rounded-md border px-3 py-2 text-sm ${resultado === k ? "border-agua bg-agua-clara/40" : "border-linha"}`}>
              <input type="radio" name="resultado" value={k} checked={resultado === k} onChange={() => setResultado(k)} className="accent-[var(--color-agua)]" />
              {v.nome}
            </label>
          ))}
        </div>
      </fieldset>
      {irregular && (
        <Campo rotulo="Categoria que corresponde ao uso encontrado">
          <select value={categoria} onChange={(e) => setCategoria(e.target.value)} className={estiloEntrada}>
            {["COMERCIAL_I", "COMERCIAL_II", "INDUSTRIAL", "PUBLICA"].map((c) => <option key={c} value={c}>{NOME_CATEGORIA[c]}</option>)}
          </select>
        </Campo>
      )}
      <Campo rotulo="Atividade observada" dica="Ex.: lanchonete aberta ao público, ateliê com atendimento.">
        <input value={atividade} onChange={(e) => setAtividade(e.target.value)} className={estiloEntrada} />
      </Campo>
      <Campo rotulo="Observações">
        <textarea value={obs} onChange={(e) => setObs(e.target.value)} rows={3} className={estiloEntrada} />
      </Campo>
      {erro && <Aviso>{erro}</Aviso>}
      <Botao type="submit" disabled={enviando}>{enviando ? "Registrando…" : "Registrar laudo"}</Botao>
    </form>
  );
}

/* ------------------------------------------------------------------ decisões */
function Decisoes() {
  const { dados, erro, recarregar } = useCarga("/laudos?decisao=ENCAMINHAR_ANALISE&limite=200");
  if (erro) return <Aviso>{erro}</Aviso>;
  if (!dados) return <Carregando />;
  const pend = dados.filter((l) => l.resultado === "IRREGULARIDADE_CONFIRMADA" && !l.aprovado_por);
  const outros = dados.filter((l) => l.resultado !== "IRREGULARIDADE_CONFIRMADA" && !l.aprovado_por);
  if (!pend.length && !outros.length) return <Vazio titulo="Nenhum laudo aguardando decisão" />;
  return (
    <div className="space-y-3">
      {[...pend, ...outros].map((l) => <CartaoDecisao key={l.id} laudo={l} aoDecidir={recarregar} />)}
    </div>
  );
}

function CartaoDecisao({ laudo, aoDecidir }) {
  const [prazo, setPrazo] = useState(30);
  const [erro, setErro] = useState(null);
  const confirmado = laudo.resultado === "IRREGULARIDADE_CONFIRMADA";
  async function decidir(decisao) {
    setErro(null);
    try { await api(`/laudos/${laudo.id}/decisao`, { metodo: "POST", corpo: { decisao, prazo_contestacao_dias: prazo } }); aoDecidir(); }
    catch (x) { setErro(x.message); }
  }
  return (
    <article className="rounded-lg border border-linha bg-superficie p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-medium">Matrícula {laudo.matricula} <Selo tom={RESULTADO[laudo.resultado].tom}>{RESULTADO[laudo.resultado].nome}</Selo></p>
          <p className="mt-1 text-sm text-tinta-2">
            {confirmado ? <>Cadastro {NOME_CATEGORIA[laudo.categoria_atual]}; o fiscal encontrou uso de <strong className="text-tinta">{NOME_CATEGORIA[laudo.categoria_constatada]}</strong>.</> : "Laudo sem conclusão sobre o uso."}
            {laudo.atividade_observada && <> Atividade: {laudo.atividade_observada}.</>}
          </p>
          <p className="mt-1 text-xs text-tinta-3">Fiscal {laudo.fiscal_matricula}, vistoria em {fmt.dataHora(laudo.realizada_em)}. Origem: {ORIGEM[laudo.origem]}.</p>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          {confirmado && (
            <Campo rotulo="Prazo de contestação (dias)">
              <input type="number" min="0" max="180" value={prazo} onChange={(e) => setPrazo(+e.target.value)} className={`${estiloEntrada} w-24`} />
            </Campo>
          )}
          {confirmado && <Botao onClick={() => decidir("RECLASSIFICAR")}>Reclassificar e notificar</Botao>}
          <Botao variante="secundario" onClick={() => decidir("MANTER")}>Manter cadastro</Botao>
        </div>
      </div>
      {erro && <div className="mt-3"><Aviso>{erro}</Aviso></div>}
    </article>
  );
}

/* ------------------------------------------------------------------ aplicação */
function Aplicacao() {
  const { dados, erro, recarregar } = useCarga("/laudos?pendentes_aplicacao=true&limite=200");
  const [msg, setMsg] = useState(null);
  if (erro) return <Aviso>{erro}</Aviso>;
  if (!dados) return <Carregando />;
  if (!dados.length) return <Vazio titulo="Nenhuma reclassificação aguardando aplicação" />;
  const hoje = new Date().toISOString().slice(0, 10);
  async function aplicar(l) {
    setMsg(null);
    try {
      const r = await api(`/laudos/${l.id}/aplicar`, { metodo: "POST" });
      setMsg({ tom: "bom", texto: `Matrícula ${l.matricula} reclassificada para ${NOME_CATEGORIA[r.historico.categoria_nova]}.` });
      recarregar();
    } catch (x) { setMsg({ tom: "critico", texto: x.message }); }
  }
  return (
    <div className="space-y-3">
      {msg && <Aviso tom={msg.tom}>{msg.texto}</Aviso>}
      <div className="overflow-x-auto rounded-lg border border-linha bg-superficie">
        <table className="w-full text-sm">
          <thead className="border-b border-linha text-left text-xs text-tinta-3">
            <tr><th className="px-4 py-2 font-medium">Matrícula</th><th className="px-4 py-2 font-medium">Mudança</th>
                <th className="px-4 py-2 font-medium">Notificado em</th><th className="px-4 py-2 font-medium">Contestação até</th><th /></tr>
          </thead>
          <tbody className="divide-y divide-linha">
            {dados.map((l) => {
              const liberado = !l.prazo_contestacao_ate || l.prazo_contestacao_ate <= hoje;
              return (
                <tr key={l.id}>
                  <td className="px-4 py-2.5">{l.matricula}</td>
                  <td className="px-4 py-2.5">{NOME_CATEGORIA[l.categoria_atual]} para {NOME_CATEGORIA[l.categoria_constatada]}</td>
                  <td className="px-4 py-2.5">{fmt.data(l.notificacao_previa_em)}</td>
                  <td className="px-4 py-2.5">{fmt.data(l.prazo_contestacao_ate)}</td>
                  <td className="px-4 py-2.5 text-right">
                    {liberado ? <Botao onClick={() => aplicar(l)}>Aplicar reclassificação</Botao>
                              : <Selo tom="atencao">Prazo de contestação aberto</Selo>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ histórico */
function Historico() {
  const { dados, erro } = useCarga("/laudos?limite=300");
  if (erro) return <Aviso>{erro}</Aviso>;
  if (!dados) return <Carregando />;
  if (!dados.length) return <Vazio titulo="Nenhum laudo registrado ainda" />;
  return (
    <div className="overflow-x-auto rounded-lg border border-linha bg-superficie">
      <table className="w-full text-sm">
        <thead className="border-b border-linha text-left text-xs text-tinta-3">
          <tr>{["Data", "Matrícula", "Origem", "Resultado", "Decisão", "Aplicado"].map((h) => <th key={h} className="px-4 py-2 font-medium">{h}</th>)}</tr>
        </thead>
        <tbody className="divide-y divide-linha">
          {dados.map((l) => (
            <tr key={l.id}>
              <td className="px-4 py-2.5 whitespace-nowrap">{fmt.data(l.realizada_em)}</td>
              <td className="px-4 py-2.5">{l.matricula}</td>
              <td className="px-4 py-2.5">{ORIGEM[l.origem]}</td>
              <td className="px-4 py-2.5"><Selo tom={RESULTADO[l.resultado].tom}>{RESULTADO[l.resultado].nome}</Selo></td>
              <td className="px-4 py-2.5">{{ MANTER: "Manter", RECLASSIFICAR: "Reclassificar", ENCAMINHAR_ANALISE: "Aguardando supervisão" }[l.decisao]}</td>
              <td className="px-4 py-2.5">{l.aplicado_em ? fmt.data(l.aplicado_em) : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
