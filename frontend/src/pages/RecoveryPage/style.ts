import styled from "styled-components";
import { brandColors } from "../../brandColors";

export const PageLayout = styled.main`
  width: 100%;
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background: ${brandColors.bone};
`;

export const PageContent = styled.div`
  display: flex;
  flex-direction: column;
  width: min(1150px, 100%);
  min-height: 0;
  flex: 1;
  gap: 14px;
  margin: 0 auto;
  padding: 18px 24px 24px;
  box-sizing: border-box;
  @media (max-width: 980px) { padding: 12px 16px; }
`;

export const WorkflowPanel = styled.section`
  display: flex;
  width: 100%;
  min-height: 450px;
  flex: 1;
  flex-direction: column;
  gap: 16px;
  padding: clamp(18px, 3vw, 30px);
  border: 1px solid ${brandColors.border};
  border-radius: 7px;
  background: #fff;
  box-sizing: border-box;
  > div { width: 100%; }
  @media (max-width: 720px) { min-height: 0; padding: 16px; }
`;

export const PageIntro = styled.header`
  h1 { margin: 0 0 7px; color: ${brandColors.ink}; font-size: clamp(21px, 3vw, 27px); }
  p { margin: 0; color: ${brandColors.textSecondary}; font-size: 13px; line-height: 1.5; }
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
  grid-template-columns: 1fr;
  gap: 12px 18px;
  align-items: end;
  @media (max-width: 980px) { grid-template-columns: 1fr; }
`;

export const SourceList = styled.div`
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  @media (max-width: 680px) { grid-template-columns: 1fr; }
`;

export const DeviceOption = styled.button<{ $selected: boolean }>`
  width: 100%;
  min-height: 74px;
  display: flex;
  align-items: center;
  gap: 13px;
  padding: 13px 15px;
  border: 1px solid ${({ $selected }) => $selected ? brandColors.revive : brandColors.border};
  border-radius: 5px;
  background: ${({ $selected }) => $selected ? "#f8fce9" : "#fff"};
  color: ${brandColors.ink};
  text-align: left;
  cursor: pointer;
  &:focus-visible { outline: 2px solid ${brandColors.revive}; outline-offset: 2px; }
  &:disabled { opacity: .55; cursor: not-allowed; }
`;

export const DeviceIcon = styled.span`
  width: 40px;
  height: 40px;
  flex: 0 0 40px;
  display: grid;
  place-items: center;
  border-radius: 7px;
  background: #eff9d5;
  color: #486b13;
  font-size: 21px;
`;

export const DeviceDetails = styled.span`
  min-width: 0;
  flex: 1;
  strong, small { display: block; overflow-wrap: anywhere; }
  strong { font-size: 12px; }
  small { margin-top: 4px; color: ${brandColors.textTertiary}; font-size: 11px; }
`;

export const SourceSelectedTag = styled.span`
  flex: 0 0 auto;
  padding: 5px 8px;
  border-radius: 4px;
  background: #eef6da;
  color: #55721c;
  font-size: 10px;
  font-weight: 650;
`;

export const CatalogStats = styled.div`
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  @media (max-width: 520px) { gap: 6px; }
`;

export const CatalogStat = styled.div`
  min-width: 0;
  padding: 12px 14px;
  border: 1px solid ${brandColors.border};
  border-radius: 5px;
  background: #fff;
  span { display: block; color: ${brandColors.textTertiary}; font-size: 11px; }
  strong { display: block; margin-top: 5px; color: ${brandColors.ink}; font-size: clamp(17px, 2vw, 23px); }
  @media (max-width: 520px) { padding: 9px; span { font-size: 10px; } }
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
  min-height: 390px;
  flex: 1;
  grid-template-columns: minmax(0, 1fr) minmax(300px, 360px);
  gap: 10px;
  > div { display: flex; min-height: 0; flex-direction: column; }
  @media (max-width: 980px) { grid-template-columns: minmax(0, 1fr) minmax(250px, 300px); }
  @media (max-width: 680px) { min-height: 560px; grid-template-columns: minmax(0, 1fr); grid-template-rows: minmax(330px, 1fr) minmax(200px, .6fr); }
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

export const StepActions = styled.div`
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: auto;
  padding-top: 6px;
  @media (max-width: 520px) {
    flex-wrap: wrap;
    > button { flex: 1 1 40%; }
  }
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
