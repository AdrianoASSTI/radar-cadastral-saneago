// Tarifa Social: busca ativa de famílias elegíveis (Lei 14.898/2024).
// Só o perfil de assistência social acessa esta tela e os dados do CadÚnico.
import { useCallback, useEffect, useState } from "react";
import { api, fmt, NOME_FAIXA } from "../api";
import { Aviso, Botao, Cabecalho, Carregando, Secao, Selo, Vazio } from "../componentes/ui";

const STATUS = {
  IDENTIFICADO: ["agua", "Identificada"], FAMILIA_CONTATADA: ["atencao", "Família contatada"],
  INCLUIDA: ["bom", "Incluída"], RECUSADA: ["neutro", "Recusada pela família"], INELEGIVEL_APOS_ANALISE: ["neutro", "Inelegível após análise"],
};

const VINCULO = { ENDERECO_EXATO: "endereço idêntico", ENDERECO_SIMILAR: "endereço semelhante",
                  PROXIMIDADE_GEO: "proximidade geográfica", MANUAL: "conferência manual" };

export default function TarifaSocial() {
  const [alertas, setAlertas] = useState(null);
  const [cob, setCob] = useState(null);
  const [erro, setErro] = useState(null);
  const [msg, setMsg] = useState(null);
  const [filtro, setFiltro] = useState("abertos");

  const ler = useCallback(() => {
    api("/tarifa-social/alertas?limite=500").then(setAlertas).catch((e) => setErro(e.message));
    api("/tarifa-social/cobertura").then(setCob).catch(() => {});
  }, []);
  useEffect(() => { ler(); }, [ler]);

  async function processar() {
    setMsg(null);
    try {
      const r = await api("/tarifa-social/processar", { metodo: "POST" });
      setMsg({ tom: "bom", texto: `${r.familias_vinculadas} família(s) ligada(s) a uma UC e ${r.alertas_gerados} novo(s) alerta(s).` });
      ler();
    } catch (x) { setMsg({ tom: "critico", texto: x.message }); }
  }
  async function mudar(a, status) {
    setMsg(null);
    try { await api(`/tarifa-social/alertas/${a.id}`, { metodo: "PATCH", corpo: { status } }); ler(); }
    catch (x) { setMsg({ tom: "critico", texto: x.message }); }
  }
  async function aplicar(a) {
    setMsg(null);
    try {
      await api(`/tarifa-social/alertas/${a.id}/aplicar-inclusao`, { metodo: "POST" });
      setMsg({ tom: "bom", texto: `Matrícula ${a.matricula} passou para a Residencial Social.` });
      ler();
    } catch (x) { setMsg({ tom: "critico", texto: x.message }); }
  }

  const lista = (alertas ?? []).filter((a) => filtro === "todos" ||
    (["IDENTIFICADO", "FAMILIA_CONTATADA"].includes(a.status) || (a.status === "INCLUIDA" && !a.aplicado_em)));

  return (
    <>
      <Cabecalho titulo="Tarifa Social"
        descricao="Famílias do CadÚnico com renda de até meio salário mínimo por pessoa, ou que recebem BPC, ligadas a uma UC que ainda paga a tarifa residencial normal. Estes dados servem só para conceder o desconto; não são usados na fiscalização.">
        <Botao onClick={processar}>Cruzar CadÚnico com o cadastro</Botao>
      </Cabecalho>
      {msg && <div className="mb-4"><Aviso tom={msg.tom}>{msg.texto}</Aviso></div>}
      {erro && <Aviso>{erro}</Aviso>}

      {cob && (
        <Secao className="mb-6">
          <div className="flex flex-wrap items-center gap-x-10 gap-y-3">
            <div>
              <div className="condensada text-4xl font-semibold tabular-nums">{fmt.pct(cob.valor)}</div>
              <div className="text-sm text-tinta-2">cobertura das famílias elegíveis (I3, meta 100%)</div>
            </div>
            <div className="text-sm text-tinta-2">
              {cob.economias_residencial_social} economia(s) com desconto para {cob.familias_elegiveis} família(s) elegível(is);
              {" "}{cob.familias_vinculadas_a_uc} família(s) já ligada(s) a uma UC; {cob.familias_incluidas_pelo_sistema} incluída(s) por esta busca.
            </div>
          </div>
        </Secao>
      )}

      <div className="mb-3 flex gap-1 text-sm" role="tablist">
        {[["abertos", "Em acompanhamento"], ["todos", "Todos"]].map(([k, n]) => (
          <button key={k} role="tab" aria-selected={filtro === k} onClick={() => setFiltro(k)}
                  className={`rounded-md px-3 py-1.5 ${filtro === k ? "bg-agua-clara font-semibold text-agua-escura" : "text-tinta-2 hover:bg-fundo"}`}>{n}</button>
        ))}
      </div>

      {!alertas && !erro && <Carregando />}
      {alertas && !lista.length && (
        <Vazio titulo="Nenhum alerta em acompanhamento">Use "Cruzar CadÚnico com o cadastro" depois que novas famílias ou UCs entrarem na base.</Vazio>
      )}
      <ul className="space-y-3">
        {lista.map((a) => {
          const ev = a.evidencia ?? {};
          const [tom, nome] = STATUS[a.status];
          return (
            <li key={a.id} className="rounded-lg border border-linha bg-superficie p-4">
              <div>
                <div>
                  <p className="font-medium">{a.logradouro}, {a.numero} <Selo tom={tom}>{nome}</Selo></p>
                  <p className="text-sm text-tinta-2">{a.bairro} (renda {NOME_FAIXA[a.faixa_renda].toLowerCase()}), matrícula {a.matricula}</p>
                  <p className="mt-2 text-sm">
                    {ev.recebe_bpc ? "Família recebe BPC." : <>Renda por pessoa de {fmt.reais(ev.renda_per_capita)}, abaixo do limite de {fmt.reais(ev.limite_renda_per_capita)}.</>}
                    {" "}A família foi ligada à UC por {VINCULO[ev.vinculo_metodo] ?? "outro critério"} (confiança {fmt.pct(ev.vinculo_confianca)}).
                  </p>
                  <p className="mt-1 text-xs text-tinta-3">Identificada em {fmt.data(a.criado_em)}{a.responsavel ? `; última ação de ${a.responsavel}` : ""}.</p>
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  {a.status === "IDENTIFICADO" && <Botao variante="secundario" onClick={() => mudar(a, "FAMILIA_CONTATADA")}>Registrar contato</Botao>}
                  {["IDENTIFICADO", "FAMILIA_CONTATADA"].includes(a.status) && (
                    <>
                      <Botao onClick={() => mudar(a, "INCLUIDA")}>Confirmar inclusão</Botao>
                      <Botao variante="fantasma" onClick={() => mudar(a, "RECUSADA")}>Família recusou</Botao>
                      <Botao variante="fantasma" onClick={() => mudar(a, "INELEGIVEL_APOS_ANALISE")}>Inelegível</Botao>
                    </>
                  )}
                  {a.status === "INCLUIDA" && !a.aplicado_em && <Botao onClick={() => aplicar(a)}>Aplicar desconto na conta</Botao>}
                  {a.aplicado_em && <Selo tom="bom">Desconto aplicado em {fmt.data(a.aplicado_em)}</Selo>}
                </div>
              </div>
            </li>
          );
        })}
      </ul>
    </>
  );
}
