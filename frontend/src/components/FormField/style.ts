import styled from "styled-components";

export const FieldLabel = styled.label<{ $grow: boolean }>`
  display: flex;
  flex: ${({ $grow }) => $grow ? "1" : "initial"};
  flex-direction: column;
  gap: 7px;
  min-width: 0;
  color: #586984;
  font-size: 12px;
  font-weight: 650;

  select, input {
    width: 100%;
    min-height: 39px;
    padding: 8px 11px;
    color: #23324a;
    background: #fff;
    border: 1px solid #d9e0ea;
    border-radius: 8px;
    outline: none;
  }

  select:focus, input:focus { border-color: #5291e4; box-shadow: 0 0 0 3px rgba(72,139,225,.13); }
`;
