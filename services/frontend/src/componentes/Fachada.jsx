// Visor da fachada: imagem JÁ anonimizada + detecções do YOLO desenhadas como
// anotação de levantamento (contorno tracejado com marcas de canto).
import { useEffect, useState } from "react";
import { api, fmt, NOME_CLASSE } from "../api";

const CANTO = 0.035; // tamanho das marcas de canto (fração da largura)

export default function Fachada({ imagem, deteccoes = [], desatualizada }) {
  const [url, setUrl] = useState(null);
  const [erro, setErro] = useState(null);
  const [foco, setFoco] = useState(null);

  useEffect(() => {
    if (!imagem?.id) return;
    let vivo = true, obj;
    setUrl(null); setErro(null);
    api(`/ucs/imagens/${imagem.id}`, { bruto: true })
      .then((r) => r.blob())
      .then((b) => { if (vivo) { obj = URL.createObjectURL(b); setUrl(obj); } })
      .catch((e) => vivo && setErro(e.status === 410 ? "A foto foi apagada ao fim do prazo de retenção (LGPD)." : e.message));
    return () => { vivo = false; if (obj) URL.revokeObjectURL(obj); };
  }, [imagem?.id]);

  if (!imagem) {
    return (
      <div className="flex aspect-[4/3] flex-col items-center justify-center rounded-md border border-dashed border-linha-forte bg-fundo px-6 text-center">
        <p className="font-medium">Sem foto recente desta fachada</p>
        <p className="mt-1 max-w-sm text-sm text-tinta-2">
          Nenhuma fonte tem imagem com menos de 18 meses. Peça uma foto ao leiturista na próxima leitura;
          até lá, a análise usa só consumo e bases públicas.
        </p>
      </div>
    );
  }

  const prop = imagem.altura_px && imagem.largura_px ? imagem.altura_px / imagem.largura_px : 0.75;

  return (
    <figure>
      <div className="relative overflow-hidden rounded-md bg-tinta">
        {url ? <img src={url} alt="Fachada do imóvel com rostos e placas de veículos borrados" className="block w-full" />
             : <div className="aspect-[4/3]" />}
        {url && (
          <svg viewBox={`0 0 1 ${prop}`} preserveAspectRatio="none" className="absolute inset-0 h-full w-full" aria-hidden="true">
            {deteccoes.map((d, i) => {
              const x1 = d.bbox_x1, y1 = d.bbox_y1 * prop, x2 = d.bbox_x2, y2 = d.bbox_y2 * prop;
              const ativo = foco === null || foco === i;
              const c = Math.min(CANTO, (x2 - x1) / 3, (y2 - y1) / 3);
              const cantos = `M${x1},${y1 + c}V${y1}H${x1 + c} M${x2 - c},${y1}H${x2}V${y1 + c} M${x2},${y2 - c}V${y2}H${x2 - c} M${x1 + c},${y2}H${x1}V${y2 - c}`;
              return (
                <g key={i} opacity={ativo ? 1 : 0.25}>
                  <rect x={x1} y={y1} width={x2 - x1} height={y2 - y1} fill={foco === i ? "rgba(255,255,255,.12)" : "none"}
                        stroke="#ffffff" strokeWidth="1.5" className="anotacao" vectorEffect="non-scaling-stroke" />
                  <path d={cantos} fill="none" stroke="#ffd166" strokeWidth="3" vectorEffect="non-scaling-stroke" />
                </g>
              );
            })}
          </svg>
        )}
        {url && deteccoes.map((d, i) => (
          <span key={i} className="pointer-events-none absolute -translate-y-full rounded-sm bg-tinta/85 px-1.5 py-0.5 text-[11px] font-medium text-white"
                style={{ left: `${d.bbox_x1 * 100}%`, top: `${d.bbox_y1 * 100}%`, opacity: foco === null || foco === i ? 1 : 0.25 }}>
            {NOME_CLASSE[d.classe] ?? d.classe} {Math.round(d.confianca * 100)}%
          </span>
        ))}
        {erro && <p className="absolute inset-x-0 bottom-0 bg-critico px-3 py-2 text-sm text-white">{erro}</p>}
      </div>
      <figcaption className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-tinta-2">
        <span>Fonte: {imagem.fonte === "LEITURISTA" ? "foto do leiturista" : imagem.fonte === "MAPILLARY" ? "Mapillary (CC BY-SA)" : imagem.fonte}</span>
        <span>Capturada em {fmt.data(imagem.capturada_em)}</span>
        <span>{imagem.rostos_borrados} rosto(s) e {imagem.placas_borradas} placa(s) borrados</span>
        <span>Será apagada em {fmt.data(imagem.expira_em)}</span>
        {desatualizada && <span className="font-medium text-atencao">Foto com mais de 18 meses</span>}
      </figcaption>
      {deteccoes.length > 0 && (
        <ul className="mt-3 flex flex-wrap gap-1.5" aria-label="Elementos detectados na fachada">
          {deteccoes.map((d, i) => (
            <li key={i}>
              <button type="button" onMouseEnter={() => setFoco(i)} onMouseLeave={() => setFoco(null)}
                      onFocus={() => setFoco(i)} onBlur={() => setFoco(null)}
                      className="rounded-full border border-linha-forte px-2.5 py-1 text-xs hover:border-agua">
                {NOME_CLASSE[d.classe] ?? d.classe} {Math.round(d.confianca * 100)}%
              </button>
            </li>
          ))}
        </ul>
      )}
    </figure>
  );
}
