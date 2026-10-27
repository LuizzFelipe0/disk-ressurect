import styled from "styled-components";

export const Notice = styled.div<{ $spaced: boolean }>`
  margin-top: ${({ $spaced }) => $spaced ? "10px" : "0"};
  padding: 10px 13px;
  border: 1px solid #f5c9ce;
  border-radius: 9px;
  background: #fff2f3;
  color: #a4313e;
  font-size: 12px;
  overflow-wrap: anywhere;
`;
