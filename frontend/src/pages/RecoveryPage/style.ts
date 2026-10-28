import styled from "styled-components";
import { InfoCard } from "../../components/InfoCard";

export const PageLayout = styled.main`
  width: min(1440px, 100%);
  height: calc(100vh + 4cm);
  margin: 0 auto;
  padding: 28px 32px 24px;
  display: grid;
  grid-template-rows: auto auto auto auto minmax(200px, 1fr) auto;
  gap: 12px;
  @media (max-width: 980px) { padding: 20px; }
`;

export const PageHeader = styled.header`
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 2px 8px;
  p { margin: 7px 0 0; color: #71809a; font-size: 14px; }
`;

export const AppTitle = styled.h1`
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  font-size: 30px;
  letter-spacing: -.035em;
  img { width: 44px; height: 44px; object-fit: contain; flex: none; }
`;

export const Eyebrow = styled.div`
  margin-bottom: 7px;
  color: #2875d2;
  font-size: 11px;
  font-weight: 750;
  letter-spacing: .13em;
`;

export const FormGrid = styled(InfoCard)`
  display: grid;
  grid-template-columns: minmax(260px, 1fr) auto;
  gap: 12px 18px;
  align-items: end;
  @media (max-width: 980px) { grid-template-columns: 1fr; }
`;

export const DestinationRow = styled(InfoCard)`
  display: flex;
  align-items: end;
  gap: 12px;
  @media (max-width: 720px) { align-items: stretch; flex-direction: column; }
`;

export const Toolbar = styled(InfoCard)`
  display: flex;
  align-items: end;
  flex-wrap: wrap;
  gap: 14px;
  padding: 10px 16px;
`;

export const SelectionActions = styled.div`
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-left: auto;
  @media (max-width: 980px) { margin-left: 0; }
`;

export const BrowserSection = styled(InfoCard)`
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
`;

export const BrowserHeading = styled.div`
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-bottom: 13px;
  border-bottom: 1px solid #edf0f5;
  h2 { margin: 0; font-size: 15px; }
  p { margin: 5px 0 0; color: #7c8aa0; font-size: 11px; }
`;

export const SearchInput = styled.input`
  width: 100%;
  min-height: 38px;
  margin: 12px 0 4px;
  padding: 8px 12px;
  border: 1px solid #d9e0ea;
  border-radius: 8px;
  color: #23324a;
  background: #fff;
  font-size: 12px;
  outline: none;
  &:focus { border-color: #5291e4; box-shadow: 0 0 0 3px rgba(72,139,225,.12); }
  &:disabled { background: #f7f9fc; cursor: not-allowed; }
`;

export const SelectionSummary = styled.span`
  margin-left: auto;
  color: #6c7b92;
  font-size: 11px;
`;

export const Footer = styled(InfoCard)`
  padding: 13px 17px;
  progress { width: 100%; height: 7px; appearance: none; }
  progress::-webkit-progress-bar { background: #e8edf5; border-radius: 9px; }
  progress::-webkit-progress-value { background: #3282dc; border-radius: 9px; }
`;

export const ProgressRow = styled.div`
  display: flex;
  align-items: center;
  gap: 12px;
  progress { flex: 1; min-width: 0; }
`;

export const StatusLine = styled.div`
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 9px;
  color: #71809a;
  font-size: 11px;
`;

export const ActionRow = styled.div<{ $topSpacing?: boolean }>`
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-top: ${({ $topSpacing }) => $topSpacing ? "9px" : "0"};
`;

export const BackendRecoveryHint = styled.span`
  color: #a4313e;
  font-size: 11px;
`;
