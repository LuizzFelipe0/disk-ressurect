import styled from "styled-components";
import { spacing, typography } from "belagio-styles-lib";
import { brandColors } from "../../brandColors";

export const TreeIndent = styled.span`
  width: 20px;
  flex: 0 0 20px;
`;

export const TreeViewport = styled.div`
  position: relative;
  flex: 1 1 0;
  height: 0;
  min-height: 0;
  max-height: min(60vh, 600px);
  overflow-y: auto;
  overflow-x: hidden;
  padding: 0;
  scrollbar-gutter: stable;
`;

export const TreeContainer = styled.ul<{ $height: number }>`
  position: relative;
  width: 100%;
  height: ${({ $height }) => $height}px;
  margin: 0;
  padding: 0;
  color: ${brandColors.ink};
  font-family: ${typography.fontFamily};
  font-size: ${typography.sizeSm};
  list-style: none;
`;

export const TreeItem = styled.li`
  position: absolute;
  top: 0;
  right: 0;
  left: 0;
  height: 36px;
  list-style: none;
`;

export const TreeRow = styled.div`
  box-sizing: border-box;
  display: flex;
  align-items: center;
  height: 36px;
  padding: 4px ${spacing[2]};
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
  flex: 0 1 240px;
  min-width: 0;
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
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  clip-path: inset(50%);
`;
