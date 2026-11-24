export interface BackendInputStream {
  readonly destroyed?: boolean;
  readonly writableEnded?: boolean;
  readonly writable?: boolean;
  write(line: string, callback: (error?: Error | null) => void): boolean;
}

/** Write one JSON-lines request without leaving a broken pipe unhandled. */
export function writeJsonLine(stream: BackendInputStream, line: string): Promise<void> {
  if (stream.destroyed || stream.writableEnded || !stream.writable) {
    return Promise.reject(new Error("Python backend input pipe is not writable"));
  }

  return new Promise<void>((resolve, reject) => {
    try {
      stream.write(line, (error) => {
        if (error) reject(error);
        else resolve();
      });
    } catch (error) {
      reject(error instanceof Error ? error : new Error(String(error)));
    }
  });
}
