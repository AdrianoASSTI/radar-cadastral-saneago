import { useState } from "react";
import { entrar, NOME_PERFIL, useSessao } from "../api";
import { Aviso, Botao, Campo, estiloEntrada } from "../componentes/ui";

// Contas de demonstração do MVP (senha = usuário + "123"); em produção, login institucional.
const DEMO = [
  { u: "analista", p: "ANALISTA", faz: "monta a fila e gera ordens de vistoria" },
  { u: "fiscal", p: "FISCAL", faz: "vistoria o imóvel e registra o laudo" },
  { u: "supervisor", p: "SUPERVISOR", faz: "decide e aplica a reclassificação" },
  { u: "gestor", p: "GESTOR", faz: "acompanha os indicadores" },
  { u: "social", p: "ASSISTENTE_SOCIAL", faz: "inclui famílias na Tarifa Social" },
];

export default function Login() {
  const { entrar: guardar } = useSessao();
  const [usuario, setUsuario] = useState("");
  const [senha, setSenha] = useState("");
  const [erro, setErro] = useState(null);
  const [enviando, setEnviando] = useState(false);

  async function enviar(e) {
    e.preventDefault();
    setErro(null); setEnviando(true);
    try { guardar(await entrar(usuario, senha)); }
    catch (x) { setErro(x.message); }
    finally { setEnviando(false); }
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
      <section className="relative flex flex-col justify-between overflow-hidden bg-agua-escura px-8 py-10 text-white lg:px-14">
        <div className="flex items-center gap-2.5">
          <img src="/icone.svg" alt="" className="h-9 w-9 rounded-md ring-1 ring-white/30" />
          <span className="expandida text-lg font-semibold">Radar Cadastral</span>
        </div>
        <div className="my-16 max-w-xl">
          <h1 className="expandida text-4xl font-semibold leading-[1.1] lg:text-5xl">
            O sistema aponta onde olhar. Quem decide a categoria é uma pessoa.
          </h1>
          <p className="mt-5 max-w-[60ch] text-[17px] leading-relaxed text-white/80">
            Fotos de fachada, consumo e bases públicas viram uma fila de vistoria ordenada pelo ganho esperado.
            Nenhuma tarifa muda sem laudo de campo e aprovação de um supervisor; famílias elegíveis à Tarifa
            Social são encontradas antes de pedirem.
          </p>
        </div>
        <p className="text-sm text-white/60">Projeto Integrador SENAI FATESG. Protótipo com dados sintéticos.</p>
        <svg viewBox="0 0 400 400" className="pointer-events-none absolute -right-24 -bottom-24 w-[28rem] opacity-[0.08]" aria-hidden="true">
          {[60, 110, 160, 210].map((r) => <circle key={r} cx="200" cy="200" r={r} fill="none" stroke="#fff" strokeWidth="2" />)}
          <path d="M200 200L380 120" stroke="#fff" strokeWidth="3" />
        </svg>
      </section>

      <section className="flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-sm">
          <h2 className="text-xl font-semibold">Entrar</h2>
          <form onSubmit={enviar} className="mt-6 space-y-4">
            <Campo rotulo="Usuário">
              <input className={estiloEntrada} value={usuario} onChange={(e) => setUsuario(e.target.value)}
                     autoComplete="username" required autoFocus />
            </Campo>
            <Campo rotulo="Senha">
              <input className={estiloEntrada} type="password" value={senha} onChange={(e) => setSenha(e.target.value)}
                     autoComplete="current-password" required />
            </Campo>
            {erro && <Aviso>{erro}</Aviso>}
            <Botao type="submit" disabled={enviando} className="w-full">{enviando ? "Entrando…" : "Entrar"}</Botao>
          </form>

          <div className="mt-10">
            <h3 className="text-sm font-medium text-tinta-2">Contas de demonstração</h3>
            <ul className="mt-3 divide-y divide-linha rounded-lg border border-linha bg-superficie">
              {DEMO.map((d) => (
                <li key={d.u}>
                  <button type="button" onClick={() => { setUsuario(d.u); setSenha(`${d.u}123`); }}
                          className="flex w-full items-baseline justify-between gap-3 px-3.5 py-2.5 text-left hover:bg-fundo">
                    <span>
                      <span className="block text-sm font-medium">{NOME_PERFIL[d.p]}</span>
                      <span className="block text-xs text-tinta-3">{d.faz}</span>
                    </span>
                    <span className="text-xs text-agua">usar</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>
    </div>
  );
}
