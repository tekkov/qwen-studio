import { Client } from '@modelcontextprotocol/client';
import { StdioClientTransport } from '@modelcontextprotocol/client/stdio';

const input = await new Promise((resolve, reject) => {
  let data = '';
  process.stdin.setEncoding('utf8');
  process.stdin.on('data', chunk => data += chunk);
  process.stdin.on('end', () => { try { resolve(JSON.parse(data)); } catch (error) { reject(error); } });
});

const config = input.config;
if (!config || config.transport !== 'stdio') throw new Error('Only stdio MCP connections are supported by this build.');

const transport = new StdioClientTransport({ command: config.command, args: config.args || [], env: { ...process.env, ...(config.env || {}) } });
const client = new Client({ name: 'qwen-local-agent', version: '1.0.0' });

try {
  await client.connect(transport);
  if (input.action === 'list') {
    const result = await client.listTools();
    process.stdout.write(JSON.stringify({ tools: result.tools || [] }));
  } else if (input.action === 'call') {
    const result = await client.callTool({ name: input.tool, arguments: input.arguments || {} });
    process.stdout.write(JSON.stringify(result));
  } else {
    throw new Error('Unknown MCP action.');
  }
} finally {
  await client.close();
}
