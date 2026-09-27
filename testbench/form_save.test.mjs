import assert from 'node:assert/strict';
import test from 'node:test';
import {saveThenRefresh, withSavedRecord} from './js/form-save.js';

const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
};

test('dialog cannot reopen stale values while acknowledged save is refreshing', async () => {
  const saved = {id: 1, email: 'élève@example.test'};
  let state = {customers: [{id: 1, email: 'old@example.test'}]};
  const write = deferred(), read = deferred(), reading = deferred();
  let open = true, saves = 0;
  const completed = saveThenRefresh({
    save: () => { saves++; return write.promise; },
    commit: record => { state = withSavedRecord(state, 'customers', record); },
    refresh: () => { reading.resolve(); return read.promise; },
    close: () => { assert.equal(state.customers[0].email, saved.email); open = false; },
  });
  assert.equal(open, true);
  write.resolve(saved);
  await reading.promise;
  assert.equal(open, true, 'A delayed GET must not leave the stale-form reopen window');
  assert.equal(state.customers[0].email, saved.email);
  read.resolve();
  assert.deepEqual(await completed, {record: saved, refreshError: null});
  assert.equal(open, false);
  assert.equal(saves, 1);
});

test('failed readback preserves acknowledged data and never resubmits the write', async () => {
  const record = {id: 9, name: 'New account'};
  let state = {customers: []}, saves = 0, closed = 0;
  const failure = new Error('Readback unavailable');
  const result = await saveThenRefresh({
    save: async () => { saves++; return record; },
    commit: value => { state = withSavedRecord(state, 'customers', value); },
    refresh: async () => { throw failure; },
    close: () => { closed++; },
  });
  assert.equal(result.refreshError, failure);
  assert.deepEqual(state.customers, [record]);
  assert.equal(result.record.id, 9);
  assert.equal(saves, 1);
  assert.equal(closed, 1);
});

test('rejected write keeps dialog open and never claims a saved record', async () => {
  const calls = [];
  await assert.rejects(saveThenRefresh({
    save: async () => { throw new Error('Duplicate email'); },
    commit: () => calls.push('commit'),
    refresh: () => calls.push('refresh'),
    close: () => calls.push('close'),
  }), /Duplicate email/);
  assert.deepEqual(calls, []);
});

test('cache uses normalized response and preserves unrelated data immutably', () => {
  const original = {run_id: 'run', customers: [{id: 1, name: 'Old'}, {id: 2, name: 'Keep'}], tickets: []};
  const saved = {id: 1, name: 'Normalized name', status: 'Active'};
  const changed = withSavedRecord(original, 'customers', saved);
  assert.equal(original.customers[0].name, 'Old');
  assert.deepEqual(changed.customers, [saved, original.customers[1]]);
  assert.equal(changed.run_id, 'run');
  assert.equal(changed.tickets, original.tickets);
});

test('new server-issued ID is inserted once', () => {
  const saved = {id: 99, name: 'Added'};
  const once = withSavedRecord({customers: []}, 'customers', saved);
  assert.deepEqual(withSavedRecord(once, 'customers', saved).customers, [saved]);
});

test('same flow supports string ticket IDs', () => {
  const saved = {id: 'AX-104', title: 'Unicode 中文', status: 'Done'};
  assert.deepEqual(withSavedRecord({tickets: [{id: 'AX-104', status: 'Backlog'}]}, 'tickets', saved).tickets, [saved]);
});

test('post-ack rendering error remains distinct from write rejection', async () => {
  const saved = {id: 1}, failure = new Error('Render failed');
  let closed = 0;
  const result = await saveThenRefresh({
    save: async () => saved,
    commit: () => { throw failure; },
    refresh: async () => assert.fail('No refresh after failed render'),
    close: () => closed++,
  });
  assert.equal(result.record, saved);
  assert.equal(result.refreshError, failure);
  assert.equal(closed, 1);
});
