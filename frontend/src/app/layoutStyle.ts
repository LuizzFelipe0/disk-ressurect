import styled from "styled-components";
import { brandColors } from "../brandColors";

export const LayoutRoot = styled.div`
  width: 100%; height: 100vh; min-height: 680px;
  display: flex; flex-direction: column; gap: 8px;
`;
export const LayoutHeader = styled.header`
  flex: 0 0 auto; background: ${brandColors.surface};
  > header { width: 100%; }
`;
export const LayoutNavigation = styled.nav`
  display: flex; flex-wrap: wrap; gap: 6px; padding: 0 24px 10px;
  a { border-radius: 6px; color: ${brandColors.textSecondary}; padding: 7px 11px; text-decoration: none; font-size: 13px; }
  a[aria-current="page"] { background: ${brandColors.revive}; color: ${brandColors.ink}; font-weight: 700; }
`;
export const LayoutMain = styled.main`
  width: min(1440px, 100%); min-height: 0; flex: 1; margin: 0 auto; padding: 0 24px;
  @media (max-width: 980px) { padding: 0 16px; }
`;
export const SimplePage = styled.section`
  display: grid; align-content: start; gap: 12px; padding: 4px 0; height: 100%; overflow: auto;
  h1 { margin: 4px 0; font-size: 23px; }
  p { margin: 4px 0; color: ${brandColors.textSecondary}; }
`;
export const PageActions = styled.div`
  display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
`;
