import styled from "styled-components";
import { brandColors } from "../../brandColors";

export const HomeLayout = styled.main`
  width: 100%;
  min-height: 100vh;
  display: flex;
  flex-direction: column;
`;

export const HomeContent = styled.section`
  width: min(1440px, 100%);
  flex: 1;
  display: grid;
  place-items: center;
  margin: 0 auto;
  padding: 32px 24px;
  box-sizing: border-box;
  > div { width: min(760px, 100%); }
  @media (max-width: 720px) { padding: 20px 16px; }
`;

export const HomeEyebrow = styled.p`
  margin: 0 0 12px;
  color: ${brandColors.revive};
  font-size: 11px;
  font-weight: 750;
  letter-spacing: .14em;
`;

export const WelcomeTitle = styled.h1`
  margin: 0 0 12px;
  color: ${brandColors.ink};
  font-size: clamp(28px, 5vw, 42px);
  line-height: 1.12;
`;

export const WelcomeBody = styled.p`
  max-width: 620px;
  margin: 0 0 24px;
  color: ${brandColors.textSecondary};
  font-size: 15px;
  line-height: 1.65;
`;
