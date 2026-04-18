"use client";

import { TraderStatsWidget } from "./TraderStatsWidget";

type Props = {
  wallet: string;
  width?: number;
  height?: number;
  // When `hoverMode` is true the widget defers its fetch by 300 ms so a fast
  // scroll over a list doesn't fire dozens of requests.
  hoverMode?: boolean;
};

/**
 * Drop-in wrapper around our own `TraderStatsWidget`.
 *
 * Originally this component embedded polymarketscan.org's iframe, but the
 * remote widget stopped loading reliably, so the whole visual has been
 * replaced by a native widget sourced from our own wallet_profiles data.
 *
 * Kept as a named component to preserve the existing import paths.
 */
export function PolymarketScanEmbed({
  wallet,
  width = 400,
  height = 400,
  hoverMode = false,
}: Props) {
  return (
    <TraderStatsWidget
      wallet={wallet}
      width={width}
      height={height}
      hoverMode={hoverMode}
      compact={hoverMode}
    />
  );
}
