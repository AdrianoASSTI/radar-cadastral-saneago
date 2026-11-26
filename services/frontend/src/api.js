// Cliente da API REST (FastAPI). Em produção o Nginx encaminha /api → api:8000.
import { createContext, useContext } from "react";

export const BASE = import.meta.env.VITE_API_URL || "/api";
const CHAVE = "radar.sessao";

export function sessaoSalva() {
  try { return JSON.parse(sessionStorage.getItem(CHAVE)); } catch { return null; }
}
export function salvarSessao(s) {
  try { s ? sessionStorage.setItem(CHAVE, JSON.stringify(s)) : sessionStorage.removeItem(CHAVE); } catch { /* modo privado */ }
}

export class ErroApi extends Error {
  constructor(status, detalhe) { super(detalhe); this.status = status; }
}

let aoExpirar = () => {};
export function definirAoExpirar(fn) { aoExpirar = fn; }

function token() { return sessaoSalva()?.token; }

export async function api(caminho, { metodo = "GET", corpo, bruto = false } = {}) {
  const r = await fetch(`${BASE}${caminho}`, {
    method: metodo,
    headers: { ...(corpo ? { "Content-Type": "application/json" } : {}),
               ...(token() ? { Authorization: `Bearer ${token()}` } : {}) },
    body: corpo ? JSON.stringify(corpo) : undefined,
  });
  if (r.status === 401 && token()) { aoExpirar(); throw new ErroApi(401, "Sessão expirada. Entre novamente."); }
  if (!r.ok) {
    let d = `Erro ${r.status}`;
    try { const j = await r.json(); d = typeof j.detail === "string" ? j.detail : (j.detail?.[0]?.msg ?? d); } catch { /* sem corpo */ }
    throw new ErroApi(r.status, d);
  }
  if (bruto) return r;
  return r.status === 204 ? null : r.json();
}

export async function entrar(usuario, senha) {
  const r = await fetch(`${BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ username: usuario, password: senha }),
  });
  if (!r.ok) throw new ErroApi(r.status, "Usuário ou senha incorretos.");
  const j = await r.json();
  return { token: j.access_token, usuario: j.usuario };
}

export const SessaoContexto = createContext(null);
export const useSessao = () => useContext(SessaoContexto);

// ----------------------------------------------------------------- formatação
const brl = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const brl0 = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 });
export const fmt = {
  reais: (v) => (v == null ? "—" : brl.format(v)),
  reais0: (v) => (v == null ? "—" : brl0.format(v)),
  pct: (v, casas = 0) => (v == null ? "—" : `${(v * 100).toLocaleString("pt-BR", { maximumFractionDigits: casas, minimumFractionDigits: casas })}%`),
  num: (v, casas = 0) => (v == null ? "—" : Number(v).toLocaleString("pt-BR", { maximumFractionDigits: casas, minimumFractionDigits: casas })),
  data: (v) => (v ? new Date(v).toLocaleDateString("pt-BR") : "—"),
  dataHora: (v) => (v ? new Date(v).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }) : "—"),
  mes: (v) => new Date(v + "T12:00:00").toLocaleDateString("pt-BR", { month: "short", year: "2-digit" }),
};

export const NOME_CATEGORIA = {
  RESIDENCIAL_SOCIAL: "Residencial Social", RESIDENCIAL_NORMAL: "Residencial", COMERCIAL_I: "Comercial I",
  COMERCIAL_II: "Comercial II", INDUSTRIAL: "Industrial", PUBLICA: "Pública", RESIDENCIAL: "Residencial",
};
export const NOME_FAIXA = { ALTA: "Alta", MEDIA_ALTA: "Média-alta", MEDIA: "Média", BAIXA: "Baixa" };
export const NOME_CLASSE = {
  placa_comercial: "Placa comercial", letreiro: "Letreiro", vitrine: "Vitrine", banner: "Faixa/banner",
  portao_industrial: "Portão industrial", doca_carga: "Doca de carga", estacionamento_clientes: "Estacionamento",
};
export const NOME_PERFIL = {
  ANALISTA: "Analista", FISCAL: "Fiscal de campo", SUPERVISOR: "Supervisão", GESTOR: "Gestão",
  ASSISTENTE_SOCIAL: "Assistência social",
};
