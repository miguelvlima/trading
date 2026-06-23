# Fase 5 - Backtesting e Simulação

## Objetivo
Implementar a capacidade de definir uma estratégia para um ativo e intervalo temporal, simular execução de ordens e medir o resultado histórico que teria sido obtido.

Este bloco é considerado funcionalidade core do produto (não é opcional).

## Resultado esperado

No fim da fase, um utilizador autenticado consegue:
- escolher ativo, timeframe e janela temporal,
- escolher estratégia(s) e parâmetros de execução,
- correr uma simulação histórica,
- visualizar relatório de performance e lista de trades simulados.

## Escopo funcional da fase

1. **Configuração de backtest**
- símbolo/instrumento,
- timeframe,
- data inicial e final,
- estratégia ou combinação de estratégias,
- parâmetros de risco/executação (stake por trade, slippage, fee, stop/take, etc.).

2. **Motor de simulação**
- geração de sinais no contexto da janela pedida,
- regras de entrada e saída por candle,
- abertura/fecho de posições simuladas,
- cálculo de custos (fee/slippage) por trade.

3. **Métricas e relatório**
- PnL absoluto e percentual,
- win rate,
- profit factor,
- máximo drawdown,
- número de trades,
- equity curve temporal.

4. **API e persistência**
- endpoint para correr backtest,
- endpoint para consultar resultados históricos do utilizador,
- persistência de runs (inputs + outputs resumidos),
- persistência de trades simulados por run.

5. **UI**
- formulário para configurar backtest,
- execução e estado do run,
- tabela de resultados por run,
- visualização da equity curve e trades.

## Fora de escopo desta fase

- execução real de ordens em broker (live trading),
- roteamento inteligente multi-broker,
- otimização exaustiva de parâmetros (grid/GA avançado),
- paper trading em tempo real.

## Regras de qualidade

- cobrir motor de simulação com testes determinísticos,
- manter isolamento por utilizador nos resultados,
- não quebrar endpoints existentes (`market-data`, `signals`, auth),
- validar performance em janelas realistas (ex.: 1-2 anos de candles diários).

## Critérios de done

- backtest executa end-to-end via API,
- UI permite correr e interpretar um backtest sem intervenção manual,
- métricas principais batem com cenários de teste esperados,
- CI verde (backend tests + frontend build),
- documentação atualizada (`README` + docs da fase).
