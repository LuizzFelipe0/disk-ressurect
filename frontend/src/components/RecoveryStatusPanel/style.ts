import styled from "styled-components";
import { spacing, typography } from "belagio-styles-lib";
import { brandColors } from "../../brandColors";

export const PanelContent = styled.div`
  display: grid;
  gap: ${spacing[3]};
`;

export const StatusMessage = styled.div`
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: ${spacing[3]};
  color: ${brandColors.textSecondary};
  font-family: ${typography.fontFamily};
  font-size: ${typography.sizeSm};
  line-height: ${typography.lineHeightNormal};
`;

export const ProgressDetails = styled.span`
  flex: 0 0 auto;
  color: ${brandColors.textTertiary};
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
  background: ${brandColors.border};
  &::-webkit-progress-bar { border-radius: ${spacing.radiusFull}; background: ${brandColors.border}; }
  &::-webkit-progress-value { border-radius: ${spacing.radiusFull}; background: ${brandColors.revive}; transition: width .2s ease; }
  &::-moz-progress-bar { border-radius: ${spacing.radiusFull}; background: ${brandColors.revive}; }
`;
