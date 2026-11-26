// Estrutura do aplicativo: sessão, rotas por perfil e moldura (navegação + estado do sistema).
import { useEffect, useMemo, useState } from "react";
import { BrowserRouter, Navigate, NavLink, Route, Routes } from "react-router-dom";
import { api, definirAoExpirar, NOME_PERFIL, salvarSessao, sessaoSalva, SessaoContexto, useSessao } from "./api";
import Login from "./paginas/Login";
import Painel from "./paginas/Painel";
import Fila from "./paginas/Fila";
import Vistorias from "./paginas/Vistorias";
import Processamento from "./paginas/Processamento";
import TarifaSocial from "./paginas/TarifaSocial";
import Auditoria from "./paginas/Auditoria";

// Quem vê o quê (a API e o banco reforçam as mesmas regras)
const PAGINAS = [
  { rota: "/fila", nome: "Fila de vistoria", el: <Fila />, perfis: ["ANALISTA", "SUPERVISOR", "GESTOR"] },
  { rota: "/vistorias", nome: "Vistorias", el: <Vistorias />, perfis: ["FISCAL", "SUPERVISOR", "ANALISTA"] },
  { rota: "/painel", nome: "Indicadores", el: <Painel />, perfis: ["GESTOR", "ANALISTA", "SUPERVISOR"] },
  { rota: "/processamento", nome: "Processamento", el: <Processamento />, perfis: ["ANALISTA", "SUPERVISOR", "GESTOR"] },
  { rota: "/tarifa-social", nome: "Tarifa Social", el: <TarifaSocial />, perfis: ["ASSISTENTE_SOCIAL"] },
  { rota: "/auditoria", nome: "Auditoria", el: <Auditoria />, perfis: ["SUPERVISOR", "GESTOR"] },
];

function EstadoSistema() {
  const [s, setS] = useState(null);
  useEffect(() => {
    let vivo = true;
    const ler = () => api("/saude").then((r) => vivo && setS(r)).catch(() => vivo && setS({ api: "erro" }));
    ler();
    const t = setInterval(ler, 15000);
    return () => { vivo = false; clearInterval(t); };
  }, []);
  if (!s) return null;
  const ok = s.banco === "ok" && s.rabbitmq === "ok";
  const pendentes = Object.entries(s.filas ?? {}).filter(([n]) => !n.includes("resultados")).reduce((a, [, v]) => a + v, 0);
  return (
    <div className="flex items-center gap-2 text-xs text-tinta-2" title={JSON.stringify(s, null, 1)}>
      <span className={`h-2 w-2 rounded-full ${ok ? "bg-bom" : "bg-critico"}`} aria-hidden="true" />
      {ok ? "Sistema operando" : "Serviço indisponível"}
      {ok && pendentes > 0 && <span className="text-tinta-3">{pendentes} UC(s) em processamento</span>}
    </div>
  );
}

function Moldura({ children }) {
  const { sessao, sair } = useSessao();
  const visiveis = PAGINAS.filter((p) => p.perfis.includes(sessao.usuario.perfil));
  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[15rem_minmax(0,1fr)]">
      <aside className="border-b border-linha bg-superficie lg:sticky lg:top-0 lg:h-screen lg:border-r lg:border-b-0">
        <div className="flex items-center gap-2.5 px-5 py-5">
          <img src="/icone.svg" alt="" className="h-8 w-8" />
          <div className="leading-tight">
            <div className="expandida font-semibold">Radar Cadastral</div>
            <div className="text-xs text-tinta-3">Atualização de categorias</div>
          </div>
        </div>
        <nav aria-label="Principal" className="flex gap-1 overflow-x-auto px-3 pb-3 lg:flex-col lg:pb-0">
          {visiveis.map((p) => (
            <NavLink key={p.rota} to={p.rota}
              className={({ isActive }) => `whitespace-nowrap rounded-md px-3 py-2 text-sm ${isActive
                ? "bg-agua-clara font-semibold text-agua-escura" : "text-tinta-2 hover:bg-fundo hover:text-tinta"}`}>
              {p.nome}
            </NavLink>
          ))}
        </nav>
        <div className="hidden border-t border-linha px-5 py-4 lg:absolute lg:inset-x-0 lg:bottom-0 lg:block">
          <div className="text-sm font-medium">{sessao.usuario.nome}</div>
          <div className="text-xs text-tinta-3">{NOME_PERFIL[sessao.usuario.perfil]}, matrícula {sessao.usuario.matricula}</div>
          <button onClick={sair} className="mt-2 text-sm text-agua hover:underline">Sair</button>
        </div>
      </aside>
      <div className="min-w-0">
        <div className="flex items-center justify-between gap-4 border-b border-linha bg-superficie/60 px-6 py-2.5 lg:px-10">
          <EstadoSistema />
          <button onClick={sair} className="text-sm text-agua hover:underline lg:hidden">Sair ({sessao.usuario.nome})</button>
        </div>
        <main className="px-6 py-8 lg:px-10">{children}</main>
      </div>
    </div>
  );
}

export default function App() {
  const [sessao, setSessao] = useState(sessaoSalva);
  const ctx = useMemo(() => ({
    sessao,
    entrar: (s) => { salvarSessao(s); setSessao(s); },
    sair: () => { salvarSessao(null); setSessao(null); },
  }), [sessao]);
  useEffect(() => definirAoExpirar(() => ctx.sair()), [ctx]);

  if (!sessao) return <SessaoContexto.Provider value={ctx}><Login /></SessaoContexto.Provider>;

  const permitidas = PAGINAS.filter((p) => p.perfis.includes(sessao.usuario.perfil));
  return (
    <SessaoContexto.Provider value={ctx}>
      <BrowserRouter>
        <Moldura>
          <Routes>
            {permitidas.map((p) => <Route key={p.rota} path={p.rota} element={p.el} />)}
            <Route path="*" element={<Navigate to={permitidas[0]?.rota ?? "/"} replace />} />
          </Routes>
        </Moldura>
      </BrowserRouter>
    </SessaoContexto.Provider>
  );
}
