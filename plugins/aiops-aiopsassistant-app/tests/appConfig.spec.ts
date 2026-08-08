import { test, expect } from './fixtures';

test('should be possible to save app configuration', async ({ appConfigPage, page }) => {
  const saveButton = page.getByRole('button', { name: /Speichern/i });

  await page.getByRole('textbox', { name: 'Chat-Backend-URL' }).fill('http://localhost:8090');

  const saveResponse = appConfigPage.waitForSettingsResponse();

  await saveButton.click();
  await expect(saveResponse).toBeOK();
});
