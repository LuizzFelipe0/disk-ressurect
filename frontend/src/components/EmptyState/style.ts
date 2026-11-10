import styled from "styled-components";
import { colors, spacing, typography } from "belagio-styles-lib";

export const EmptyStateContainer = styled.div`
  display: grid;
  min-height: 140px;
  justify-items: center;
  align-content: center;
  gap: ${spacing[3]};
  padding: ${spacing[5]};
  color: ${colors.textSecondary};
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
  color: ${colors.blue};
  background: ${colors.backgroundSecondary};
  font-size: ${typography.sizeXl};
`;

export const EmptyCopy = styled.div`
  display: grid;
  gap: ${spacing[1]};
  max-width: 480px;
  p { color: ${colors.textTertiary}; line-height: ${typography.lineHeightNormal}; }
`;

export const EmptyTitle = styled.div`
  color: ${colors.textSecondary};
  font-weight: ${typography.weightMedium};
`;

export const EmptyAction = styled.div`
  margin-top: ${spacing[1]};
`;
