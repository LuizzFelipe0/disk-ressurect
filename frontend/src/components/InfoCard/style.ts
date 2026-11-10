import styled from "styled-components";
import { brandColors } from "../../brandColors";

export const CardContainer = styled.section`
  border: 1px solid ${brandColors.border};
  background: ${brandColors.surface};
  border-radius: 14px;
  box-shadow: 0 5px 20px rgba(11,11,12,.045);
  padding: 17px 19px;
`;
