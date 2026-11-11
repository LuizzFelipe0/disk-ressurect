import styled from "styled-components";
import { spacing, typography } from "belagio-styles-lib";
import { brandColors } from "../../brandColors";

export const TreeIndent = styled.span`
  width: 20px;
  flex: 0 0 20px;
`;

export const TreeContainer = styled.ul`
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  padding: ${spacing[2]} 0;
  color: ${brandColors.ink};
  font-family: ${typography.fontFamily};
  font-size: ${typography.sizeSm};

  &, ul { list-style: none; }
`;

export const TreeChildren = styled.ul`
  margin-left: ${spacing[5]};
  padding-left: ${spacing[2]};
  border-left: 1px solid ${brandColors.border};
`;

export const TreeRow = styled.div`
  display: flex;
  align-items: center;
  min-height: 36px;
  padding: ${spacing[1]} ${spacing[2]};
  gap: ${spacing[2]};
  border-radius: ${spacing.radiusMd};
  transition: background-color .15s ease;
  &:hover { background: ${brandColors.surfaceMuted}; }
  input { width: 15px; height: 15px; margin: 0; accent-color: ${brandColors.revive}; }
  input:focus-visible { outline: 2px solid ${brandColors.revive}; outline-offset: 2px; }
`;

export const TreeName = styled.span`
  display: flex;
  min-width: 0;
  align-items: center;
  gap: ${spacing[2]};
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: ${typography.sizeSm};
  span { color: ${brandColors.ink}; font-size: ${typography.sizeMd}; }
`;

export const TreeMeta = styled.span`
  flex: 0 0 140px;
  overflow: hidden;
  text-align: right;
  text-overflow: ellipsis;
  color: ${brandColors.textTertiary};
  font-size: ${typography.sizeXs};
  white-space: nowrap;
`;

export const PreviewAction = styled.span`
  display: flex;
  flex: 0 0 96px;
  width: 96px;
  justify-content: center;
  button { width: 84px; }
`;

export const ExpandButton = styled.button`
  display: grid;
  flex: 0 0 24px;
  width: 24px;
  height: 24px;
  place-items: center;
  padding: 0;
  border: 0;
  border-radius: ${spacing.radiusSm};
  color: ${brandColors.textSecondary};
  background: transparent;
  cursor: pointer;
  font-size: ${typography.sizeLg};
  &:hover:not(:disabled) { color: ${brandColors.ink}; background: ${brandColors.surfaceMuted}; }
  &:focus-visible { outline: 2px solid ${brandColors.revive}; outline-offset: 1px; }
  &:disabled { cursor: progress; opacity: .55; }
`;

export const TreeLoading = styled.div`
  margin: 0 0 ${spacing[2]} 48px;
  color: ${brandColors.textTertiary};
  font-size: ${typography.sizeXs};
`;
