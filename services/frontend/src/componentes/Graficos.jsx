// Gráficos em SVG (sem biblioteca): marcas finas, grade recessiva, rótulos diretos
// seletivos e tooltip ao passar o mouse. Cores: paleta categórica validada.
import { useId, useState } from "react";
import { fmt } from "../api";

const SERIE_1 = "var(--color-serie-1)";
const SERIE_2 = "var(--color-serie-2)";

/* ------------------------------------------------------------------ fatores (XAI)
   Barras divergentes: contribuição de cada atributo, em log-odds, para a classe
   explicada. Laranja = empurra para "uso não residencial"; azul = afasta. */
export function Fatores({ fatores = [] }) {
  const max = Math.max(0.01, ...fatores.map((f) => Math.abs(f.contribuicao)));
  return (
    <div>
      <ul className="space-y-1.5">
        {fatores.map((f) => {
          const w = (Math.abs(f.contribuicao) / max) * 50;
          const pos = f.contribuicao >= 0;
          return (
            <li key={f.fator} className="grid grid-cols-[minmax(0,1fr)_minmax(0,0.8fr)_3.2rem] items-center gap-3 text-sm"
                title={`${f.descricao}: valor ${f.valor}; contribuição ${f.contribuicao > 0 ? "+" : ""}${f.contribuicao}`}>
              <span className="truncate text-tinta-2">{f.descricao}</span>
              <span className="relative h-3.5">
                <span className="absolute inset-y-0 left-1/2 w-px bg-linha-forte" aria-hidden="true" />
                <span className="absolute inset-y-0.5 rounded-sm"
                      style={{ left: pos ? "50%" : `${50 - w}%`, width: `${Math.max(w, 0.6)}%`,
                               background: pos ? SERIE_2 : SERIE_1 }} />
              </span>
              <span className="text-right text-xs tabular-nums text-tinta-2">{pos ? "+" : "−"}{fmt.num(Math.abs(f.contribuicao), 2)}</span>
            </li>
          );
        })}
      </ul>
      <div className="mt-3 flex gap-4 text-xs text-tinta-2">
        <span className="inline-flex items-center gap-1.5"><i className="h-2.5 w-2.5 rounded-sm" style={{ background: SERIE_2 }} />Aumenta a chance de uso não declarado</span>
        <span className="inline-flex items-center gap-1.5"><i className="h-2.5 w-2.5 rounded-sm" style={{ background: SERIE_1 }} />Diminui</span>
        <span className="ml-auto">contribuição em log-odds</span>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ série de consumo */
export function SerieConsumo({ consumo = [], altura = 150 }) {
  const [hover, setHover] = useState(null);
  const id = useId();
  if (!consumo.length) return null;
  const L = 560, A = altura, mx = 34, my = 14;
  const vs = consumo.map((c) => Number(c.volume_m3));
  const vmax = Math.max(10, ...vs) * 1.1;
  const x = (i) => mx + (i / Math.max(1, consumo.length - 1)) * (L - mx - 8);
  const y = (v) => A - my - (v / vmax) * (A - 2 * my);
  const d = vs.map((v, i) => `${i ? "L" : "M"}${x(i)},${y(v)}`).join("");
  const marcas = [0, Math.round(vmax / 2), Math.round(vmax / 1.1)];
  return (
    <div className="relative">
      <svg viewBox={`0 0 ${L} ${A}`} className="w-full" role="img" aria-labelledby={id}
           onMouseLeave={() => setHover(null)}>
        <title id={id}>Consumo mensal dos últimos {consumo.length} meses, em metros cúbicos</title>
        {marcas.map((m) => (
          <g key={m}>
            <line x1={mx} x2={L - 8} y1={y(m)} y2={y(m)} stroke="var(--color-linha)" strokeWidth="1" />
            <text x={mx - 6} y={y(m) + 4} textAnchor="end" fontSize="11" fill="var(--color-tinta-3)">{m}</text>
          </g>
        ))}
        <path d={d} fill="none" stroke={SERIE_1} strokeWidth="2" strokeLinejoin="round" />
        {consumo.map((c, i) => c.tipo_leitura === "ESTIMADA" && (
          <circle key={i} cx={x(i)} cy={y(vs[i])} r="4" fill="var(--color-superficie)" stroke={SERIE_1} strokeWidth="2" />
        ))}
        {[0, Math.floor(consumo.length / 2), consumo.length - 1].map((i) => (
          <text key={i} x={x(i)} y={A - 1} textAnchor={i === 0 ? "start" : i === consumo.length - 1 ? "end" : "middle"}
                fontSize="11" fill="var(--color-tinta-3)">{fmt.mes(consumo[i].competencia)}</text>
        ))}
        {hover !== null && (
          <g>
            <line x1={x(hover)} x2={x(hover)} y1={my} y2={A - my} stroke="var(--color-tinta-3)" strokeWidth="1" />
            <circle cx={x(hover)} cy={y(vs[hover])} r="4.5" fill={SERIE_1} stroke="var(--color-superficie)" strokeWidth="2" />
          </g>
        )}
        {consumo.map((_, i) => (
          <rect key={i} x={x(i) - (L / consumo.length) / 2} y="0" width={L / consumo.length} height={A}
                fill="transparent" onMouseEnter={() => setHover(i)} />
        ))}
      </svg>
      {hover !== null && (
        <div className="pointer-events-none absolute top-0 rounded-md border border-linha bg-superficie px-2.5 py-1.5 text-xs shadow-sm"
             style={{ left: `${Math.min(80, (x(hover) / L) * 100)}%` }}>
          <div className="font-medium">{fmt.mes(consumo[hover].competencia)}</div>
          <div>{fmt.num(vs[hover])} m³{consumo[hover].tipo_leitura === "ESTIMADA" ? " (estimada)" : ""}</div>
        </div>
      )}
      <p className="mt-1 text-xs text-tinta-3">Metros cúbicos por mês. Círculos vazados são leituras estimadas.</p>
    </div>
  );
}

/* ------------------------------------------------------------------ barras com IC 95%
   Barras horizontais de proporção (0–1) com bigode do intervalo de confiança,
   linha de referência opcional (meta/limite) e rótulo direto do valor. */
export function BarrasIC({ itens, referencia, rotuloReferencia, cor = SERIE_1, formato = (v) => fmt.pct(v) }) {
  const [hover, setHover] = useState(null);
  const max = Math.max(0.05, referencia ?? 0, ...itens.map((i) => i.ic?.[1] ?? i.valor ?? 0)) * 1.08;
  const pc = (v) => `${(v / max) * 100}%`;
  return (
    <div className="space-y-3">
      {itens.map((it, k) => (
        <div key={it.rotulo} className="grid grid-cols-[8.5rem_minmax(0,1fr)_4.5rem] items-center gap-3 text-sm"
             onMouseEnter={() => setHover(k)} onMouseLeave={() => setHover(null)}>
          <span className="text-tinta-2">{it.rotulo}</span>
          <span className="relative h-5">
            <span className="absolute inset-y-0 left-0 w-px bg-linha-forte" />
            {it.valor != null && (
              <span className="absolute inset-y-1 left-0 rounded-r-[4px]" style={{ width: pc(it.valor), background: it.cor ?? cor }} />
            )}
            {it.ic && (
              <span className="absolute top-1/2 h-px bg-tinta" style={{ left: pc(it.ic[0]), width: `calc(${pc(it.ic[1])} - ${pc(it.ic[0])})` }}>
                <span className="absolute -top-1 left-0 h-2 w-px bg-tinta" />
                <span className="absolute -top-1 right-0 h-2 w-px bg-tinta" />
              </span>
            )}
            {referencia != null && (
              <span className="absolute -inset-y-1 w-0 border-l border-dashed border-critico" style={{ left: pc(referencia) }} />
            )}
            {hover === k && it.dica && (
              <span className="absolute -top-8 left-0 z-10 whitespace-nowrap rounded-md border border-linha bg-superficie px-2 py-1 text-xs shadow-sm">
                {it.dica}
              </span>
            )}
          </span>
          <span className="text-right font-medium tabular-nums">{it.valor == null ? "—" : formato(it.valor)}</span>
        </div>
      ))}
      {referencia != null && rotuloReferencia && (
        <p className="flex items-center gap-2 text-xs text-tinta-2">
          <span className="h-3 w-0 border-l border-dashed border-critico" /> {rotuloReferencia}
        </p>
      )}
    </div>
  );
}
