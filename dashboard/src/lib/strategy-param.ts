export type Strategy = "BASKET" | "SCALPER";

export function resolveStrategy(request: Request): Strategy {
  const { searchParams } = new URL(request.url);
  const raw = (searchParams.get("strategy") || "").toUpperCase();
  return raw === "SCALPER" ? "SCALPER" : "BASKET";
}
