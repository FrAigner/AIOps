import React, { ChangeEvent, useState } from 'react';
import { lastValueFrom } from 'rxjs';
import { css } from '@emotion/css';
import { AppPluginMeta, GrafanaTheme2, PluginConfigPageProps, PluginMeta } from '@grafana/data';
import { getBackendSrv } from '@grafana/runtime';
import { Button, Field, FieldSet, Input, useStyles2 } from '@grafana/ui';
import { testIds } from '../testIds';

type AppPluginSettings = {
  chatBackendUrl?: string;
};

export interface AppConfigProps extends PluginConfigPageProps<AppPluginMeta<AppPluginSettings>> {}

const DEFAULT_BACKEND_URL = 'http://localhost:8090';

const AppConfig = ({ plugin }: AppConfigProps) => {
  const s = useStyles2(getStyles);
  const { enabled, pinned, jsonData } = plugin.meta;
  const [chatBackendUrl, setChatBackendUrl] = useState(jsonData?.chatBackendUrl || '');

  const onChange = (event: ChangeEvent<HTMLInputElement>) => {
    setChatBackendUrl(event.target.value.trim());
  };

  const onSubmit = () => {
    updatePluginAndReload(plugin.meta.id, {
      enabled,
      pinned,
      jsonData: { chatBackendUrl },
    });
  };

  return (
    <form onSubmit={onSubmit}>
      <FieldSet label="AI-Assistant-Backend">
        <Field
          label="Chat-Backend-URL"
          description={
            'Der ai-analyst-Dienst (OpenAI-kompatibles LLM-Backend, ' +
            'austauschbar per LLM_BASE_URL). Vom Browser aus erreichbar, ' +
            'nicht der interne Docker-Hostname.'
          }
          className={s.marginTop}
        >
          <Input
            width={60}
            name="chatBackendUrl"
            id="config-chat-backend-url"
            data-testid={testIds.appConfig.chatBackendUrl}
            value={chatBackendUrl}
            placeholder={`z.B. ${DEFAULT_BACKEND_URL}`}
            onChange={onChange}
          />
        </Field>

        <div className={s.marginTop}>
          <Button type="submit" data-testid={testIds.appConfig.submit}>
            Speichern
          </Button>
        </div>
      </FieldSet>
    </form>
  );
};

export default AppConfig;

const getStyles = (theme: GrafanaTheme2) => ({
  marginTop: css`
    margin-top: ${theme.spacing(3)};
  `,
});

const updatePluginAndReload = async (pluginId: string, data: Partial<PluginMeta<AppPluginSettings>>) => {
  try {
    await updatePlugin(pluginId, data);
    window.location.reload();
  } catch (e) {
    console.error('Error while updating the plugin', e);
  }
};

const updatePlugin = async (pluginId: string, data: Partial<PluginMeta>) => {
  const response = await getBackendSrv().fetch({
    url: `/api/plugins/${pluginId}/settings`,
    method: 'POST',
    data,
  });

  return lastValueFrom(response);
};
