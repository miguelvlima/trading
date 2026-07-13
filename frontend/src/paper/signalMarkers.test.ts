import { describe, expect, it } from "vitest";

import type { PaperSignalWire } from "./api";
import { signalMarkers } from "./signalMarkers";

const T0 = Date.parse("2026-07-08T14:00:00Z") / 1000;
const BAR_TIMES = [T0, T0 + 300, T0 + 600, T0 + 900]; // 5m candles

function signal(overrides: Partial<PaperSignalWire>): PaperSignalWire {
  return {
    id: 1,
    at: "2026-07-08T14:05:00Z",
    symbol: "AAPL",
    strategy: "bollinger_breakout",
    direction: "BUY",
    strength: 0.01,
    min_strength: 0.3,
    rationale: null,
    bar_time: "2026-07-08T14:05:00Z",
    outcome: "skipped",
    reason: "below_min_strength",
    order_id: null,
    ...overrides,
  };
}

describe("signalMarkers", () => {
  it("inclui sinais fracos (skipped), esbatidos, ancorados à vela certa", () => {
    const markers = signalMarkers([signal({})], "AAPL", BAR_TIMES);
    expect(markers).toHaveLength(1);
    expect(Number(markers[0].time)).toBe(T0 + 300);
    expect(markers[0].position).toBe("belowBar");
    expect(markers[0].shape).toBe("arrowUp");
    expect(markers[0].text).toContain("0.01");
  });

  it("snap para a vela anterior quando o tempo do sinal cai entre velas", () => {
    const markers = signalMarkers(
      [signal({ bar_time: "2026-07-08T14:07:30Z" })],
      "AAPL",
      BAR_TIMES,
    );
    expect(Number(markers[0].time)).toBe(T0 + 300);
  });

  it("descarta sinais fora do intervalo carregado e de outros símbolos", () => {
    const markers = signalMarkers(
      [
        signal({ bar_time: "2026-07-01T00:00:00Z" }), // antes das velas
        signal({ symbol: "NVDA" }),
      ],
      "AAPL",
      BAR_TIMES,
    );
    expect(markers).toHaveLength(0);
  });

  it("SELL fica acima da vela com seta para baixo; proposto não é esbatido", () => {
    const markers = signalMarkers(
      [signal({ direction: "SELL", outcome: "proposed" })],
      "AAPL",
      BAR_TIMES,
    );
    expect(markers[0].position).toBe("aboveBar");
    expect(markers[0].shape).toBe("arrowDown");
    expect(markers[0].color).toBe("#ef4444");
  });

  it("usa o created_at quando o sinal antigo não tem bar_time", () => {
    const markers = signalMarkers([signal({ bar_time: null })], "AAPL", BAR_TIMES);
    expect(markers).toHaveLength(1);
  });

  it("ordena os marcadores por tempo", () => {
    const markers = signalMarkers(
      [
        signal({ id: 2, bar_time: "2026-07-08T14:15:00Z" }),
        signal({ id: 1, bar_time: "2026-07-08T14:00:00Z" }),
      ],
      "AAPL",
      BAR_TIMES,
    );
    expect(Number(markers[0].time)).toBeLessThan(Number(markers[1].time));
  });
});
