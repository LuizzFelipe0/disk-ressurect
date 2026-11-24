import styled from "styled-components";
import { brandColors } from "../../brandColors";

export const PageLayout = styled.main`
  width: 100%;
  height: 100vh;
  min-height: 680px;
  display: flex;
  flex-direction: column;
`;

export const PageContent = styled.div`
  display: grid;
  width: min(1440px, 100%);
  min-height: 0;
  flex: 1;
  grid-template-rows: auto auto minmax(0, 1fr) auto;
  gap: 10px;
  margin: 0 auto;
  padding: 10px 24px;
  box-sizing: border-box;
  @media (max-width: 980px) { padding: 12px 16px; }
`;

export const PageHeader = styled.div`
  flex: 0 0 auto;
  width: 100%;
  min-width: 0;
  > header { width: 100%; }
`;

export const Eyebrow = styled.div`
  margin-bottom: 7px;
  color: ${brandColors.ink};
  font-size: 11px;
  font-weight: 750;
  letter-spacing: .13em;
`;

export const FormGrid = styled.div`
  display: grid;
  grid-template-columns: minmax(260px, 1fr) auto;
  gap: 12px 18px;
  align-items: end;
  @media (max-width: 980px) { grid-template-columns: 1fr; }
`;

export const FormControl = styled.div`
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 7px;
  color: ${brandColors.textSecondary};
  font-size: 12px;
  font-weight: 650;
`;

export const FormControlCaption = styled.span``;

export const OrphanScanControls = styled.div`
  margin-top: 12px;
  color: ${brandColors.textSecondary};
  font-size: 12px;
  label { display: flex; align-items: center; gap: 8px; font-weight: 650; }
  input { accent-color: ${brandColors.revive}; }
  p { margin: 4px 0 0 24px; color: ${brandColors.textTertiary}; font-size: 11px; }
`;

export const CarvingBudgetControls = styled.div`
  display: flex;
  flex-wrap: wrap;
  align-items: end;
  gap: 12px;
  margin: 10px 0 0 24px;
  > div { flex: 0 1 220px; min-width: 190px; }
  > div > div { width: 100%; }
`;

export const DestinationRow = styled.div`
  display: flex;
  align-items: end;
  gap: 12px;
  @media (max-width: 720px) { align-items: stretch; flex-direction: column; }
`;

export const DestinationInput = styled.div`
  flex: 1;
  min-width: 0;
`;

export const SearchBox = styled.div`
  margin: 8px 0 4px;
`;

export const SelectionActions = styled.div`
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
`;

export const BrowserSection = styled.div`
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  overflow: hidden;
`;

export const BrowserFrame = styled.div`
  display: grid;
  width: 100%;
  min-height: 0;
  grid-template-columns: minmax(0, 1fr) minmax(300px, 360px);
  gap: 10px;
  > div { display: flex; min-height: 0; flex-direction: column; }
  @media (max-width: 980px) { grid-template-columns: minmax(0, 1fr) minmax(250px, 300px); }
`;

export const PreviewPane = styled.section`
  display: flex;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  > div { display: flex; min-width: 0; min-height: 0; height: 100%; flex-direction: column; }
  /* Card applies header spacing inline; add one spacing step to align its divider with Found Files. */
  > div > div:first-child { padding-bottom: 32px !important; }
`;

export const PreviewBody = styled.div`
  display: flex;
  min-width: 0;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  gap: 12px;
  overflow: auto;
  padding: 16px;
  h3 { overflow-wrap: anywhere; font-size: 13px; }
  p { color: ${brandColors.textSecondary}; font-size: 12px; line-height: 1.5; }
  img { max-height: 100%; margin: auto; object-fit: contain; }
  iframe { width: 100%; min-height: 0; flex: 1; border: 0; }
`;

export const BrowserHeading = styled.div`
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: flex-start;
  gap: 10px;
  padding-bottom: 8px;
  border-bottom: 1px solid ${brandColors.border};
  h2 { margin: 0; font-size: 15px; }
  p { margin: 5px 0 0; color: ${brandColors.textTertiary}; font-size: 11px; }
`;

export const ValidationNotice = styled.p<{ $inconclusive: boolean }>`
  margin: 7px 0 0;
  color: ${({ $inconclusive }) => $inconclusive ? brandColors.warning : brandColors.textSecondary};
  font-size: 11px;
  line-height: 1.45;
`;

export const SelectionSummary = styled.span`
  color: ${brandColors.textSecondary};
  font-size: 11px;
`;

export const AuditActions = styled.div`
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 10px;
  margin-left: auto;
`;

export const ActionRow = styled.div`
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
`;

export const HeaderActions = styled.div`
  display: flex;
  align-items: center;
  gap: 10px;
  > span button { display: inline-flex; align-items: center; gap: 8px; }
  img { width: 18px; height: 18px; object-fit: contain; }
`;

export const FilterBackdrop = styled.div`
  position: fixed;
  z-index: 1000;
  inset: 0;
  display: flex;
  justify-content: flex-end;
  background: rgba(13, 18, 24, .48);
`;

export const FilterPanel = styled.section`
  display: flex;
  width: min(520px, 96vw);
  height: 100%;
  background: #fff;
  box-shadow: -12px 0 36px rgba(0, 0, 0, .18);
  overflow: hidden;
`;

export const FilterPanelContent = styled.div`
  display: flex;
  min-width: 0;
  width: 100%;
  flex-direction: column;
  overflow-y: auto;
  padding: 24px;
`;

export const FilterPanelHeading = styled.div`
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 26px;
  h2 { margin: 0; color: ${brandColors.ink}; font-size: 20px; }
`;

export const FilterSection = styled.section`
  display: flex;
  flex-wrap: wrap;
  align-items: end;
  gap: 12px;
  padding: 0 0 24px;
  margin: 0 0 24px;
  border-bottom: 1px solid ${brandColors.border};
  scroll-margin-top: 24px;
  > span { flex-basis: 100%; color: ${brandColors.ink}; font-size: 14px; font-weight: 700; }
  > :not(span) { flex: 1 1 200px; min-width: 0; }
`;
