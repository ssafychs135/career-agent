import { live } from './adapter.js';
import { encode, MAX_LINE, parseRequest } from './protocol.js';

// One request per process. stdin is bounded and must end; no live SDK is loaded.
async function main(): Promise<void> {
  let size = 0;
  const chunks: Buffer[] = [];
  for await (const chunk of process.stdin) {
    const data = Buffer.from(chunk as Uint8Array);
    size += data.length;
    if (size > MAX_LINE) throw Error('protocol_error');
    chunks.push(data);
  }
  const text = new TextDecoder('utf-8', { fatal: true }).decode(Buffer.concat(chunks));
  const req = parseRequest(text);
  process.stdout.write(encode(live(req)));
}
main().catch(() => { process.exitCode = 2; });
