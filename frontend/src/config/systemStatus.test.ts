import { describe, expect, it } from "vitest";

import {
  type SystemCheck,
  normalizeReport,
  sortChecksBySeverity,
  worstStatus,
} from "./systemStatus";

function makeCheck(overrides: Partial<SystemCheck> = {}): SystemCheck {
  return {
    key: "database",
    label: "Base de dados",
    status: "ok",
    detail: "Ligação OK.",
    hint: null,
    data: {},
    ...overrides,
  };
}

describe("worstStatus", () => {
  it("devolve o estado mais severo do conjunto", () => {
    expect(worstStatus([makeCheck(), makeCheck()])).toBe("ok");
    expect(worstStatus([makeCheck(), makeCheck({ status: "warn" })])).toBe("warn");
    expect(
      worstStatus([makeCheck({ status: "warn" }), makeCheck({ status: "fail" })]),
    ).toBe("fail");
    expect(worstStatus([])).toBe("ok");
  });
});

describe("sortChecksBySeverity", () => {
  it("ordena pior-primeiro mantendo a ordem original dentro do nível", () => {
    const checks = [
      makeCheck({ key: "a", status: "ok" }),
      makeCheck({ key: "b", status: "fail" }),
      makeCheck({ key: "c", status: "warn" }),
      makeCheck({ key: "d", status: "warn" }),
    ];
    expect(sortChecksBySeverity(checks).map((c) => c.key)).toEqual(["b", "c", "d", "a"]);
    // Não muta o original.
    expect(checks.map((c) => c.key)).toEqual(["a", "b", "c", "d"]);
  });
});

describe("normalizeReport", () => {
  it("aceita o payload do backend tal e qual", () => {
    const report = normalizeReport({
      generated_at: "2026-07-09T16:00:00Z",
      overall: "warn",
      checks: [
        {
          key: "gateway",
          label: "IB Gateway (socket)",
          status: "fail",
          detail: "Porta 4002 fechada, mas 4001 está aberta.",
          hint: "Ajusta IBKR_GATEWAY_PORT.",
          data: { open_sibling_port: 4001 },
        },
      ],
    });
    expect(report.overall).toBe("warn");
    expect(report.checks).toHaveLength(1);
    expect(report.checks[0].hint).toContain("IBKR_GATEWAY_PORT");
  });

  it("nunca rebenta com payloads estranhos e degrada estados desconhecidos para warn", () => {
    const report = normalizeReport({
      checks: [{ key: "x", status: "banana", detail: 42 }],
    });
    expect(report.checks[0].status).toBe("warn");
    expect(report.checks[0].detail).toBe("42");
    expect(report.overall).toBe("warn"); // derivado dos checks quando falta

    expect(normalizeReport(null).checks).toEqual([]);
    expect(normalizeReport(undefined).overall).toBe("ok");
  });
});
