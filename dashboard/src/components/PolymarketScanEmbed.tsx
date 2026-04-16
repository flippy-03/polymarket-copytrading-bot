"use client";

import { useEffect, useRef, useState } from "react";

type Props = {
  wallet: string;
  width?: number;
  height?: number;
  // When `hoverMode` is true the iframe is lazy-loaded on a 300ms debounce so a
  // fast scroll over a list doesn't fire dozens of requests.
  hoverMode?: boolean;
};

/**
 * Lightweight wrapper around the polymarketscan.org trader widget.
 *
 * In `hoverMode`, the iframe only mounts after the component has been rendered
 * for 300ms. That lets us drop it into a popover that shows on row hover
 * without hammering the remote service.
 */
export function PolymarketScanEmbed({
  wallet,
  width = 400,
  height = 400,
  hoverMode = false,
}: Props) {
  const [visible, setVisible] = useState(!hoverMode);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!hoverMode) {
      setVisible(true);
      return;
    }
    timer.current = setTimeout(() => setVisible(true), 300);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [hoverMode, wallet]);

  if (!visible) {
    return (
      <div
        style={{
          width,
          height,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "var(--text-secondary)",
          fontSize: 12,
          borderRadius: 12,
          border: "1px solid var(--border)",
          background: "var(--bg-secondary)",
        }}
      >
        Loading polymarketscan…
      </div>
    );
  }

  const src = `https://polymarketscan.org/embed/trader/${wallet}?theme=dark`;
  return (
    <iframe
      src={src}
      width={width}
      height={height}
      frameBorder={0}
      style={{
        borderRadius: 12,
        border: "1px solid #333",
        background: "var(--bg-secondary)",
      }}
      loading="lazy"
    />
  );
}
