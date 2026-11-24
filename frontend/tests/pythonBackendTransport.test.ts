import { Writable } from "node:stream";
import { describe, expect, it } from "vitest";
import { writeJsonLine } from "../src/utils/pythonBackendTransport";

describe("writeJsonLine", () => {
  it("writes a complete JSON-lines message", async () => {
    let written = "";
    const stream = new Writable({
      write(chunk, _encoding, callback) {
        written += chunk.toString();
        callback();
      },
    });

    await expect(writeJsonLine(stream, '{"id":"request-1"}\n')).resolves.toBeUndefined();
    expect(written).toBe('{"id":"request-1"}\n');
    stream.destroy();
  });

  it("surfaces a broken-pipe write error while the process listener handles the stream event", async () => {
    const stream = new Writable({
      write(_chunk, _encoding, callback) {
        const error = Object.assign(new Error("broken pipe"), { code: "EPIPE" });
        callback(error);
      },
    });
    const streamErrors: Error[] = [];
    stream.on("error", (error) => streamErrors.push(error));

    await expect(writeJsonLine(stream, "{}\n")).rejects.toMatchObject({
      message: "broken pipe",
      code: "EPIPE",
    });
    await new Promise<void>((resolve) => setImmediate(resolve));
    expect(streamErrors).toHaveLength(1);
  });

  it("rejects a closed input pipe before attempting a write", async () => {
    const stream = new Writable({ write: (_chunk, _encoding, callback) => callback() });
    stream.destroy();

    await expect(writeJsonLine(stream, "{}\n")).rejects.toThrow(
      "Python backend input pipe is not writable",
    );
  });
});
