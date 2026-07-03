import { describe, expect, it } from "vitest";

import {
  filterItemsByCreatedDate,
  pageRangeLabel,
  paginateItems,
  totalPagesFor,
} from "./backtestWorkspaceList";

describe("backtestWorkspaceList", () => {
  it("filters items by created date range", () => {
    const items = [
      { id: 1, created_at: "2024-06-01T10:00:00Z" },
      { id: 2, created_at: "2024-07-01T10:00:00Z" },
    ];
    const filtered = filterItemsByCreatedDate(items, "2024-06-15", "2024-07-31", (item) => item.created_at);
    expect(filtered.map((item) => item.id)).toEqual([2]);
  });

  it("paginates items", () => {
    const items = Array.from({ length: 25 }, (_, index) => index + 1);
    expect(paginateItems(items, 2, 10)).toEqual([11, 12, 13, 14, 15, 16, 17, 18, 19, 20]);
    expect(totalPagesFor(25, 10)).toBe(3);
    expect(pageRangeLabel(2, 10, 25)).toBe("11–20 de 25");
  });
});
