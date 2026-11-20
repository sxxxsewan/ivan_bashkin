import http from 'k6/http';
import { check } from 'k6';
import { SharedArray } from 'k6/data';
import { Counter, Trend } from 'k6/metrics';
import execution from 'k6/execution';

const baseUrl = __ENV.BASE_URL || 'http://localhost:8000';
const scenario = __ENV.SCENARIO || 'mixed';
const rate = Number(__ENV.RATE || 1);
const duration = __ENV.DURATION || '30s';
const offset = Number(__ENV.OFFSET || 0);
const dataDir = __ENV.DATA_DIR || '../logs/dz2';

const issuePairs = new SharedArray('issue pairs', () =>
  JSON.parse(open(`${dataDir}/issue_pairs.json`)),
);
const returnLoanIds = new SharedArray('return loan IDs', () =>
  JSON.parse(open(`${dataDir}/return_loan_ids.json`)),
);
const detailLoanIds = new SharedArray('detail loan IDs', () =>
  JSON.parse(open(`${dataDir}/detail_loan_ids.json`)),
);
const dbTime = new Trend('db_time_ms', true);
const appTime = new Trend('app_time_ms', true);
const dbTimeShare = new Trend('db_time_share_pct');
const dbQueries = new Counter('db_query_count');
const operationMetrics = {
  'GET /api/v1/loans': {
    requests: new Counter('op_list_requests'),
    http: new Trend('op_list_http_ms', true),
    db: new Trend('op_list_db_ms', true),
    app: new Trend('op_list_app_ms', true),
    dbShare: new Trend('op_list_db_share_pct'),
    dbQueries: new Counter('op_list_db_queries'),
  },
  'GET /api/v1/loans/{id}': {
    requests: new Counter('op_detail_requests'),
    http: new Trend('op_detail_http_ms', true),
    db: new Trend('op_detail_db_ms', true),
    app: new Trend('op_detail_app_ms', true),
    dbShare: new Trend('op_detail_db_share_pct'),
    dbQueries: new Counter('op_detail_db_queries'),
  },
  'POST /api/v1/loans': {
    requests: new Counter('op_issue_requests'),
    http: new Trend('op_issue_http_ms', true),
    db: new Trend('op_issue_db_ms', true),
    app: new Trend('op_issue_app_ms', true),
    dbShare: new Trend('op_issue_db_share_pct'),
    dbQueries: new Counter('op_issue_db_queries'),
  },
  'POST /api/v1/loans/{id}/return': {
    requests: new Counter('op_return_requests'),
    http: new Trend('op_return_http_ms', true),
    db: new Trend('op_return_db_ms', true),
    app: new Trend('op_return_app_ms', true),
    dbShare: new Trend('op_return_db_share_pct'),
    dbQueries: new Counter('op_return_db_queries'),
  },
  'GET /api/v1/summary': {
    requests: new Counter('op_summary_requests'),
    http: new Trend('op_summary_http_ms', true),
    db: new Trend('op_summary_db_ms', true),
    app: new Trend('op_summary_app_ms', true),
    dbShare: new Trend('op_summary_db_share_pct'),
    dbQueries: new Counter('op_summary_db_queries'),
  },
};

export const options = {
  scenarios: {
    [scenario]: {
      executor: 'constant-arrival-rate',
      rate,
      timeUnit: '1s',
      duration,
      preAllocatedVUs: Math.max(10, Math.min(256, rate)),
      maxVUs: Math.max(20, Math.min(1024, rate * 4)),
    },
  },
  thresholds: {
    http_req_duration: ['p(95)<500'],
    http_req_failed: ['rate<0.01'],
  },
};

export function setup() {
  const response = http.post(
    `${baseUrl}/api/v1/auth/login`,
    { username: __ENV.USERNAME || 'admin', password: __ENV.PASSWORD || 'admin123' },
    {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      responseCallback: http.expectedStatuses(200),
      tags: { name: 'POST /api/v1/auth/login', operation: 'login' },
    },
  );
  check(response, {
    'login succeeded': (res) => res.status === 200 && Boolean(res.json('access_token')),
  });
  if (response.status !== 200) {
    throw new Error(`Load-test setup login failed with HTTP ${response.status}`);
  }
  return { token: response.json('access_token') };
}

function requestParams(token, operation) {
  return {
    headers: { Authorization: `Bearer ${token}` },
    responseCallback: http.expectedStatuses(200, 201, 409),
    tags: { operation },
  };
}

function captureTiming(response, operation) {
  const header = (name) =>
    response.headers[Object.keys(response.headers).find((key) => key.toLowerCase() === name)];
  const timing = header('server-timing') || '';
  const db = timing.match(/(?:^|,\s*)db;dur=([0-9.]+)/);
  const app = timing.match(/(?:^|,\s*)app;dur=([0-9.]+)/);
  const queries = Number(header('x-db-query-count'));
  if (!db || !app || !Number.isFinite(queries)) {
    throw new Error('API timing headers are missing or invalid');
  }
  const operationMetric = operationMetrics[operation];
  if (!operationMetric) {
    throw new Error(`Unknown operation timing metric: ${operation}`);
  }
  const dbDuration = Number(db[1]);
  const appDuration = Number(app[1]);
  dbTime.add(dbDuration);
  appTime.add(appDuration);
  const serverTime = Number(db[1]) + Number(app[1]);
  if (serverTime > 0) {
    const share = (100 * dbDuration) / serverTime;
    dbTimeShare.add(share);
    operationMetric.dbShare.add(share);
  }
  dbQueries.add(queries);
  operationMetric.requests.add(1);
  operationMetric.http.add(response.timings.duration);
  operationMetric.db.add(dbDuration);
  operationMetric.app.add(appDuration);
  operationMetric.dbQueries.add(queries);
  return response;
}

function chooseOperation(index) {
  const slot = index % 100;
  if (slot < 35) return 'list';
  if (slot < 60) return 'detail';
  if (slot < 80) return 'issue';
  if (slot < 95) return 'return';
  return 'summary';
}

function runMixed(token, index) {
  const operation = chooseOperation(index);
  if (operation === 'list') {
    const statuses = ['active', 'returned', 'overdue'];
    const status = statuses[Math.floor(Math.random() * statuses.length)];
    return captureTiming(http.get(
      `${baseUrl}/api/v1/loans?page=1&size=20&status=${status}`,
      requestParams(token, 'GET /api/v1/loans'),
    ), 'GET /api/v1/loans');
  }
  if (operation === 'detail') {
    const loanId = detailLoanIds[index % detailLoanIds.length];
    return captureTiming(http.get(
      `${baseUrl}/api/v1/loans/${loanId}`,
      requestParams(token, 'GET /api/v1/loans/{id}'),
    ), 'GET /api/v1/loans/{id}');
  }
  if (operation === 'issue') {
    const pairIndex = Math.floor(index / 100) * 20 + (index % 100) - 60;
    const pair = issuePairs[pairIndex];
    if (!pair) {
      throw new Error(`Issue ID pool exhausted at global iteration ${index}`);
    }
    return captureTiming(http.post(
      `${baseUrl}/api/v1/loans`,
      JSON.stringify({ reader_id: pair.reader_id, copy_id: pair.copy_id }),
      {
        ...requestParams(token, 'POST /api/v1/loans'),
        headers: {
          ...requestParams(token, 'POST /api/v1/loans').headers,
          'Content-Type': 'application/json',
        },
      },
    ), 'POST /api/v1/loans');
  }
  if (operation === 'return') {
    const loanIndex = Math.floor(index / 100) * 15 + (index % 100) - 80;
    const loanId = returnLoanIds[loanIndex];
    if (loanId === undefined) {
      throw new Error(`Return ID pool exhausted at global iteration ${index}`);
    }
    return captureTiming(http.post(
      `${baseUrl}/api/v1/loans/${loanId}/return`,
      null,
      requestParams(token, 'POST /api/v1/loans/{id}/return'),
    ), 'POST /api/v1/loans/{id}/return');
  }
  return captureTiming(http.get(
    `${baseUrl}/api/v1/summary`,
    requestParams(token, 'GET /api/v1/summary'),
  ), 'GET /api/v1/summary');
}

export default function (data) {
  const globalIteration = offset + execution.scenario.iterationInTest;
  if (scenario === 'heavy') {
    captureTiming(http.get(
      `${baseUrl}/api/v1/summary`,
      requestParams(data.token, 'GET /api/v1/summary'),
    ), 'GET /api/v1/summary');
    return;
  }
  runMixed(data.token, globalIteration);
}
