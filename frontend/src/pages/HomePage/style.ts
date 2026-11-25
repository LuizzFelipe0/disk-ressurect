import styled from "styled-components";
import { Link } from "react-router-dom";
import { brandColors } from "../../brandColors";

export const HomeLayout = styled.main`
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background: ${brandColors.bone};
`;

export const HomeContent = styled.section`
  width: min(1150px, 100%);
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
  margin: 0 auto;
  padding: 28px 24px;
  box-sizing: border-box;
  > div:last-child { width: 100%; padding: clamp(22px, 4vw, 38px); }
  @media (max-width: 720px) { padding: 20px 16px; }
`;

export const HomeEyebrow = styled.p`
  margin: 0 0 10px;
  color: ${brandColors.revive};
  font-size: 11px;
  font-weight: 750;
  letter-spacing: .14em;
`;

export const WelcomeTitle = styled.h1`
  margin: 0 0 8px;
  color: ${brandColors.ink};
  font-size: clamp(25px, 4vw, 32px);
  line-height: 1.2;
`;

export const WelcomeBody = styled.p`
  max-width: 680px;
  margin: 0 0 24px;
  color: ${brandColors.textSecondary};
  font-size: 14px;
  line-height: 1.6;
`;

export const SourceGrid = styled.div`
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
  @media (max-width: 680px) { grid-template-columns: 1fr; }
`;

export const SourceCard = styled(Link)`
  width: 100%;
  min-height: 210px;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  padding: 22px;
  border: 1px solid ${brandColors.border};
  border-radius: 7px;
  background: #fff;
  color: ${brandColors.ink};
  text-align: left;
  text-decoration: none;
  transition: border-color .15s ease, box-shadow .15s ease;
  &:hover, &:focus-visible { border-color: ${brandColors.revive}; box-shadow: 0 0 0 2px rgba(183, 241, 61, .18); }
  &:focus-visible { outline: 2px solid ${brandColors.revive}; outline-offset: 2px; }
  > span:last-child { margin-top: auto; color: ${brandColors.ink}; font-size: 12px; font-weight: 700; }
`;

export const SourceIcon = styled.span`
  width: 48px;
  height: 48px;
  display: grid;
  place-items: center;
  margin-bottom: 14px;
  border-radius: 8px;
  background: #eff9d5;
  color: #486b13;
  font-size: 25px;
`;

export const SourceTitle = styled.strong`
  margin-bottom: 7px;
  font-size: 15px;
`;

export const SourceDescription = styled.span`
  margin-bottom: 18px;
  color: ${brandColors.textSecondary};
  font-size: 12px;
  line-height: 1.5;
`;

export const ReadOnlyNotice = styled.p`
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 18px 0 0;
  padding: 13px 15px;
  border: 1px solid #dce9bd;
  border-radius: 5px;
  background: #f5f9e9;
  color: #53672c;
  font-size: 12px;
`;
