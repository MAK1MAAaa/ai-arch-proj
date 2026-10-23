import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import { getOctokit } from '@actions/github';

const repository = 'MAK1MAAaa/ai-arch-proj';
type Octokit = ReturnType<typeof getOctokit>;

type WorkflowRunFixture = {
  id: number;
  workflow_id: number;
  run_number: number;
  run_attempt: number;
  event: string;
  path: string;
  head_repository: { full_name: string };
  head_branch: string;
  head_sha: string;
  actor: { login: string };
  triggering_actor: { login: string };
  status: string;
  conclusion: string | null;
  pull_requests: { number: number }[];
  html_url: string;
};

type PullRequestFixture = {
  number: number;
  state: string;
  draft: boolean;
  user: { login: string };
  head: { repo: { full_name: string }; ref: string; sha: string };
  base: { repo: { full_name: string }; ref: string; sha: string };
};

type ApprovalFixture = {
  commit_id: string;
  event: 'APPROVE';
  body?: string;
};

type Fixture = {
  run: WorkflowRunFixture;
  eventRun: WorkflowRunFixture;
  pr: PullRequestFixture;
  runs: WorkflowRunFixture[];
  jobs: { name: string; status?: string; conclusion: string | null }[];
  reviews: { user: { login: string }; state: string; commit_id: string }[];
  approvals: ApprovalFixture[];
  failures: (string | Error)[];
  requests: string[];
  latestReads: number;
  prReads: number;
  currentRuns?: (readCount: number) => WorkflowRunFixture[];
  currentPr?: (readCount: number) => PullRequestFixture;
};

type Mutation = (state: Fixture) => void;
type WorkflowContext = {
  repo: { owner: string; repo: string };
  payload: { workflow_run: WorkflowRunFixture };
};
type CoreFixture = {
  info: (message: string) => void;
  setFailed: (message: string | Error) => void;
};
type WorkflowScript = (
  github: Octokit,
  context: WorkflowContext,
  core: CoreFixture,
) => Promise<void>;
type AsyncFunctionConstructor = new (...parameters: string[]) => WorkflowScript;

const asyncPrototype: unknown = Object.getPrototypeOf(async function () {});
const AsyncFunction = (asyncPrototype as { constructor: AsyncFunctionConstructor }).constructor;

function isApproval(value: unknown): value is ApprovalFixture {
  return typeof value === 'object' && value !== null
    && 'commit_id' in value && typeof value.commit_id === 'string'
    && 'event' in value && value.event === 'APPROVE'
    && (!('body' in value) || typeof value.body === 'string');
}

function workflowScript(filename: string): WorkflowScript {
  const text = readFileSync(new URL(`../../.github/workflows/${filename}`, import.meta.url), 'utf8');
  const lines = text.split(/\r?\n/);
  const marker = lines.findIndex((line) => /^\s+script: \|$/.test(line));
  assert.notEqual(marker, -1, `No github-script block in ${filename}`);
  const whitespace = lines[marker].match(/^\s*/);
  assert(whitespace !== null);
  const indent = whitespace[0].length + 2;
  const body: string[] = [];
  for (const line of lines.slice(marker + 1)) {
    if (line.trim() && !line.startsWith(' '.repeat(indent))) break;
    body.push(line.slice(indent));
  }
  return new AsyncFunction('github', 'context', 'core', body.join('\n'));
}

function fixture(): Fixture {
  const run: WorkflowRunFixture = {
    id: 101, workflow_id: 7, run_number: 10, run_attempt: 1,
    event: 'pull_request', path: '.github/workflows/ci.yml',
    head_repository: { full_name: repository }, head_branch: 'feature/dev',
    head_sha: 'a'.repeat(40), actor: { login: 'MAK1MAAaa' },
    triggering_actor: { login: 'MAK1MAAaa' },
    status: 'completed',
    conclusion: 'success', pull_requests: [{ number: 1 }],
    html_url: `https://github.com/${repository}/actions/runs/101`,
  };
  const pr: PullRequestFixture = {
    number: 1, state: 'open', draft: false, user: { login: 'MAK1MAAaa' },
    head: { repo: { full_name: repository }, ref: 'feature/dev', sha: run.head_sha },
    base: { repo: { full_name: repository }, ref: 'main', sha: 'c'.repeat(40) },
  };
  return {
    run, eventRun: structuredClone(run), pr,
    runs: [run], jobs: [{ name: 'quality-gate', status: 'completed', conclusion: 'success' }],
    reviews: [], approvals: [], failures: [], requests: [], latestReads: 0, prReads: 0,
  };
}

function octokitFor(state: Fixture): Octokit {
  const prefix = `/repos/${repository}`;
  const fetch: typeof globalThis.fetch = async (input, options = {}) => {
    const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url);
    const method = options.method ?? 'GET';
    const route = `${method} ${url.pathname}`;
    const page = Number(url.searchParams.get('page') ?? 1);
    state.requests.push(`${route}?page=${page}`);
    let body: unknown;
    let nextPage = false;
    if (route === `GET ${prefix}/actions/runs/101`) {
      body = state.run;
    } else if (route === `GET ${prefix}/actions/workflows/7/runs`) {
      assert.equal(url.searchParams.get('branch'), 'feature/dev');
      assert.equal(url.searchParams.get('event'), 'pull_request');
      if (page === 1) state.latestReads++;
      const current = state.currentRuns ? state.currentRuns(state.latestReads) : state.runs;
      body = {
        total_count: current.length + 1,
        workflow_runs: page === 1 ? current : [{ ...state.run, id: 100, run_number: 9 }],
      };
      nextPage = page === 1;
    } else if (route === `GET ${prefix}/actions/runs/101/attempts/1/jobs`) {
      body = {
        total_count: state.jobs.length + 1,
        jobs: page === 1 ? [{ name: 'checks (windows-latest)', conclusion: 'success' }] : state.jobs,
      };
      nextPage = page === 1;
    } else if (route === `GET ${prefix}/pulls`) {
      assert.equal(url.searchParams.get('state'), 'open');
      assert.equal(url.searchParams.get('base'), 'main');
      assert.equal(url.searchParams.get('head'), 'MAK1MAAaa:feature/dev');
      body = [state.pr];
    } else if (route === `GET ${prefix}/pulls/1`) {
      state.prReads++;
      body = state.currentPr ? state.currentPr(state.prReads) : state.pr;
    } else if (route === `GET ${prefix}/pulls/1/reviews`) {
      body = state.reviews;
    } else if (route === `POST ${prefix}/pulls/1/reviews`) {
      assert(typeof options.body === 'string');
      const review: unknown = JSON.parse(options.body);
      assert(isApproval(review));
      state.approvals.push(review);
      body = { id: 42, ...review };
    } else {
      throw new Error(`Unexpected network request: ${route}`);
    }
    const headers: Record<string, string> = { 'content-type': 'application/json' };
    if (nextPage) {
      const next = new URL(url);
      next.searchParams.set('page', '2');
      headers.link = `<${next}>; rel="next"`;
    }
    const response = new Response(JSON.stringify(body), {
      status: method === 'POST' ? 201 : 200, headers,
    });
    Object.defineProperty(response, 'url', { value: url.toString() });
    return response;
  };
  return getOctokit('test-token-never-used-on-network', { request: { fetch } });
}

async function execute(mutate: Mutation = () => {}): Promise<Fixture> {
  const state = fixture();
  mutate(state);
  await workflowScript('auto-approve.yml')(
    octokitFor(state),
    {
      repo: { owner: 'MAK1MAAaa', repo: 'ai-arch-proj' },
      payload: { workflow_run: state.eventRun },
    },
    { info: () => {}, setFailed: (message) => state.failures.push(message) },
  );
  for (const approval of state.approvals) {
    assert.equal(approval.commit_id, state.run.head_sha);
    assert.equal(approval.event, 'APPROVE');
  }
  return state;
}

test('real Octokit normalizes object-wrapped workflow runs and jobs across pages', async () => {
  const state = fixture();
  const github = octokitFor(state);
  const runs = await github.paginate(github.rest.actions.listWorkflowRuns, {
    owner: 'MAK1MAAaa', repo: 'ai-arch-proj', workflow_id: 7,
    branch: 'feature/dev', event: 'pull_request', per_page: 100,
  }, (response) => {
    assert(Array.isArray(response.data));
    return response.data;
  });
  assert.deepEqual(runs.map((run) => run.id), [101, 100]);
  const jobs = await github.paginate(github.rest.actions.listJobsForWorkflowRunAttempt, {
    owner: 'MAK1MAAaa', repo: 'ai-arch-proj', run_id: 101, attempt_number: 1, per_page: 100,
  });
  assert.deepEqual(jobs.map((job) => job.name), ['checks (windows-latest)', 'quality-gate']);
});

test('approval reads all pages and approves the current successful commit', async () => {
  const state = await execute();
  assert.equal(state.approvals.length, 1);
  assert.deepEqual(state.failures, []);
  assert(state.requests.some((route) => route.includes('/jobs?page=2')));
});

const scenarios: [name: string, mutate: Mutation][] = [
  ['a newer pending CI', (s) => { s.runs = [{ ...s.run, id: 102, run_number: 11, status: 'queued', conclusion: null }]; }],
  ['a newer failed CI', (s) => { s.runs = [{ ...s.run, id: 102, run_number: 11, conclusion: 'failure' }]; }],
  ['an untrusted actor', (s) => { s.run.actor.login = 'outsider'; }],
  ['an untrusted rerun actor', (s) => { s.run.triggering_actor.login = 'outsider'; }],
  ['a fork', (s) => { s.run.head_repository.full_name = 'outsider/ai-arch-proj'; }],
  ['a different workflow file', (s) => { s.run.path = '.github/workflows/other.yml'; }],
  ['an unfinished CI run', (s) => { s.run.status = 'in_progress'; s.run.conclusion = null; }],
  ['an unsuccessful CI run', (s) => { s.run.conclusion = 'failure'; }],
  ['an older rerun attempt', (s) => { s.run.run_attempt = 2; }],
  ['an unlinked pull request', (s) => { s.run.pull_requests = []; }],
  ['a missing quality gate', (s) => { s.jobs = []; }],
  ['a skipped quality gate', (s) => { s.jobs[0].conclusion = 'skipped'; }],
  ['a changed PR head', (s) => { s.pr.head.sha = 'b'.repeat(40); }],
  ['a changed target branch', (s) => { s.pr.base.ref = 'other'; }],
  ['a draft PR', (s) => { s.pr.draft = true; }],
  ['an existing current approval', (s) => { s.reviews = [{ user: { login: 'github-actions[bot]' }, state: 'APPROVED', commit_id: s.run.head_sha }]; }],
  ['a race introducing newer CI', (s) => { s.currentRuns = (count) => count === 1 ? [s.run] : [{ ...s.run, id: 102, run_number: 11, status: 'queued', conclusion: null }]; }],
  ['a race changing the PR head', (s) => { s.currentPr = (count) => count === 1 ? s.pr : { ...s.pr, head: { ...s.pr.head, sha: 'b'.repeat(40) } }; }],
];
for (const [name, mutate] of scenarios) {
  test(`approval is refused for ${name}`, async () => {
    const state = await execute(mutate);
    assert.equal(state.approvals.length, 0);
  });
}

test('a dismissed approval does not prevent reapproval after successful CI', async () => {
  const state = await execute((s) => {
    s.reviews = [{ user: { login: 'github-actions[bot]' }, state: 'DISMISSED', commit_id: s.run.head_sha }];
  });
  assert.equal(state.approvals.length, 1);
});

