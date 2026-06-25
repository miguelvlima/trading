import { ApiError } from "../../realtime/api";

export type HotSort = "change_pct" | "rvol" | "volume";
export type HotDirection = "up" | "down" | "both";

export type HotMoverSpark = { points: number[]; interval: string };

export type HotMover = {
  symbol: string;
  name: string | null;
  last: string; // Decimal serialized as string
  change_pct: string;
  volume: number;
  rel_volume: string | null;
  spark: HotMoverSpark;
};

export type HotMoversResponse = {
  as_of: string;
  sort: string;
  items: HotMover[];
};

export async function fetchHotMovers(
  baseUrl: string,
  token: string,
  params: { limit?: number; sort: HotSort; direction: HotDirection; minPrice?: number },
  signal?: AbortSignal,
): Promise<HotMoversResponse> {
  const query = new URLSearchParams({
    limit: String(params.limit ?? 10),
    sort: params.sort,
    direction: params.direction,
    min_price: String(params.minPrice ?? 0.3),
  });
  let response: Response;
  try {
    response = await fetch(`${baseUrl}/market-scanner/hot-movers?${query.toString()}`, {
      headers: { Authorization: `Bearer ${token}` },
      signal,
    });
  } catch (error) {
    if ((error as Error).name === "AbortError") throw error;
    throw new ApiError(0, "Não foi possível contactar o servidor.");
  }
  if (response.status === 401) throw new ApiError(401, "Sessão expirada. Faça login novamente.");
  if (!response.ok) throw new ApiError(response.status, `Pedido falhou (HTTP ${response.status}).`);
  return (await response.json()) as HotMoversResponse;
}
