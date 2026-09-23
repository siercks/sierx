import type { Config } from '../api/client';
export function CustomFields({
  definitions,
  values,
}: {
  definitions: Config['fields'];
  values: Record<string, unknown>;
}) {
  return (
    <>
      {definitions.map((f) => (
        <label key={f.key}>
          {f.name}
          <input type="hidden" name={'present:' + f.key} value="1" />
          {f.data_type === 'bool' ? (
            <select
              name={'field:' + f.key}
              defaultValue={
                values[f.key] === undefined || values[f.key] === null
                  ? ''
                  : String(values[f.key])
              }
            >
              <option value="">Not set</option>
              <option value="true">Yes</option>
              <option value="false">No</option>
            </select>
          ) : f.data_type === 'select' || f.data_type === 'multiselect' ? (
            <select
              multiple={f.data_type === 'multiselect'}
              name={'field:' + f.key}
              defaultValue={
                f.data_type === 'multiselect'
                  ? ((values[f.key] as string[]) ?? [])
                  : String(values[f.key] ?? '')
              }
            >
              <option value="">Not set</option>
              {(f.options as string[]).map((o) => (
                <option key={o}>{o}</option>
              ))}
            </select>
          ) : (
            <input
              name={'field:' + f.key}
              type={
                f.data_type === 'number'
                  ? 'number'
                  : f.data_type === 'date'
                    ? 'date'
                    : f.data_type === 'url'
                      ? 'url'
                      : 'text'
              }
              step={f.data_type === 'number' ? 'any' : undefined}
              defaultValue={String(values[f.key] ?? '')}
            />
          )}
        </label>
      ))}
    </>
  );
}
export function customValues(
  data: FormData,
  definitions: Config['fields'],
  previous: Record<string, unknown>,
) {
  const output = { ...previous };
  for (const f of definitions) {
    const raw = data.get('field:' + f.key);
    if (raw === null) {
      if (f.data_type === 'multiselect' && data.has('present:' + f.key))
        output[f.key] = [];
      continue;
    }
    output[f.key] =
      raw === ''
        ? null
        : f.data_type === 'number'
          ? Number(raw)
          : f.data_type === 'bool'
            ? raw === 'true'
            : f.data_type === 'multiselect'
              ? data.getAll('field:' + f.key).filter(Boolean)
              : raw;
  }
  return output;
}
