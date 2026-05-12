/**
 * axe-core accessibility test helpers.
 *
 * Keep this helper dependency-free beyond axe-core so component tests can import
 * it in Vitest without pulling in Jest-specific matchers.
 */
import axeCore from 'axe-core';
import type { AxeResults, ElementContext, RunOptions } from 'axe-core';

const defaultRunOptions: RunOptions = {
  runOnly: {
    type: 'tag',
    values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'],
  },
  rules: {
    'aria-allowed-attr': { enabled: true },
    'aria-required-attr': { enabled: true },
    'aria-valid-attr-value': { enabled: true },
    'button-name': { enabled: true },
    'image-alt': { enabled: true },
    'input-button-name': { enabled: true },
    label: { enabled: true },
    'link-name': { enabled: true },
    list: { enabled: true },
    listitem: { enabled: true },
  },
};

function mergeRunOptions(options?: RunOptions): RunOptions {
  if (!options) {
    return defaultRunOptions;
  }

  return {
    ...defaultRunOptions,
    ...options,
    rules: {
      ...defaultRunOptions.rules,
      ...options.rules,
    },
  };
}

export const wcagLevels = {
  A: { runOnly: { type: 'tag' as const, values: ['wcag2a', 'wcag21a'] } },
  AA: {
    runOnly: {
      type: 'tag' as const,
      values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'],
    },
  },
  AAA: {
    runOnly: {
      type: 'tag' as const,
      values: [
        'wcag2a',
        'wcag2aa',
        'wcag2aaa',
        'wcag21a',
        'wcag21aa',
        'wcag21aaa',
      ],
    },
  },
} satisfies Record<string, RunOptions>;

export async function axe(
  context: ElementContext,
  options?: RunOptions
): Promise<AxeResults> {
  return axeCore.run(context, mergeRunOptions(options));
}

export async function checkA11y(
  container: HTMLElement,
  options?: RunOptions
): Promise<AxeResults> {
  const results = await axe(container, options);

  if (results.violations.length > 0) {
    console.error('Accessibility violations:', formatViolations(results));
  }

  return results;
}

export function createAxeWithRules(rules: string[]): typeof axe {
  return (context: ElementContext, options?: RunOptions) => {
    const ruleOptions = rules.reduce<NonNullable<RunOptions['rules']>>(
      (acc, rule) => {
        acc[rule] = { enabled: true };
        return acc;
      },
      {}
    );

    return axe(context, {
      ...options,
      runOnly: { type: 'rule', values: rules },
      rules: {
        ...options?.rules,
        ...ruleOptions,
      },
    });
  };
}

export function formatViolations(results: AxeResults): string {
  if (results.violations.length === 0) {
    return 'No accessibility violations';
  }

  return results.violations
    .map((violation) => {
      const nodes = violation.nodes
        .map((node) => `  - ${node.html}\n    ${node.failureSummary}`)
        .join('\n');

      return `${violation.id} (${violation.impact})
${violation.description}
${violation.helpUrl}
Affected nodes:
${nodes}`;
    })
    .join('\n\n');
}
