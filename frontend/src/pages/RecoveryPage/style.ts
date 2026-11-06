import styled from "styled-components";

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
  grid-template-rows: auto auto auto minmax(0, 1fr) auto;
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
  color: #2875d2;
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
  color: #586984;
  font-size: 12px;
  font-weight: 650;
`;

export const FormControlCaption = styled.span``;

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

export const FileTypesControls = styled.div`
  display: flex;
  align-items: end;
  gap: 8px;
  min-width: 0;
  flex: 1 1 320px;
  > :first-child { min-width: 0; flex: 1; }
`;

export const MinimumSizeControl = styled.div`
  flex: 0 1 220px;
  min-width: 190px;
  > div { width: 100%; }
`;

export const Toolbar = styled.div`
  display: flex;
  align-items: flex-end;
  flex-wrap: wrap;
  gap: 12px;
`;

export const SelectionActions = styled.div`
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-left: auto;
  @media (max-width: 980px) { margin-left: 0; }
`;

export const BrowserSection = styled.div`
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  overflow: hidden;
`;

export const BrowserFrame = styled.div`
  display: flex;
  width: 100%;
  min-height: 0;
  > div {
    display: flex;
    min-height: 0;
    flex: 1;
    flex-direction: column;
  }
`;

export const BrowserHeading = styled.div`
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-bottom: 8px;
  border-bottom: 1px solid #edf0f5;
  h2 { margin: 0; font-size: 15px; }
  p { margin: 5px 0 0; color: #7c8aa0; font-size: 11px; }
`;

export const SelectionSummary = styled.span`
  margin-left: auto;
  color: #6c7b92;
  font-size: 11px;
`;

export const ActionRow = styled.div`
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
`;
