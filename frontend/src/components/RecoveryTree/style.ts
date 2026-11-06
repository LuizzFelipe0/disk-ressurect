import styled from "styled-components";
import { colors, spacing, typography } from "belagio-styles-lib";

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
  color: ${colors.textPrimary};
  font-family: ${typography.fontFamily};
  font-size: ${typography.sizeSm};

  &, ul { list-style: none; }
`;

export const TreeChildren = styled.ul`
  margin-left: ${spacing[5]};
  padding-left: ${spacing[2]};
  border-left: 1px solid ${colors.separator};
`;

export const TreeRow = styled.div`
  display: flex;
  align-items: center;
  min-height: 36px;
  padding: ${spacing[1]} ${spacing[2]};
  gap: ${spacing[2]};
  border-radius: ${spacing.radiusMd};
  transition: background-color .15s ease;
  &:hover { background: #f1f5ff; }
  input { width: 15px; height: 15px; margin: 0; accent-color: ${colors.blue}; }
  input:focus-visible { outline: 2px solid ${colors.blue}; outline-offset: 2px; }
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
  span { color: ${colors.blue}; font-size: ${typography.sizeMd}; }
`;

export const TreeMeta = styled.span`
  margin-left: auto;
  color: ${colors.textTertiary};
  font-size: ${typography.sizeXs};
  white-space: nowrap;
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
  color: ${colors.textSecondary};
  background: transparent;
  cursor: pointer;
  font-size: ${typography.sizeLg};
  &:hover:not(:disabled) { color: ${colors.blue}; background: ${colors.backgroundSecondary}; }
  &:focus-visible { outline: 2px solid ${colors.blue}; outline-offset: 1px; }
  &:disabled { cursor: progress; opacity: .55; }
`;

export const TreeLoading = styled.div`
  margin: 0 0 ${spacing[2]} 48px;
  color: ${colors.textTertiary};
  font-size: ${typography.sizeXs};
`;
