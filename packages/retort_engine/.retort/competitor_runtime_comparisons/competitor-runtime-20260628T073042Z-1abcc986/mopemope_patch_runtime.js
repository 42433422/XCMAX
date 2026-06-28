
const fs = require("node:fs");

const patchPath = process.argv[2];
const outputPath = process.argv[3];
const patch = fs.readFileSync(patchPath, "utf8");

function parsePatch(filename, patchText) {
  const lines = patchText.split("\n");
  const results = [];
  for (let i = 0; i < lines.length; i++) {
    const match = lines[i].match(/@@ -(\d+),(\d+) \+(\d+),(\d+) @@(.*)/);
    if (!match) continue;
    const fromStart = Number.parseInt(match[1], 10);
    const fromCount = Number.parseInt(match[2], 10);
    const toStart = Number.parseInt(match[3], 10);
    const toCount = Number.parseInt(match[4], 10);
    const fromContent = [];
    const toContent = [];
    let lineNo = toStart - 1;
    i++;
    while (i < lines.length && !lines[i].startsWith("@@")) {
      const line = lines[i];
      if (line.startsWith("+")) {
        lineNo++;
        toContent.push(`${lineNo} ${line}`);
      } else if (line.startsWith("-")) {
        fromContent.push(line);
      } else {
        lineNo++;
        fromContent.push(line);
        toContent.push(`${lineNo} ${line}`);
      }
      i++;
    }
    i--;
    results.push({
      from: { filename, startLine: fromStart, lineCount: fromCount, content: fromContent },
      to: { filename, startLine: toStart, lineCount: toCount, content: toContent },
    });
  }
  return results;
}

const hunks = parsePatch("src/main.ts", patch);
const addedLineCount = hunks.reduce((total, hunk) => total + hunk.to.content.filter((line) => line.includes(" +")).length, 0);
fs.writeFileSync(outputPath, JSON.stringify({ status: "parsed", hunk_count: hunks.length, added_line_count: addedLineCount, hunks }, null, 2));
