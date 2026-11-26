// Painel de indicadores de impacto (I1–I5), calculados na hora pela API.
import { useEffect, useState } from "react";
import { api, fmt, NOME_FAIXA } from "../api";
import { BarrasIC } from "../componentes/Graficos";
import { Aviso, Cabecalho, Carregando, Secao, Selo } from "../componentes/ui";

const SERIE_1 = "var(--color-serie-1)";
const SERIE_2 = "var(--color-serie-2)";

export default function Painel() {
  const [d, setD] = useState(null);
  const [erro, setErro] = useState(null);
  useEffect(() => { api("/indicadores").then(setD).catch((e) => setErro(e.message)); }, []);

  if (erro) return <Aviso>{erro}</Aviso>;
  if (!d) return <Carregando texto="Calculando os indicadores…" />;
  const { I1, I2, I3, I4, I5 } = d;
  const g = I1.grupos;

  return (
    <>
      <Cabecalho titulo="Indicadores de impacto"
        descricao={`Calculados a partir dos laudos, reclassificações e análises registrados. Atualizado em ${fmt.dataHora(d.gerado_em)}. Intervalos de confiança de 95% (Wilson) aparecem como traço sobre as barras.`} />

      <section className="mb-6 rounded-lg border border-linha bg-superficie p-6">
        <div className="grid gap-8 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
          <div>
            <h2 className="text-sm font-semibold text-tinta-2">Acerto das vistorias (I1)</h2>
            <p className="expandida mt-2 text-2xl font-semibold leading-snug">
              {g.RADAR.valor == null
                ? "Ainda não há vistorias indicadas pelo Radar com resultado."
                : <>Vistorias indicadas pelo Radar acertam <span className="condensada text-4xl">{fmt.pct(g.RADAR.valor)}</span>; as do método atual, {fmt.pct(g.METODO_ATUAL.valor)}.</>}
            </p>
            <div className="mt-3 flex flex-wrap items-center gap-2 text-sm text-tinta-2">
              {I1.razao_radar_controle != null && <span>Razão {fmt.num(I1.razao_radar_controle, 1)}× (meta {fmt.num(I1.meta_razao, 0)}×)</span>}
              {I1.atingiu_meta != null && <Selo tom={I1.atingiu_meta ? "bom" : "atencao"}>{I1.atingiu_meta ? "Meta atingida" : "Abaixo da meta"}</Selo>}
            </div>
            <p className="mt-3 text-xs text-tinta-3">
              Acerto = vistorias que confirmaram uso diferente do cadastro ÷ vistorias conclusivas (imóvel fechado e inconclusivo não entram).
            </p>
          </div>
          <BarrasIC itens={[
            { rotulo: "Radar", valor: g.RADAR.valor, ic: g.RADAR.ic95, cor: SERIE_1, dica: `${g.RADAR.sucessos} de ${g.RADAR.n} vistorias conclusivas` },
            { rotulo: "Método atual", valor: g.METODO_ATUAL.valor, ic: g.METODO_ATUAL.ic95, cor: SERIE_2, dica: `${g.METODO_ATUAL.sucessos} de ${g.METODO_ATUAL.n}` },
            { rotulo: "Amostra aleatória", valor: g.AMOSTRA_ALEATORIA.valor, ic: g.AMOSTRA_ALEATORIA.ic95, cor: "var(--color-tinta-3)", dica: `${g.AMOSTRA_ALEATORIA.sucessos} de ${g.AMOSTRA_ALEATORIA.n}` },
          ]} />
        </div>
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        <Secao titulo="Receita recuperada por real investido (I2)"
               descricao="Aumento anual de faturamento das reclassificações aplicadas no período, dividido pelo custo da solução.">
          <div className="flex items-baseline gap-3">
            <span className="condensada text-4xl font-semibold tabular-nums">{I2.valor == null ? "—" : fmt.num(I2.valor, 2)}</span>
            <span className="text-sm text-tinta-2">reais recuperados para cada real investido</span>
          </div>
          <dl className="mt-4 grid grid-cols-2 gap-4 text-sm">
            <div><dt className="text-xs text-tinta-3">Receita recuperada por ano</dt><dd className="font-semibold">{fmt.reais0(I2.receita_recuperada_anual)}</dd></div>
            <div><dt className="text-xs text-tinta-3">Custo no período</dt><dd className="font-semibold">{fmt.reais0(I2.custo)}</dd></div>
          </dl>
          <p className="mt-3 text-xs text-tinta-3">{I2.reclassificacoes.length} reclassificação(ões) aplicada(s) nos últimos 12 meses. Custo: {I2.origem_custo}.</p>
        </Secao>

        <Secao titulo="Cobertura da Tarifa Social (I3)"
               descricao="Economias na categoria Residencial Social em relação às famílias elegíveis do CadÚnico (renda até ½ salário mínimo por pessoa ou BPC).">
          <div className="flex items-baseline gap-3">
            <span className="condensada text-4xl font-semibold tabular-nums">{fmt.pct(I3.valor)}</span>
            <span className="text-sm text-tinta-2">das famílias elegíveis já têm o desconto</span>
          </div>
          <div className="mt-4 h-2.5 overflow-hidden rounded-full bg-fundo" role="img" aria-label={`Cobertura ${fmt.pct(I3.valor)} de 100%`}>
            <div className="h-full rounded-full bg-agua" style={{ width: `${Math.min(100, (I3.valor ?? 0) * 100)}%` }} />
          </div>
          <p className="mt-3 text-sm text-tinta-2">
            {I3.economias_residencial_social} economia(s) com o desconto para {I3.familias_elegiveis} família(s) elegível(is).
            {" "}{I3.alertas_abertos} alerta(s) em acompanhamento pela assistência social.
          </p>
        </Secao>

        <Secao titulo="Precisão e recall do modelo (I4)"
               descricao={`Precisão nos ${I4.k} primeiros da fila (10% das UCs ranqueadas) e recall estimado na amostra aleatória vistoriada.`}>
          <BarrasIC itens={[
            { rotulo: "Precisão@10%", valor: I4.precisao_at_k.valor, ic: I4.precisao_at_k.ic95, dica: `${I4.precisao_at_k.sucessos} de ${I4.precisao_at_k.n} vistoriadas no topo` },
            { rotulo: "Recall@10%", valor: I4.recall_at_k.valor, ic: I4.recall_at_k.ic95, dica: `${I4.recall_at_k.sucessos} de ${I4.recall_at_k.n} irregulares da amostra` },
            { rotulo: "Recall (p ≥ 50%)", valor: I4.recall_no_limiar.valor, ic: I4.recall_no_limiar.ic95 },
          ]} />
          <p className="mt-3 text-xs text-tinta-3">
            {I4.cobertura_rotulos_top_k != null && `${fmt.pct(I4.cobertura_rotulos_top_k)} do topo da fila já foi vistoriado. `}
            O recall só é confiável com vistorias da amostra aleatória (sorteada na fila).
          </p>
        </Secao>

        <Secao titulo="Equidade entre faixas de renda (I5)"
               descricao="Entre os imóveis indicados pelo Radar e vistoriados, quantos estavam com o cadastro correto (falso positivo), por faixa de renda do bairro.">
          <div className="mb-3 flex flex-wrap items-center gap-2 text-sm">
            <span className="text-tinta-2">Maior razão entre faixas: {I5.razao_max_min == null ? "—" : `${fmt.num(I5.razao_max_min, 2)}×`} (limite {fmt.num(I5.limite, 2)}×)</span>
            <Selo tom={I5.situacao === "revisar_modelo" ? "critico" : I5.situacao === "dentro_do_limite" ? "bom" : "neutro"}>
              {{ revisar_modelo: "Revisar o modelo", dentro_do_limite: "Dentro do limite", amostra_insuficiente: "Poucas vistorias por faixa" }[I5.situacao]}
            </Selo>
          </div>
          <BarrasIC itens={Object.keys(NOME_FAIXA).map((f) => ({
            rotulo: `Renda ${NOME_FAIXA[f].toLowerCase()}`, valor: I5.fdr_por_faixa[f]?.valor ?? null, ic: I5.fdr_por_faixa[f]?.ic95,
            dica: I5.fdr_por_faixa[f] ? `${I5.fdr_por_faixa[f].sucessos} de ${I5.fdr_por_faixa[f].n} indicadas` : "sem vistorias",
          }))} />
          <h3 className="mt-5 text-sm font-semibold">Quanto cada faixa aparece no topo da fila</h3>
          <BarrasIC itens={Object.keys(NOME_FAIXA).map((f) => ({
            rotulo: `Renda ${NOME_FAIXA[f].toLowerCase()}`, valor: I5.paridade_de_selecao.por_faixa[f]?.taxa_indicacao ?? null, cor: SERIE_2,
            dica: `${I5.paridade_de_selecao.por_faixa[f]?.indicadas_top_k ?? 0} de ${I5.paridade_de_selecao.por_faixa[f]?.ucs ?? 0} UCs no topo`,
          }))} />
          <p className="mt-3 text-xs text-tinta-3">Diferenças grandes de indicação entre faixas pedem auditoria antes de ampliar a fiscalização.</p>
        </Secao>
      </div>
    </>
  );
}
