import stylelint from 'stylelint';
export function violations(root) {
  const problems = [];
  root.walkDecls((decl) => {
    if (
      /var\(--status-/.test(decl.value) &&
      ![
        'border-left-color',
        'border-inline-start-color',
        'fill',
        'stroke',
      ].includes(decl.prop)
    )
      problems.push({
        decl,
        message: 'Status colors are limited to small edges or glyphs',
      });
    if (
      /^outline(-style|-width)?$/.test(decl.prop) &&
      /^(none|0)(px)?$/.test(decl.value)
    )
      problems.push({ decl, message: 'Do not remove the focus outline' });
  });
  return problems;
}
const name = 'sierx/token-and-focus';
export default stylelint.createPlugin(name, () => (root, result) => {
  for (const { decl, message } of violations(root))
    stylelint.utils.report({ ruleName: name, result, node: decl, message });
});
