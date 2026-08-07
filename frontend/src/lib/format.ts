export function formatUsd(value: number | null, currency: string): string {
  if (value === null) return "--";
  return value.toLocaleString(undefined, {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  });
}

/** Same as formatUsd but abbreviates large totals (1.2M, 340K) -- for
 * dashboard-style summary tiles where a long full-precision figure crowds a
 * large font, not for figures the user needs to act on precisely (call
 * amounts, per-position values), which should keep using formatUsd. */
export function formatUsdCompact(value: number | null, currency: string): string {
  if (value === null) return "--";
  return value.toLocaleString(undefined, {
    style: "currency",
    currency,
    notation: "compact",
    maximumFractionDigits: 1,
  });
}

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}
