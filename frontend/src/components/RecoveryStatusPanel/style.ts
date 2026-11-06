import styled from "styled-components";
import { colors, spacing, typography } from "belagio-styles-lib";

export const PanelContent = styled.div`
  display: grid;
  gap: ${spacing[3]};
`;

export const StatusMessage = styled.div`
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: ${spacing[3]};
  color: ${colors.textSecondary};
  font-family: ${typography.fontFamily};
  font-size: ${typography.sizeSm};
  line-height: ${typography.lineHeightNormal};
`;

export const ProgressDetails = styled.span`
  flex: 0 0 auto;
  color: ${colors.textTertiary};
  font-size: ${typography.sizeXs};
  white-space: nowrap;
`;

export const ProgressTrack = styled.progress`
  display: block;
  width: 100%;
  height: 7px;
  appearance: none;
  border: 0;
  border-radius: ${spacing.radiusFull};
  background: ${colors.separator};
  &::-webkit-progress-bar { border-radius: ${spacing.radiusFull}; background: ${colors.separator}; }
  &::-webkit-progress-value { border-radius: ${spacing.radiusFull}; background: ${colors.blue}; transition: width .2s ease; }
  &::-moz-progress-bar { border-radius: ${spacing.radiusFull}; background: ${colors.blue}; }
`;
