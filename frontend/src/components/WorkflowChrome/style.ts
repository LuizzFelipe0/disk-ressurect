import styled from "styled-components";

export const PageHeader = styled.div`
  flex: 0 0 auto;
  width: 100%;
  min-width: 0;
  > header { width: 100%; }
`;

export const HeaderActions = styled.div`
  display: flex;
  align-items: center;
  gap: 10px;
  > span button { display: inline-flex; align-items: center; gap: 8px; }
  img { width: 18px; height: 18px; object-fit: contain; }
`;
