// A write acknowledgement and a failed refresh are different outcomes. Keeping
// the modal locked until readback settles also prevents reopening a stale form.
export async function saveThenRefresh({save, commit, refresh, close}) {
  const record = await save();
  let refreshError = null;
  try {
    commit(record);
    await refresh();
  } catch (error) {
    refreshError = error;
  }
  close();
  return {record, refreshError};
}

export function withSavedRecord(state, collection, record) {
  const found = state[collection].some(item => item.id === record.id);
  return {...state, [collection]: found
    ? state[collection].map(item => item.id === record.id ? record : item)
    : [...state[collection], record]};
}
