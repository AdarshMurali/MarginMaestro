// Exact palette given by the user (2026-08-03) for the landing page redesign
// -- shared across every page migrating to that look (login, 2026-08-06;
// more to follow), so this lives in one place instead of being redefined
// per file.
export const BLACK = "#090909";
export const DARK_GREEN = "#20463B";
export const LIGHT_GREEN = "#D3F770";
export const WHITE = "#FFFFFF";

// The dark-zone hero gradient from the landing page (see app/page.tsx for
// the full derivation notes) -- reused wherever a page wants the same
// black-to-green backdrop.
export const HERO_GRADIENT = `linear-gradient(187.13deg,
  ${BLACK} 0%, ${BLACK} 25.57%, ${BLACK} 51.15%,
  #14211c 57.97%, ${DARK_GREEN} 66.49%,
  ${DARK_GREEN} 100%)`;

// White Paper theme (home redesign "E4", 2026-10-15): black and white with
// three status colours only. The status trio is for small marks (dots, thin
// bars, short labels), never large fills.
export const INK = "#0A0A0A";
export const MUTED = "#5C5C5C";
export const LINE = "#E5E5E5";
export const BRAND_GREEN = "#00D17A"; // logo + rising prices on black
export const STATUS_GREEN = "#00B86B";
export const STATUS_AMBER = "#F5A623";
export const STATUS_RED = "#E5484D";
export const TEXT_RED = "#C42A30"; // red text on white (4.5:1)
export const TEXT_AMBER = "#A15C00"; // amber text on white (4.5:1)
