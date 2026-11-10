import styled from "styled-components";
import { spacing, typography } from "belagio-styles-lib";
import { brandColors } from "../../brandColors";

export const EmptyStateContainer = styled.div`
  display: grid;
  min-height: 140px;
  justify-items: center;
  align-content: center;
  gap: ${spacing[3]};
  padding: ${spacing[5]};
  color: ${brandColors.textSecondary};
  font-family: ${typography.fontFamily};
  font-size: ${typography.sizeSm};
  text-align: center;
`;

export const EmptyVisual = styled.span`
  display: grid;
  width: 38px;
  height: 38px;
  place-items: center;
  border-radius: ${spacing.radiusFull};
  color: ${brandColors.ink};
  background: ${brandColors.revive};
  font-size: ${typography.sizeXl};

  svg {
    display: block;
    width: 22px;
    height: 22px;
    fill: none;
    stroke: currentColor;
    stroke-width: 2.2;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
`;

export const EmptyCopy = styled.div`
  display: grid;
  gap: ${spacing[1]};
  max-width: 480px;
  p { color: ${brandColors.textTertiary}; line-height: ${typography.lineHeightNormal}; }
`;

export const EmptyTitle = styled.div`
  color: ${brandColors.textSecondary};
  font-weight: ${typography.weightMedium};
`;

export const EmptyAction = styled.div`
  margin-top: ${spacing[1]};
`;
