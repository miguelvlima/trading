# IBKR Gateway — descobertas empíricas (Fase 0 do Paper Trading)

**Data das sondagens:** 2026-07-08, 22:38–22:41 UTC (mercado US em after-hours; RTH é 13:30–20:00 UTC no verão)
**Ferramenta:** `backend/app/scripts/probe_gateway.py` (novo; read-only, só market data, zero chamadas de ordens)
**Ambiente:** IB Gateway local em `127.0.0.1:4001`, `ib_insync 0.9.86`, ligação `readonly=True`

Como repetir (idealmente com o mercado aberto, para taxas de ticks representativas):

```powershell
cd backend
.venv/Scripts/python.exe -m app.scripts.probe_gateway --duration 60 --md-type 3
```

---

## 1. Conta e segurança — ⚠️ descoberta mais importante

- O Gateway está ligado à conta **`U26609700` — uma conta REAL (live)**. Contas paper têm prefixo `DU…`. A porta configurada no `.env` é a **4001 (live)**, não a 4002 (paper) que é o default do `config.py`.
- Toda a ligação da app é `readonly=True` (provider e sondagem), portanto **nenhuma ordem pode ser enviada por esta via** — mas o invariante PAPER desta fase deixa de ser só disciplina de código e passa a ser proteção contra dinheiro real.
- **Recomendação:** correr o Gateway com o login paper (porta 4002) para este projeto. Independentemente disso, o paper engine não importa nenhuma API de ordens (`placeOrder`, `Order`, etc.) — e deve haver um teste que o garante.

## 2. Entitlements de dados: só dados ATRASADOS (15 min)

- Com `reqMarketDataType(1)` (live): **zero ticks** em 60 s e erro `10089` por símbolo ("os dados solicitados exigem outra inscrição… dados atrasados estão disponíveis"). O pedido live não degrada sozinho — simplesmente não chega nada.
- Com `reqMarketDataType(3)` (delayed): ticks a fluir, todos marcados `DELAYED`. Isto confirma o default de produção `IBKR_MARKET_DATA_TYPE=3`.
- **Consequência de desenho:** todos os preços que o paper engine vê têm ~15 minutos de atraso. Cada fill simulado, evento e snapshot tem de registar `data_liveness=DELAYED`, e o cockpit tem de o mostrar de forma permanente. Um "fill ao preço do feed" é um fill a um preço com 15 min — aceitável para paper trading pedagógico, inaceitável de esconder.

## 3. O que chega realmente nos ticks (delayed, after-hours, 60 s)

| Símbolo | Updates | Updates/s | last | bid/ask | sizes | Spread mediano (bps) | Intervalo mediano | Gap máx |
|---|---|---|---|---|---|---|---|---|
| AAPL | 8 | 0,13 | 75% | 62,5% | 62,5–75% | 5,4 | 1,4 s | 28,0 s |
| MSFT | 7 | 0,12 | 100% | 57,1% | 57,1–100% | 6,0 | ~0 s (bursts) | 24,4 s |
| NVDA | 14 | 0,23 | 85,7% | 78,6% | 78,6–85,7% | 4,4 | 3,0 s | 14,1 s |
| SPY | 13 | 0,22 | 100% | 76,9% | 76,9–100% | 1,2 | 3,0 s | 15,0 s |

Notas:

- **bid/ask chegam e são plausíveis** (com tamanhos). A presença <100% é o arranque da subscrição: os campos chegam em eventos separados e o `Ticker` do ib_insync funde-os num snapshot; passados 2–3 eventos há quase sempre bid+ask+last coerentes.
- **Spreads after-hours:** ~4–6 bps em AAPL/MSFT/NVDA, ~1 bps em SPY. Em RTH serão mais apertados. São utilizáveis para fills a bid/ask.
- **Frequência:** um update a cada ~3–8 s (mediana) com gaps até ~30 s **fora de horas**. Em RTH espera-se muito mais denso, mas o desenho tem de tolerar gaps de dezenas de segundos sem declarar o feed morto.
- **`volume` acumulado do stream delayed vem corrompido** (ex.: AAPL `41 300 460 499 375`) — não usar volume de ticks para nada; volume relativo vem das barras persistidas em `market_bars`.
- `halted` nunca veio preenchido no delayed.

## 4. Timestamps do broker NÃO são fiáveis para o ledger

`ticker.time` == hora local de receção (diferença medida: 0,000–0,001 s em >40 amostras). Ou seja, o ib_insync está a carimbar com o relógio local na chegada — **não há timestamp de exchange utilizável no stream delayed**.

**Consequência:** o ledger (`PaperEngineEvent`, fills) usa o relógio local em UTC como fonte de verdade, e cada fill guarda a **idade da cotação usada** (agora − timestamp do último tick) em vez de fingir precisão de exchange.

## 5. Ligação, reconexão e ruído

- Connect: 0,20–0,31 s. Reconnect (disconnect limpo → connect): **0,50 s**. O Gateway aguenta reconexões rápidas sem estado pendurado.
- O provider existente (`IBKRProvider`/`IBKRStreamingProvider`) já: reconecta lazily com backoff (`PacingThrottle`), roda client IDs por sessão WS (evita erro 326), nunca deixa morrer o worker. Nada disto precisa de ser alterado para o paper engine.
- Mensagens `2104/2106/2158` ("conexão do centro de dados OK") chegam ao ligar e repetem-se periodicamente — são **informativas**, não erros; o ledger não deve tratá-las como falhas. O `10089` deve ser exposto como "só dados atrasados", não como erro fatal.
- Sem Gateway: o fallback é o provider `yfinance` (polling REST) + últimas barras na BD — sem ticks, sem bid/ask. Nesse modo o paper engine **não deve dar fills**: ordens aprovadas ficam paradas com motivo `feed_unavailable`, registado em evento.

## 6. Como isto muda o desenho do engine

1. **Modelo de fill principal: bid/ask, não last+slippage.** BUY preenche ao `ask`, SELL ao `bid` — o custo do spread fica capturado naturalmente. Condições: o último tick do símbolo tem bid+ask válidos, idade ≤ limiar de frescura, spread ≤ teto de sanidade (p. ex. 50 bps). **Fallback:** `last` + modelo de slippage do backtest (reutilizado via execution_engine). Fees: `commission_models.ibkr_us_tiered` (o mesmo do backtest).
2. **Frescura como pré-condição de fill, não só badge.** Sem tick fresco (limiar configurável; os gaps de ~30 s fora de horas mostram que 120 s é razoável em RTH) a ordem aprovada não é preenchida — fica em espera com evento `fill_deferred_stale_feed`. Fora de RTH, por omissão o engine não propõe nem preenche (configurável), porque delayed + liquidez fina tornam o fill irrealista.
3. **Tudo carimbado com liveness.** Ordens, fills e eventos carregam `market_data_type` (`DELAYED` hoje; `REALTIME` se um dia houver subscrição) + idade da cotação. A UI mostra "dados atrasados ~15 min" sempre que aplicável.
4. **Relógio local UTC no ledger** (ponto 4). O timestamp do tick usado fica guardado no payload do fill para auditoria.
5. **Volume de ticks ignorado** (ponto 3); sizing/risco usam preço, nunca volume do stream.
6. **Invariante PAPER com teste:** um teste estático garante que `app/services/paper_trading/` não importa símbolos de execução de ordens do ib_insync.

## 7. Limitações desta sondagem

- Corrida **fora de horas** — as taxas de ticks e spreads em RTH serão diferentes (mais ticks, spreads mais apertados). Vale a pena repetir com o mercado aberto e anexar os números aqui.
- Não foi testada a perda abrupta do Gateway (matar o processo a meio de um stream); o comportamento documentado do provider (log + retorno vazio + backoff) cobre o caso, e o engine trata "sem ticks" como feed obsoleto de qualquer forma.
