#!/usr/bin/env node

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { createRequire } from 'module';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

function parseArgs(argv) {
  const args = { _: [] };
  for (let i = 2; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg.startsWith('--')) {
      const key = arg.replace(/^--/, '');
      const next = argv[i + 1];
      if (next && !next.startsWith('--')) {
        args[key] = next;
        i += 1;
      } else {
        args[key] = true;
      }
    } else {
      args._.push(arg);
    }
  }
  return args;
}

const args = parseArgs(process.argv);
const repo = args.repo ? path.resolve(args.repo) : process.cwd();
const focus = (args.focus || 'domain,infra,tests')
  .split(',')
  .map((v) => v.trim())
  .filter(Boolean);
const top = Number.parseInt(args.top || '40', 10);
const format = args.format || 'json';
const outPath = args.out ? path.resolve(args.out) : null;
const include = (args.include || '')
  .split(',')
  .map((v) => v.trim())
  .filter(Boolean);
const exclude = (args.exclude || '')
  .split(',')
  .map((v) => v.trim())
  .filter(Boolean);

const defaultExclude = [
  '/node_modules/',
  '/dist/',
  '/build/',
  '/coverage/',
  '/.git/',
  '/.turbo/',
  '/.next/',
  '/.cache/',
  '/.codex/',
  '/test-legacy/',
];

function shouldSkip(filePath) {
  const normalized = filePath.split(path.sep).join('/');
  if (defaultExclude.some((part) => normalized.includes(part))) return true;
  if (exclude.some((part) => normalized.includes(part))) return true;
  if (include.length > 0 && !include.some((part) => normalized.includes(part))) return true;
  return false;
}

function walk(dir, out) {
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  for (const entry of entries) {
    const full = path.join(dir, entry.name);
    if (shouldSkip(full)) continue;
    if (entry.isDirectory()) {
      walk(full, out);
    } else if (entry.isFile() && full.endsWith('.ts') && !full.endsWith('.d.ts')) {
      out.push(full);
    }
  }
}

function loadTypeScript(repoRoot) {
  try {
    const requireFromRepo = createRequire(path.join(repoRoot, 'package.json'));
    return requireFromRepo('typescript');
  } catch (error) {
    return null;
  }
}

const ts = loadTypeScript(repo);
if (!ts) {
  console.error('TypeScript not found under repo. Install deps or run from a repo with node_modules.');
  process.exit(2);
}

function getCategory(filePath) {
  const normalized = filePath.split(path.sep).join('/');
  if (
    normalized.includes('/test/') ||
    normalized.includes('/tests/') ||
    normalized.includes('/test-legacy/') ||
    normalized.endsWith('.test.ts') ||
    normalized.endsWith('.spec.ts')
  ) {
    return 'tests';
  }
  if (
    normalized.includes('/core/') ||
    normalized.includes('/infra/') ||
    normalized.includes('/common/') ||
    normalized.includes('/scripts/shared/') ||
    normalized.includes('/config/')
  ) {
    return 'infra';
  }
  return 'domain';
}

function isBranchNode(node) {
  return (
    ts.isIfStatement(node) ||
    ts.isForStatement(node) ||
    ts.isForInStatement(node) ||
    ts.isForOfStatement(node) ||
    ts.isWhileStatement(node) ||
    ts.isDoStatement(node) ||
    ts.isSwitchStatement(node) ||
    ts.isConditionalExpression(node) ||
    ts.isTryStatement(node) ||
    ts.isCatchClause(node)
  );
}

function isBlockLike(node) {
  return (
    ts.isBlock(node) ||
    ts.isIfStatement(node) ||
    ts.isForStatement(node) ||
    ts.isForInStatement(node) ||
    ts.isForOfStatement(node) ||
    ts.isWhileStatement(node) ||
    ts.isDoStatement(node) ||
    ts.isSwitchStatement(node) ||
    ts.isTryStatement(node) ||
    ts.isCatchClause(node)
  );
}

function getLineSpan(sourceFile, node) {
  const start = sourceFile.getLineAndCharacterOfPosition(node.getStart());
  const end = sourceFile.getLineAndCharacterOfPosition(node.getEnd());
  return {
    startLine: start.line + 1,
    endLine: end.line + 1,
    lineSpan: end.line - start.line + 1,
  };
}

function scoreFunction(metrics) {
  let score = 0;
  if (metrics.lineSpan >= 80) score += 2;
  if (metrics.lineSpan >= 120) score += 1;
  if (metrics.branchCount >= 12) score += 2;
  if (metrics.branchCount >= 20) score += 1;
  if (metrics.maxDepth >= 4) score += 2;
  if (metrics.maxDepth >= 6) score += 1;
  if (metrics.paramCount >= 6) score += 1;
  if (metrics.genericCount >= 6) score += 1;
  return score;
}

function scoreClass(metrics) {
  let score = 0;
  if (metrics.constructorParams >= 6) score += 2;
  if (metrics.constructorParams >= 9) score += 1;
  if (metrics.methodCount >= 15) score += 1;
  return score;
}

function scoreFile(metrics, filePath) {
  let score = 0;
  if (metrics.lineCount >= 400) score += 2;
  if (metrics.lineCount >= 600) score += 1;
  if (metrics.importCount >= 30) score += 1;
  if (metrics.exportCount >= 6) score += 1;
  if (/(factory|builder|strategy|orchestrator|manager|wrapper|adapter|provider)/i.test(filePath)) score += 1;
  return score;
}

function analyzeFile(filePath) {
  const sourceText = fs.readFileSync(filePath, 'utf8');
  const sourceFile = ts.createSourceFile(filePath, sourceText, ts.ScriptTarget.Latest, true);
  const fileLineCount = sourceFile.getLineAndCharacterOfPosition(sourceFile.getEnd()).line + 1;
  let importCount = 0;
  let exportCount = 0;
  const zones = [];

  function addFunctionZone(name, node, extra) {
    const span = getLineSpan(sourceFile, node);
    const metrics = {
      lineSpan: span.lineSpan,
      branchCount: extra.branchCount,
      maxDepth: extra.maxDepth,
      paramCount: extra.paramCount,
      genericCount: extra.genericCount,
    };
    const score = scoreFunction(metrics);
    if (score <= 0) return;
    zones.push({
      kind: 'function',
      name,
      filePath,
      startLine: span.startLine,
      endLine: span.endLine,
      metrics,
      score,
    });
  }

  function addClassZone(name, node, metrics) {
    const span = getLineSpan(sourceFile, node);
    const score = scoreClass(metrics);
    if (score <= 0) return;
    zones.push({
      kind: 'class',
      name,
      filePath,
      startLine: span.startLine,
      endLine: span.endLine,
      metrics,
      score,
    });
  }

  function analyzeFunctionLike(node, name) {
    let branchCount = 0;
    let maxDepth = 0;
    let depth = 0;
    let genericCount = 0;

    function walk(n) {
      if (isBranchNode(n)) branchCount += 1;
      if (ts.isTypeReferenceNode(n) && n.typeArguments && n.typeArguments.length > 0) {
        genericCount += n.typeArguments.length;
      }
      if (isBlockLike(n)) {
        depth += 1;
        if (depth > maxDepth) maxDepth = depth;
      }
      ts.forEachChild(n, walk);
      if (isBlockLike(n)) {
        depth -= 1;
      }
    }

    if (node.body) {
      walk(node.body);
    }

    const paramCount = node.parameters ? node.parameters.length : 0;
    addFunctionZone(name, node, { branchCount, maxDepth, paramCount, genericCount });
  }

  function visit(node, classStack) {
    if (ts.isImportDeclaration(node)) importCount += 1;
    if (node.modifiers && node.modifiers.some((m) => m.kind === ts.SyntaxKind.ExportKeyword)) exportCount += 1;

    if (ts.isFunctionDeclaration(node) && node.name) {
      analyzeFunctionLike(node, node.name.text);
    }

    if (ts.isMethodDeclaration(node) && node.name) {
      const className = classStack.length > 0 ? classStack[classStack.length - 1] : 'AnonymousClass';
      analyzeFunctionLike(node, `${className}.${node.name.getText(sourceFile)}`);
    }

    if (ts.isArrowFunction(node) || ts.isFunctionExpression(node)) {
      if (ts.isVariableDeclaration(node.parent) && node.parent.name) {
        analyzeFunctionLike(node, node.parent.name.getText(sourceFile));
      }
    }

    if (ts.isClassDeclaration(node) && node.name) {
      const className = node.name.text;
      const constructorNode = node.members.find((m) => ts.isConstructorDeclaration(m));
      const constructorParams = constructorNode ? constructorNode.parameters.length : 0;
      const methodCount = node.members.filter((m) => ts.isMethodDeclaration(m)).length;
      addClassZone(className, node, { constructorParams, methodCount });
      classStack.push(className);
      ts.forEachChild(node, (child) => visit(child, classStack));
      classStack.pop();
      return;
    }

    ts.forEachChild(node, (child) => visit(child, classStack));
  }

  visit(sourceFile, []);

  const fileScore = scoreFile({ lineCount: fileLineCount, importCount, exportCount }, filePath);
  if (fileScore > 0) {
    zones.push({
      kind: 'file',
      name: path.basename(filePath),
      filePath,
      startLine: 1,
      endLine: fileLineCount,
      metrics: { lineCount: fileLineCount, importCount, exportCount },
      score: fileScore,
    });
  }

  return {
    filePath,
    category: getCategory(filePath),
    fileMetrics: { lineCount: fileLineCount, importCount, exportCount },
    zones,
  };
}

const files = [];
walk(repo, files);

const results = [];
for (const file of files) {
  const analysis = analyzeFile(file);
  for (const zone of analysis.zones) {
    results.push({
      ...zone,
      category: analysis.category,
    });
  }
}

const filtered = results.filter((r) => focus.includes(r.category));
const sorted = filtered.sort((a, b) => b.score - a.score || b.metrics?.lineSpan - a.metrics?.lineSpan || 0);
const topResults = Number.isFinite(top) ? sorted.slice(0, top) : sorted;

if (format === 'md') {
  const lines = [];
  lines.push('# Overengineering Scan Report');
  lines.push('');
  lines.push(`Scanned repo: ${repo}`);
  lines.push(`Focus: ${focus.join(', ')}`);
  lines.push(`Total candidates: ${topResults.length}`);
  lines.push('');
  lines.push('| Score | Category | Kind | Location | Evidence |');
  lines.push('| --- | --- | --- | --- | --- |');
  for (const r of topResults) {
    const location = `${path.relative(repo, r.filePath)}:${r.startLine}`;
    const evidence = Object.entries(r.metrics)
      .map(([k, v]) => `${k}=${v}`)
      .join(', ');
    lines.push(`| ${r.score} | ${r.category} | ${r.kind} | ${location} (${r.name}) | ${evidence} |`);
  }
  const out = lines.join('\n');
  if (outPath) {
    fs.writeFileSync(outPath, out, 'utf8');
  } else {
    process.stdout.write(out);
  }
} else {
  const payload = {
    repo,
    focus,
    generatedAt: new Date().toISOString(),
    results: topResults,
  };
  const out = JSON.stringify(payload, null, 2);
  if (outPath) {
    fs.writeFileSync(outPath, out, 'utf8');
  } else {
    process.stdout.write(out);
  }
}
