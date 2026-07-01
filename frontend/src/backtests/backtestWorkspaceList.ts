export function appendCreatedDateQuery(
  query: URLSearchParams,
  from: string,
  to: string,
): void {
  if (from) {
    query.set("start", `${from}T00:00:00Z`);
  }
  if (to) {
    query.set("end", `${to}T23:59:59Z`);
  }
}

export function filterItemsByCreatedDate<T>(
  items: T[],
  from: string,
  to: string,
  readCreatedAt: (item: T) => string,
): T[] {
  if (!from && !to) {
    return items;
  }
  const startMs = from ? Date.parse(`${from}T00:00:00Z`) : Number.NEGATIVE_INFINITY;
  const endMs = to ? Date.parse(`${to}T23:59:59Z`) : Number.POSITIVE_INFINITY;
  return items.filter((item) => {
    const createdMs = Date.parse(readCreatedAt(item));
    return createdMs >= startMs && createdMs <= endMs;
  });
}

export function paginateItems<T>(items: T[], page: number, pageSize: number): T[] {
  const safePage = Math.max(1, page);
  const start = (safePage - 1) * pageSize;
  return items.slice(start, start + pageSize);
}

export function totalPagesFor(itemCount: number, pageSize: number): number {
  return Math.max(1, Math.ceil(itemCount / pageSize));
}

export function pageRangeLabel(page: number, pageSize: number, totalItems: number): string {
  if (totalItems === 0) {
    return "0 de 0";
  }
  const start = (page - 1) * pageSize + 1;
  const end = Math.min(page * pageSize, totalItems);
  return `${start}–${end} de ${totalItems}`;
}
