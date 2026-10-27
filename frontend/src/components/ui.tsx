import styled, { css } from "styled-components";

export const Page = styled.main`
  width: min(1440px, 100%); min-height: 100vh; margin: 0 auto; padding: 28px 32px 24px;
  display: grid; grid-template-rows: auto auto auto auto minmax(240px, 1fr) auto; gap: 14px;
  @media (max-width: 980px) { padding: 20px; }
`;

export const Header = styled.header`
  display: flex; justify-content: space-between; align-items: center; padding: 4px 2px 8px;
  h1 { margin: 0; font-size: 30px; letter-spacing: -.035em; }
  p { margin: 7px 0 0; color: #71809a; font-size: 14px; }
`;

export const Eyebrow = styled.div`
  margin-bottom: 7px; color: #2875d2; font-size: 11px; font-weight: 750; letter-spacing: .13em;
`;

export const Badge = styled.span<{ $tone?: "ready" | "error" | "working" }>`
  padding: 9px 12px; border-radius: 999px; font-size: 12px; font-weight: 650;
  color: ${({ $tone }) => $tone === "error" ? "#b63c49" : $tone === "ready" ? "#17825f" : "#2672cd"};
  background: ${({ $tone }) => $tone === "error" ? "#fde9eb" : $tone === "ready" ? "#e2f6ee" : "#e3efff"};
`;

export const Card = styled.section`
  border: 1px solid #e7ebf2; background: rgba(255,255,255,.96); border-radius: 14px;
  box-shadow: 0 5px 20px rgba(32,56,94,.045); padding: 17px 19px;
`;

export const FormGrid = styled(Card)`
  display: grid; grid-template-columns: minmax(260px, 1fr) auto; gap: 12px 18px; align-items: end;
  @media (max-width: 980px) { grid-template-columns: 1fr; }
`;

export const DestinationRow = styled(Card)`
  display: flex; align-items: end; gap: 12px;
  @media (max-width: 720px) { align-items: stretch; flex-direction: column; }
`;

export const Toolbar = styled(Card)`
  display: flex; align-items: end; flex-wrap: wrap; gap: 20px;
`;

export const FilterGroup = styled.div`
  display: flex; flex-direction: column; gap: 7px; min-width: 170px;
  label { color: #586984; font-size: 12px; font-weight: 650; }
  small { color: #8793a6; font-size: 10px; }
  select { min-height: 38px; padding: 8px 11px; border: 1px solid #d9e0ea; border-radius: 8px; background: #fff; color: #23324a; }
`;

export const FileTypes = styled.div`
  display: flex; flex-wrap: wrap; max-width: 560px; gap: 6px;
  label { display: flex; align-items: center; gap: 5px; padding: 5px 8px; border-radius: 7px; background: #f5f8fc; color: #51647f; font-size: 11px; cursor: pointer; }
  input { accent-color: #2879d5; }
`;

export const SelectionActions = styled.div`
  display: flex; flex-wrap: wrap; align-items: center; gap: 8px;
  margin-left: auto;
  @media (max-width: 980px) { margin-left: 0; }
`;

export const ErrorNotice = styled.div`
  padding: 10px 13px; border: 1px solid #f5c9ce; border-radius: 9px; background: #fff2f3; color: #a4313e; font-size: 12px; overflow-wrap: anywhere;
`;

export const SelectionSummary = styled.span`
  margin-left: auto; color: #6c7b92; font-size: 11px;
`;

export const BrowserSection = styled(Card)`
  display: flex; flex-direction: column; min-height: 0; overflow: hidden;
`;

export const Field = styled.label`
  display: flex; flex-direction: column; gap: 7px; min-width: 0; color: #586984; font-size: 12px; font-weight: 650;
  select, input { width: 100%; min-height: 39px; padding: 8px 11px; color: #23324a; background: #fff; border: 1px solid #d9e0ea; border-radius: 8px; outline: none; }
  select:focus, input:focus { border-color: #5291e4; box-shadow: 0 0 0 3px rgba(72,139,225,.13); }
`;

export const ActionRow = styled.div`
  display: flex; flex-wrap: wrap; align-items: center; gap: 8px;
`;

export const Button = styled.button<{ $variant?: "primary" | "success" | "secondary" }>`
  min-height: 38px; padding: 0 14px; border: 1px solid transparent; border-radius: 8px;
  font-size: 12px; font-weight: 700; transition: transform .12s, box-shadow .12s, opacity .12s;
  ${({ $variant }) => $variant === "primary" ? css`color: #fff; background: #2879d5;` : $variant === "success" ? css`color: #fff; background: #19a777;` : css`color: #35597f; background: #f7f9fc; border-color: #dce4ee;`}
  &:not(:disabled):hover { transform: translateY(-1px); box-shadow: 0 4px 11px rgba(33,70,120,.14); }
  &:disabled { cursor: not-allowed; opacity: .45; }
`;

export const BrowserCard = styled(Card)`
  display: flex; flex-direction: column; min-height: 0; overflow: hidden;
`;

export const BrowserHeading = styled.div`
  display: flex; justify-content: space-between; align-items: center; padding-bottom: 13px; border-bottom: 1px solid #edf0f5;
  h2 { margin: 0; font-size: 15px; } p { margin: 5px 0 0; color: #7c8aa0; font-size: 11px; }
`;

export const TreeContainer = styled.div`
  min-height: 0; overflow: auto; padding: 9px 2px;
`;

export const TreeRow = styled.div<{ $depth: number }>`
  display: flex; align-items: center; min-height: 34px; padding: 3px 8px 3px ${({ $depth }) => 8 + $depth * 20}px; gap: 9px; border-radius: 7px;
  &:hover { background: #f4f8fe; }
  input { width: 15px; height: 15px; margin: 0; accent-color: #2879d5; }
`;

export const TreeName = styled.span`
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px;
`;

export const TreeMeta = styled.span`
  margin-left: auto; color: #93a0b3; font-size: 10px; white-space: nowrap;
`;

export const ExpandButton = styled.button`
  width: 20px; padding: 0; border: 0; color: #7790ad; background: transparent; cursor: pointer; font-size: 18px;
`;

export const EmptyState = styled.div`
  display: grid; min-height: 140px; place-items: center; color: #8592a6; font-size: 13px;
`;

export const Footer = styled(Card)`
  padding: 13px 17px;
  progress { width: 100%; height: 7px; appearance: none; }
  progress::-webkit-progress-bar { background: #e8edf5; border-radius: 9px; }
  progress::-webkit-progress-value { background: #3282dc; border-radius: 9px; }
`;

export const StatusLine = styled.div`
  display: flex; justify-content: space-between; gap: 12px; margin-bottom: 9px; color: #71809a; font-size: 11px;
`;
