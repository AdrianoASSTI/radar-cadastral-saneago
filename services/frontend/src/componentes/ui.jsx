// Primitivas de interface: botões, selos de estado, seções, estados vazios e de erro.

export function Botao({ variante = "primario", className = "", ...p }) {
  const base = "inline-flex items-center justify-center gap-2 rounded-md px-3.5 py-2 text-sm font-medium " +
    "transition-colors disabled:cursor-not-allowed disabled:opacity-50";
  const v = {
    primario: "bg-agua text-white hover:bg-agua-escura",
    secundario: "border border-linha-forte bg-superficie text-tinta hover:border-agua hover:text-agua",
    fantasma: "text-agua hover:bg-agua-clara",
    perigo: "bg-critico text-white hover:brightness-95",
  }[variante];
  return <button className={`${base} ${v} ${className}`} {...p} />;
}

const ICONES = {
  bom: <path d="M3.5 8.5l3 3 6-7" />,
  atencao: <path d="M8 3.5v5.5M8 11.6v.4" />,
  critico: <path d="M4.5 4.5l7 7M11.5 4.5l-7 7" />,
  neutro: <circle cx="8" cy="8" r="2.2" />,
};
const COR_SELO = {
  bom: "bg-bom-fundo text-bom", atencao: "bg-atencao-fundo text-atencao",
  critico: "bg-critico-fundo text-critico", neutro: "bg-fundo text-tinta-2", agua: "bg-agua-clara text-agua-escura",
};

/** Selo de estado: cor reservada + ícone + rótulo (nunca só a cor). */
export function Selo({ tom = "neutro", children }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${COR_SELO[tom]}`}>
      <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="2"
           strokeLinecap="round" aria-hidden="true">{ICONES[tom] ?? ICONES.neutro}</svg>
      {children}
    </span>
  );
}

export function Secao({ titulo, descricao, acoes, children, className = "" }) {
  return (
    <section className={`rounded-lg border border-linha bg-superficie ${className}`}>
      {(titulo || acoes) && (
        <header className="flex flex-wrap items-start justify-between gap-3 border-b border-linha px-5 py-3.5">
          <div>
            <h2 className="text-[15px] font-semibold">{titulo}</h2>
            {descricao && <p className="mt-0.5 max-w-prose text-sm text-tinta-2">{descricao}</p>}
          </div>
          {acoes}
        </header>
      )}
      <div className="p-5">{children}</div>
    </section>
  );
}

export function Cabecalho({ titulo, descricao, children }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="expandida text-2xl font-semibold tracking-tight">{titulo}</h1>
        {descricao && <p className="mt-1 max-w-[68ch] text-[15px] text-tinta-2">{descricao}</p>}
      </div>
      {children}
    </div>
  );
}

export function Carregando({ texto = "Carregando…" }) {
  return (
    <div role="status" className="flex items-center gap-2 py-6 text-sm text-tinta-3">
      <span className="h-2 w-2 animate-pulse rounded-full bg-agua" /> {texto}
    </div>
  );
}

export function Aviso({ tom = "critico", children }) {
  const c = { critico: "border-critico/30 bg-critico-fundo text-critico", atencao: "border-atencao/30 bg-atencao-fundo text-atencao",
              bom: "border-bom/30 bg-bom-fundo text-bom", agua: "border-agua/30 bg-agua-clara text-agua-escura" }[tom];
  return <div role={tom === "critico" ? "alert" : "status"} className={`rounded-md border px-3.5 py-2.5 text-sm ${c}`}>{children}</div>;
}

export function Vazio({ titulo, children }) {
  return (
    <div className="rounded-lg border border-dashed border-linha-forte px-6 py-10 text-center">
      <p className="font-medium">{titulo}</p>
      {children && <div className="mx-auto mt-1 max-w-prose text-sm text-tinta-2">{children}</div>}
    </div>
  );
}

export function Campo({ rotulo, children, dica }) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="font-medium text-tinta-2">{rotulo}</span>
      {children}
      {dica && <span className="text-xs text-tinta-3">{dica}</span>}
    </label>
  );
}

export const estiloEntrada =
  "rounded-md border border-linha-forte bg-superficie px-2.5 py-1.5 text-sm text-tinta focus:border-agua focus:outline-none";

/** Barra de probabilidade compacta (0–1), com o valor em texto ao lado. */
export function BarraProb({ valor }) {
  return (
    <span className="inline-flex items-center gap-2">
      <span className="h-1.5 w-16 overflow-hidden rounded-full bg-fundo" aria-hidden="true">
        <span className="block h-full rounded-full bg-agua" style={{ width: `${Math.round(valor * 100)}%` }} />
      </span>
      <span className="w-9 text-right text-sm tabular-nums">{Math.round(valor * 100)}%</span>
    </span>
  );
}
