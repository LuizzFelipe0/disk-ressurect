import styled from "styled-components";

export const TreeIndent = styled.span`
  width: 20px;
  flex: 0 0 20px;
`;

export const TreeContainer = styled.div`
  min-height: 0;
  overflow: auto;
  padding: 9px 2px;
`;

export const TreeRow = styled.div<{ $depth: number }>`
  display: flex;
  align-items: center;
  min-height: 34px;
  padding: 3px 8px 3px ${({ $depth }) => 8 + $depth * 20}px;
  gap: 9px;
  border-radius: 7px;
  &:hover { background: #f4f8fe; }
  input { width: 15px; height: 15px; margin: 0; accent-color: #2879d5; }
`;

export const TreeName = styled.span`
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
`;

export const TreeMeta = styled.span`
  margin-left: auto;
  color: #93a0b3;
  font-size: 10px;
  white-space: nowrap;
`;

export const ExpandButton = styled.button`
  width: 20px;
  padding: 0;
  border: 0;
  color: #7790ad;
  background: transparent;
  cursor: pointer;
  font-size: 18px;
`;
