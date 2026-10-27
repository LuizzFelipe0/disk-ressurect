const INVALID_DISPLAY_CHARACTERS = /[\uFFFD\u0000-\u001F\u007F]/g;

export function sanitizeDisplayText(value: string): string {
  return value
    .replace(INVALID_DISPLAY_CHARACTERS, " ")
    .replace(/\s{2,}/g, " ")
    .trim();
}
