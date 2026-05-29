export const formatVnd = (n: number): string =>
  new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 0 }).format(Math.round(n));

export const formatVndShort = (n: number): string => {
  const abs = Math.abs(n);
  if (abs >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(2)} tỷ`;
  if (abs >= 1_000_000) return `${(n / 1_000_000).toFixed(1)} tr`;
  if (abs >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return `${n.toFixed(0)}`;
};

export const formatPct = (n: number, digits = 2): string =>
  `${n.toFixed(digits)}%`;

export const formatPctSigned = (n: number, digits = 2): string =>
  `${n >= 0 ? "+" : ""}${n.toFixed(digits)}%`;

export const formatTimestamp = (iso?: string): string => {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("vi-VN", {
      hour: "2-digit",
      minute: "2-digit",
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
    });
  } catch {
    return iso;
  }
};

export const todayIso = (): string => {
  const d = new Date();
  return d.toISOString().slice(0, 10);
};

export const formatDateVn = (iso: string): string => {
  if (!iso || iso.length < 10) return iso;
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}/${m}/${y}`;
};
