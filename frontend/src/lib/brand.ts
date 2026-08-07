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
