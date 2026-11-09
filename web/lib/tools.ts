// The MCP server's tools, read from the definitions it publishes at
// /tools/openai.json, so the API page never states a count or a list that the
// server does not.

export type ToolInfo = { name: string; description: string };

/** Name and description of each tool in OpenAI function-calling form; anything else is skipped. */
export function toolList(definitions: unknown): ToolInfo[] {
  if (!Array.isArray(definitions)) return [];
  const tools: ToolInfo[] = [];
  for (const entry of definitions) {
    const fn = (entry as { function?: { name?: unknown; description?: unknown } } | null)?.function;
    if (fn && typeof fn.name === "string") {
      tools.push({ name: fn.name, description: typeof fn.description === "string" ? fn.description : "" });
    }
  }
  return tools;
}

const NUMBER_WORDS = [
  "no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
  "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty",
];

/** "ten" for 10, the digits above twenty. */
export const countWord = (n: number): string => NUMBER_WORDS[n] ?? String(n);
