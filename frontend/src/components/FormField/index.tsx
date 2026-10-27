import React from "react";
import { FieldLabel } from "./style";

interface FormFieldProps extends React.LabelHTMLAttributes<HTMLLabelElement> {
  label: React.ReactNode;
  children: React.ReactNode;
  grow?: boolean;
}

export const FormField: React.FC<FormFieldProps> = ({ label, children, grow = false, ...props }) => (
  <FieldLabel $grow={grow} {...props}>
    {label}
    {children}
  </FieldLabel>
);
