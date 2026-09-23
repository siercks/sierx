import { expect, type Page } from '@playwright/test';
import { HtmlValidate } from 'html-validate';
const validator = new HtmlValidate({
  rules: {
    'wcag/h30': 'error',
    'wcag/h32': 'error',
    'wcag/h36': 'error',
    'wcag/h37': 'error',
    'wcag/h63': 'error',
    'wcag/h67': 'error',
    'wcag/h71': 'error',
    'input-missing-label': 'error',
    'no-dup-id': 'error',
    'no-redundant-for': 'error',
    'heading-level': 'error',
    'svg-focusable': 'off',
  },
});
export async function audit(page: Page) {
  const report = await validator.validateString(await page.content());
  expect(report.results.flatMap((r) => r.messages)).toEqual([]);
  const controls = page.locator(
    'button:visible, input:visible, select:visible, textarea:visible, a:visible',
  );
  for (const control of await controls.all()) {
    if (
      await control.evaluate(
        (e) => !!e.closest('[aria-hidden="true"], [inert]'),
      )
    )
      continue;
    await expect(control).toHaveAccessibleName(/.+/);
  }
  const problems = await page.evaluate(() => {
    const out: string[] = [];
    for (const element of document.querySelectorAll<HTMLElement>(
      'button,input,select,textarea',
    )) {
      if (!element.checkVisibility()) continue;
      const r = element.getBoundingClientRect();
      if (r.width < 24 || r.height < 24)
        out.push('Small target: ' + element.outerHTML.slice(0, 100));
    }
    return out;
  });
  expect(problems).toEqual([]);
}
export async function keyboardActivate(page: Page, name: string) {
  const target = page.getByRole('button', { name, exact: true }).last();
  for (let i = 0; i < 150; i++) {
    if (await target.evaluate((e) => e === document.activeElement)) {
      await page.keyboard.press('Enter');
      return;
    }
    await page.keyboard.press('Tab');
  }
  throw new Error('Keyboard could not reach ' + name);
}
