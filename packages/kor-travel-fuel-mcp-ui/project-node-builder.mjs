import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

// Python runtime 명령은 제외하되 실제 Dockerfile의 Node stage를 빠짐없이 중앙 검사기에 보낸다.
export function projectNodeBuilder(source) {
  const stages = source.split(/(?=^FROM\s)/m).filter(x => /^FROM\s/m.test(x));
  const node = stages.filter(x => /^FROM\s+(?:--platform=\S+\s+)?(?:docker\.io\/(?:library\/)?|library\/)?node:/m.test(x));
  if (node.length !== 1 || !/^FROM[^\n]+ AS fuel-mcp-ui\s*$/m.test(node[0])) throw new Error("유일한 fuel-mcp-ui Node stage가 필요합니다");
  const rest = stages.filter(x => x !== node[0]).join("\n");
  if (/^FROM\s+(?:--platform=\S+\s+)?fuel-mcp-ui(?:\s|$)/m.test(rest) || /\b(?:npm|npx)\s/m.test(rest)) throw new Error("검사 범위 밖 Node 명령을 허용하지 않습니다");
  return node[0];
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.stdout.write(projectNodeBuilder(readFileSync(new URL("../../backend/Dockerfile", import.meta.url), "utf8")));
}
