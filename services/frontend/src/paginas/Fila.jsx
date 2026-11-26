// Fila de vistoria: lista ordenada pelo Ganho Esperado + painel de detalhe com a
// fachada anotada, a explicação do modelo e as evidências que sustentam a indicação.
import { useCallback, useEffect, useState } from "react";
import { api, fmt, NOME_CATEGORIA, NOME_FAIXA, useSessao } from "../api";
import Fachada from "../componentes/Fachada";
import { Fatores, SerieConsumo } from "../componentes/Graficos";
import { Aviso, BarraProb, Botao, Cabecalho, Campo, Carregando, estiloEntrada, Selo, Vazio } from "../componentes/ui";

const PAGINA = 40;

export default function Fila() {
  const { sessao } = useSessao();
  const podeAgir = ["ANALISTA", "SUPERVISOR"].includes(sessao.usuario.perfil);
  const [filtros, setFiltros] = useState({ probabilidade_minima: "0.5", faixa_renda: "", categoria_sugerida: "" });
  const [itens, setItens] = useState([]);
  const [total, setTotal] = useState(0);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState(null);
  const [sel, setSel] = useState(null);
  const [msg, setMsg] = useState(null);
  const [qtd, setQtd] = useState(10);

  const carregar = useCallback(async (offset = 0) => {
    setCarregando(true); setErro(null);
    const q = new URLSearchParams({ limite: PAGINA, offset });
    Object.entries(filtros).forEach(([k, v]) => v && q.set(k, v));
    try {
      const r = await api(`/fila?${q}`);
      setTotal(r.total);
      setItens((ant) => (offset ? [...ant, ...r.itens] : r.itens));
      if (!offset) setSel(r.itens[0] ?? null);
    } catch (e) { setErro(e.message); }
    finally { setCarregando(false); }
  }, [filtros]);

  useEffect(() => { carregar(0); }, [carregar]);

  async function gerarOrdens(corpo, texto) {
    setMsg(null);
    try {
      const r = await api("/fila/ordens", { metodo: "POST", corpo });
      setMsg({ tom: "bom", texto: `${r.ordens_criadas} ${texto}` });
      carregar(0);
    } catch (e) { setMsg({ tom: "critico", texto: e.message }); }
  }

  async function sortearAmostra() {
    setMsg(null);
    try {
      const r = await api("/ordens/controle", { metodo: "POST", corpo: { origem: "AMOSTRA_ALEATORIA", quantidade: qtd } });
      setMsg({ tom: "bom", texto: `${r.ordens_criadas} UC(s) sorteada(s) para a amostra aleatória (estima o recall, I4).` });
      carregar(0);
    } catch (e) { setMsg({ tom: "critico", texto: e.message }); }
  }

  const mudar = (k) => (e) => setFiltros((f) => ({ ...f, [k]: e.target.value }));

  return (
    <>
      <Cabecalho titulo="Fila de vistoria"
        descricao="Imóveis residenciais com sinais de uso comercial ou industrial, ordenados pelo ganho anual esperado. A indicação é uma recomendação: a categoria só muda depois do laudo de campo e da decisão de um supervisor.">
        {podeAgir && (
          <div className="flex flex-wrap items-end gap-2">
            <Campo rotulo="Quantidade">
              <input type="number" min="1" max="200" value={qtd} onChange={(e) => setQtd(+e.target.value)}
                     className={`${estiloEntrada} w-20`} />
            </Campo>
            <Botao onClick={() => gerarOrdens({ quantidade: qtd, probabilidade_minima: +filtros.probabilidade_minima || 0 },
                                              "ordem(ns) de vistoria criada(s) a partir do topo da fila.")}>
              Gerar ordens para os {qtd} primeiros
            </Botao>
            <Botao variante="secundario" onClick={sortearAmostra}>Sortear amostra aleatória</Botao>
          </div>
        )}
      </Cabecalho>

      {msg && <div className="mb-4"><Aviso tom={msg.tom}>{msg.texto}</Aviso></div>}

      <div className="mb-4 flex flex-wrap gap-3">
        <Campo rotulo="Probabilidade mínima">
          <select value={filtros.probabilidade_minima} onChange={mudar("probabilidade_minima")} className={estiloEntrada}>
            <option value="0">Todas</option><option value="0.5">50% ou mais</option><option value="0.8">80% ou mais</option>
          </select>
        </Campo>
        <Campo rotulo="Faixa de renda do bairro">
          <select value={filtros.faixa_renda} onChange={mudar("faixa_renda")} className={estiloEntrada}>
            <option value="">Todas</option>
            {Object.entries(NOME_FAIXA).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </Campo>
        <Campo rotulo="Categoria sugerida">
          <select value={filtros.categoria_sugerida} onChange={mudar("categoria_sugerida")} className={estiloEntrada}>
            <option value="">Todas</option>
            {["COMERCIAL_I", "COMERCIAL_II", "INDUSTRIAL"].map((c) => <option key={c} value={c}>{NOME_CATEGORIA[c]}</option>)}
          </select>
        </Campo>
      </div>

      {erro && <Aviso>{erro}</Aviso>}

      <div className="grid gap-6 xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.25fr)]">
        <div>
          <p className="mb-2 text-sm text-tinta-2">{fmt.num(total)} UC(s) na fila com esses filtros</p>
          {!carregando && !itens.length && !erro && (
            <Vazio titulo="Nenhuma UC na fila com esses filtros">
              Reduza a probabilidade mínima ou rode um novo lote de análise em Processamento.
            </Vazio>
          )}
          <ol className="divide-y divide-linha overflow-hidden rounded-lg border border-linha bg-superficie">
            {itens.map((it) => (
              <li key={it.resultado_analise_id}>
                <button type="button" onClick={() => setSel(it)} aria-current={sel?.resultado_analise_id === it.resultado_analise_id}
                  className={`grid w-full grid-cols-[3rem_minmax(0,1fr)_auto] items-center gap-3 border-l-[3px] px-4 py-3 text-left ${
                    sel?.resultado_analise_id === it.resultado_analise_id ? "border-agua bg-agua-clara/50" : "border-transparent hover:bg-fundo"}`}>
                  <span className="condensada text-3xl font-semibold leading-none text-tinta-3 tabular-nums">{it.posicao}</span>
                  <span className="min-w-0">
                    <span className="flex items-center gap-2">
                      <span className="truncate text-sm font-medium">{it.logradouro}, {it.numero}</span>
                      <span className="shrink-0 rounded-sm bg-fundo px-1.5 py-px text-[11px] font-medium text-tinta-2">{NOME_CATEGORIA[it.categoria_sugerida]}</span>
                    </span>
                    <span className="block truncate text-xs text-tinta-2">{it.bairro}, renda {NOME_FAIXA[it.faixa_renda].toLowerCase()}</span>
                  </span>
                  <span className="text-right">
                    <span className="block text-sm font-semibold tabular-nums">{fmt.reais0(it.ganho_esperado_anual)}</span>
                    <BarraProb valor={it.probabilidade_irregularidade} />
                  </span>
                </button>
              </li>
            ))}
          </ol>
          {carregando && <Carregando />}
          {!carregando && itens.length < total && (
            <Botao variante="secundario" className="mt-3 w-full" onClick={() => carregar(itens.length)}>Mostrar mais {Math.min(PAGINA, total - itens.length)}</Botao>
          )}
        </div>

        <div className="xl:sticky xl:top-6 xl:self-start">
          {sel ? <Detalhe item={sel} podeAgir={podeAgir}
                          aoGerar={() => gerarOrdens({ resultado_analise_ids: [sel.resultado_analise_id] }, "ordem criada para esta UC.")} />
               : !carregando && <Vazio titulo="Selecione uma UC na lista" />}
        </div>
      </div>
    </>
  );
}

function Detalhe({ item, podeAgir, aoGerar }) {
  const [uc, setUc] = useState(null);
  const [erro, setErro] = useState(null);
  useEffect(() => {
    let vivo = true;
    setUc(null); setErro(null);
    api(`/ucs/${item.uc_id}`).then((r) => vivo && setUc(r)).catch((e) => vivo && setErro(e.message));
    return () => { vivo = false; };
  }, [item.uc_id]);

  const ex = item.explicabilidade ?? {};
  const ev = ex.evidencias ?? {};
  return (
    <article className="rounded-lg border border-linha bg-superficie">
      <header className="border-b border-linha px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-xs text-tinta-3">Posição {item.posicao} na fila, matrícula {item.matricula}</p>
            <h2 className="expandida mt-0.5 text-lg font-semibold">{item.logradouro}, {item.numero}</h2>
            <p className="text-sm text-tinta-2">{item.bairro}, região {item.regiao}</p>
          </div>
          {podeAgir && <Botao onClick={aoGerar}>Gerar ordem de vistoria</Botao>}
        </div>
        <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
          <Dado rotulo="Cadastro atual" valor={NOME_CATEGORIA[item.categoria_atual]} />
          <Dado rotulo="Categoria provável" valor={NOME_CATEGORIA[item.categoria_sugerida]} />
          <Dado rotulo="Probabilidade" valor={fmt.pct(item.probabilidade_irregularidade)} />
          <Dado rotulo="Ganho esperado por ano" valor={fmt.reais0(item.ganho_esperado_anual)}
                dica={ex.ganho ? `${fmt.reais0(ex.ganho.ganho_se_confirmado_anual)} se a vistoria confirmar` : null} />
        </dl>
      </header>

      <div className="space-y-6 p-5">
        {erro && <Aviso>{erro}</Aviso>}
        {!uc && !erro && <Carregando texto="Carregando a fachada e as evidências…" />}
        {uc && <Fachada imagem={uc.imagem} deteccoes={uc.deteccoes} desatualizada={item.imagem_desatualizada} />}

        <div>
          <h3 className="text-sm font-semibold">Por que esta UC está na fila</h3>
          {ex.resumo_a_favor?.length > 0 && (
            <p className="mt-1 max-w-prose text-sm text-tinta-2">
              Pesaram a favor: {ex.resumo_a_favor.map((s) => s.toLowerCase()).join("; ")}.
              {ex.resumo_contra?.length > 0 && <> Pesaram contra: {ex.resumo_contra.map((s) => s.toLowerCase()).join("; ")}.</>}
            </p>
          )}
          <div className="mt-3"><Fatores fatores={ex.fatores ?? []} /></div>
          <p className="mt-2 text-xs text-tinta-3">{ex.metodo}</p>
        </div>

        <div className="grid gap-6 md:grid-cols-2">
          <div>
            <h3 className="text-sm font-semibold">Bases públicas</h3>
            <ul className="mt-2 space-y-2 text-sm">
              {(ev.cnpjs ?? []).map((c, i) => (
                <li key={i}>
                  <span className="font-medium">{c.razao_social}</span>{" "}
                  <Selo tom={c.situacao === "ATIVA" ? "agua" : "neutro"}>{c.situacao === "ATIVA" ? "CNPJ ativo" : `CNPJ ${c.situacao.toLowerCase()}`}</Selo>
                  <span className="block text-xs text-tinta-2">{c.cnae_descricao}. Porte {c.porte}, a {fmt.num(c.distancia_m, 1)} m do endereço.</span>
                </li>
              ))}
              {!(ev.cnpjs ?? []).length && <li className="text-tinta-2">Nenhum CNPJ no endereço.</li>}
              <li className="text-tinta-2">
                {(ev.alvaras ?? []).length
                  ? ev.alvaras.map((a) => `Alvará ${a.numero} (${a.atividade}), ${a.vigente ? "vigente" : "vencido"}`).join("; ")
                  : "Sem alvará de funcionamento no endereço."}
              </li>
              <li className="text-tinta-2">Zoneamento: {String(ev.zona_uso ?? "não identificado").replaceAll("_", " ").toLowerCase()}.</li>
            </ul>
          </div>
          <div>
            <h3 className="text-sm font-semibold">Conta mensal no consumo atual</h3>
            {uc && (
              <p className="mt-2 text-sm text-tinta-2">
                Com {fmt.num(uc.volume_referencia_m3, 1)} m³/mês, a conta passaria de{" "}
                <strong className="text-tinta">{fmt.reais(uc.ultima_analise?.fatura_atual_mensal)}</strong> para{" "}
                <strong className="text-tinta">{fmt.reais(uc.ultima_analise?.fatura_sugerida_mensal)}</strong> por mês
                ({NOME_CATEGORIA[item.categoria_sugerida]}, tarifa SANEAGO 2026).
              </p>
            )}
            <h3 className="mt-4 text-sm font-semibold">Conferir a fachada</h3>
            <p className="mt-1 text-xs text-tinta-3">Só para consulta humana; essas imagens não entram na análise automática.</p>
            <div className="mt-2 flex flex-wrap gap-2">
              <a className="text-sm text-agua underline-offset-2 hover:underline" href={item.links.street_view} target="_blank" rel="noreferrer">Street View</a>
              <a className="text-sm text-agua underline-offset-2 hover:underline" href={item.links.google_maps} target="_blank" rel="noreferrer">Google Maps</a>
              <a className="text-sm text-agua underline-offset-2 hover:underline" href={item.links.geo360_goiania} target="_blank" rel="noreferrer">Geo360 Goiânia</a>
              <span className="text-xs text-tinta-3">({item.links.coordenadas})</span>
            </div>
          </div>
        </div>

        {uc && (
          <div>
            <h3 className="text-sm font-semibold">Consumo nos últimos {uc.consumo.length} meses</h3>
            <div className="mt-2"><SerieConsumo consumo={uc.consumo} /></div>
          </div>
        )}
      </div>
    </article>
  );
}

function Dado({ rotulo, valor, dica }) {
  return (
    <div>
      <dt className="text-xs text-tinta-3">{rotulo}</dt>
      <dd className="text-[15px] font-semibold tabular-nums">{valor}</dd>
      {dica && <dd className="text-xs text-tinta-2">{dica}</dd>}
    </div>
  );
}

