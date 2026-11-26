# Frontend — Radar Cadastral SANEAGO

React 19 + Vite + Tailwind v4. Servido pelo Nginx no contêiner `frontend`
(http://localhost:5173), que também repassa `/api/*` para a API.

## Telas por perfil

| Tela | Perfis | O que faz |
|---|---|---|
| Fila de vistoria | analista, supervisor, gestor | ranking por ganho esperado, explicação (SHAP), fachada anonimizada com detecções, links Street View/Maps/Geo360 (só visualização humana), geração de ordens e amostra aleatória |
| Vistorias | fiscal, supervisor, analista | laudo de campo (o fiscal não vê probabilidade nem origem), decisão do supervisor com prazo de contestação, aplicação da reclassificação |
| Indicadores | gestor, analista, supervisor | I1–I5 com intervalos de Wilson |
| Processamento | analista, supervisor, gestor | lotes de coleta + IA (sequencial/paralelo) |
| Tarifa Social | assistente social | cruzamento CadÚnico × cadastro, acompanhamento e aplicação do desconto |
| Auditoria | supervisor, gestor | trilha imutável de eventos |

Contas de demonstração: `analista`, `fiscal`, `supervisor`, `gestor`, `social` (senha = login + `123`).

## Desenvolvimento sem Docker

```bash
cd services/frontend
npm install
npm run dev        # http://localhost:5173, com proxy /api → http://localhost:8000
```
