import { spawn } from 'node:child_process';

const fatalPatterns = [
  {
    name: 'React act boundary warning',
    pattern: /not wrapped in act/i,
  },
  {
    name: 'React act environment warning',
    pattern: /The current testing environment is not configured to support act/i,
  },
  {
    name: 'Radix Dialog missing title',
    pattern: /`DialogContent`\s+requires\s+a\s+`DialogTitle`/i,
  },
  {
    name: 'Radix Dialog missing description',
    pattern: /Missing `Description`[^\n]*(?:DialogContent|aria-describedby=\{undefined\})/i,
  },
  {
    name: 'Radix Dialog undefined aria-describedby',
    pattern: /aria-describedby=\{undefined\}[^\n]*DialogContent/i,
  },
  {
    name: 'Tailwind ambiguous utility',
    pattern: /The class `[^`]+` is ambiguous and matches multiple utilities/i,
  },
  {
    name: 'React invalid DOM nesting',
    pattern: /In HTML, <[^>]+> cannot be a descendant of <[^>]+>/i,
  },
  {
    name: 'React nested DOM warning',
    pattern: /cannot contain a nested <[^>]+>/i,
  },
  {
    name: 'React validateDOMNesting warning',
    pattern: /validateDOMNesting/i,
  },
];

function findFatalWarnings(output) {
  return fatalPatterns.filter(({ pattern }) => pattern.test(output));
}

function runSelfTest() {
  const fixtures = [
    'Warning: An update to TestComponent inside a test was not wrapped in act(...).',
    'The current testing environment is not configured to support act(...)',
    '`DialogContent` requires a `DialogTitle` for the component to be accessible.',
    'Warning: Missing `Description` or `aria-describedby={undefined}` for {DialogContent}.',
    'The class `duration-[12s]` is ambiguous and matches multiple utilities.',
    'In HTML, <div> cannot be a descendant of <p>.',
    '<p> cannot contain a nested <div>.',
    'Warning: validateDOMNesting(...): <div> cannot appear as a descendant of <p>.',
  ];
  const misses = fixtures.filter((fixture) => findFatalWarnings(fixture).length === 0);
  const falsePositive = findFatalWarnings('52 tests passed without target warnings.').length > 0;

  if (misses.length > 0 || falsePositive) {
    console.error('warning gate self-test failed');
    for (const miss of misses) {
      console.error(`missed fixture: ${miss}`);
    }
    if (falsePositive) {
      console.error('clean output matched a fatal warning pattern');
    }
    process.exit(1);
  }

  console.log('warning gate self-test passed');
}

function parseCommand(argv) {
  const separatorIndex = argv.indexOf('--');
  const commandArgs = separatorIndex === -1 ? argv : argv.slice(separatorIndex + 1);
  if (commandArgs.length === 0) {
    console.error('usage: node scripts/fail-on-warning-output.mjs -- <command> [args...]');
    process.exit(2);
  }
  return [commandArgs[0], commandArgs.slice(1)];
}

if (process.argv.includes('--self-test')) {
  runSelfTest();
  process.exit(0);
}

const [command, args] = parseCommand(process.argv.slice(2));
const child = spawn(command, args, {
  env: process.env,
  shell: process.platform === 'win32',
  stdio: ['ignore', 'pipe', 'pipe'],
});

const outputChunks = [];

child.stdout.on('data', (chunk) => {
  outputChunks.push(chunk);
  process.stdout.write(chunk);
});

child.stderr.on('data', (chunk) => {
  outputChunks.push(chunk);
  process.stderr.write(chunk);
});

child.on('error', (error) => {
  console.error(`failed to start warning-gated command: ${error.message}`);
  process.exit(1);
});

child.on('close', (code, signal) => {
  const output = Buffer.concat(outputChunks).toString('utf8');
  const matchedWarnings = findFatalWarnings(output);

  if (matchedWarnings.length > 0) {
    console.error('\nfrontend warning gate failed. Remove these warning classes before merging:');
    for (const warning of matchedWarnings) {
      console.error(`- ${warning.name}`);
    }
    process.exit(1);
  }

  if (signal) {
    console.error(`warning-gated command terminated by signal ${signal}`);
    process.exit(1);
  }

  process.exit(code ?? 0);
});
